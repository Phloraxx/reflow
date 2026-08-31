from __future__ import annotations

from dataclasses import dataclass

from .compiler import CompiledAdapter, SampleValidationReport
from .contracts import ActivationState, AdapterSpec, DriftState
from .profile import StructuralProfile


@dataclass(frozen=True, slots=True)
class ApprovedAdapterVersion:
    spec: AdapterSpec
    schema_fingerprint: str
    source_columns: tuple[str, ...]
    source_type_families: tuple[tuple[str, tuple[str, ...]], ...]

    @classmethod
    def from_compiled(
        cls,
        adapter: CompiledAdapter,
        profile: StructuralProfile,
        report: SampleValidationReport,
    ) -> ApprovedAdapterVersion:
        if report.state is not ActivationState.APPROVED:
            raise ValueError("only an approved sample validation can activate an adapter")
        source_columns = tuple(
            sorted(
                mapping.source_column
                for mapping in adapter.spec.mappings
                if mapping.source_column is not None
            )
        )
        families = tuple(
            (name, profile.column(name).type_families)
            for name in source_columns
            if profile.column(name) is not None
        )
        if len(families) != len(source_columns):
            raise AssertionError("compiled adapter references a column missing from approval profile")
        return cls(
            spec=adapter.spec,
            schema_fingerprint=profile.schema_fingerprint,
            source_columns=source_columns,
            source_type_families=families,
        )


class InMemoryAdapterStore:
    def __init__(self) -> None:
        self._versions: dict[str, list[ApprovedAdapterVersion]] = {}

    def activate(self, version: ApprovedAdapterVersion) -> None:
        existing = self._versions.setdefault(version.spec.adapter_id, [])
        if existing and version.spec.version <= existing[-1].spec.version:
            raise ValueError("adapter versions must increase monotonically")
        existing.append(version)

    def latest(self, adapter_id: str) -> ApprovedAdapterVersion | None:
        versions = self._versions.get(adapter_id)
        return None if not versions else versions[-1]

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
