from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from reflow import domain
from reflow.ingestion import CanonicalBatch, SourceLink
from reflow.journal import (
    AppendResult,
    InMemoryJournal,
    JournalConflictError,
    make_source_envelope,
)

__all__ = [
    "RazorpayAccountContext",
    "RazorpayEvidenceOrigin",
    "RazorpayIntegrationError",
    "compile_payment_webhook",
    "compile_recon_items",
    "compile_settlement_api_entity",
    "compile_settlement_webhook",
]


class RazorpayIntegrationError(ValueError):
    """Provider-shaped Razorpay evidence violates the Gate 15 contract."""


class RazorpayEvidenceOrigin(StrEnum):
    SYNTHETIC = "synthetic"
    PROVIDER_DOC_FIXTURE = "provider_doc_fixture"
    REAL_TEST_MODE = "real_test_mode"
    REAL_LIVE = "real_live"


@dataclass(frozen=True, slots=True)
class RazorpayAccountContext:
    account_id: str
    evidence_origin: RazorpayEvidenceOrigin
    settlement_currency: domain.Currency = domain.Currency.INR

    def __post_init__(self) -> None:
        if not isinstance(self.account_id, str) or not self.account_id.strip():
            raise RazorpayIntegrationError("Razorpay account id must be a non-empty string")
        if self.account_id != self.account_id.strip():
            raise RazorpayIntegrationError("Razorpay account id must be trimmed")
        if not isinstance(self.evidence_origin, RazorpayEvidenceOrigin):
            raise TypeError("evidence_origin must be RazorpayEvidenceOrigin")
        if self.evidence_origin is RazorpayEvidenceOrigin.SYNTHETIC:
            raise RazorpayIntegrationError(
                "synthetic evidence belongs to normalized ingestion, not the provider integration"
            )
        if not isinstance(self.settlement_currency, domain.Currency):
            raise TypeError("settlement_currency must be Currency")


def _aware(value: datetime, label: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{label} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise RazorpayIntegrationError(f"{label} must be timezone-aware")


def _non_empty_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RazorpayIntegrationError(f"{label} must be a non-empty string")
    if value != value.strip():
        raise RazorpayIntegrationError(f"{label} must be trimmed")
    return value


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RazorpayIntegrationError(f"{label} must be string or null")
    stripped = value.strip()
    return stripped or None


def _integer(value: object, label: str, *, non_negative: bool = True) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RazorpayIntegrationError(f"{label} must be integer subunits")
    if non_negative and value < 0:
        raise RazorpayIntegrationError(f"{label} cannot be negative")
    return value


def _timestamp(value: object, label: str) -> datetime:
    seconds = _integer(value, label)
    try:
        return datetime.fromtimestamp(seconds, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise RazorpayIntegrationError(f"{label} is outside supported timestamp range") from exc


def _currency(value: object) -> domain.Currency:
    text = _non_empty_text(value, "currency")
    try:
        return domain.Currency(text)
    except ValueError as exc:
        raise RazorpayIntegrationError(f"unsupported currency {text!r}") from exc


def _safe_timestamp(value: object, label: str) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    try:
        return _timestamp(value, label)
    except RazorpayIntegrationError:
        return None


def _settlement_currency(
    entity: Mapping[str, object], context: RazorpayAccountContext
) -> domain.Currency:
    supplied = entity.get("currency")
    if supplied is None:
        return context.settlement_currency
    parsed = _currency(supplied)
    if parsed is not context.settlement_currency:
        raise RazorpayIntegrationError(
            "settlement payload currency does not match Razorpay account context"
        )
    return parsed


def _header(headers: Mapping[str, str], name: str) -> str | None:
    target = name.casefold()
    for key, value in headers.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise TypeError("webhook headers must map strings to strings")
        if key.casefold() == target:
            return value.strip() or None
    return None


def _verify_webhook(
    *,
    raw_body: bytes,
    headers: Mapping[str, str],
    webhook_secret: str,
) -> tuple[str, str]:
    if not isinstance(raw_body, bytes):
        raise TypeError("raw webhook body must be bytes")
    secret = _non_empty_text(webhook_secret, "webhook secret")
    signature = _header(headers, "X-Razorpay-Signature")
    if signature is None:
        raise RazorpayIntegrationError("missing Razorpay webhook signature")
    event_id = _header(headers, "x-razorpay-event-id")
    if event_id is None:
        raise RazorpayIntegrationError("missing Razorpay webhook event id")
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise RazorpayIntegrationError("Razorpay webhook signature verification failed")
    return event_id, signature


def _parse_event(raw_body: bytes) -> Mapping[str, object]:
    try:
        value = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RazorpayIntegrationError("signed webhook body is not valid JSON") from exc
    if not isinstance(value, dict):
        raise RazorpayIntegrationError("Razorpay webhook body must be a JSON object")
    return value


def _require_event_account(event: Mapping[str, object], context: RazorpayAccountContext) -> None:
    account_id = _non_empty_text(event.get("account_id"), "webhook account_id")
    if account_id != context.account_id:
        raise RazorpayIntegrationError("webhook account does not match Razorpay account context")


def _webhook_payload(
    *,
    raw_body: bytes,
    event_id: str,
    signature: str,
    context: RazorpayAccountContext,
) -> dict[str, object]:
    return {
        "provider": "razorpay",
        "evidence_origin": context.evidence_origin.value,
        "account_id": context.account_id,
        "settlement_currency": context.settlement_currency.value,
        "x_razorpay_event_id": event_id,
        "x_razorpay_signature": signature,
        "raw_body_base64": base64.b64encode(raw_body).decode("ascii"),
    }


def _append_webhook(
    *,
    source_kind: domain.SourceKind,
    schema_version: str,
    raw_body: bytes,
    event: Mapping[str, object],
    event_id: str,
    signature: str,
    context: RazorpayAccountContext,
    journal: InMemoryJournal,
    received_at: datetime,
) -> AppendResult:
    occurred_at = _safe_timestamp(event.get("created_at"), "webhook created_at")
    return journal.append(
        make_source_envelope(
            source_kind=source_kind,
            source_record_id=event_id,
            occurred_at=occurred_at,
            received_at=received_at,
            schema_version=schema_version,
            payload=_webhook_payload(
                raw_body=raw_body,
                event_id=event_id,
                signature=signature,
                context=context,
            ),
        )
    )


def _retained_webhook_event(envelope: domain.SourceEnvelope) -> Mapping[str, object]:
    encoded = envelope.payload.get("raw_body_base64")
    if not isinstance(encoded, str):
        raise AssertionError("Gate 15 webhook envelope lost raw body")
    try:
        raw_body = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise AssertionError("Gate 15 webhook envelope raw body is corrupt") from exc
    return _parse_event(raw_body)


def _require_webhook_event_shape(event: Mapping[str, object], expected_entity: str) -> None:
    if event.get("entity") != "event":
        raise RazorpayIntegrationError("Razorpay webhook event envelope must identify an event")
    contains = event.get("contains")
    if not isinstance(contains, list) or expected_entity not in contains:
        raise RazorpayIntegrationError(
            f"Razorpay webhook event envelope must contain {expected_entity!r}"
        )


def _payload_entity(event: Mapping[str, object], key: str) -> Mapping[str, object]:
    payload = event.get("payload")
    if not isinstance(payload, Mapping):
        raise RazorpayIntegrationError("webhook payload must be an object")
    wrapper = payload.get(key)
    if not isinstance(wrapper, Mapping):
        raise RazorpayIntegrationError(f"webhook payload is missing {key!r} entity wrapper")
    entity = wrapper.get("entity")
    if not isinstance(entity, Mapping):
        raise RazorpayIntegrationError(f"webhook payload {key!r} entity must be an object")
    return entity


_PAYMENT_EVENT_KINDS = {
    "payment.authorized": domain.PaymentEventKind.AUTHORIZED,
    "payment.captured": domain.PaymentEventKind.CAPTURED,
    "payment.failed": domain.PaymentEventKind.FAILED,
}


def compile_payment_webhook(
    *,
    raw_body: bytes,
    headers: Mapping[str, str],
    webhook_secret: str,
    context: RazorpayAccountContext,
    journal: InMemoryJournal,
    received_at: datetime,
) -> CanonicalBatch:
    if not isinstance(context, RazorpayAccountContext):
        raise TypeError("context must be RazorpayAccountContext")
    if not isinstance(journal, InMemoryJournal):
        raise TypeError("journal must be InMemoryJournal")
    _aware(received_at, "received_at")
    event_id, signature = _verify_webhook(
        raw_body=raw_body,
        headers=headers,
        webhook_secret=webhook_secret,
    )
    parsed = _parse_event(raw_body)
    _require_event_account(parsed, context)
    result = _append_webhook(
        source_kind=domain.SourceKind.RAZORPAY_EVENT,
        schema_version="razorpay-payment-webhook-v1",
        raw_body=raw_body,
        event=parsed,
        event_id=event_id,
        signature=signature,
        context=context,
        journal=journal,
        received_at=received_at,
    )
    event = _retained_webhook_event(result.envelope)
    _require_webhook_event_shape(event, "payment")
    event_name = _non_empty_text(event.get("event"), "webhook event")
    kind = _PAYMENT_EVENT_KINDS.get(event_name)
    if kind is None:
        raise RazorpayIntegrationError(f"unsupported payment webhook event {event_name!r}")
    payment = _payload_entity(event, "payment")
    if payment.get("entity") != "payment":
        raise RazorpayIntegrationError("payment webhook entity must identify a payment")
    try:
        payment_id = domain.PaymentId(_non_empty_text(payment.get("id"), "payment id"))
    except (TypeError, ValueError) as exc:
        raise RazorpayIntegrationError("invalid Razorpay payment id") from exc
    order_raw = payment.get("order_id")
    if order_raw is None:
        order_id = None
    else:
        try:
            order_id = domain.OrderId(_non_empty_text(order_raw, "order id"))
        except (TypeError, ValueError) as exc:
            raise RazorpayIntegrationError("invalid Razorpay order id") from exc
    amount = _integer(payment.get("amount"), "payment amount")
    if amount <= 0:
        raise RazorpayIntegrationError("payment amount must be positive")
    occurred_at = _timestamp(event.get("created_at"), "webhook created_at")
    payment_event = domain.PaymentEvent(
        source_event_id=event_id,
        payment_id=payment_id,
        order_id=order_id,
        kind=kind,
        amount=domain.Money(amount, _currency(payment.get("currency"))),
        occurred_at=occurred_at,
        received_at=result.envelope.received_at,
        error_code=_optional_text(payment.get("error_code"), "payment error_code"),
        error_reason=_optional_text(payment.get("error_reason"), "payment error_reason"),
    )
    link = SourceLink(
        source_kind=domain.SourceKind.RAZORPAY_EVENT,
        source_record_id=event_id,
        envelope_id=result.envelope.id,
        canonical_record_id=event_id,
    )
    return CanonicalBatch(
        orders=(),
        payment_events=(payment_event,),
        recon_entries=(),
        settlements=(),
        bank_entries=(),
    )._bind_source_links((link,))


def _recon_raw_identity(
    item: Mapping[str, object], context: RazorpayAccountContext
) -> tuple[str, str, str, str]:
    settlement_id = _non_empty_text(item.get("settlement_id"), "recon settlement_id")
    kind = _non_empty_text(item.get("type"), "recon type")
    entity_id = _non_empty_text(item.get("entity_id"), "recon entity_id")
    source_record_id = f"{context.account_id}:{settlement_id}:{kind}:{entity_id}"
    return source_record_id, settlement_id, kind, entity_id


def _recon_payload(
    item: Mapping[str, object], context: RazorpayAccountContext
) -> dict[str, object]:
    return {
        "provider": "razorpay",
        "evidence_origin": context.evidence_origin.value,
        "account_id": context.account_id,
        "item": dict(item),
    }


def _recon_id(
    *,
    account_id: str,
    settlement_id: str,
    kind: str,
    entity_id: str,
) -> domain.ReconEntryId:
    material = f"{account_id}\0{settlement_id}\0{kind}\0{entity_id}".encode()
    return domain.ReconEntryId(f"recon_{hashlib.sha256(material).hexdigest()[:24]}")


def _recon_entity(kind: str, entity_id: str) -> tuple[domain.ReconEntityKind, domain.EntityId]:
    mapping: dict[str, tuple[domain.ReconEntityKind, type[domain.EntityId]]] = {
        "payment": (domain.ReconEntityKind.PAYMENT, domain.PaymentId),
        "refund": (domain.ReconEntityKind.REFUND, domain.RefundId),
        "transfer": (domain.ReconEntityKind.TRANSFER, domain.TransferId),
        "adjustment": (domain.ReconEntityKind.ADJUSTMENT, domain.AdjustmentId),
    }
    selected = mapping.get(kind)
    if selected is None:
        raise RazorpayIntegrationError(f"unsupported Razorpay recon type {kind!r}")
    entity_kind, id_type = selected
    try:
        typed_id = id_type(entity_id)
    except (TypeError, ValueError) as exc:
        raise RazorpayIntegrationError(
            "recon entity id prefix does not agree with provider entity type"
        ) from exc
    return entity_kind, typed_id


def _retained_recon_item(envelope: domain.SourceEnvelope) -> Mapping[str, object]:
    item = envelope.payload.get("item")
    if not isinstance(item, Mapping):
        raise AssertionError("Gate 15 recon envelope lost raw provider item")
    return item


def _normalize_recon_item(
    *,
    item: Mapping[str, object],
    context: RazorpayAccountContext,
    raw_identity: tuple[str, str, str, str],
) -> domain.SettlementReconEntry:
    _, settlement_text, kind_text, entity_text = raw_identity
    try:
        settlement_id = domain.SettlementId(settlement_text)
    except (TypeError, ValueError) as exc:
        raise RazorpayIntegrationError("recon requires a standard setl_ settlement id") from exc
    entity_kind, entity_id = _recon_entity(kind_text, entity_text)
    debit = _integer(item.get("debit"), "recon debit")
    credit = _integer(item.get("credit"), "recon credit")
    if (debit > 0) == (credit > 0):
        raise RazorpayIntegrationError(
            "recon requires exactly one positive debit or credit direction"
        )
    amount = _integer(item.get("amount"), "recon amount")
    if amount <= 0:
        raise RazorpayIntegrationError("recon amount must be positive")
    fee = _integer(item.get("fee"), "recon fee")
    tax = _integer(item.get("tax"), "recon tax")
    if item.get("settled") is not True:
        raise RazorpayIntegrationError("recon item must be settled before composition")
    currency = _currency(item.get("currency"))
    if entity_kind is domain.ReconEntityKind.PAYMENT:
        if credit <= 0:
            raise RazorpayIntegrationError("payment recon must contribute a provider credit")
        gross = amount
    elif entity_kind is domain.ReconEntityKind.REFUND:
        if debit <= 0:
            raise RazorpayIntegrationError("refund recon must contribute a provider debit")
        gross = -amount
    else:
        gross = amount if credit > 0 else -amount
    effect = credit - debit
    return domain.SettlementReconEntry(
        id=_recon_id(
            account_id=context.account_id,
            settlement_id=settlement_text,
            kind=kind_text,
            entity_id=entity_text,
        ),
        settlement_id=settlement_id,
        entity_kind=entity_kind,
        entity_id=entity_id,
        gross_amount=domain.Money(gross, currency),
        fee=domain.Money(fee, currency),
        tax=domain.Money(tax, currency),
        settlement_effect=domain.Money(effect, currency),
        occurred_at=_timestamp(item.get("settled_at"), "recon settled_at"),
        settlement_utr=_optional_text(item.get("settlement_utr"), "recon settlement_utr"),
    )


def compile_recon_items(
    *,
    items: Sequence[Mapping[str, object]],
    context: RazorpayAccountContext,
    journal: InMemoryJournal,
    received_at: datetime,
) -> CanonicalBatch:
    if not isinstance(context, RazorpayAccountContext):
        raise TypeError("context must be RazorpayAccountContext")
    if not isinstance(journal, InMemoryJournal):
        raise TypeError("journal must be InMemoryJournal")
    _aware(received_at, "received_at")
    if isinstance(items, (str, bytes)) or not isinstance(items, Sequence):
        raise TypeError("recon items must be a sequence of provider objects")

    # Phase 1: retain every safely identifiable provider row before interpreting semantics.
    retained_rows: list[tuple[tuple[str, str, str, str], str, domain.SourceEnvelope]] = []
    first_retention_failure: Exception | None = None
    for supplied in items:
        if not isinstance(supplied, Mapping):
            if first_retention_failure is None:
                first_retention_failure = RazorpayIntegrationError(
                    "each recon item must be an object"
                )
            continue
        try:
            raw_identity = _recon_raw_identity(supplied, context)
        except RazorpayIntegrationError as exc:
            if first_retention_failure is None:
                first_retention_failure = exc
            continue
        source_record_id, _, _, _ = raw_identity
        envelope = make_source_envelope(
            source_kind=domain.SourceKind.RAZORPAY_RECON,
            source_record_id=source_record_id,
            occurred_at=_safe_timestamp(supplied.get("settled_at"), "recon settled_at"),
            received_at=received_at,
            schema_version="razorpay-settlement-recon-provider-v1",
            payload=_recon_payload(supplied, context),
        )
        try:
            result = journal.append(envelope)
        except JournalConflictError as exc:
            # The journal retains the conflicting envelope before raising. Keep scanning so
            # later identifiable rows from the same provider response are not lost.
            if first_retention_failure is None:
                first_retention_failure = exc
            continue
        retained_rows.append((raw_identity, source_record_id, result.envelope))

    if first_retention_failure is not None:
        raise first_retention_failure

    # Phase 2: normalize only from retained immutable provider evidence.
    entries: dict[domain.ReconEntryId, domain.SettlementReconEntry] = {}
    links: dict[domain.ReconEntryId, SourceLink] = {}
    for raw_identity, source_record_id, envelope in retained_rows:
        retained = _retained_recon_item(envelope)
        retained_identity = _recon_raw_identity(retained, context)
        if retained_identity != raw_identity:
            raise AssertionError("retained provider recon identity changed after journaling")
        entry = _normalize_recon_item(
            item=retained,
            context=context,
            raw_identity=retained_identity,
        )
        link = SourceLink(
            source_kind=domain.SourceKind.RAZORPAY_RECON,
            source_record_id=source_record_id,
            envelope_id=envelope.id,
            canonical_record_id=str(entry.id),
        )
        prior_entry = entries.get(entry.id)
        if prior_entry is not None and prior_entry != entry:
            raise RazorpayIntegrationError(
                "provider recon identity produced conflicting canonical fact"
            )
        entries[entry.id] = entry
        links[entry.id] = link
    ordered_ids = tuple(sorted(entries, key=str))
    return CanonicalBatch(
        orders=(),
        payment_events=(),
        recon_entries=tuple(entries[value] for value in ordered_ids),
        settlements=(),
        bank_entries=(),
    )._bind_source_links(tuple(links[value] for value in ordered_ids))


def _normalize_standard_settlement(
    *,
    entity: Mapping[str, object],
    context: RazorpayAccountContext,
    processed_at: datetime,
) -> domain.Settlement:
    if entity.get("entity") != "settlement":
        raise RazorpayIntegrationError("settlement entity must identify a settlement")
    if entity.get("status") != "processed":
        raise RazorpayIntegrationError(
            "settlement entity must be processed before canonicalization"
        )
    settlement_text = _non_empty_text(entity.get("id"), "settlement id")
    try:
        settlement_id = domain.SettlementId(settlement_text)
    except (TypeError, ValueError) as exc:
        raise RazorpayIntegrationError("standard settlement compiler requires setl_ id") from exc
    amount = _integer(entity.get("amount"), "settlement amount")
    if amount <= 0:
        raise RazorpayIntegrationError("settlement amount must be positive")
    # Razorpay's standard settlement entity exposes created_at but not a processed_at field.
    # Validate the provider timestamp without pretending it is the processing observation time.
    _timestamp(entity.get("created_at"), "settlement created_at")
    return domain.Settlement(
        id=settlement_id,
        amount=domain.Money(amount, _settlement_currency(entity, context)),
        processed_at=processed_at,
        utr=_optional_text(entity.get("utr"), "settlement UTR"),
    )


def _settlement_api_payload(
    entity: Mapping[str, object], context: RazorpayAccountContext
) -> dict[str, object]:
    return {
        "provider": "razorpay",
        "evidence_origin": context.evidence_origin.value,
        "account_id": context.account_id,
        "settlement_currency": context.settlement_currency.value,
        "entity": dict(entity),
    }


def _retained_settlement_api_entity(
    envelope: domain.SourceEnvelope,
) -> Mapping[str, object]:
    entity = envelope.payload.get("entity")
    if not isinstance(entity, Mapping):
        raise AssertionError("Gate 15 settlement API envelope lost provider entity")
    return entity


def compile_settlement_api_entity(
    *,
    entity: Mapping[str, object],
    context: RazorpayAccountContext,
    journal: InMemoryJournal,
    received_at: datetime,
) -> CanonicalBatch:
    if not isinstance(context, RazorpayAccountContext):
        raise TypeError("context must be RazorpayAccountContext")
    if not isinstance(journal, InMemoryJournal):
        raise TypeError("journal must be InMemoryJournal")
    if not isinstance(entity, Mapping):
        raise TypeError("settlement API entity must be a provider object")
    _aware(received_at, "received_at")
    settlement_text = _non_empty_text(entity.get("id"), "settlement id")
    source_record_id = f"{context.account_id}:api:{settlement_text}"
    result = journal.append(
        make_source_envelope(
            source_kind=domain.SourceKind.RAZORPAY_SETTLEMENT,
            source_record_id=source_record_id,
            occurred_at=_safe_timestamp(entity.get("created_at"), "settlement created_at"),
            received_at=received_at,
            schema_version="razorpay-settlement-api-entity-v1",
            payload=_settlement_api_payload(entity, context),
        )
    )
    retained = _retained_settlement_api_entity(result.envelope)
    settlement = _normalize_standard_settlement(
        entity=retained,
        context=context,
        processed_at=result.envelope.received_at,
    )
    link = SourceLink(
        source_kind=domain.SourceKind.RAZORPAY_SETTLEMENT,
        source_record_id=source_record_id,
        envelope_id=result.envelope.id,
        canonical_record_id=str(settlement.id),
    )
    return CanonicalBatch(
        orders=(),
        payment_events=(),
        recon_entries=(),
        settlements=(settlement,),
        bank_entries=(),
    )._bind_source_links((link,))


def compile_settlement_webhook(
    *,
    raw_body: bytes,
    headers: Mapping[str, str],
    webhook_secret: str,
    context: RazorpayAccountContext,
    journal: InMemoryJournal,
    received_at: datetime,
) -> CanonicalBatch:
    if not isinstance(context, RazorpayAccountContext):
        raise TypeError("context must be RazorpayAccountContext")
    if not isinstance(journal, InMemoryJournal):
        raise TypeError("journal must be InMemoryJournal")
    _aware(received_at, "received_at")
    event_id, signature = _verify_webhook(
        raw_body=raw_body,
        headers=headers,
        webhook_secret=webhook_secret,
    )
    parsed = _parse_event(raw_body)
    _require_event_account(parsed, context)
    result = _append_webhook(
        source_kind=domain.SourceKind.RAZORPAY_SETTLEMENT,
        schema_version="razorpay-settlement-webhook-v1",
        raw_body=raw_body,
        event=parsed,
        event_id=event_id,
        signature=signature,
        context=context,
        journal=journal,
        received_at=received_at,
    )
    event = _retained_webhook_event(result.envelope)
    _require_webhook_event_shape(event, "settlement")
    event_name = _non_empty_text(event.get("event"), "webhook event")
    if event_name != "settlement.processed":
        raise RazorpayIntegrationError(
            f"unsupported settlement webhook {event_name!r}; only processed is canonicalized"
        )
    entity = _payload_entity(event, "settlement")
    settlement = _normalize_standard_settlement(
        entity=entity,
        context=context,
        processed_at=_timestamp(event.get("created_at"), "webhook created_at"),
    )
    link = SourceLink(
        source_kind=domain.SourceKind.RAZORPAY_SETTLEMENT,
        source_record_id=event_id,
        envelope_id=result.envelope.id,
        canonical_record_id=str(settlement.id),
    )
    return CanonicalBatch(
        orders=(),
        payment_events=(),
        recon_entries=(),
        settlements=(settlement,),
        bank_entries=(),
    )._bind_source_links((link,))
