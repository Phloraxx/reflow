from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

from reflow.domain import SourceKind
from reflow.ingestion import ObservedBatch, ingest_observed_batch, merge_canonical_batches
from reflow.instant_settlement_integration import compile_instant_settlement_api_entity
from reflow.instant_settlement_proof import (
    InstantSettlementReceiptStatus,
    prove_all_instant_settlement_receipts,
)
from reflow.journal import InMemoryJournal
from reflow.razorpay_integration import RazorpayAccountContext, RazorpayEvidenceOrigin

RECEIVED = datetime(2026, 9, 4, 0, 0, tzinfo=UTC)
PROCESSED = datetime.fromtimestamp(1_596_778_752, tz=UTC)


def _context() -> RazorpayAccountContext:
    return RazorpayAccountContext(
        "acc_gate51",
        RazorpayEvidenceOrigin.PROVIDER_DOC_FIXTURE,
    )


def _entity() -> dict[str, object]:
    return {
        "id": "setlod_GATE51_MULTI",
        "entity": "settlement.ondemand",
        "amount_requested": 300_000,
        "amount_settled": 299_115,
        "amount_pending": 0,
        "amount_reversed": 0,
        "fees": 885,
        "tax": 135,
        "currency": "INR",
        "settle_full_balance": False,
        "status": "processed",
        "description": "Need stock",
        "notes": {},
        "created_at": 1_596_771_429,
        "ondemand_payouts": {
            "entity": "collection",
            "count": 2,
            "items": [
                {
                    "id": "setlodp_GATE51_A",
                    "entity": "settlement.ondemand_payout",
                    "initiated_at": 1_596_771_430,
                    "processed_at": 1_596_778_752,
                    "reversed_at": None,
                    "amount": 200_000,
                    "amount_settled": 199_410,
                    "fees": 590,
                    "tax": 90,
                    "utr": "UTR-GATE51-A",
                    "status": "processed",
                    "created_at": 1_596_771_429,
                },
                {
                    "id": "setlodp_GATE51_B",
                    "entity": "settlement.ondemand_payout",
                    "initiated_at": 1_596_771_431,
                    "processed_at": 1_596_778_753,
                    "reversed_at": None,
                    "amount": 100_000,
                    "amount_settled": 99_705,
                    "fees": 295,
                    "tax": 45,
                    "utr": "UTR-GATE51-B",
                    "status": "processed",
                    "created_at": 1_596_771_429,
                },
            ],
        },
    }


def _bank_rows(*, second_amount: int = 99_705, duplicate_a: bool = False):
    rows = [
        {
            "bank_entry_id": "bank_gate51_a",
            "amount_paise": 199_410,
            "currency": "INR",
            "occurred_at": (PROCESSED + timedelta(minutes=1)).isoformat(),
            "narration": "Razorpay instant payout A",
            "utr": "UTR-GATE51-A",
        },
        {
            "bank_entry_id": "bank_gate51_b",
            "amount_paise": second_amount,
            "currency": "INR",
            "occurred_at": (PROCESSED + timedelta(minutes=2)).isoformat(),
            "narration": "Razorpay instant payout B",
            "utr": "UTR-GATE51-B",
        },
    ]
    if duplicate_a:
        rows.append(
            {
                "bank_entry_id": "bank_gate51_a_duplicate",
                "amount_paise": 1,
                "currency": "INR",
                "occurred_at": (PROCESSED + timedelta(minutes=3)).isoformat(),
                "narration": "Conflicting duplicate UTR",
                "utr": "UTR-GATE51-A",
            }
        )
    return tuple(rows)


def _batch(entity: dict[str, object], bank_rows: tuple[dict[str, object], ...]):
    journal = InMemoryJournal()
    instant = compile_instant_settlement_api_entity(
        entity=entity,
        context=_context(),
        journal=journal,
        received_at=RECEIVED,
    )
    bank = ingest_observed_batch(
        ObservedBatch((), (), (), (), bank_rows),
        journal,
        received_at=RECEIVED,
    )
    return merge_canonical_batches(instant, bank), journal


def test_two_explicit_payouts_can_prove_two_bank_credits_for_one_parent() -> None:
    batch, journal = _batch(_entity(), _bank_rows())
    proof = prove_all_instant_settlement_receipts(batch)[0]
    assert proof.status is InstantSettlementReceiptStatus.PROVEN
    assert proof.expected_amount.amount_paise == 299_115
    assert proof.observed_bank_credit.amount_paise == 299_115
    assert proof.residual.is_zero
    assert {str(value) for value in proof.bank_entry_ids} == {
        "bank_gate51_a",
        "bank_gate51_b",
    }
    assert len(proof.payout_proofs) == 2
    assert all(
        item.status is InstantSettlementReceiptStatus.PROVEN
        for item in proof.payout_proofs
    )
    assert set(proof.source_envelope_ids).issubset({item.id for item in journal.entries()})


def test_reused_utr_across_explicit_payouts_is_contradicted() -> None:
    entity = deepcopy(_entity())
    payouts = entity["ondemand_payouts"]
    assert isinstance(payouts, dict)
    items = payouts["items"]
    assert isinstance(items, list)
    second = items[1]
    assert isinstance(second, dict)
    second["utr"] = "UTR-GATE51-A"
    batch, _ = _batch(entity, _bank_rows())
    proof = prove_all_instant_settlement_receipts(batch)[0]
    assert proof.status is InstantSettlementReceiptStatus.CONTRADICTED
    assert "INSTANT_PAYOUT_UTR_REUSED" in proof.reason_codes
    source_index = batch.source_index()
    payout_sources = {
        source_index[(SourceKind.RAZORPAY_INSTANT_SETTLEMENT, "setlodp_GATE51_A")],
        source_index[(SourceKind.RAZORPAY_INSTANT_SETTLEMENT, "setlodp_GATE51_B")],
    }
    for child in proof.payout_proofs:
        assert payout_sources.issubset(set(child.source_envelope_ids))


def test_multiple_bank_entries_for_one_payout_utr_are_contradicted() -> None:
    batch, _ = _batch(_entity(), _bank_rows(duplicate_a=True))
    proof = prove_all_instant_settlement_receipts(batch)[0]
    assert proof.status is InstantSettlementReceiptStatus.CONTRADICTED
    assert "BANK_UTR_REUSED_ACROSS_ENTRIES" in proof.reason_codes


def test_payout_amount_mismatch_stays_residual_not_inferred_as_split() -> None:
    batch, _ = _batch(_entity(), _bank_rows(second_amount=99_700))
    proof = prove_all_instant_settlement_receipts(batch)[0]
    assert proof.status is InstantSettlementReceiptStatus.RESIDUAL
    assert proof.residual.amount_paise == 5
    assert "BANK_AMOUNT_MISMATCH" in proof.reason_codes


def test_unprocessed_payout_is_incomplete_even_if_bank_amount_is_available() -> None:
    entity = deepcopy(_entity())
    entity["status"] = "partially_processed"
    entity["amount_settled"] = 199_410
    payouts = entity["ondemand_payouts"]
    assert isinstance(payouts, dict)
    items = payouts["items"]
    assert isinstance(items, list)
    second = items[1]
    assert isinstance(second, dict)
    second["status"] = "created"
    second["processed_at"] = None
    second["amount_settled"] = None
    second["utr"] = None
    batch, _ = _batch(entity, _bank_rows())
    proof = prove_all_instant_settlement_receipts(batch)[0]
    assert proof.status is InstantSettlementReceiptStatus.INCOMPLETE
    assert "INSTANT_PAYOUT_NOT_PROCESSED" in proof.reason_codes


def test_parent_and_payout_settled_totals_must_agree_before_green() -> None:
    entity = deepcopy(_entity())
    entity["amount_settled"] = 299_114
    batch, _ = _batch(entity, _bank_rows())
    proof = prove_all_instant_settlement_receipts(batch)[0]
    assert proof.status is InstantSettlementReceiptStatus.CONTRADICTED
    assert "INSTANT_SETTLEMENT_PAYOUT_TOTAL_MISMATCH" in proof.reason_codes
