from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence

from reflow.domain import Money, PaymentCurrentState, PaymentEvent, PaymentEventKind, PaymentId
from reflow.domain.types import OrderId, PaymentStatus


class PaymentStateError(ValueError):
    """Payment evidence is internally inconsistent and cannot be reduced safely."""


def _same_source_fact(left: PaymentEvent, right: PaymentEvent) -> bool:
    """Compare source facts while ignoring local retry receipt metadata."""
    return (
        left.source_event_id == right.source_event_id
        and left.payment_id == right.payment_id
        and left.order_id == right.order_id
        and left.kind is right.kind
        and left.amount == right.amount
        and left.occurred_at == right.occurred_at
        and left.error_code == right.error_code
        and left.error_reason == right.error_reason
    )


def _deduplicate(events: Sequence[PaymentEvent]) -> tuple[PaymentEvent, ...]:
    by_event_id: dict[str, PaymentEvent] = {}
    for event in events:
        existing = by_event_id.get(event.source_event_id)
        if existing is None:
            by_event_id[event.source_event_id] = event
        elif _same_source_fact(existing, event):
            if event.received_at < existing.received_at:
                by_event_id[event.source_event_id] = event
        else:
            raise PaymentStateError(
                f"source event id {event.source_event_id!r} has conflicting payloads"
            )
    return tuple(by_event_id.values())


def reduce_payment_events(events: Sequence[PaymentEvent]) -> PaymentCurrentState:
    unique = _deduplicate(events)
    if not unique:
        raise PaymentStateError("cannot reduce an empty payment timeline")

    payment_ids = {event.payment_id for event in unique}
    if len(payment_ids) != 1:
        raise PaymentStateError("one reducer call cannot contain multiple payment ids")
    payment_id = next(iter(payment_ids))

    currencies = {event.amount.currency for event in unique}
    amounts = {event.amount.amount_paise for event in unique}
    if len(currencies) != 1 or len(amounts) != 1:
        raise PaymentStateError("payment amount/currency changed across source events")
    amount = unique[0].amount

    explicit_orders: set[OrderId] = {
        event.order_id for event in unique if event.order_id is not None
    }
    if len(explicit_orders) > 1:
        raise PaymentStateError("payment events reference multiple order ids")
    order_id = next(iter(explicit_orders)) if explicit_orders else None

    kinds = {event.kind for event in unique}
    warnings: list[str] = []
    captured_events = [event for event in unique if event.kind is PaymentEventKind.CAPTURED]

    if PaymentEventKind.FAILED in kinds and PaymentEventKind.CAPTURED in kinds:
        warnings.append("FAILED_AND_CAPTURED_OBSERVED")

    if PaymentEventKind.CAPTURED in kinds:
        status = PaymentStatus.CAPTURED
    elif PaymentEventKind.FAILED in kinds:
        status = PaymentStatus.FAILED
    elif PaymentEventKind.AUTHORIZED in kinds:
        status = PaymentStatus.AUTHORIZED
    else:
        status = PaymentStatus.CREATED

    captured_at = (
        min(event.occurred_at for event in captured_events) if captured_events else None
    )
    return PaymentCurrentState(
        payment_id=payment_id,
        order_id=order_id,
        amount=amount,
        status=status,
        last_occurred_at=max(event.occurred_at for event in unique),
        captured_at=captured_at,
        refunded_amount=Money.zero(amount.currency),
        warnings=tuple(sorted(warnings)),
    )


def reduce_all_payments(events: Iterable[PaymentEvent]) -> tuple[PaymentCurrentState, ...]:
    grouped: dict[PaymentId, list[PaymentEvent]] = defaultdict(list)
    for event in events:
        grouped[event.payment_id].append(event)
    return tuple(
        reduce_payment_events(grouped[payment_id])
        for payment_id in sorted(grouped, key=str)
    )
