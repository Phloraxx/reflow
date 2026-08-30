from dataclasses import replace
from datetime import UTC, datetime

from reflow.bank_proof import BankReceiptStatus, prove_all_bank_receipts
from reflow.ingestion import ingest_observed_batch
from reflow.journal import InMemoryJournal
from reflow.simulator import CorruptionPlan, generate_world, observe_world

RECEIVED = datetime(2026, 8, 30, 0, 0, tzinfo=UTC)


def test_reused_settlement_utr_does_not_attribute_one_bank_row_to_two_settlements() -> None:
    world = generate_world(500)
    observed = observe_world(world, seed=501, plan=CorruptionPlan(kinds=()))
    first, second = world.cases[0], world.cases[1]
    assert first.settlement.utr is not None

    settlement_rows = [dict(row) for row in observed.observed.settlement_rows]
    second_row = next(
        row for row in settlement_rows if row["settlement_id"] == str(second.settlement.id)
    )
    second_row["utr"] = first.settlement.utr

    malformed = replace(
        observed.observed,
        settlement_rows=tuple(settlement_rows),
    )
    journal = InMemoryJournal()
    batch = ingest_observed_batch(malformed, journal, received_at=RECEIVED)
    by_id = {proof.settlement_id: proof for proof in prove_all_bank_receipts(batch)}

    for settlement_id in (first.settlement.id, second.settlement.id):
        proof = by_id[settlement_id]
        assert proof.status is BankReceiptStatus.CONTRADICTED
        assert proof.bank_entry_ids == ()
        assert proof.observed_bank_credit.is_zero
        assert "SETTLEMENT_UTR_REUSED" in proof.reason_codes
