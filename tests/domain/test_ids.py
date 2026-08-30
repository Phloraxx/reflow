import pytest

from reflow.domain.types import OrderId, PaymentId, ProofVersionId, RefundId


def test_entity_ids_are_not_interchangeable() -> None:
    payment = PaymentId("pay_abc")
    refund = RefundId("rfnd_abc")
    assert payment != refund
    assert type(payment) is PaymentId
    assert type(refund) is RefundId


def test_wrong_id_prefix_is_rejected() -> None:
    with pytest.raises(ValueError):
        PaymentId("order_abc")


def test_prefix_without_identifier_suffix_is_rejected() -> None:
    with pytest.raises(ValueError):
        PaymentId("pay_")
    with pytest.raises(ValueError):
        PaymentId("pay_   ")


def test_surrounding_identifier_whitespace_is_rejected() -> None:
    with pytest.raises(ValueError):
        PaymentId(" pay_abc")
    with pytest.raises(ValueError):
        PaymentId("pay_abc ")


def test_valid_order_id() -> None:
    assert str(OrderId("order_abc")) == "order_abc"


def test_proof_version_id_requires_its_own_prefix() -> None:
    proof_id = ProofVersionId("proofv_abc")
    assert str(proof_id) == "proofv_abc"
    with pytest.raises(ValueError):
        ProofVersionId("proof_abc")
