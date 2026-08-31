from __future__ import annotations

from reflow.adapter_compiler import (
    AdapterApprovalEvidence,
    AdapterSpec,
    ApprovalEvidenceKind,
    ApprovedAdapterVersion,
    CanonicalRecordKind,
    FieldMapping,
    InMemoryAdapterStore,
    TransformKind,
    compile_adapter,
    evaluate_migration,
    migration_approval_evidence,
    profile_rows,
    validate_sample,
)
from reflow.domain import SourceKind


def _spec(version: int, *, amount_column: str) -> AdapterSpec:
    return AdapterSpec(
        adapter_id="bank_migrating",
        version=version,
        source_kind=SourceKind.BANK,
        record_kind=CanonicalRecordKind.BANK_ENTRY,
        mappings=tuple(
            sorted(
                (
                    FieldMapping("amount_paise", TransformKind.RUPEES_TO_PAISE, amount_column),
                    FieldMapping("bank_entry_id", TransformKind.TEXT, "Ref"),
                    FieldMapping("currency", TransformKind.CONSTANT, constant="INR"),
                    FieldMapping("narration", TransformKind.TEXT, "Description"),
                    FieldMapping("occurred_at", TransformKind.ISO_DATETIME, "Timestamp"),
                    FieldMapping("utr", TransformKind.OPTIONAL_TEXT, "UTR"),
                ),
                key=lambda item: item.target_field,
            )
        ),
    )


def _old_rows() -> tuple[dict[str, object], ...]:
    return (
        {
            "Ref": "bank_migration_1",
            "Credit": "100.00",
            "Timestamp": "2026-08-31T10:00:00+05:30",
            "Description": "credit",
            "UTR": "UTR-M1",
        },
    )


def _new_rows(amount: str = "100.00") -> tuple[dict[str, object], ...]:
    return (
        {
            "Ref": "bank_migration_1",
            "Bank Credit": amount,
            "Timestamp": "2026-08-31T10:00:00+05:30",
            "Description": "credit",
            "UTR": "UTR-M1",
        },
    )


def test_schema_migration_replays_to_identical_canonical_financial_output() -> None:
    old_profile = profile_rows(_old_rows())
    new_profile = profile_rows(_new_rows())
    current = compile_adapter(_spec(1, amount_column="Credit"), old_profile)
    proposed = compile_adapter(_spec(2, amount_column="Bank Credit"), new_profile)
    evaluation = evaluate_migration(
        current,
        proposed,
        old_fixture_rows=_old_rows(),
        migrated_fixture_rows=_new_rows(),
    )
    assert evaluation.safe_to_activate
    assert evaluation.canonical_diff is not None
    assert evaluation.canonical_diff.is_identical
    assert evaluation.canonical_diff.unchanged_count == 1


def test_migration_that_changes_money_is_not_silently_safe() -> None:
    current = compile_adapter(_spec(1, amount_column="Credit"), profile_rows(_old_rows()))
    changed_rows = _new_rows("101.00")
    proposed = compile_adapter(_spec(2, amount_column="Bank Credit"), profile_rows(changed_rows))
    evaluation = evaluate_migration(
        current,
        proposed,
        old_fixture_rows=_old_rows(),
        migrated_fixture_rows=changed_rows,
    )
    assert not evaluation.safe_to_activate
    assert evaluation.canonical_diff is not None
    assert evaluation.canonical_diff.changed_ids == ("bank_migration_1",)


def test_activating_new_version_keeps_old_schema_fingerprint_resolvable() -> None:
    store = InMemoryAdapterStore()
    old_profile = profile_rows(_old_rows())
    new_profile = profile_rows(_new_rows())
    current = compile_adapter(_spec(1, amount_column="Credit"), old_profile)
    first = ApprovedAdapterVersion.from_compiled(
        current,
        old_profile,
        validate_sample(current, _old_rows()),
        AdapterApprovalEvidence(
            kind=ApprovalEvidenceKind.OPERATOR_REVIEW,
            reference="initial-reviewed-adapter",
        ),
    )
    store.activate(first)

    proposed = compile_adapter(_spec(2, amount_column="Bank Credit"), new_profile)
    migration = evaluate_migration(
        current,
        proposed,
        old_fixture_rows=_old_rows(),
        migrated_fixture_rows=_new_rows(),
    )
    second = ApprovedAdapterVersion.from_compiled(
        proposed,
        new_profile,
        validate_sample(proposed, _new_rows()),
        migration_approval_evidence(migration, reference="migration-v1-to-v2"),
    )
    store.activate(second)
    assert store.resolve_schema("bank_migrating", old_profile.schema_fingerprint).spec.version == 1
    assert store.resolve_schema("bank_migrating", new_profile.schema_fingerprint).spec.version == 2
