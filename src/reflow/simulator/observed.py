from __future__ import annotations

from dataclasses import dataclass

from reflow.ingestion.records import ObservedBatch


@dataclass(frozen=True, slots=True)
class CorruptionRecord:
    kind: str
    source: str
    target_id: str
    detail: str


@dataclass(frozen=True, slots=True)
class ObservationBundle:
    observed: ObservedBatch
    manifest: tuple[CorruptionRecord, ...]
