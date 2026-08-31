from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum

from reflow.ingestion import RawRecord

from .compiler import compile_adapter, validate_sample
from .contracts import (
    AdapterApprovalEvidence,
    AdapterSpec,
    ApprovalEvidenceKind,
)
from .lifecycle import ApprovedAdapterVersion, InMemoryAdapterStore
from .migration import CanonicalMigrationDiff, evaluate_migration, migration_approval_evidence
from .profile import profile_rows


class MigrationExpectation(StrEnum):
    SAFE_TO_ACTIVATE = "safe_to_activate"
    MUST_REJECT = "must_reject"


@dataclass(frozen=True, slots=True)
class MigrationBenchmarkCase:
    case_id: str
    current_spec: AdapterSpec
    proposed_spec: AdapterSpec
    old_rows: tuple[RawRecord, ...]
    new_rows: tuple[RawRecord, ...]
    expectation: MigrationExpectation

    def __post_init__(self) -> None:
        if not self.case_id or self.case_id != self.case_id.strip():
            raise ValueError("migration benchmark case id must be non-empty and trimmed")
        if self.current_spec.adapter_id != self.proposed_spec.adapter_id:
            raise ValueError("migration specs must share adapter identity")
        if self.current_spec.source_kind is not self.proposed_spec.source_kind:
            raise ValueError("migration specs must share source kind")
        if self.current_spec.record_kind is not self.proposed_spec.record_kind:
            raise ValueError("migration specs must share record kind")
        if self.proposed_spec.version <= self.current_spec.version:
            raise ValueError("migration proposed version must increase")
        if not self.old_rows or not self.new_rows:
            raise ValueError("migration benchmark requires old and new fixtures")


@dataclass(frozen=True, slots=True)
class MigrationCaseResult:
    case_id: str
    safe_to_activate: bool
    activated: bool
    routing_verified: bool
    canonical_diff: CanonicalMigrationDiff | None
    rejection_reason: str | None


@dataclass(frozen=True, slots=True)
class MigrationBenchmarkReport:
    case_count: int
    expected_safe: int
    expected_rejections: int
    safe_activations: int
    unsafe_activations: int
    false_rejections: int
    correct_rejections: int
    routing_failures: int

    def __post_init__(self) -> None:
        values = tuple(asdict(self).values())
        if any(not isinstance(value, int) or value < 0 for value in values):
            raise ValueError("migration benchmark counts must be non-negative integers")
        if self.expected_safe + self.expected_rejections != self.case_count:
            raise ValueError("migration expectations do not partition")
        if self.safe_activations + self.false_rejections != self.expected_safe:
            raise ValueError("safe migration outcomes do not partition")
        if self.unsafe_activations + self.correct_rejections != self.expected_rejections:
            raise ValueError("unsafe migration outcomes do not partition")
        if self.routing_failures > self.safe_activations + self.unsafe_activations:
            raise ValueError("routing failures exceed activated migrations")


def run_migration_case(case: MigrationBenchmarkCase) -> MigrationCaseResult:
    old_profile = profile_rows(case.old_rows)
    new_profile = profile_rows(case.new_rows)
    current = compile_adapter(case.current_spec, old_profile)
    proposed = compile_adapter(case.proposed_spec, new_profile)
    current_report = validate_sample(current, case.old_rows)
    current_version = ApprovedAdapterVersion.from_compiled(
        current,
        old_profile,
        current_report,
        AdapterApprovalEvidence(
            kind=ApprovalEvidenceKind.OPERATOR_REVIEW,
            reference=f"benchmark-bootstrap:{case.case_id}",
        ),
    )
    store = InMemoryAdapterStore()
    store.activate(current_version)

    evaluation = evaluate_migration(
        current,
        proposed,
        old_fixture_rows=case.old_rows,
        migrated_fixture_rows=case.new_rows,
    )
    if not evaluation.safe_to_activate:
        return MigrationCaseResult(
            case_id=case.case_id,
            safe_to_activate=False,
            activated=False,
            routing_verified=False,
            canonical_diff=evaluation.canonical_diff,
            rejection_reason=evaluation.rejection_reason,
        )

    proposed_report = validate_sample(proposed, case.new_rows)
    proposed_version = ApprovedAdapterVersion.from_compiled(
        proposed,
        new_profile,
        proposed_report,
        migration_approval_evidence(
            evaluation,
            reference=f"benchmark-migration:{case.case_id}",
        ),
    )
    store.activate(proposed_version)
    old_resolved = store.resolve_schema(
        case.current_spec.adapter_id, old_profile.schema_fingerprint
    )
    new_resolved = store.resolve_schema(
        case.proposed_spec.adapter_id, new_profile.schema_fingerprint
    )
    routing_verified = (
        old_resolved is not None
        and old_resolved.spec.version == case.current_spec.version
        and new_resolved is not None
        and new_resolved.spec.version == case.proposed_spec.version
    )
    return MigrationCaseResult(
        case_id=case.case_id,
        safe_to_activate=True,
        activated=True,
        routing_verified=routing_verified,
        canonical_diff=evaluation.canonical_diff,
        rejection_reason=None,
    )


def score_migration_results(
    cases: tuple[MigrationBenchmarkCase, ...],
    results: tuple[MigrationCaseResult, ...],
) -> MigrationBenchmarkReport:
    case_index = {case.case_id: case for case in cases}
    result_index = {result.case_id: result for result in results}
    if len(case_index) != len(cases) or len(result_index) != len(results):
        raise ValueError("migration benchmark ids must be unique")
    if set(case_index) != set(result_index):
        raise ValueError("migration results must cover every case exactly once")

    safe_activations = 0
    unsafe_activations = 0
    false_rejections = 0
    correct_rejections = 0
    routing_failures = 0
    for case_id, case in case_index.items():
        result = result_index[case_id]
        if result.activated and not result.routing_verified:
            routing_failures += 1
        if case.expectation is MigrationExpectation.SAFE_TO_ACTIVATE:
            if result.activated and result.safe_to_activate and result.routing_verified:
                safe_activations += 1
            else:
                false_rejections += 1
        elif result.activated:
            unsafe_activations += 1
        else:
            correct_rejections += 1

    return MigrationBenchmarkReport(
        case_count=len(cases),
        expected_safe=sum(
            case.expectation is MigrationExpectation.SAFE_TO_ACTIVATE for case in cases
        ),
        expected_rejections=sum(
            case.expectation is MigrationExpectation.MUST_REJECT for case in cases
        ),
        safe_activations=safe_activations,
        unsafe_activations=unsafe_activations,
        false_rejections=false_rejections,
        correct_rejections=correct_rejections,
        routing_failures=routing_failures,
    )


def run_migration_benchmark(
    cases: tuple[MigrationBenchmarkCase, ...],
) -> tuple[tuple[MigrationCaseResult, ...], MigrationBenchmarkReport]:
    results = tuple(run_migration_case(case) for case in cases)
    return results, score_migration_results(cases, results)
