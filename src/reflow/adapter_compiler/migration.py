from __future__ import annotations

from dataclasses import dataclass

from reflow import domain
from reflow.ingestion import RawRecord

from .compiler import CanonicalRecord, CompiledAdapter, SampleValidationReport, validate_sample


def _identity(record: CanonicalRecord) -> str:
    if isinstance(record, domain.PaymentEvent):
        return record.source_event_id
    return str(record.id)


def _index_records(
    adapter: CompiledAdapter,
    rows: tuple[RawRecord, ...],
) -> dict[str, CanonicalRecord]:
    indexed: dict[str, CanonicalRecord] = {}
    for row in rows:
        record = adapter.canonicalize(row)
        identity = _identity(record)
        if identity in indexed:
            raise ValueError(
            f"migration fixture contains duplicate canonical identity {identity!r}"
        )
        indexed[identity] = record
    return indexed


@dataclass(frozen=True, slots=True)
class CanonicalMigrationDiff:
    added_ids: tuple[str, ...]
    removed_ids: tuple[str, ...]
    changed_ids: tuple[str, ...]
    unchanged_count: int

    @property
    def is_identical(self) -> bool:
        return not self.added_ids and not self.removed_ids and not self.changed_ids


@dataclass(frozen=True, slots=True)
class MigrationEvaluation:
    old_validation: SampleValidationReport
    new_validation: SampleValidationReport
    canonical_diff: CanonicalMigrationDiff | None
    safe_to_activate: bool
    rejection_reason: str | None


def evaluate_migration(
    current: CompiledAdapter,
    proposed: CompiledAdapter,
    *,
    old_fixture_rows: tuple[RawRecord, ...],
    migrated_fixture_rows: tuple[RawRecord, ...],
) -> MigrationEvaluation:
    old_validation = validate_sample(current, old_fixture_rows)
    new_validation = validate_sample(proposed, migrated_fixture_rows)
    if old_validation.state.value != "approved":
        return MigrationEvaluation(
            old_validation=old_validation,
            new_validation=new_validation,
            canonical_diff=None,
            safe_to_activate=False,
            rejection_reason="current adapter no longer replays its historical fixture corpus",
        )
    if new_validation.state.value != "approved":
        return MigrationEvaluation(
            old_validation=old_validation,
            new_validation=new_validation,
            canonical_diff=None,
            safe_to_activate=False,
            rejection_reason="proposed adapter does not validate its migrated fixture corpus",
        )

    old_records = _index_records(current, old_fixture_rows)
    new_records = _index_records(proposed, migrated_fixture_rows)
    old_ids = set(old_records)
    new_ids = set(new_records)
    common = old_ids & new_ids
    changed = tuple(
        sorted(
            identity
            for identity in common
            if old_records[identity] != new_records[identity]
        )
    )
    diff = CanonicalMigrationDiff(
        added_ids=tuple(sorted(new_ids - old_ids)),
        removed_ids=tuple(sorted(old_ids - new_ids)),
        changed_ids=changed,
        unchanged_count=sum(old_records[identity] == new_records[identity] for identity in common),
    )
    return MigrationEvaluation(
        old_validation=old_validation,
        new_validation=new_validation,
        canonical_diff=diff,
        safe_to_activate=diff.is_identical,
        rejection_reason=(
            None if diff.is_identical else "migration changes canonical financial output"
        ),
    )
