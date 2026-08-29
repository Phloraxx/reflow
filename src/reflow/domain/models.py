from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping, Sequence

from .types import (
    AdjustmentId,
    BankEntryId,
    Currency,
    EdgeState,
    EntityId,
    EvidenceEdgeId,
    EvidenceStrength,
    ExceptionCaseId,
    ExceptionKind,
    OrderId,
    PaymentEventKind,
    PaymentId,
    PaymentStatus,
    ProofId,
    ProofStatus,
    ReconEntityKind,
    ReconEntryId,
    RefundId,
    SettlementId,
    SourceEnvelopeId,
    SourceKind,
    TransferId,
)


def _aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _non_negative(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be int")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")


@dataclass(frozen=True, slots=True)
class Money:
    amount_paise: int
    currency: Currency = Currency.INR

    def __post_init__(self) -> None:
        if isinstance(self.amount_paise, bool) or not isinstance(self.amount_paise, int):
            raise TypeError("amount_paise must be an integer; float and bool are forbidden")
        if not isinstance(self.currency, Currency):
            raise TypeError("currency must be Currency")
        if not -(2**63) <= self.amount_paise <= 2**63 - 1:
            raise OverflowError("amount_paise must fit signed int64")

    @classmethod
    def zero(cls, currency: Currency = Currency.INR) -> Money:
        return cls(0, currency)

    def _same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise ValueError(f"currency mismatch: {self.currency} != {other.currency}")

    def __add__(self, other: Money) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        self._same_currency(other)
        return Money(self.amount_paise + other.amount_paise, self.currency)

    def __sub__(self, other: Money) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        self._same_currency(other)
        return Money(self.amount_paise - other.amount_paise, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount_paise, self.currency)

    @property
    def is_zero(self) -> bool:
        return self.amount_paise == 0


@dataclass(frozen=True, slots=True)
class SourceEnvelope:
    id: SourceEnvelopeId
    source_kind: SourceKind
    source_record_id: str
    occurred_at: datetime
    received_at: datetime
    payload_sha256: str
    schema_version: str
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _aware(self.occurred_at, "occurred_at")
        _aware(self.received_at, "received_at")
        if self.received_at < self.occurred_at:
            raise ValueError("received_at cannot precede occurred_at")
        if not self.source_record_id:
            raise ValueError("source_record_id cannot be empty")
        if len(self.payload_sha256) != 64:
            raise ValueError("payload_sha256 must be a 64-character hex digest")
        try:
            int(self.payload_sha256, 16)
        except ValueError as exc:
            raise ValueError("payload_sha256 must be hexadecimal") from exc
        if not self.schema_version:
            raise ValueError("schema_version cannot be empty")


@dataclass(frozen=True, slots=True)
class MerchantOrder:
    id: OrderId
    amount: Money
    created_at: datetime
    external_reference: str | None = None

    def __post_init__(self) -> None:
        _aware(self.created_at, "created_at")
        if self.amount.amount_paise <= 0:
            raise ValueError("order amount must be positive")


@dataclass(frozen=True, slots=True)
class PaymentEvent:
    source_event_id: str
    payment_id: PaymentId
    order_id: OrderId | None
    kind: PaymentEventKind
    amount: Money
    occurred_at: datetime
    received_at: datetime
    error_code: str | None = None
    error_reason: str | None = None

    def __post_init__(self) -> None:
        _aware(self.occurred_at, "occurred_at")
        _aware(self.received_at, "received_at")
        if self.received_at < self.occurred_at:
            raise ValueError("received_at cannot precede occurred_at")
        if not self.source_event_id:
            raise ValueError("source_event_id cannot be empty")
        if self.amount.amount_paise <= 0:
            raise ValueError("payment event amount must be positive")


@dataclass(frozen=True, slots=True)
class PaymentCurrentState:
    payment_id: PaymentId
    order_id: OrderId | None
    amount: Money
    status: PaymentStatus
    last_occurred_at: datetime
    captured_at: datetime | None = None
    refunded_amount: Money = field(default_factory=Money.zero)
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _aware(self.last_occurred_at, "last_occurred_at")
        if self.captured_at is not None:
            _aware(self.captured_at, "captured_at")
        if self.refunded_amount.currency != self.amount.currency:
            raise ValueError("refund currency must match payment currency")
        _non_negative(self.refunded_amount.amount_paise, "refunded_amount")
        if self.refunded_amount.amount_paise > self.amount.amount_paise:
            raise ValueError("refunded amount cannot exceed payment amount")


@dataclass(frozen=True, slots=True)
class Refund:
    id: RefundId
    payment_id: PaymentId
    amount: Money
    created_at: datetime

    def __post_init__(self) -> None:
        _aware(self.created_at, "created_at")
        if self.amount.amount_paise <= 0:
            raise ValueError("refund amount must be positive; direction is expressed by entity kind")


@dataclass(frozen=True, slots=True)
class Transfer:
    id: TransferId
    payment_id: PaymentId | None
    amount: Money
    created_at: datetime

    def __post_init__(self) -> None:
        _aware(self.created_at, "created_at")
        if self.amount.amount_paise == 0:
            raise ValueError("transfer amount cannot be zero")


@dataclass(frozen=True, slots=True)
class Adjustment:
    id: AdjustmentId
    amount: Money
    created_at: datetime
    reason: str

    def __post_init__(self) -> None:
        _aware(self.created_at, "created_at")
        if self.amount.amount_paise == 0:
            raise ValueError("adjustment amount cannot be zero")
        if not self.reason:
            raise ValueError("adjustment reason cannot be empty")


@dataclass(frozen=True, slots=True)
class SettlementReconEntry:
    id: ReconEntryId
    settlement_id: SettlementId
    entity_kind: ReconEntityKind
    entity_id: EntityId
    gross_amount: Money
    fee: Money
    tax: Money
    settlement_effect: Money
    occurred_at: datetime

    def __post_init__(self) -> None:
        _aware(self.occurred_at, "occurred_at")
        currencies = {
            self.gross_amount.currency,
            self.fee.currency,
            self.tax.currency,
            self.settlement_effect.currency,
        }
        if len(currencies) != 1:
            raise ValueError("all recon money fields must use one currency")
        _non_negative(self.fee.amount_paise, "fee")
        _non_negative(self.tax.amount_paise, "tax")
        expected_types: dict[ReconEntityKind, type[EntityId]] = {
            ReconEntityKind.PAYMENT: PaymentId,
            ReconEntityKind.REFUND: RefundId,
            ReconEntityKind.TRANSFER: TransferId,
            ReconEntityKind.ADJUSTMENT: AdjustmentId,
        }
        expected = expected_types[self.entity_kind]
        if not isinstance(self.entity_id, expected):
            raise TypeError(
                f"{self.entity_kind.value} recon entry requires {expected.__name__}, "
                f"got {type(self.entity_id).__name__}"
            )


@dataclass(frozen=True, slots=True)
class Settlement:
    id: SettlementId
    amount: Money
    processed_at: datetime
    utr: str | None

    def __post_init__(self) -> None:
        _aware(self.processed_at, "processed_at")
        if self.amount.amount_paise <= 0:
            raise ValueError("settlement amount must be positive")
        if self.utr is not None and not self.utr.strip():
            raise ValueError("utr cannot be blank")


@dataclass(frozen=True, slots=True)
class BankEntry:
    id: BankEntryId
    amount: Money
    occurred_at: datetime
    narration: str
    utr: str | None

    def __post_init__(self) -> None:
        _aware(self.occurred_at, "occurred_at")
        if self.amount.amount_paise == 0:
            raise ValueError("bank entry amount cannot be zero")
        if self.utr is not None and not self.utr.strip():
            raise ValueError("utr cannot be blank")


@dataclass(frozen=True, slots=True)
class EvidenceEdge:
    id: EvidenceEdgeId
    from_id: EntityId
    to_id: EntityId
    relationship: str
    strength: EvidenceStrength
    state: EdgeState
    evidence_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.relationship:
            raise ValueError("relationship cannot be empty")
        if not self.evidence_ids:
            raise ValueError("evidence edge must cite at least one evidence id")


@dataclass(frozen=True, slots=True)
class Residual:
    amount: Money
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProofVersion:
    version: int
    generated_at: datetime
    ruleset_version: str

    def __post_init__(self) -> None:
        _aware(self.generated_at, "generated_at")
        if self.version < 1:
            raise ValueError("proof version must be >= 1")
        if not self.ruleset_version:
            raise ValueError("ruleset_version cannot be empty")


@dataclass(frozen=True, slots=True)
class ReconciliationProof:
    id: ProofId
    settlement_id: SettlementId
    version: ProofVersion
    status: ProofStatus
    expected_settlement: Money
    observed_settlement: Money
    observed_bank_credit: Money | None
    residual: Residual
    component_ids: tuple[ReconEntryId, ...]
    evidence_edge_ids: tuple[EvidenceEdgeId, ...]

    def __post_init__(self) -> None:
        currency = self.expected_settlement.currency
        if self.observed_settlement.currency != currency or self.residual.amount.currency != currency:
            raise ValueError("proof money must use one currency")
        if self.observed_bank_credit is not None and self.observed_bank_credit.currency != currency:
            raise ValueError("bank proof currency must match settlement currency")
        if self.status is ProofStatus.PROVEN_RECONCILED and not self.residual.amount.is_zero:
            raise ValueError("a proven reconciliation cannot carry a non-zero residual")


@dataclass(frozen=True, slots=True)
class ExceptionCase:
    id: ExceptionCaseId
    settlement_id: SettlementId | None
    kind: ExceptionKind
    created_at: datetime
    reason_codes: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    residual: Residual | None = None
    human_summary: str | None = None

    def __post_init__(self) -> None:
        _aware(self.created_at, "created_at")
        if not self.reason_codes:
            raise ValueError("exception must preserve at least one reason code")


def sum_money(values: Sequence[Money], currency: Currency = Currency.INR) -> Money:
    total = Money.zero(currency)
    for value in values:
        total = total + value
    return total
