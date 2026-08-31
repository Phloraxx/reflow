from __future__ import annotations

from reflow.adapter_compiler.migration_benchmark import (
    MigrationExpectation,
    run_migration_benchmark,
)
from reflow.adapter_compiler.migration_benchmark_fixtures import (
    development_migration_cases,
)


def test_migration_benchmark_exercises_real_automatic_activation_path() -> None:
    cases = development_migration_cases()
    results, report = run_migration_benchmark(cases)
    assert report.case_count == 3
    assert report.expected_safe == 1
    assert report.safe_activations == 1
    assert report.expected_rejections == 2
    assert report.correct_rejections == 2
    assert report.unsafe_activations == 0
    assert report.false_rejections == 0
    assert report.routing_failures == 0
    safe = next(item for item in results if item.case_id == "migration_safe_header_rename")
    assert safe.activated and safe.routing_verified


def test_wrong_unit_and_identity_migrations_do_not_activate() -> None:
    cases = development_migration_cases()
    results, _ = run_migration_benchmark(cases)
    rejected = {
        result.case_id: result
        for result in results
        if result.case_id != "migration_safe_header_rename"
    }
    assert rejected["migration_wrong_unit"].canonical_diff is not None
    assert rejected["migration_wrong_identity"].canonical_diff is not None
    assert all(not item.activated for item in rejected.values())
    expectations = {case.case_id: case.expectation for case in cases}
    assert all(
        expectations[case_id] is MigrationExpectation.MUST_REJECT
        for case_id in rejected
    )


def test_migration_benchmark_artifact_and_cli_are_replayable(tmp_path) -> None:
    import json
    import subprocess
    import sys

    from reflow.adapter_compiler.migration_benchmark_artifact import (
        migration_benchmark_payload,
        verify_migration_benchmark_payload,
    )

    cases = development_migration_cases()
    results, report = run_migration_benchmark(cases)
    payload = migration_benchmark_payload(cases, results, report)
    assert verify_migration_benchmark_payload(payload) == report

    artifact = tmp_path / "gate12-migration.json"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "reflow.adapter_compiler.migration_benchmark_runner",
            "--output",
            str(artifact),
        ],
        check=True,
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "reflow.adapter_compiler.migration_benchmark_verify_cli",
            str(artifact),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "0 unsafe activations" in completed.stdout
    assert json.loads(artifact.read_text())["report"]["safe_activations"] == 1
