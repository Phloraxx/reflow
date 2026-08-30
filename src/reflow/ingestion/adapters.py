from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

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
    SourceEnvelopeId,
    SourceKind,
    TransferId,
)
from reflow.domain.types import EntityId

from .records import ObservedBatch, RawRecord


class AdapterError(ValueError):
    """Known source did not satisfy its declared deterministic contract."""


type SourceIdentity = tuple[SourceKind, str]

_CANONICAL_CONTRACT_VERSION = "normalized-fixture-canonical-v1"


@dataclass(frozen=True, slots=True)
class SourceLink:
    source_kind: SourceKind
    source_record_id: str
    envelope_id: SourceEnvelopeId

    @property
    def identity(self) -> SourceIdentity:
        return (self.source_kind, self.source_record_id)


def _canonical_json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"unsupported canonical digest value {type(value).__name__}")


def _feed_digest_rows(
    digest: Any,
    label: str,
    rows: Iterable[Any],
) -> None:
    digest.update(label.encode())
    digest.update(b"\0")
    for row in rows:
        encoded = json.dumps(
            asdict(row),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
            default=_canonical_json_default,
        ).encode()
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)


def _canonical_compilation_sha256(
    *,
    orders: tuple[MerchantOrder, ...],
    payment_events: tuple[PaymentEvent, ...],
    recon_entries: tuple[SettlementReconEntry, ...],
    settlements: tuple[Settlement, ...],
    bank_entries: tuple[BankEntry, ...],
    source_links: tuple[SourceLink, ...],
) -> str:
    digest = hashlib.sha256()
    digest.update(_CANONICAL_CONTRACT_VERSION.encode())
    digest.update(b"\0")
    # Compilation identity is about retained source facts, not source delivery order.
    _feed_digest_rows(digest, "orders", sorted(orders, key=lambda row: str(row.id)))
    _feed_digest_rows(
        digest,
        "payment_events",
        sorted(payment_events, key=lambda row: row.source_event_id),
    )
    _feed_digest_rows(
        digest, "recon_entries", sorted(recon_entries, key=lambda row: str(row.id))
    )
    _feed_digest_rows(
        digest, "settlements", sorted(settlements, key=lambda row: str(row.id))
    )
    _feed_digest_rows(
        digest, "bank_entries", sorted(bank_entries, key=lambda row: str(row.id))
    )
    _feed_digest_rows(
        digest,
        "source_links",
        sorted(
            source_links,
            key=lambda row: (
                row.source_kind.value,
                row.source_record_id,
                str(row.envelope_id),
            ),
        ),
    )
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class CanonicalBatch:
    orders: tuple[MerchantOrder, ...]
    payment_events: tuple[PaymentEvent, ...]
    recon_entries: tuple[SettlementReconEntry, ...]
    settlements: tuple[Settlement, ...]
    bank_entries: tuple[BankEntry, ...]
    source_links: tuple[SourceLink, ...] = ()
    compilation_sha256: str | None = None

    def __post_init__(self) -> None:
        if not self.source_links:
            if self.compilation_sha256 is not None:
                raise ValueError("unbound canonical batch cannot carry a compilation digest")
            return

        indexed: dict[SourceIdentity, SourceEnvelopeId] = {}
        for link in self.source_links:
            if link.identity in indexed:
                raise ValueError(
                    "canonical batch contains duplicate source provenance identity: "
                    f"{link.source_kind.value}/{link.source_record_id}"
                )
            indexed[link.identity] = link.envelope_id

        expected: set[SourceIdentity] = set()
        expected.update((SourceKind.MERCHANT, str(row.id)) for row in self.orders)
        expected.update(
            (SourceKind.RAZORPAY_EVENT, row.source_event_id)
            for row in self.payment_events
        )
        expected.update(
            (SourceKind.RAZORPAY_RECON, str(row.id)) for row in self.recon_entries
        )
        expected.update(
            (SourceKind.RAZORPAY_SETTLEMENT, str(row.id)) for row in self.settlements
        )
        expected.update((SourceKind.BANK, str(row.id)) for row in self.bank_entries)

        canonical_count = (
            len(self.orders)
            + len(self.payment_events)
            + len(self.recon_entries)
            + len(self.settlements)
            + len(self.bank_entries)
        )
        if canonical_count != len(expected):
            raise ValueError("journal-backed canonical batch contains duplicate source identities")

        actual = set(indexed)
        missing = expected - actual
        extra = actual - expected
        if missing or extra:
            detail: list[str] = []
            if missing:
                detail.append(
                    "missing="
                    + ",".join(
                        f"{kind.value}/{record_id}"
                        for kind, record_id in sorted(
                            missing, key=lambda item: (item[0].value, item[1])
                        )
                    )
                )
            if extra:
                detail.append(
                    "extra="
                    + ",".join(
                        f"{kind.value}/{record_id}"
                        for kind, record_id in sorted(
                            extra, key=lambda item: (item[0].value, item[1])
                        )
                    )
                )
            raise ValueError("canonical source provenance mismatch: " + "; ".join(detail))

        if self.compilation_sha256 is None:
            raise ValueError("journal-backed canonical batch requires compilation integrity")
        expected_digest = _canonical_compilation_sha256(
            orders=self.orders,
            payment_events=self.payment_events,
            recon_entries=self.recon_entries,
            settlements=self.settlements,
            bank_entries=self.bank_entries,
            source_links=self.source_links,
        )
        if self.compilation_sha256 != expected_digest:
            raise ValueError("canonical batch facts no longer match its compiled source binding")

    def source_index(self) -> dict[SourceIdentity, SourceEnvelopeId]:
        return {link.identity: link.envelope_id for link in self.source_links}

    def _bind_source_links(self, source_links: tuple[SourceLink, ...]) -> CanonicalBatch:
        if self.source_links or self.compilation_sha256 is not None:
            raise ValueError("canonical batch is already bound to source provenance")
        digest = _canonical_compilation_sha256(
            orders=self.orders,
            payment_events=self.payment_events,
            recon_entries=self.recon_entries,
            settlements=self.settlements,
            bank_entries=self.bank_entries,
            source_links=source_links,
        )
        return CanonicalBatch(
            orders=self.orders,
            payment_events=self.payment_events,
            recon_entries=self.recon_entries,
            settlements=self.settlements,
            bank_entries=self.bank_entries,
            source_links=source_links,
            compilation_sha256=digest,
        )


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
    """Validate the normalized synthetic fixture contract, not raw Razorpay Recon fields."""
    if fee < 0 or tax < 0:
        raise AdapterError("recon fee and tax must be non-negative")
    if kind is ReconEntityKind.PAYMENT:
        if gross <= 0 or effect != gross - fee - tax:
            raise AdapterError("payment recon sign/arithmetic invariant failed")
    elif kind is ReconEntityKind.REFUND:
        if gross >= 0 or fee != 0 or tax != 0 or effect != gross:
            raise AdapterError("refund recon sign/arithmetic invariant failed")
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
