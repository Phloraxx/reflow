from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from reflow.domain import (
    AdjustmentId,
    BankEntry,
    BankEntryId,
    Currency,
    MerchantOrder,
    Money,
    OrderId,
    PaymentEvent,
    PaymentEventKind,
    PaymentId,
    ReconEntityKind,
    ReconEntryId,
    RefundId,
    Settlement,
    SettlementId,
    SettlementReconEntry,
    TransferId,
)
from reflow.domain.types import EntityId
from reflow.simulator.observed import ObservedBatch, RawRecord


class AdapterError(ValueError):
    """Known source did not satisfy its declared deterministic contract."""


@dataclass(frozen=True, slots=True)
class CanonicalBatch:
    orders: tuple[MerchantOrder, ...]
    payment_events: tuple[PaymentEvent, ...]
    recon_entries: tuple[SettlementReconEntry, ...]
    settlements: tuple[Settlement, ...]
    bank_entries: tuple[BankEntry, ...]


def _required(row: RawRecord, key: str) -> object:
    if key not in row:
        raise AdapterError(f"missing required field {key!r}")
    return row[key]


def _text(row: RawRecord, key: str, *, allow_none: bool = False) -> str | None:
    value = _required(row, key)
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value.strip():
        raise AdapterError(f"{key!r} must be a non-empty string")
    return value.strip()


def _optional_string(row: RawRecord, key: str) -> str | None:
    value = row.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise AdapterError(f"{key!r} must be a string or null")
    return value


def _paise(row: RawRecord, key: str, *, allow_negative: bool = True) -> int:
    value = _required(row, key)
    if isinstance(value, bool):
        raise AdapterError(f"{key!r} must be integer paise, not bool")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped or any(char in stripped for char in ".,eE"):
            raise AdapterError(f"{key!r} must be an integer-paise field")
        try:
            parsed = int(stripped)
        except ValueError as exc:
            raise AdapterError(f"{key!r} is not valid integer paise") from exc
    else:
        raise AdapterError(f"{key!r} must be integer paise")
    if not allow_negative and parsed < 0:
        raise AdapterError(f"{key!r} cannot be negative for this source")
    return parsed


def _currency(row: RawRecord, key: str = "currency") -> Currency:
    value = _text(row, key)
    assert value is not None
    try:
        return Currency(value)
    except ValueError as exc:
        raise AdapterError(f"unsupported currency {value!r}") from exc


def _time(row: RawRecord, key: str) -> datetime:
    value = _text(row, key)
    assert value is not None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise AdapterError(f"{key!r} must be an ISO-8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AdapterError(f"{key!r} must include timezone information")
    return parsed


def _optional_id(row: RawRecord, key: str, id_type: type[EntityId]) -> EntityId | None:
    value = row.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise AdapterError(f"{key!r} must be a string or null")
    try:
        return id_type(value)
    except (TypeError, ValueError) as exc:
        raise AdapterError(f"invalid {key!r}: {value!r}") from exc


def _id(row: RawRecord, key: str, id_type: type[EntityId]) -> EntityId:
    value = _text(row, key)
    assert value is not None
    try:
        return id_type(value)
    except (TypeError, ValueError) as exc:
        raise AdapterError(f"invalid {key!r}: {value!r}") from exc


def adapt_merchant_row(row: RawRecord) -> MerchantOrder:
    order_id = _id(row, "order_id", OrderId)
    assert isinstance(order_id, OrderId)
    external = _optional_string(row, "external_reference")
    amount = _paise(row, "amount_paise", allow_negative=False)
    if amount <= 0:
        raise AdapterError("merchant order amount must be positive")
    return MerchantOrder(
        id=order_id,
        amount=Money(amount, _currency(row)),
        created_at=_time(row, "created_at"),
        external_reference=external,
    )


def adapt_payment_event(row: RawRecord) -> PaymentEvent:
    payment_id = _id(row, "payment_id", PaymentId)
    assert isinstance(payment_id, PaymentId)
    order_id = _optional_id(row, "order_id", OrderId)
    assert order_id is None or isinstance(order_id, OrderId)
    kind_text = _text(row, "event_kind")
    assert kind_text is not None
    try:
        kind = PaymentEventKind(kind_text)
    except ValueError as exc:
        raise AdapterError(f"unsupported payment event kind {kind_text!r}") from exc
    amount = _paise(row, "amount_paise", allow_negative=False)
    if amount <= 0:
        raise AdapterError("payment event amount must be positive")
    event_id = _text(row, "event_id")
    assert event_id is not None
    return PaymentEvent(
        source_event_id=event_id,
        payment_id=payment_id,
        order_id=order_id,
        kind=kind,
        amount=Money(amount, _currency(row)),
        occurred_at=_time(row, "occurred_at"),
        received_at=_time(row, "received_at"),
        error_code=_optional_string(row, "error_code"),
        error_reason=_optional_string(row, "error_reason"),
    )


def _recon_entity_id(row: RawRecord, kind: ReconEntityKind) -> EntityId:
    id_types: dict[ReconEntityKind, type[EntityId]] = {
        ReconEntityKind.PAYMENT: PaymentId,
        ReconEntityKind.REFUND: RefundId,
        ReconEntityKind.TRANSFER: TransferId,
        ReconEntityKind.ADJUSTMENT: AdjustmentId,
    }
    return _id(row, "entity_id", id_types[kind])


def _validate_recon_signs(
    kind: ReconEntityKind,
    gross: int,
    fee: int,
    tax: int,
    effect: int,
) -> None:
    if fee < 0 or tax < 0:
        raise AdapterError("recon fee and tax must be non-negative")
    if kind is ReconEntityKind.PAYMENT:
        if gross <= 0 or effect != gross - fee - tax:
            raise AdapterError("payment recon sign/arithmetic invariant failed")
    elif kind is ReconEntityKind.REFUND:
        if gross >= 0 or effect > 0:
            raise AdapterError("refund recon must reduce settlement value")
    elif fee != 0 or tax != 0 or effect != gross:
        raise AdapterError("transfer/adjustment recon must carry direct signed effect")


def adapt_recon_row(row: RawRecord) -> SettlementReconEntry:
    kind_text = _text(row, "entity_kind")
    assert kind_text is not None
    try:
        kind = ReconEntityKind(kind_text)
    except ValueError as exc:
        raise AdapterError(f"unsupported recon entity kind {kind_text!r}") from exc
    gross = _paise(row, "gross_amount_paise")
    fee = _paise(row, "fee_paise", allow_negative=False)
    tax = _paise(row, "tax_paise", allow_negative=False)
    effect = _paise(row, "settlement_effect_paise")
    _validate_recon_signs(kind, gross, fee, tax, effect)
    recon_id = _id(row, "recon_id", ReconEntryId)
    settlement_id = _id(row, "settlement_id", SettlementId)
    assert isinstance(recon_id, ReconEntryId)
    assert isinstance(settlement_id, SettlementId)
    currency = _currency(row)
    return SettlementReconEntry(
        id=recon_id,
        settlement_id=settlement_id,
        entity_kind=kind,
        entity_id=_recon_entity_id(row, kind),
        gross_amount=Money(gross, currency),
        fee=Money(fee, currency),
        tax=Money(tax, currency),
        settlement_effect=Money(effect, currency),
        occurred_at=_time(row, "occurred_at"),
    )


def adapt_settlement_row(row: RawRecord) -> Settlement:
    settlement_id = _id(row, "settlement_id", SettlementId)
    assert isinstance(settlement_id, SettlementId)
    amount = _paise(row, "amount_paise", allow_negative=False)
    if amount <= 0:
        raise AdapterError("settlement amount must be positive")
    utr_value = _optional_string(row, "utr")
    if utr_value is not None and not utr_value.strip():
        raise AdapterError("settlement UTR cannot be blank")
    return Settlement(
        id=settlement_id,
        amount=Money(amount, _currency(row)),
        processed_at=_time(row, "processed_at"),
        utr=utr_value.strip() if utr_value is not None else None,
    )


def adapt_bank_row(row: RawRecord) -> BankEntry:
    bank_id = _id(row, "bank_entry_id", BankEntryId)
    assert isinstance(bank_id, BankEntryId)
    amount = _paise(row, "amount_paise", allow_negative=False)
    if amount <= 0:
        raise AdapterError("bank settlement-credit feed requires a positive credit")
    narration = _text(row, "narration")
    assert narration is not None
    utr_value = _optional_string(row, "utr")
    return BankEntry(
        id=bank_id,
        amount=Money(amount, _currency(row)),
        occurred_at=_time(row, "occurred_at"),
        narration=narration,
        utr=utr_value.strip() if utr_value is not None and utr_value.strip() else None,
    )


def adapt_observed_batch(batch: ObservedBatch) -> CanonicalBatch:
    return CanonicalBatch(
        orders=tuple(adapt_merchant_row(row) for row in batch.merchant_rows),
        payment_events=tuple(adapt_payment_event(row) for row in batch.razorpay_events),
        recon_entries=tuple(adapt_recon_row(row) for row in batch.recon_rows),
        settlements=tuple(adapt_settlement_row(row) for row in batch.settlement_rows),
        bank_entries=tuple(adapt_bank_row(row) for row in batch.bank_rows),
    )
