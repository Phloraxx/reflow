from __future__ import annotations

import os
import uuid
from copy import deepcopy

import pytest

from reflow.evaluation.persistence_runner import (
    PERSISTENCE_BENCHMARK_SCHEMA_VERSION,
    run_persistence_benchmark,
    verify_persistence_benchmark_payload,
)


def test_persistence_benchmark_payload_rejects_tampering() -> None:
    payload = {
        "schema_version": PERSISTENCE_BENCHMARK_SCHEMA_VERSION,
        "config": {
            "namespace": "unit",
            "record_count": 2,
            "database_mode": "postgresql",
            "worker_count": 1,
        },
        "hardware": {},
        "metrics": {
            "source_cold_stored": 2,
            "source_warm_duplicates": 2,
            "artifact_cold_stored": 2,
            "artifact_warm_duplicates": 2,
        },
        "artifact_sha256": "0" * 64,
    }
    with pytest.raises(ValueError, match="digest"):
        verify_persistence_benchmark_payload(payload)


def test_persistence_benchmark_runs_cold_and_warm_against_real_postgres() -> None:
    dsn = os.getenv("REFLOW_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("REFLOW_TEST_POSTGRES_DSN is not configured")
    payload = run_persistence_benchmark(
        dsn=dsn,
        namespace=f"pytest-{uuid.uuid4().hex}",
        record_count=3,
    )
    verify_persistence_benchmark_payload(payload)
    assert payload["schema_version"] == PERSISTENCE_BENCHMARK_SCHEMA_VERSION
    metrics = payload["metrics"]
    assert metrics["source_cold_stored"] == 3
    assert metrics["source_warm_duplicates"] == 3
    assert metrics["artifact_cold_stored"] == 3
    assert metrics["artifact_warm_duplicates"] == 3


def test_persistence_benchmark_digest_detects_metric_change() -> None:
    dsn = os.getenv("REFLOW_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("REFLOW_TEST_POSTGRES_DSN is not configured")
    payload = run_persistence_benchmark(
        dsn=dsn,
        namespace=f"pytest-{uuid.uuid4().hex}",
        record_count=1,
    )
    tampered = deepcopy(payload)
    tampered["metrics"]["source_cold_stored"] = 99
    with pytest.raises(ValueError, match="digest"):
        verify_persistence_benchmark_payload(tampered)
