from datetime import UTC, datetime, timedelta

import pytest

from reflow.domain.models import MerchantOrder, Money, PaymentEvent, SettlementReconEntry
from reflow.domain.types import (
    OrderId,
    PaymentEventKind,
    PaymentId,
    ReconEntityKind,
    ReconEntryId,
    RefundId,
    SettlementId,
)

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValueError):
        MerchantOrder(OrderId("order_1"), Money(100), datetime(2026, 8, 29))


def test_received_before_occurred_is_rejected() -> None:
    with pytest.raises(ValueError):
        PaymentEvent(
            source_event_id="evt_1",
            payment_id=PaymentId("pay_1"),
            order_id=OrderId("order_1"),
            kind=PaymentEventKind.CREATED,
            amount=Money(100),
            occurred_at=NOW,
            received_at=NOW - timedelta(seconds=1),
        )


def test_recon_kind_requires_matching_id_type() -> None:
    with pytest.raises(TypeError):
        SettlementReconEntry(
            id=ReconEntryId("recon_1"),
            settlement_id=SettlementId("setl_1"),
            entity_kind=ReconEntityKind.PAYMENT,
            entity_id=RefundId("rfnd_1"),
            gross_amount=Money(10_000),
            fee=Money(100),
            tax=Money(18),
            settlement_effect=Money(9_882),
            occurred_at=NOW,
        )
