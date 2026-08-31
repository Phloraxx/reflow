from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from reflow.ingestion import RawRecord

from .benchmark import spec_payload
from .migration import CanonicalMigrationDiff
from .migration_benchmark import (
    MigrationBenchmarkCase,
    MigrationBenchmarkReport,
    MigrationCaseResult,
    MigrationExpectation,
    run_migration_benchmark,
)
from .spec_io import parse_adapter_spec_payload

MIGRATION_BENCHMARK_SCHEMA_VERSION = "gate12-migration-benchmark-v1"


class MigrationArtifactVerificationError(ValueError):
    pass


def _diff_payload(diff: CanonicalMigrationDiff | None) -> dict[str, object] | None:
    if diff is None:
        return None
    return {
        "added_ids": list(diff.added_ids),
        "removed_ids": list(diff.removed_ids),
        "changed_ids": list(diff.changed_ids),
        "unchanged_count": diff.unchanged_count,
    }


def migration_benchmark_payload(
    cases: tuple[MigrationBenchmarkCase, ...],
    results: tuple[MigrationCaseResult, ...],
    report: MigrationBenchmarkReport,
) -> dict[str, Any]:
    return {
        "schema_version": MIGRATION_BENCHMARK_SCHEMA_VERSION,
        "cases": [
            {
                "case_id": case.case_id,
                "current_spec": spec_payload(case.current_spec),
                "proposed_spec": spec_payload(case.proposed_spec),
                "old_rows": [dict(row) for row in case.old_rows],
                "new_rows": [dict(row) for row in case.new_rows],
                "expectation": case.expectation.value,
            }
            for case in cases
        ],
        "results": [
            {
                "case_id": result.case_id,
                "safe_to_activate": result.safe_to_activate,
                "activated": result.activated,
                "routing_verified": result.routing_verified,
                "canonical_diff": _diff_payload(result.canonical_diff),
                "rejection_reason": result.rejection_reason,
            }
            for result in results
        ],
        "report": asdict(report),
    }


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise MigrationArtifactVerificationError(f"{label} must be an object")
    return value


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise MigrationArtifactVerificationError(f"{label} must be an array")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise MigrationArtifactVerificationError(f"{label} must be a string")
    return value


def _rows(value: object, label: str) -> tuple[RawRecord, ...]:
    rows: list[RawRecord] = []
    for raw in _list(value, label):
        rows.append(dict(_mapping(raw, f"{label} row")))
    return tuple(rows)


def _case_from_payload(value: object) -> MigrationBenchmarkCase:
    item = _mapping(value, "migration case")
    try:
        current_spec = parse_adapter_spec_payload(item.get("current_spec"))
        proposed_spec = parse_adapter_spec_payload(item.get("proposed_spec"))
        expectation = MigrationExpectation(
            _string(item.get("expectation"), "migration expectation")
        )
    except (TypeError, ValueError) as exc:
        raise MigrationArtifactVerificationError(
            f"invalid migration case contract: {exc}"
        ) from exc
    return MigrationBenchmarkCase(
        case_id=_string(item.get("case_id"), "migration case id"),
        current_spec=current_spec,
        proposed_spec=proposed_spec,
        old_rows=_rows(item.get("old_rows"), "old rows"),
        new_rows=_rows(item.get("new_rows"), "new rows"),
        expectation=expectation,
    )


def verify_migration_benchmark_payload(payload: object) -> MigrationBenchmarkReport:
    root = _mapping(payload, "migration benchmark")
    if root.get("schema_version") != MIGRATION_BENCHMARK_SCHEMA_VERSION:
        raise MigrationArtifactVerificationError("unsupported migration benchmark schema")
    cases = tuple(_case_from_payload(item) for item in _list(root.get("cases"), "cases"))
    results, report = run_migration_benchmark(cases)
    recomputed = migration_benchmark_payload(cases, results, report)
    if root.get("results") != recomputed["results"]:
        raise MigrationArtifactVerificationError(
            "stored migration results differ from deterministic replay"
        )
    if root.get("report") != recomputed["report"]:
        raise MigrationArtifactVerificationError(
            "stored migration report differs from deterministic replay"
        )
    return report
