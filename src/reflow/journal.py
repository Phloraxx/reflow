from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from reflow.domain import SourceEnvelope, SourceEnvelopeId, SourceKind
from reflow.domain.source_hash import source_envelope_id_value, source_payload_sha256


class JournalConflictError(ValueError):
    """A stable source identity was reused for different raw payload evidence."""


class AppendDisposition(StrEnum):
    STORED = "stored"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class AppendResult:
    disposition: AppendDisposition
    envelope: SourceEnvelope


@runtime_checkable
class Journal(Protocol):
    """Append-only raw-evidence journal contract used by deterministic production paths."""

    def append(self, envelope: SourceEnvelope) -> AppendResult: ...

    def get(self, source_kind: SourceKind, source_record_id: str) -> SourceEnvelope | None: ...

    def get_by_id(self, envelope_id: SourceEnvelopeId) -> SourceEnvelope | None: ...

    def entries(self) -> tuple[SourceEnvelope, ...]: ...

    def __len__(self) -> int: ...


def payload_sha256(payload: Mapping[str, object]) -> str:
    try:
        return source_payload_sha256(payload)
    except (TypeError, ValueError) as exc:
        raise TypeError("source payload must be deterministic JSON data") from exc


def make_source_envelope(
    *,
    source_kind: SourceKind,
    source_record_id: str,
    occurred_at: datetime | None,
    received_at: datetime,
    schema_version: str,
    payload: Mapping[str, object],
) -> SourceEnvelope:
    digest = payload_sha256(payload)
    envelope_id = SourceEnvelopeId(
        source_envelope_id_value(source_kind.value, source_record_id, digest)
    )
    return SourceEnvelope(
        id=envelope_id,
        source_kind=source_kind,
        source_record_id=source_record_id,
        occurred_at=occurred_at,
        received_at=received_at,
        payload_sha256=digest,
        schema_version=schema_version,
        payload=payload,
    )


class InMemoryJournal:
    """Append-only reference journal used before a persistence backend is selected."""

    def __init__(self) -> None:
        self._primary_by_identity: dict[tuple[SourceKind, str], SourceEnvelope] = {}
        self._records_by_id: dict[SourceEnvelopeId, SourceEnvelope] = {}

    def append(self, envelope: SourceEnvelope) -> AppendResult:
        key = (envelope.source_kind, envelope.source_record_id)
        primary = self._primary_by_identity.get(key)
        if primary is None:
            self._primary_by_identity[key] = envelope
            self._records_by_id[envelope.id] = envelope
            return AppendResult(AppendDisposition.STORED, envelope)

        if primary.payload_sha256 == envelope.payload_sha256:
            return AppendResult(AppendDisposition.DUPLICATE, primary)

        # A conflicting source version is still evidence. Preserve it before failing closed.
        self._records_by_id.setdefault(envelope.id, envelope)
        raise JournalConflictError(
            "same source identity arrived with a different payload hash: "
            f"{envelope.source_kind.value}/{envelope.source_record_id}"
        )

    def get(self, source_kind: SourceKind, source_record_id: str) -> SourceEnvelope | None:
        """Return the first retained source fact for a stable source identity."""
        return self._primary_by_identity.get((source_kind, source_record_id))

    def get_by_id(self, envelope_id: SourceEnvelopeId) -> SourceEnvelope | None:
        """Return an exact retained envelope by immutable evidence identity."""
        return self._records_by_id.get(envelope_id)

    def entries(self) -> tuple[SourceEnvelope, ...]:
        return tuple(
            sorted(
                self._records_by_id.values(),
                key=lambda row: (
                    row.received_at,
                    row.source_kind.value,
                    row.source_record_id,
                    str(row.id),
                ),
            )
        )

    def __len__(self) -> int:
        return len(self._records_by_id)
