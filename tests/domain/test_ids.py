import pytest

from reflow.domain.types import OrderId, PaymentId, RefundId


def test_entity_ids_are_not_interchangeable() -> None:
    payment = PaymentId("pay_abc")
    refund = RefundId("rfnd_abc")
    assert payment != refund
    assert type(payment) is PaymentId
    assert type(refund) is RefundId


def test_wrong_id_prefix_is_rejected() -> None:
    with pytest.raises(ValueError):
        PaymentId("order_abc")


def test_valid_order_id() -> None:
    assert str(OrderId("order_abc")) == "order_abc"
