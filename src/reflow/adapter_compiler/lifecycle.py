from __future__ import annotations

from dataclasses import dataclass

from .compiler import CompiledAdapter, SampleValidationReport
from .contracts import (
    ActivationState,
    AdapterApprovalEvidence,
    AdapterSpec,
    ApprovalEvidenceKind,
    DriftState,
)
from .profile import StructuralProfile


@dataclass(frozen=True, slots=True)
class ApprovedAdapterVersion:
    spec: AdapterSpec
    schema_fingerprint: str
    source_columns: tuple[str, ...]
    source_type_families: tuple[tuple[str, tuple[str, ...]], ...]
    approval_evidence: AdapterApprovalEvidence

    def __post_init__(self) -> None:
        expected_columns = tuple(
            sorted(
                mapping.source_column
                for mapping in self.spec.mappings
                if mapping.source_column is not None
            )
        )
        if self.source_columns != expected_columns:
            raise ValueError("approved adapter source columns do not match its spec")
        family_names = tuple(name for name, _ in self.source_type_families)
        if family_names != self.source_columns:
            raise ValueError("approved adapter source type families do not match its columns")
        if len(self.schema_fingerprint) != 64 or any(
            char not in "0123456789abcdef" for char in self.schema_fingerprint
        ):
            raise ValueError("approved adapter schema fingerprint must be lowercase SHA-256")

    @classmethod
    def from_compiled(
        cls,
        adapter: CompiledAdapter,
        profile: StructuralProfile,
        report: SampleValidationReport,
        approval_evidence: AdapterApprovalEvidence,
    ) -> ApprovedAdapterVersion:
        if approval_evidence.kind is ApprovalEvidenceKind.OPERATOR_REVIEW:
            if report.state not in {ActivationState.APPROVED, ActivationState.NEEDS_REVIEW}:
                raise ValueError("operator review cannot authorize a rejected adapter")
        elif report.state is not ActivationState.APPROVED:
            raise ValueError("migration activation requires approved deterministic validation")
        source_columns = tuple(
            sorted(
                mapping.source_column
                for mapping in adapter.spec.mappings
                if mapping.source_column is not None
            )
        )
        family_rows: list[tuple[str, tuple[str, ...]]] = []
        for name in source_columns:
            column = profile.column(name)
            if column is None:
                raise AssertionError(
                    "compiled adapter references a column missing from approval profile"
                )
            family_rows.append((name, column.type_families))
        families = tuple(family_rows)
        return cls(
            spec=adapter.spec,
            schema_fingerprint=profile.schema_fingerprint,
            source_columns=source_columns,
            source_type_families=families,
            approval_evidence=approval_evidence,
        )


class InMemoryAdapterStore:
    def __init__(self) -> None:
        self._versions: dict[str, list[ApprovedAdapterVersion]] = {}

    def activate(self, version: ApprovedAdapterVersion) -> None:
        existing = self._versions.setdefault(version.spec.adapter_id, [])
        if existing:
            latest = existing[-1]
            if version.spec.source_kind is not latest.spec.source_kind:
                raise ValueError("adapter source kind cannot change across versions")
            if version.spec.record_kind is not latest.spec.record_kind:
                raise ValueError("adapter record kind cannot change across versions")
            if version.spec.version <= latest.spec.version:
                raise ValueError("adapter versions must increase monotonically")
        existing.append(version)

    def latest(self, adapter_id: str) -> ApprovedAdapterVersion | None:
        versions = self._versions.get(adapter_id)
        return None if not versions else versions[-1]

    def resolve_schema(
        self, adapter_id: str, schema_fingerprint: str
    ) -> ApprovedAdapterVersion | None:
        versions = self._versions.get(adapter_id, ())
        matches = [
            version for version in versions if version.schema_fingerprint == schema_fingerprint
        ]
        return None if not matches else matches[-1]

    def get_version(self, adapter_id: str, version: int) -> ApprovedAdapterVersion | None:
        matches = [
            item for item in self._versions.get(adapter_id, ()) if item.spec.version == version
        ]
        if len(matches) > 1:
            raise AssertionError("adapter store contains duplicate version identity")
        return None if not matches else matches[0]

    def versions(self, adapter_id: str) -> tuple[ApprovedAdapterVersion, ...]:
        return tuple(self._versions.get(adapter_id, ()))


def detect_drift(
    approved: ApprovedAdapterVersion | None,
    profile: StructuralProfile,
) -> DriftState:
    if approved is None:
        return DriftState.UNRECOGNIZED_SOURCE
    if approved.schema_fingerprint == profile.schema_fingerprint:
        return DriftState.KNOWN_SCHEMA

    current_columns = profile.column_names()
    required_columns = set(approved.source_columns)
    if not required_columns.issubset(current_columns):
        return DriftState.BREAKING_DRIFT

    approved_types = dict(approved.source_type_families)
    changed_types = False
    for column_name in approved.source_columns:
        current = profile.column(column_name)
        assert current is not None
        old = set(approved_types[column_name]) - {"null"}
        new = set(current.type_families) - {"null"}
        if old and new and old.isdisjoint(new):
            return DriftState.BREAKING_DRIFT
        if set(approved_types[column_name]) != set(current.type_families):
            changed_types = True

    if changed_types:
        return DriftState.REQUIRES_MIGRATION
    return DriftState.BENIGN_DRIFT
