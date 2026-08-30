from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

type RawRecord = Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ObservedBatch:
    """Normalized source transport rows before canonical financial compilation."""

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
