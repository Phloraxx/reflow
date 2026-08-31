from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy

import pytest

from reflow.adapter_compiler.benchmark import (
    AdapterCaseExpectation,
    benchmark_payload,
    run_adapter_benchmark,
)
from reflow.adapter_compiler.benchmark_fixtures import (
    WrongUnitMutationProvider,
    development_adapter_cases,
    development_reference_provider,
)
from reflow.adapter_compiler.benchmark_verify import (
    AdapterArtifactVerificationError,
    verify_adapter_benchmark_payload,
)


def test_development_adapter_benchmark_has_zero_unsafe_activations() -> None:
    cases = development_adapter_cases()
    results, report = run_adapter_benchmark(development_reference_provider(), cases)
    assert report.case_count == 11
    assert report.unsafe_activations == 0
    assert report.safe_activations == report.expected_activations == 0
    assert report.correct_reviews == report.expected_reviews == 7
    assert report.correct_previews == 7
    assert report.incorrect_previews == 0
    assert report.correct_rejections == report.expected_rejections == 4
    assert report.false_rejections_or_reviews == 0
    assert len(results) == len(cases)


def test_known_wrong_integer_unit_proposal_cannot_activate() -> None:
    cases = development_adapter_cases()
    provider = WrongUnitMutationProvider(
        development_reference_provider(),
        "bench_bank_integer_rupees",
    )
    results, report = run_adapter_benchmark(provider, cases)
    target = next(result for result in results if result.case_id == "bench_bank_integer_rupees")
    assert target.state.value == "rejected"
    assert report.unsafe_activations == 0
    assert report.incorrect_previews == 1
    assert report.false_rejections_or_reviews == 0
    assert report.correct_reviews == report.expected_reviews - 1


def test_uncontrolled_semantic_mapping_is_review_not_activation() -> None:
    cases = development_adapter_cases()
    case = next(item for item in cases if item.case_id == "bench_bank_no_control")
    assert case.expectation is AdapterCaseExpectation.MUST_REVIEW
    results, report = run_adapter_benchmark(development_reference_provider(), (case,))
    assert results[0].state.value == "needs_review"
    assert report.safe_activations == 0
    assert report.unsafe_activations == 0
    assert report.correct_reviews == 1


def test_adapter_benchmark_artifact_replays_from_rows_specs_and_controls() -> None:
    cases = development_adapter_cases()
    results, report = run_adapter_benchmark(development_reference_provider(), cases)
    payload = benchmark_payload(
        cases,
        results,
        report,
        provider_name="development",
    )
    assert verify_adapter_benchmark_payload(payload) == report


def test_adapter_benchmark_verifier_rejects_tampered_metric() -> None:
    cases = development_adapter_cases()
    results, report = run_adapter_benchmark(development_reference_provider(), cases)
    payload = benchmark_payload(cases, results, report, provider_name="development")
    tampered = deepcopy(payload)
    tampered["report"]["unsafe_activations"] = 1
    with pytest.raises(AdapterArtifactVerificationError, match="stored report"):
        verify_adapter_benchmark_payload(tampered)


def test_adapter_benchmark_verifier_rejects_tampered_spec() -> None:
    cases = development_adapter_cases()
    results, report = run_adapter_benchmark(development_reference_provider(), cases)
    payload = benchmark_payload(cases, results, report, provider_name="development")
    tampered = deepcopy(payload)
    target = next(
        item for item in tampered["results"] if item["case_id"] == "bench_bank_integer_rupees"
    )
    mapping = next(
        item for item in target["proposed_spec"]["mappings"]
        if item["target_field"] == "amount_paise"
    )
    mapping["transform"] = "integer_paise"
    with pytest.raises(AdapterArtifactVerificationError, match="state differs"):
        verify_adapter_benchmark_payload(tampered)


def test_adapter_benchmark_cli_and_verifier_cli(tmp_path) -> None:
    artifact = tmp_path / "gate12.json"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "reflow.adapter_compiler.benchmark_runner",
            "--provider",
            "development",
            "--output",
            str(artifact),
        ],
        check=True,
    )
    payload = json.loads(artifact.read_text())
    assert payload["report"]["unsafe_activations"] == 0
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "reflow.adapter_compiler.benchmark_verify_cli",
            str(artifact),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "0 unsafe activations" in completed.stdout
