from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import permutations

import pytest

from reflow.domain import Money, OrderId, PaymentEvent, PaymentEventKind, PaymentId
from reflow.domain.types import PaymentStatus
from reflow.payment_state import PaymentStateError, reduce_payment_events

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def _event(
    event_id: str,
    kind: PaymentEventKind,
    second: int,
    *,
    amount: int = 10_000,
) -> PaymentEvent:
    return PaymentEvent(
        source_event_id=event_id,
        payment_id=PaymentId("pay_1"),
        order_id=OrderId("order_1"),
        kind=kind,
        amount=Money(amount),
        occurred_at=NOW + timedelta(seconds=second),
        received_at=NOW + timedelta(seconds=second + 10),
    )


def test_delivery_permutations_produce_same_captured_truth() -> None:
    timeline = (
        _event("evt_created", PaymentEventKind.CREATED, 1),
        _event("evt_failed", PaymentEventKind.FAILED, 2),
        _event("evt_captured", PaymentEventKind.CAPTURED, 3),
    )
    outputs = {reduce_payment_events(order) for order in permutations(timeline)}
    assert len(outputs) == 1
    state = outputs.pop()
    assert state.status is PaymentStatus.CAPTURED
    assert state.warnings == ("FAILED_AND_CAPTURED_OBSERVED",)


def test_exact_duplicate_event_does_not_change_state() -> None:
    captured = _event("evt_captured", PaymentEventKind.CAPTURED, 3)
    once = reduce_payment_events((captured,))
    twice = reduce_payment_events((captured, captured))
    assert once == twice


def test_retry_with_later_local_received_at_is_still_idempotent() -> None:
    captured = _event("evt_captured", PaymentEventKind.CAPTURED, 3)
    retry = replace(captured, received_at=captured.received_at + timedelta(minutes=5))
    once = reduce_payment_events((captured,))
    retried = reduce_payment_events((retry, captured))
    assert retried == once


def test_late_delivery_does_not_change_event_time_truth() -> None:
    created = _event("evt_created", PaymentEventKind.CREATED, 1)
    captured = _event("evt_captured", PaymentEventKind.CAPTURED, 3)
    delayed = replace(captured, received_at=captured.received_at + timedelta(days=2))
    state = reduce_payment_events((delayed, created))
    assert state.status is PaymentStatus.CAPTURED
    assert state.last_occurred_at == captured.occurred_at
    assert state.captured_at == captured.occurred_at


def test_replay_is_pure_and_repeatable() -> None:
    timeline = (
        _event("evt_created", PaymentEventKind.CREATED, 1),
        _event("evt_captured", PaymentEventKind.CAPTURED, 3),
    )
    assert reduce_payment_events(timeline) == reduce_payment_events(timeline)


def test_conflicting_duplicate_event_id_is_rejected() -> None:
    first = _event("evt_same", PaymentEventKind.FAILED, 2)
    second = _event("evt_same", PaymentEventKind.CAPTURED, 3)
    with pytest.raises(PaymentStateError):
        reduce_payment_events((first, second))


def test_amount_change_across_events_is_rejected() -> None:
    with pytest.raises(PaymentStateError):
        reduce_payment_events(
            (
                _event("evt_1", PaymentEventKind.CREATED, 1, amount=10_000),
                _event("evt_2", PaymentEventKind.CAPTURED, 2, amount=10_001),
            )
        )
