from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

RawRecord: TypeAlias = dict[str, object]


@dataclass(frozen=True, slots=True)
class ObservedBatch:
    merchant_rows: tuple[RawRecord, ...]
    razorpay_events: tuple[RawRecord, ...]
    recon_rows: tuple[RawRecord, ...]
    settlement_rows: tuple[RawRecord, ...]
    bank_rows: tuple[RawRecord, ...]

    @property
    def record_count(self) -> int:
        return (
            len(self.merchant_rows)
            + len(self.razorpay_events)
            + len(self.recon_rows)
            + len(self.settlement_rows)
            + len(self.bank_rows)
        )


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
