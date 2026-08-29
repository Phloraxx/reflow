from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from reflow.domain import SourceEnvelope, SourceEnvelopeId, SourceKind
from reflow.domain.source_hash import source_payload_sha256


class JournalConflictError(ValueError):
    """A stable source identity was reused for different raw payload evidence."""


class AppendDisposition(StrEnum):
    STORED = "stored"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class AppendResult:
    disposition: AppendDisposition
    envelope: SourceEnvelope


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
    identity = f"{source_kind.value}\0{source_record_id}\0{digest}".encode()
    envelope_id = SourceEnvelopeId(f"src_{hashlib.sha256(identity).hexdigest()[:24]}")
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
        self._records: dict[tuple[SourceKind, str], SourceEnvelope] = {}

    def append(self, envelope: SourceEnvelope) -> AppendResult:
        key = (envelope.source_kind, envelope.source_record_id)
        existing = self._records.get(key)
        if existing is None:
            self._records[key] = envelope
            return AppendResult(AppendDisposition.STORED, envelope)
        if existing.payload_sha256 == envelope.payload_sha256:
            return AppendResult(AppendDisposition.DUPLICATE, existing)
        raise JournalConflictError(
            "same source identity arrived with a different payload hash: "
            f"{envelope.source_kind.value}/{envelope.source_record_id}"
        )

    def get(self, source_kind: SourceKind, source_record_id: str) -> SourceEnvelope | None:
        return self._records.get((source_kind, source_record_id))

    def entries(self) -> tuple[SourceEnvelope, ...]:
        return tuple(
            sorted(
                self._records.values(),
                key=lambda row: (
                    row.received_at,
                    row.source_kind.value,
                    row.source_record_id,
                ),
            )
        )

    def __len__(self) -> int:
        return len(self._records)
