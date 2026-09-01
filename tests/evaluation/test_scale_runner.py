from __future__ import annotations

from copy import deepcopy

import pytest

from reflow.evaluation.profiles import EvaluationProfile
from reflow.evaluation.scale_runner import (
    SCALE_BENCHMARK_SCHEMA_VERSION,
    run_scale_benchmark,
    verify_scale_benchmark_payload,
)


def test_scale_benchmark_artifact_is_self_verifying_and_discloses_runtime() -> None:
    payload = run_scale_benchmark(
        settlement_count=5,
        profile=EvaluationProfile.CLEAN,
        world_seed=901,
        observation_seed=1901,
    )
    verify_scale_benchmark_payload(payload)
    assert payload["schema_version"] == SCALE_BENCHMARK_SCHEMA_VERSION
    assert payload["status"] == "evaluated"
    config = payload["config"]
    hardware = payload["hardware"]
    metrics = payload["metrics"]
    assert config["worker_count"] == 1
    assert config["database_mode"] == "in_memory_core"
    assert hardware["python"]
    assert hardware["cpu_count"]
    assert metrics["raw_rows"] > 0
    assert metrics["proof_count"] == 5
    assert metrics["seconds_total"] >= 0
    assert metrics["max_rss_kib"] > 0


def test_scale_benchmark_digest_rejects_tampering() -> None:
    payload = run_scale_benchmark(
        settlement_count=3,
        profile=EvaluationProfile.CLEAN,
        world_seed=902,
        observation_seed=1902,
    )
    tampered = deepcopy(payload)
    tampered["metrics"]["proof_count"] = 999
    with pytest.raises(ValueError, match="digest"):
        verify_scale_benchmark_payload(tampered)


def test_scale_benchmark_deterministic_non_timing_outcomes_for_same_seed() -> None:
    first = run_scale_benchmark(
        settlement_count=4,
        profile=EvaluationProfile.RECONCILIATION_ADVERSARIAL,
        world_seed=903,
        observation_seed=1903,
    )
    second = run_scale_benchmark(
        settlement_count=4,
        profile=EvaluationProfile.RECONCILIATION_ADVERSARIAL,
        world_seed=903,
        observation_seed=1903,
    )
    for key in (
        "raw_rows",
        "journal_entries",
        "world_payment_events",
        "world_recon_entries",
        "graph_edges",
        "proof_count",
        "exception_count",
    ):
        assert first["metrics"][key] == second["metrics"][key]
    assert first["status_counts"] == second["status_counts"]
    assert first["source_rejection"] == second["source_rejection"]
