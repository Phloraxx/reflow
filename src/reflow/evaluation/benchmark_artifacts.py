from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SCALE_BENCHMARK_SCHEMA_VERSION = "gate17-scale-benchmark-v1"
PERSISTENCE_BENCHMARK_SCHEMA_VERSION = "gate17-persistence-benchmark-v1"

__all__ = [
    "PERSISTENCE_BENCHMARK_SCHEMA_VERSION",
    "SCALE_BENCHMARK_SCHEMA_VERSION",
    "artifact_digest",
    "load_verified_benchmark",
    "verify_persistence_benchmark_payload",
    "verify_scale_benchmark_payload",
]


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def artifact_digest(payload: dict[str, Any]) -> str:
    material = dict(payload)
    material.pop("artifact_sha256", None)
    return hashlib.sha256(_canonical_bytes(material)).hexdigest()


def _require_digest(payload: dict[str, Any], label: str) -> None:
    digest = payload.get("artifact_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError(f"{label} artifact digest is invalid")
    if digest != artifact_digest(payload):
        raise ValueError(f"{label} artifact digest does not match payload")


def verify_scale_benchmark_payload(payload: object) -> None:
    if not isinstance(payload, dict):
        raise ValueError("scale benchmark artifact root must be an object")
    if payload.get("schema_version") != SCALE_BENCHMARK_SCHEMA_VERSION:
        raise ValueError("scale benchmark schema version mismatch")
    _require_digest(payload, "scale benchmark")
    config = payload.get("config")
    hardware = payload.get("hardware")
    metrics = payload.get("metrics")
    if not all(isinstance(value, dict) for value in (config, hardware, metrics)):
        raise ValueError("scale benchmark artifact sections are invalid")
    assert isinstance(config, dict)
    if config.get("worker_count") != 1:
        raise ValueError("Gate 17 benchmark must disclose one-process execution")
    if config.get("database_mode") != "in_memory_core":
        raise ValueError("Gate 17 core benchmark database mode is invalid")


def verify_persistence_benchmark_payload(payload: object) -> None:
    if not isinstance(payload, dict):
        raise ValueError("persistence benchmark artifact root must be an object")
    if payload.get("schema_version") != PERSISTENCE_BENCHMARK_SCHEMA_VERSION:
        raise ValueError("persistence benchmark schema version mismatch")
    _require_digest(payload, "persistence benchmark")
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


def load_verified_benchmark(path: Path) -> dict[str, Any]:
    payload: object = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError("benchmark artifact root must be an object")
    schema = payload.get("schema_version")
    if schema == SCALE_BENCHMARK_SCHEMA_VERSION:
        verify_scale_benchmark_payload(payload)
    elif schema == PERSISTENCE_BENCHMARK_SCHEMA_VERSION:
        verify_persistence_benchmark_payload(payload)
    elif schema == "gate19-final-summary-v1":
        from .final_summary import verify_final_summary_payload

        verify_final_summary_payload(payload)
    else:
        raise ValueError(f"unsupported benchmark schema {schema!r}")
    return payload
