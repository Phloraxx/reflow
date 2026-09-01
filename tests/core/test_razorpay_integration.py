from __future__ import annotations

import base64
import hashlib
import hmac
import inspect
import json
from datetime import UTC, datetime, timedelta

import pytest

import reflow.razorpay_integration as razorpay_module
from reflow.bank_proof import BankReceiptStatus, prove_all_bank_receipts
from reflow.domain import Currency, PaymentEventKind, ReconEntityKind, SourceKind
from reflow.ingestion import merge_canonical_batches
from reflow.journal import InMemoryJournal, JournalConflictError
from reflow.money_graph import build_money_graph
from reflow.payment_state import reduce_all_payments
from reflow.razorpay_integration import (
    RazorpayAccountContext,
    RazorpayEvidenceOrigin,
    RazorpayIntegrationError,
    compile_payment_webhook,
    compile_recon_items,
    compile_settlement_api_entity,
    compile_settlement_webhook,
)
from reflow.settlement_proof import CompositionStatus, prove_all_settlement_compositions

SECRET = "whsec_gate15_test"
ACCOUNT = "acc_gate15_demo"
RECEIVED = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _context(origin: RazorpayEvidenceOrigin = RazorpayEvidenceOrigin.PROVIDER_DOC_FIXTURE):
    return RazorpayAccountContext(account_id=ACCOUNT, evidence_origin=origin)


def _body(event: str, entity_key: str, entity: dict[str, object], *, created_at: int = 1788263700):
    return json.dumps(
        {
            "entity": "event",
            "account_id": ACCOUNT,
            "event": event,
            "contains": [entity_key],
            "payload": {entity_key: {"entity": entity}},
            "created_at": created_at,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _headers(raw: bytes, *, event_id: str = "evt_gate15_1", secret: str = SECRET):
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return {
        "X-Razorpay-Signature": signature,
        "x-razorpay-event-id": event_id,
    }


def _payment(*, status: str = "captured", payment_id: str = "pay_gate15demo"):
    return {
        "id": payment_id,
        "entity": "payment",
        "amount": 10000,
        "currency": "INR",
        "status": status,
        "order_id": "order_gate15demo",
        "error_code": None,
        "error_reason": None,
        "created_at": 1788260100,
    }


def _settlement(*, settlement_id: str = "setl_gate15demo", status: str = "processed"):
    return {
        "id": settlement_id,
        "entity": "settlement",
        "amount": 97100,
        "status": status,
        "utr": "UTR-GATE15-1",
        "created_at": 1788263600,
    }


def _recon(
    *,
    kind: str = "payment",
    entity_id: str = "pay_GATE15DOC",
    settlement_id: str = "setl_GATE15DOC",
    debit: int = 0,
    credit: int = 97100,
    amount: int = 100000,
    fee: int = 2900,
    tax: int = 0,
    settled: bool = True,
    settled_at: int = 1788263600,
    settlement_utr: str | None = "UTR-GATE15-1",
):
    return {
        "entity_id": entity_id,
        "type": kind,
        "debit": debit,
        "credit": credit,
        "amount": amount,
        "currency": "INR",
        "fee": fee,
        "tax": tax,
        "settled": settled,
        "created_at": 1788250000,
        "settled_at": settled_at,
        "settlement_id": settlement_id,
        "settlement_utr": settlement_utr,
    }


def test_valid_payment_webhook_signature_is_verified_over_exact_raw_bytes() -> None:
    raw = _body("payment.captured", "payment", _payment())
    journal = InMemoryJournal()
    batch = compile_payment_webhook(
        raw_body=raw,
        headers=_headers(raw),
        webhook_secret=SECRET,
        context=_context(),
        journal=journal,
        received_at=RECEIVED,
    )
    assert batch.payment_events[0].kind is PaymentEventKind.CAPTURED
    assert len(journal) == 1


def test_invalid_signature_fails_before_journal_or_canonicalization() -> None:
    raw = _body("payment.captured", "payment", _payment())
    journal = InMemoryJournal()
    with pytest.raises(RazorpayIntegrationError, match="signature"):
        compile_payment_webhook(
            raw_body=raw,
            headers=_headers(raw, secret="wrong"),
            webhook_secret=SECRET,
            context=_context(),
            journal=journal,
            received_at=RECEIVED,
        )
    assert len(journal) == 0


def test_raw_webhook_bytes_and_auth_headers_are_retained() -> None:
    raw = _body("payment.authorized", "payment", _payment(status="captured"))
    journal = InMemoryJournal()
    headers = _headers(raw, event_id="evt_raw_keep")
    compile_payment_webhook(
        raw_body=raw,
        headers=headers,
        webhook_secret=SECRET,
        context=_context(),
        journal=journal,
        received_at=RECEIVED,
    )
    envelope = journal.entries()[0]
    assert base64.b64decode(envelope.payload["raw_body_base64"]) == raw
    assert envelope.payload["x_razorpay_event_id"] == "evt_raw_keep"
    assert envelope.payload["x_razorpay_signature"] == headers["X-Razorpay-Signature"]
    assert envelope.payload["evidence_origin"] == "provider_doc_fixture"


def test_webhook_account_mismatch_fails_closed() -> None:
    raw = _body("payment.captured", "payment", _payment())
    with pytest.raises(RazorpayIntegrationError, match="account"):
        compile_payment_webhook(
            raw_body=raw,
            headers=_headers(raw),
            webhook_secret=SECRET,
            context=RazorpayAccountContext(
                "acc_other", RazorpayEvidenceOrigin.PROVIDER_DOC_FIXTURE
            ),
            journal=InMemoryJournal(),
            received_at=RECEIVED,
        )


def test_webhook_event_id_is_required() -> None:
    raw = _body("payment.captured", "payment", _payment())
    headers = _headers(raw)
    headers.pop("x-razorpay-event-id")
    with pytest.raises(RazorpayIntegrationError, match="event id"):
        compile_payment_webhook(
            raw_body=raw,
            headers=headers,
            webhook_secret=SECRET,
            context=_context(),
            journal=InMemoryJournal(),
            received_at=RECEIVED,
        )


def test_exact_duplicate_webhook_delivery_is_idempotent() -> None:
    raw = _body("payment.captured", "payment", _payment())
    headers = _headers(raw, event_id="evt_duplicate")
    journal = InMemoryJournal()
    first = compile_payment_webhook(
        raw_body=raw,
        headers=headers,
        webhook_secret=SECRET,
        context=_context(),
        journal=journal,
        received_at=RECEIVED,
    )
    second = compile_payment_webhook(
        raw_body=raw,
        headers=headers,
        webhook_secret=SECRET,
        context=_context(),
        journal=journal,
        received_at=RECEIVED + timedelta(seconds=5),
    )
    assert first == second
    assert len(journal) == 1


def test_same_webhook_event_id_with_different_valid_body_fails_as_journal_conflict() -> None:
    first = _body("payment.failed", "payment", _payment(status="failed"))
    second = _body("payment.captured", "payment", _payment(status="captured"))
    journal = InMemoryJournal()
    compile_payment_webhook(
        raw_body=first,
        headers=_headers(first, event_id="evt_conflict"),
        webhook_secret=SECRET,
        context=_context(),
        journal=journal,
        received_at=RECEIVED,
    )
    with pytest.raises(JournalConflictError):
        compile_payment_webhook(
            raw_body=second,
            headers=_headers(second, event_id="evt_conflict"),
            webhook_secret=SECRET,
            context=_context(),
            journal=journal,
            received_at=RECEIVED + timedelta(seconds=1),
        )
    assert len(journal) == 2


def test_authorized_event_name_controls_transition_even_if_snapshot_is_captured() -> None:
    raw = _body("payment.authorized", "payment", _payment(status="captured"))
    batch = compile_payment_webhook(
        raw_body=raw,
        headers=_headers(raw),
        webhook_secret=SECRET,
        context=_context(),
        journal=InMemoryJournal(),
        received_at=RECEIVED,
    )
    assert batch.payment_events[0].kind is PaymentEventKind.AUTHORIZED


def test_out_of_order_failed_and_captured_delivery_reduces_deterministically() -> None:
    captured = _body(
        "payment.captured", "payment", _payment(status="captured"), created_at=1788263800
    )
    failed = _body("payment.failed", "payment", _payment(status="failed"), created_at=1788263700)
    journal = InMemoryJournal()
    b1 = compile_payment_webhook(
        raw_body=captured,
        headers=_headers(captured, event_id="evt_cap"),
        webhook_secret=SECRET,
        context=_context(),
        journal=journal,
        received_at=RECEIVED,
    )
    b2 = compile_payment_webhook(
        raw_body=failed,
        headers=_headers(failed, event_id="evt_fail"),
        webhook_secret=SECRET,
        context=_context(),
        journal=journal,
        received_at=RECEIVED + timedelta(seconds=1),
    )
    events = b1.payment_events + b2.payment_events
    state = reduce_all_payments(events)[0]
    assert state.status.value == "captured"


def test_out_of_range_webhook_timestamp_is_retained_raw_then_rejected() -> None:
    raw = _body(
        "payment.captured",
        "payment",
        _payment(status="captured"),
        created_at=10**30,
    )
    journal = InMemoryJournal()
    with pytest.raises(RazorpayIntegrationError, match="timestamp"):
        compile_payment_webhook(
            raw_body=raw,
            headers=_headers(raw, event_id="evt_bad_timestamp"),
            webhook_secret=SECRET,
            context=_context(),
            journal=journal,
            received_at=RECEIVED,
        )
    assert len(journal) == 1
    assert journal.entries()[0].occurred_at is None


def test_payment_webhook_uses_top_level_event_time() -> None:
    raw = _body("payment.captured", "payment", _payment(), created_at=1788263900)
    batch = compile_payment_webhook(
        raw_body=raw,
        headers=_headers(raw),
        webhook_secret=SECRET,
        context=_context(),
        journal=InMemoryJournal(),
        received_at=RECEIVED,
    )
    assert int(batch.payment_events[0].occurred_at.timestamp()) == 1788263900
    assert int(batch.payment_events[0].occurred_at.timestamp()) != _payment()["created_at"]


def test_provider_payment_recon_uses_credit_minus_debit() -> None:
    batch = compile_recon_items(
        items=(_recon(),), context=_context(), journal=InMemoryJournal(), received_at=RECEIVED
    )
    row = batch.recon_entries[0]
    assert row.entity_kind is ReconEntityKind.PAYMENT
    assert row.gross_amount.amount_paise == 100000
    assert row.settlement_effect.amount_paise == 97100


def test_provider_refund_recon_debit_is_negative_effect() -> None:
    item = _recon(
        kind="refund",
        entity_id="rfnd_GATE15DOC",
        debit=242500,
        credit=0,
        amount=242500,
        fee=0,
        tax=0,
    )
    row = compile_recon_items(
        items=(item,), context=_context(), journal=InMemoryJournal(), received_at=RECEIVED
    ).recon_entries[0]
    assert row.gross_amount.amount_paise == -242500
    assert row.settlement_effect.amount_paise == -242500


def test_provider_transfer_recon_does_not_double_count_fee_and_tax() -> None:
    item = _recon(
        kind="transfer",
        entity_id="trf_GATE15DOC",
        debit=100296,
        credit=0,
        amount=100000,
        fee=296,
        tax=46,
    )
    row = compile_recon_items(
        items=(item,), context=_context(), journal=InMemoryJournal(), received_at=RECEIVED
    ).recon_entries[0]
    assert row.gross_amount.amount_paise == -100000
    assert row.fee.amount_paise == 296
    assert row.tax.amount_paise == 46
    assert row.settlement_effect.amount_paise == -100296


def test_provider_adjustment_recon_direct_credit() -> None:
    item = _recon(
        kind="adjustment",
        entity_id="adj_GATE15DOC",
        debit=0,
        credit=1012,
        amount=1012,
        fee=0,
        tax=0,
    )
    row = compile_recon_items(
        items=(item,), context=_context(), journal=InMemoryJournal(), received_at=RECEIVED
    ).recon_entries[0]
    assert row.gross_amount.amount_paise == 1012
    assert row.settlement_effect.amount_paise == 1012


@pytest.mark.parametrize("debit,credit", [(100, 100), (0, 0)])
def test_recon_requires_exactly_one_financial_direction(debit: int, credit: int) -> None:
    journal = InMemoryJournal()
    with pytest.raises(RazorpayIntegrationError, match=r"debit|credit|direction"):
        compile_recon_items(
            items=(_recon(debit=debit, credit=credit),),
            context=_context(),
            journal=journal,
            received_at=RECEIVED,
        )
    assert len(journal) == 1


def test_recon_entity_type_prefix_mismatch_is_rejected_after_raw_retention() -> None:
    journal = InMemoryJournal()
    with pytest.raises(RazorpayIntegrationError, match=r"entity.*type|prefix"):
        compile_recon_items(
            items=(_recon(kind="refund", entity_id="pay_WRONGTYPE", debit=100, credit=0),),
            context=_context(),
            journal=journal,
            received_at=RECEIVED,
        )
    assert len(journal) == 1


def test_unsettled_recon_item_is_retained_raw_then_rejected() -> None:
    journal = InMemoryJournal()
    with pytest.raises(RazorpayIntegrationError, match="settled"):
        compile_recon_items(
            items=(_recon(settled=False),),
            context=_context(),
            journal=journal,
            received_at=RECEIVED,
        )
    assert len(journal) == 1


def test_out_of_range_recon_timestamp_is_retained_raw_then_rejected() -> None:
    journal = InMemoryJournal()
    with pytest.raises(RazorpayIntegrationError, match="timestamp"):
        compile_recon_items(
            items=(_recon(settled_at=10**30),),
            context=_context(),
            journal=journal,
            received_at=RECEIVED,
        )
    assert len(journal) == 1


def test_provider_recon_raw_identity_binds_to_deterministic_canonical_id() -> None:
    item = _recon()
    journal = InMemoryJournal()
    first = compile_recon_items(
        items=(item,), context=_context(), journal=journal, received_at=RECEIVED
    )
    second = compile_recon_items(
        items=(item,),
        context=_context(),
        journal=journal,
        received_at=RECEIVED + timedelta(seconds=5),
    )
    assert first.recon_entries[0].id == second.recon_entries[0].id
    link = first.source_links[0]
    assert link.source_record_id != str(first.recon_entries[0].id)
    assert link.canonical_record_id == str(first.recon_entries[0].id)
    assert (
        first.source_index()[(SourceKind.RAZORPAY_RECON, str(first.recon_entries[0].id))]
        == link.envelope_id
    )


def test_processed_settlement_webhook_normalizes_amount_utr_and_event_time() -> None:
    raw = _body("settlement.processed", "settlement", _settlement(), created_at=1788264000)
    batch = compile_settlement_webhook(
        raw_body=raw,
        headers=_headers(raw, event_id="evt_settlement"),
        webhook_secret=SECRET,
        context=_context(),
        journal=InMemoryJournal(),
        received_at=RECEIVED,
    )
    settlement = batch.settlements[0]
    assert settlement.amount.amount_paise == 97100
    assert settlement.amount.currency is Currency.INR
    assert settlement.utr == "UTR-GATE15-1"
    assert int(settlement.processed_at.timestamp()) == 1788264000


def test_processed_settlement_api_entity_uses_observation_time_and_retains_created_at() -> None:
    entity = _settlement()
    journal = InMemoryJournal()
    batch = compile_settlement_api_entity(
        entity=entity,
        context=_context(),
        journal=journal,
        received_at=RECEIVED,
    )
    settlement = batch.settlements[0]
    assert settlement.amount.currency is Currency.INR
    assert settlement.processed_at == RECEIVED
    assert settlement.processed_at != datetime.fromtimestamp(entity["created_at"], tz=UTC)
    envelope = journal.entries()[0]
    assert int(envelope.occurred_at.timestamp()) == entity["created_at"]
    retained = envelope.payload["entity"]
    assert "currency" not in retained
    assert envelope.payload["evidence_origin"] == "provider_doc_fixture"
    assert batch.source_links[0].canonical_record_id == str(settlement.id)


def test_unprocessed_settlement_api_entity_is_retained_then_rejected() -> None:
    journal = InMemoryJournal()
    with pytest.raises(RazorpayIntegrationError, match="processed"):
        compile_settlement_api_entity(
            entity=_settlement(status="created"),
            context=_context(),
            journal=journal,
            received_at=RECEIVED,
        )
    assert len(journal) == 1


def test_malformed_settlement_api_created_at_is_retained_then_rejected() -> None:
    entity = _settlement()
    entity["created_at"] = 10**30
    journal = InMemoryJournal()
    with pytest.raises(RazorpayIntegrationError, match="timestamp"):
        compile_settlement_api_entity(
            entity=entity,
            context=_context(),
            journal=journal,
            received_at=RECEIVED,
        )
    assert len(journal) == 1
    assert journal.entries()[0].occurred_at is None


def test_settlement_webhook_account_mismatch_fails() -> None:
    raw = _body("settlement.processed", "settlement", _settlement())
    with pytest.raises(RazorpayIntegrationError, match="account"):
        compile_settlement_webhook(
            raw_body=raw,
            headers=_headers(raw),
            webhook_secret=SECRET,
            context=RazorpayAccountContext(
                "acc_other", RazorpayEvidenceOrigin.PROVIDER_DOC_FIXTURE
            ),
            journal=InMemoryJournal(),
            received_at=RECEIVED,
        )


def test_unsupported_settlement_event_is_not_canonicalized() -> None:
    raw = _body("settlement.failed", "settlement", _settlement(status="failed"))
    with pytest.raises(RazorpayIntegrationError, match=r"unsupported|processed"):
        compile_settlement_webhook(
            raw_body=raw,
            headers=_headers(raw),
            webhook_secret=SECRET,
            context=_context(),
            journal=InMemoryJournal(),
            received_at=RECEIVED,
        )


def test_instant_settlement_id_is_not_coerced_to_standard_settlement() -> None:
    raw = _body("settlement.processed", "settlement", _settlement(settlement_id="setlod_GATE15"))
    journal = InMemoryJournal()
    with pytest.raises(RazorpayIntegrationError, match=r"standard settlement|setl_"):
        compile_settlement_webhook(
            raw_body=raw,
            headers=_headers(raw),
            webhook_secret=SECRET,
            context=_context(),
            journal=journal,
            received_at=RECEIVED,
        )
    assert len(journal) == 1


def test_synthetic_origin_is_rejected_by_provider_context() -> None:
    with pytest.raises((RazorpayIntegrationError, ValueError), match=r"synthetic|provider"):
        RazorpayAccountContext(ACCOUNT, RazorpayEvidenceOrigin.SYNTHETIC)


def test_provider_shaped_recon_and_settlement_feed_existing_gate7_proof() -> None:
    # Provider-shaped arithmetic: payment credit is already net provider effect.
    settlement_id = "setl_GATE15E2E"
    recon = _recon(
        settlement_id=settlement_id,
        entity_id="pay_GATE15E2E",
        credit=97100,
        debit=0,
        amount=100000,
        fee=2900,
        tax=0,
    )
    journal = InMemoryJournal()
    recon_batch = compile_recon_items(
        items=(recon,),
        context=_context(),
        journal=journal,
        received_at=RECEIVED,
    )
    raw = _body(
        "settlement.processed",
        "settlement",
        _settlement(settlement_id=settlement_id),
        created_at=1788264000,
    )
    settlement_batch = compile_settlement_webhook(
        raw_body=raw,
        headers=_headers(raw, event_id="evt_setl_e2e"),
        webhook_secret=SECRET,
        context=_context(),
        journal=journal,
        received_at=RECEIVED,
    )
    # Merge through the public ingestion helper to the existing proof path.
    combined = merge_canonical_batches(recon_batch, settlement_batch)
    proof = prove_all_settlement_compositions(combined, build_money_graph(combined))[0]
    assert proof.status is CompositionStatus.PROVEN
    assert proof.residual.is_zero


def test_recon_settlement_utr_mismatch_contradicts_existing_gate7_proof() -> None:
    settlement_id = "setl_GATE15UTR"
    journal = InMemoryJournal()
    recon = _recon(
        settlement_id=settlement_id,
        entity_id="pay_GATE15UTR",
        settlement_utr="UTR-WRONG",
    )
    recon_batch = compile_recon_items(
        items=(recon,), context=_context(), journal=journal, received_at=RECEIVED
    )
    raw = _body(
        "settlement.processed",
        "settlement",
        _settlement(settlement_id=settlement_id),
        created_at=1788264000,
    )
    settlement_batch = compile_settlement_webhook(
        raw_body=raw,
        headers=_headers(raw, event_id="evt_setl_utr"),
        webhook_secret=SECRET,
        context=_context(),
        journal=journal,
        received_at=RECEIVED,
    )
    combined = merge_canonical_batches(recon_batch, settlement_batch)
    proof = prove_all_settlement_compositions(combined, build_money_graph(combined))[0]
    assert proof.status is CompositionStatus.CONTRADICTED
    assert "SETTLEMENT_UTR_MISMATCH" in proof.reason_codes


def test_processed_settlement_does_not_prove_bank_receipt_without_bank_evidence() -> None:
    raw = _body(
        "settlement.processed",
        "settlement",
        _settlement(),
        created_at=1788264000,
    )
    batch = compile_settlement_webhook(
        raw_body=raw,
        headers=_headers(raw, event_id="evt_setl_bank_wait"),
        webhook_secret=SECRET,
        context=_context(),
        journal=InMemoryJournal(),
        received_at=RECEIVED,
    )
    proof = prove_all_bank_receipts(batch)[0]
    assert proof.status is BankReceiptStatus.WAITING
    assert not proof.residual.is_zero


def test_explicit_evidence_origin_is_retained_without_promotion() -> None:
    context = RazorpayAccountContext(ACCOUNT, RazorpayEvidenceOrigin.REAL_TEST_MODE)
    journal = InMemoryJournal()
    compile_recon_items(
        items=(_recon(),),
        context=context,
        journal=journal,
        received_at=RECEIVED,
    )
    assert journal.entries()[0].payload["evidence_origin"] == "real_test_mode"


def test_payment_webhook_delivery_permutation_does_not_change_compilation_identity() -> None:
    captured = _body(
        "payment.captured", "payment", _payment(status="captured"), created_at=1788263800
    )
    failed = _body("payment.failed", "payment", _payment(status="failed"), created_at=1788263700)
    first_journal = InMemoryJournal()
    first_cap = compile_payment_webhook(
        raw_body=captured,
        headers=_headers(captured, event_id="evt_perm_cap"),
        webhook_secret=SECRET,
        context=_context(),
        journal=first_journal,
        received_at=RECEIVED,
    )
    first_fail = compile_payment_webhook(
        raw_body=failed,
        headers=_headers(failed, event_id="evt_perm_fail"),
        webhook_secret=SECRET,
        context=_context(),
        journal=first_journal,
        received_at=RECEIVED + timedelta(seconds=1),
    )
    second_journal = InMemoryJournal()
    second_fail = compile_payment_webhook(
        raw_body=failed,
        headers=_headers(failed, event_id="evt_perm_fail"),
        webhook_secret=SECRET,
        context=_context(),
        journal=second_journal,
        received_at=RECEIVED + timedelta(seconds=1),
    )
    second_cap = compile_payment_webhook(
        raw_body=captured,
        headers=_headers(captured, event_id="evt_perm_cap"),
        webhook_secret=SECRET,
        context=_context(),
        journal=second_journal,
        received_at=RECEIVED,
    )
    first = merge_canonical_batches(first_cap, first_fail)
    second = merge_canonical_batches(second_fail, second_cap)
    assert first.compilation_sha256 == second.compilation_sha256
    assert reduce_all_payments(first.payment_events) == reduce_all_payments(second.payment_events)


def test_gate15_public_compile_surface_is_journal_first() -> None:
    assert set(razorpay_module.__all__) == {
        "RazorpayAccountContext",
        "RazorpayEvidenceOrigin",
        "RazorpayIntegrationError",
        "compile_payment_webhook",
        "compile_recon_items",
        "compile_settlement_api_entity",
        "compile_settlement_webhook",
    }
    for name in (
        "compile_payment_webhook",
        "compile_recon_items",
        "compile_settlement_webhook",
    ):
        signature = inspect.signature(getattr(razorpay_module, name))
        assert "journal" in signature.parameters


def test_gate15_module_does_not_import_simulator_truth() -> None:
    source = inspect.getsource(razorpay_module)
    assert "reflow.simulator" not in source
    assert "simulator.truth" not in source
