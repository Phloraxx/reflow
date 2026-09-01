from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from reflow import domain
from reflow.journal import AppendDisposition, make_source_envelope
from reflow.persistence import (
    ArtifactKind,
    ArtifactWriteDisposition,
    PostgresApplicationStore,
)

PERSISTENCE_BENCHMARK_SCHEMA_VERSION = "gate17-persistence-benchmark-v1"
_BASE_TIME = datetime(2026, 9, 1, 16, 0, tzinfo=UTC)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _artifact_digest(payload: dict[str, Any]) -> str:
    material = dict(payload)
    material.pop("artifact_sha256", None)
    return hashlib.sha256(_canonical_bytes(material)).hexdigest()


def verify_persistence_benchmark_payload(payload: object) -> None:
    if not isinstance(payload, dict):
        raise ValueError("persistence benchmark artifact root must be an object")
    if payload.get("schema_version") != PERSISTENCE_BENCHMARK_SCHEMA_VERSION:
        raise ValueError("persistence benchmark schema version mismatch")
    digest = payload.get("artifact_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError("persistence benchmark artifact digest is invalid")
    if digest != _artifact_digest(payload):
        raise ValueError("persistence benchmark artifact digest does not match payload")
    config = payload.get("config")
    metrics = payload.get("metrics")
    if not isinstance(config, dict) or not isinstance(metrics, dict):
        raise ValueError("persistence benchmark artifact sections are invalid")
    if config.get("database_mode") != "postgresql":
        raise ValueError("persistence benchmark database mode is invalid")
    record_count = config.get("record_count")
    if isinstance(record_count, bool) or not isinstance(record_count, int) or record_count < 1:
        raise ValueError("persistence benchmark record count is invalid")
    for name in (
        "source_cold_stored",
        "source_warm_duplicates",
        "artifact_cold_stored",
        "artifact_warm_duplicates",
    ):
        if metrics.get(name) != record_count:
            raise ValueError(f"persistence benchmark {name} count is invalid")


def _rate(count: int, seconds: float) -> float | None:
    return None if seconds <= 0 else round(count / seconds, 2)


def _source_envelopes(namespace: str, record_count: int) -> tuple[domain.SourceEnvelope, ...]:
    return tuple(
        make_source_envelope(
            source_kind=domain.SourceKind.BANK,
            source_record_id=f"gate17-benchmark/{namespace}/source/{index:08d}",
            occurred_at=_BASE_TIME + timedelta(microseconds=index),
            received_at=_BASE_TIME + timedelta(seconds=1, microseconds=index),
            schema_version="gate17-persistence-benchmark-v1",
            payload={
                "benchmark_namespace": namespace,
                "sequence": index,
                "amount_paise": index + 1,
            },
        )
        for index in range(record_count)
    )


def _artifact_payload(namespace: str, index: int) -> dict[str, object]:
    return {
        "benchmark_namespace": namespace,
        "sequence": index,
        "status": "synthetic_persistence_benchmark",
    }


def run_persistence_benchmark(
    *,
    dsn: str,
    namespace: str,
    record_count: int,
) -> dict[str, Any]:
    if not isinstance(namespace, str) or not namespace.strip() or namespace != namespace.strip():
        raise ValueError("benchmark namespace must be non-empty and trimmed")
    if isinstance(record_count, bool) or not isinstance(record_count, int):
        raise TypeError("record_count must be int")
    if record_count < 1:
        raise ValueError("record_count must be positive")

    store = PostgresApplicationStore(dsn)
    envelopes = _source_envelopes(namespace, record_count)

    started = time.perf_counter()
    cold_source = tuple(store.append(envelope).disposition for envelope in envelopes)
    source_cold_done = time.perf_counter()
    if any(item is not AppendDisposition.STORED for item in cold_source):
        raise ValueError("persistence benchmark namespace already contains source rows")

    warm_source = tuple(store.append(envelope).disposition for envelope in envelopes)
    source_warm_done = time.perf_counter()
    if any(item is not AppendDisposition.DUPLICATE for item in warm_source):
        raise AssertionError("warm source replay did not remain idempotent")

    artifact_ids = tuple(
        f"gate17-benchmark:{namespace}:artifact:{index:08d}" for index in range(record_count)
    )
    cold_artifacts = tuple(
        store.put_artifact(
            kind=ArtifactKind.PROOF_VERSION,
            artifact_id=artifact_id,
            payload=_artifact_payload(namespace, index),
            scope_id=None,
            observed_at=_BASE_TIME + timedelta(microseconds=index),
        ).disposition
        for index, artifact_id in enumerate(artifact_ids)
    )
    artifact_cold_done = time.perf_counter()
    if any(item is not ArtifactWriteDisposition.STORED for item in cold_artifacts):
        raise ValueError("persistence benchmark namespace already contains artifacts")

    warm_artifacts = tuple(
        store.put_artifact(
            kind=ArtifactKind.PROOF_VERSION,
            artifact_id=artifact_id,
            payload=_artifact_payload(namespace, index),
            scope_id=None,
            observed_at=_BASE_TIME + timedelta(microseconds=index),
        ).disposition
        for index, artifact_id in enumerate(artifact_ids)
    )
    artifact_warm_done = time.perf_counter()
    if any(item is not ArtifactWriteDisposition.DUPLICATE for item in warm_artifacts):
        raise AssertionError("warm artifact replay did not remain idempotent")

    reconstructed = PostgresApplicationStore(dsn, initialize=False)
    first_source = reconstructed.get_by_id(envelopes[0].id)
    last_artifact = reconstructed.get_artifact(artifact_ids[-1])
    if first_source != envelopes[0] or last_artifact is None:
        raise AssertionError("persistence benchmark restart verification failed")

    source_cold_seconds = source_cold_done - started
    source_warm_seconds = source_warm_done - source_cold_done
    artifact_cold_seconds = artifact_cold_done - source_warm_done
    artifact_warm_seconds = artifact_warm_done - artifact_cold_done
    metrics: dict[str, object] = {
        "source_cold_stored": record_count,
        "source_warm_duplicates": record_count,
        "artifact_cold_stored": record_count,
        "artifact_warm_duplicates": record_count,
        "source_cold_seconds": round(source_cold_seconds, 6),
        "source_warm_seconds": round(source_warm_seconds, 6),
        "artifact_cold_seconds": round(artifact_cold_seconds, 6),
        "artifact_warm_seconds": round(artifact_warm_seconds, 6),
        "source_cold_ops_per_second": _rate(record_count, source_cold_seconds),
        "source_warm_ops_per_second": _rate(record_count, source_warm_seconds),
        "artifact_cold_ops_per_second": _rate(record_count, artifact_cold_seconds),
        "artifact_warm_ops_per_second": _rate(record_count, artifact_warm_seconds),
    }
    payload: dict[str, Any] = {
        "schema_version": PERSISTENCE_BENCHMARK_SCHEMA_VERSION,
        "config": {
            "namespace": namespace,
            "record_count": record_count,
            "database_mode": "postgresql",
            "worker_count": 1,
        },
        "hardware": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": sys.version.split()[0],
            "cpu_count": os.cpu_count(),
        },
        "metrics": metrics,
        "artifact_sha256": "",
    }
    payload["artifact_sha256"] = _artifact_digest(payload)
    verify_persistence_benchmark_payload(payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Run or verify Gate 17 PostgreSQL persistence")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--records", type=int)
    mode.add_argument("--verify", type=Path)
    parser.add_argument("--namespace")
    parser.add_argument("--dsn", default=os.getenv("REFLOW_BENCHMARK_POSTGRES_DSN"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.verify is not None:
        payload: object = json.loads(args.verify.read_text())
        verify_persistence_benchmark_payload(payload)
        print(json.dumps({"status": "verified", "artifact": str(args.verify)}, sort_keys=True))
        return
    if args.dsn is None:
        parser.error("--dsn or REFLOW_BENCHMARK_POSTGRES_DSN is required")
    if args.namespace is None:
        parser.error("--namespace is required for a benchmark run")
    assert args.records is not None
    payload = run_persistence_benchmark(
        dsn=args.dsn,
        namespace=args.namespace,
        record_count=args.records,
    )
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered)


if __name__ == "__main__":
    main()
