from dataclasses import replace
from datetime import UTC, datetime

from reflow.bank_proof import BankReceiptStatus, prove_all_bank_receipts
from reflow.ingestion import ingest_observed_batch
from reflow.journal import InMemoryJournal
from reflow.simulator import CorruptionPlan, WorldConfig, generate_world, observe_world

RECEIVED = datetime(2026, 8, 30, 0, 0, tzinfo=UTC)


def test_common_amount_volume_does_not_embed_all_fuzzy_candidates_in_each_proof() -> None:
    config = WorldConfig(
        settlement_count=1_000,
        min_payments=1,
        max_payments=1,
        high_cardinality_payments=1,
    )
    world = generate_world(900, config)
    observed = observe_world(world, seed=901, plan=CorruptionPlan(kinds=())).observed

    common_amount = 10_000
    settlement_rows = []
    for row in observed.settlement_rows:
        changed = dict(row)
        changed["amount_paise"] = common_amount
        settlement_rows.append(changed)

    bank_rows = []
    for row in observed.bank_rows:
        changed = dict(row)
        changed["amount_paise"] = common_amount
        bank_rows.append(changed)

    common_amount_batch = replace(
        observed,
        settlement_rows=tuple(settlement_rows),
        bank_rows=tuple(bank_rows),
    )
    journal = InMemoryJournal()
    batch = ingest_observed_batch(
        common_amount_batch,
        journal,
        received_at=RECEIVED,
    )
    proofs = prove_all_bank_receipts(batch)

    assert len(proofs) == 1_000
    bank_count = len(batch.bank_entries)
    assert bank_count > 800

    for proof in proofs:
        assert proof.status in {BankReceiptStatus.PROVEN, BankReceiptStatus.WAITING}
        # Same-amount collisions are diagnostic counts, not thousands of copied
        # fuzzy candidate IDs/source envelopes inside every authoritative proof.
        assert proof.same_amount_nonidentity_count >= bank_count - 1
        assert len(proof.source_envelope_ids) <= 2
        assert len(proof.bank_entry_ids) <= 1
