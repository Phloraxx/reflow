from __future__ import annotations

from dataclasses import replace

from reflow import domain

from .contracts import AdapterSpec, CanonicalRecordKind, FieldMapping, TransformKind
from .migration_benchmark import MigrationBenchmarkCase, MigrationExpectation


def _mappings(*items: FieldMapping) -> tuple[FieldMapping, ...]:
    return tuple(sorted(items, key=lambda item: item.target_field))


def _bank_spec(
    *,
    version: int,
    amount_column: str,
    amount_transform: TransformKind = TransformKind.RUPEES_TO_PAISE,
) -> AdapterSpec:
    return AdapterSpec(
        adapter_id="gate12_migration_adapter",
        version=version,
        source_kind=domain.SourceKind.BANK,
        record_kind=CanonicalRecordKind.BANK_ENTRY,
        mappings=_mappings(
            FieldMapping("amount_paise", amount_transform, amount_column),
            FieldMapping("bank_entry_id", TransformKind.TEXT, "Txn"),
            FieldMapping("currency", TransformKind.CONSTANT, constant="INR"),
            FieldMapping("narration", TransformKind.TEXT, "Memo"),
            FieldMapping("occurred_at", TransformKind.ISO_DATETIME, "Timestamp"),
            FieldMapping("utr", TransformKind.OPTIONAL_TEXT, "Reference"),
        ),
    )


def _old_rows(amount: str = "100") -> tuple[dict[str, object], ...]:
    return (
        {
            "Txn": "bank_migration_bench_001",
            "Credit": amount,
            "Timestamp": "2026-08-31T10:00:00+05:30",
            "Memo": "SETTLEMENT CREDIT",
            "Reference": "UTR-MIG-BENCH-001",
        },
    )


def _new_rows(amount: str = "100") -> tuple[dict[str, object], ...]:
    return (
        {
            "Txn": "bank_migration_bench_001",
            "Bank Credit": amount,
            "Timestamp": "2026-08-31T10:00:00+05:30",
            "Memo": "SETTLEMENT CREDIT",
            "Reference": "UTR-MIG-BENCH-001",
        },
    )


def development_migration_cases() -> tuple[MigrationBenchmarkCase, ...]:
    current = _bank_spec(version=1, amount_column="Credit")
    safe = _bank_spec(version=2, amount_column="Bank Credit")
    wrong_unit = _bank_spec(
        version=2,
        amount_column="Bank Credit",
        amount_transform=TransformKind.INTEGER_PAISE,
    )
    wrong_identity = replace(
        safe,
        mappings=_mappings(
            *(
                replace(mapping, source_column="Reference")
                if mapping.target_field == "narration"
                else replace(mapping, source_column="Memo")
                if mapping.target_field == "utr"
                else mapping
                for mapping in safe.mappings
            )
        ),
    )
    return (
        MigrationBenchmarkCase(
            case_id="migration_safe_header_rename",
            current_spec=current,
            proposed_spec=safe,
            old_rows=_old_rows(),
            new_rows=_new_rows(),
            expectation=MigrationExpectation.SAFE_TO_ACTIVATE,
        ),
        MigrationBenchmarkCase(
            case_id="migration_wrong_unit",
            current_spec=current,
            proposed_spec=wrong_unit,
            old_rows=_old_rows(),
            new_rows=_new_rows(),
            expectation=MigrationExpectation.MUST_REJECT,
        ),
        MigrationBenchmarkCase(
            case_id="migration_wrong_identity",
            current_spec=current,
            proposed_spec=wrong_identity,
            old_rows=_old_rows(),
            new_rows=_new_rows(),
            expectation=MigrationExpectation.MUST_REJECT,
        ),
    )
