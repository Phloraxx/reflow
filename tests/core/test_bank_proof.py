from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from reflow.bank_proof import (
    BankReceiptProofError,
    BankReceiptStatus,
    prove_all_bank_receipts,
    prove_bank_receipt,
)
from reflow.domain import Money, SourceKind
from reflow.ingestion import ingest_observed_batch
from reflow.journal import InMemoryJournal
from reflow.simulator import (
    CorruptionKind,
    CorruptionPlan,
    WorldConfig,
    generate_world,
    observe_world,
)

RECEIVED = datetime(2026, 8, 30, 0, 0, tzinfo=UTC)


def _observed(seed: int, *corruptions: CorruptionKind, config: WorldConfig | None = None):
    return observe_world(
        generate_world(seed, config),
        seed=seed + 2000,
        plan=CorruptionPlan(kinds=tuple(corruptions)),
    ).observed


def _ingest(observed):
    journal = InMemoryJournal()
    batch = ingest_observed_batch(observed, journal, received_at=RECEIVED)
    return batch, journal


def _proofs(seed: int, *corruptions: CorruptionKind):
    batch, journal = _ingest(_observed(seed, *corruptions))
    return batch, journal, prove_all_bank_receipts(batch)


def test_clean_world_matches_gate_8_supported_bank_semantics() -> None:
    seed = 101
    world = generate_world(seed)
    batch, _, proofs = _proofs(seed)
    by_id = {proof.settlement_id: proof for proof in proofs}

    assert len(proofs) == len(batch.settlements)
    for case in world.cases:
        proof = by_id[case.settlement.id]
        if case.scenario == "missing_bank_receipt":
            assert proof.status is BankReceiptStatus.WAITING
            assert proof.bank_entry_ids == ()
            assert proof.reason_codes == ("BANK_RECEIPT_NOT_OBSERVED",)
        elif case.scenario == "incorrect_bank_amount":
            assert proof.status is BankReceiptStatus.RESIDUAL
            assert proof.residual.amount_paise == 137
            assert proof.reason_codes == ("BANK_AMOUNT_MISMATCH",)
        else:
            assert proof.status is BankReceiptStatus.PROVEN
            assert proof.residual.is_zero
            assert proof.reason_codes == ()


def test_two_distinct_bank_transactions_reusing_standard_settlement_utr_are_contradicted() -> None:
    seed = 102
    world = generate_world(seed)
    observed = _observed(seed)
    case = next(case for case in world.cases if case.scenario == "clean")
    original = next(
        row for row in observed.bank_rows if row["bank_entry_id"] == str(case.bank_entries[0].id)
    )
    duplicate_utr = dict(original)
    duplicate_utr["bank_entry_id"] = "bank_duplicate_utr_attack"
    duplicate_utr["amount_paise"] = 1
    duplicate_utr["occurred_at"] = (
        case.bank_entries[0].occurred_at + timedelta(minutes=1)
    ).isoformat()

    batch, _ = _ingest(replace(observed, bank_rows=(*observed.bank_rows, duplicate_utr)))
    proof = next(
        proof
        for proof in prove_all_bank_receipts(batch)
        if proof.settlement_id == case.settlement.id
    )

    assert proof.status is BankReceiptStatus.CONTRADICTED
    assert proof.bank_entry_ids == ()
    assert set(str(entry_id) for entry_id in proof.reused_bank_utr_ids) == {
        str(case.bank_entries[0].id),
        "bank_duplicate_utr_attack",
    }
    assert proof.observed_bank_credit.is_zero
    assert proof.reason_codes == ("BANK_UTR_REUSED_ACROSS_ENTRIES",)


def test_bank_proof_source_envelopes_resolve_to_raw_journal() -> None:
    batch, journal, proofs = _proofs(103)
    journal_ids = {entry.id for entry in journal.entries()}
    source_index = batch.source_index()

    for proof in proofs:
        assert set(proof.source_envelope_ids).issubset(journal_ids)
        assert source_index[(SourceKind.RAZORPAY_SETTLEMENT, str(proof.settlement_id))] in (
            proof.source_envelope_ids
        )
        for bank_entry_id in (
            *proof.bank_entry_ids,
            *proof.early_bank_entry_ids,
            *proof.reused_bank_utr_ids,
        ):
            assert source_index[(SourceKind.BANK, str(bank_entry_id))] in (
                proof.source_envelope_ids
            )


def test_missing_bank_utr_never_falls_back_to_same_amount_or_narration() -> None:
    seed = 104
    world = generate_world(seed)
    observed = _observed(seed)
    case = next(case for case in world.cases if case.scenario == "clean")
    target_id = str(case.bank_entries[0].id)

    bank_rows = [dict(row) for row in observed.bank_rows]
    target = next(row for row in bank_rows if row["bank_entry_id"] == target_id)
    target["utr"] = None
    target["narration"] = f"RAZORPAY SETTLEMENT {case.settlement.utr}"

    batch, _ = _ingest(replace(observed, bank_rows=tuple(bank_rows)))
    proof = next(
        proof
        for proof in prove_all_bank_receipts(batch)
        if proof.settlement_id == case.settlement.id
    )

    assert proof.status is BankReceiptStatus.WAITING
    assert proof.bank_entry_ids == ()
    assert proof.same_amount_nonidentity_count >= 1
    assert proof.reason_codes == (
        "BANK_RECEIPT_NOT_OBSERVED",
        "SAME_AMOUNT_NOT_IDENTITY",
    )


def test_corrupted_bank_utr_does_not_match_by_amount_and_nearby_time() -> None:
    seed = 105
    world = generate_world(seed)
    observed = _observed(seed)
    case = next(case for case in world.cases if case.scenario == "clean")
    target_id = str(case.bank_entries[0].id)

    bank_rows = [dict(row) for row in observed.bank_rows]
    target = next(row for row in bank_rows if row["bank_entry_id"] == target_id)
    target["utr"] = "CORRUPTED-UTR"

    batch, _ = _ingest(replace(observed, bank_rows=tuple(bank_rows)))
    proof = next(
        proof
        for proof in prove_all_bank_receipts(batch)
        if proof.settlement_id == case.settlement.id
    )

    assert proof.status is BankReceiptStatus.WAITING
    assert proof.same_amount_nonidentity_count >= 1
    assert "SAME_AMOUNT_NOT_IDENTITY" in proof.reason_codes


def test_settlement_without_utr_is_incomplete_even_with_exact_amount_bank_credit() -> None:
    seed = 106
    world = generate_world(seed)
    observed = _observed(seed)
    case = next(case for case in world.cases if case.scenario == "clean")

    settlement_rows = [dict(row) for row in observed.settlement_rows]
    target = next(
        row for row in settlement_rows if row["settlement_id"] == str(case.settlement.id)
    )
    target["utr"] = None

    batch, _ = _ingest(replace(observed, settlement_rows=tuple(settlement_rows)))
    proof = next(
        proof
        for proof in prove_all_bank_receipts(batch)
        if proof.settlement_id == case.settlement.id
    )

    assert proof.status is BankReceiptStatus.INCOMPLETE
    assert proof.bank_entry_ids == ()
    assert proof.same_amount_nonidentity_count >= 1
    assert proof.reason_codes == (
        "SAME_AMOUNT_NOT_IDENTITY",
        "SETTLEMENT_UTR_MISSING",
    )


def test_exact_utr_with_wrong_amount_is_residual_not_proven() -> None:
    seed = 107
    world = generate_world(seed)
    _, _, proofs = _proofs(seed)
    case = next(case for case in world.cases if case.scenario == "incorrect_bank_amount")
    proof = next(proof for proof in proofs if proof.settlement_id == case.settlement.id)

    assert proof.status is BankReceiptStatus.RESIDUAL
    assert proof.bank_entry_ids == tuple(entry.id for entry in case.bank_entries)
    assert proof.residual.amount_paise == 137
    assert proof.reason_codes == ("BANK_AMOUNT_MISMATCH",)


def test_bank_credit_before_settlement_processing_is_contradicted_and_excluded() -> None:
    seed = 108
    world = generate_world(seed)
    observed = _observed(seed)
    case = next(case for case in world.cases if case.scenario == "clean")
    target_id = str(case.bank_entries[0].id)

    bank_rows = [dict(row) for row in observed.bank_rows]
    target = next(row for row in bank_rows if row["bank_entry_id"] == target_id)
    target["occurred_at"] = (case.settlement.processed_at - timedelta(minutes=1)).isoformat()

    batch, _ = _ingest(replace(observed, bank_rows=tuple(bank_rows)))
    proof = next(
        proof
        for proof in prove_all_bank_receipts(batch)
        if proof.settlement_id == case.settlement.id
    )

    assert proof.status is BankReceiptStatus.CONTRADICTED
    assert proof.bank_entry_ids == ()
    assert proof.early_bank_entry_ids == (case.bank_entries[0].id,)
    assert proof.observed_bank_credit.is_zero
    assert proof.reason_codes == ("BANK_CREDIT_PRECEDES_SETTLEMENT",)


def test_credit_at_exact_settlement_processing_time_is_causally_admissible() -> None:
    seed = 109
    world = generate_world(seed)
    _, _, proofs = _proofs(seed)
    case = next(case for case in world.cases if case.scenario == "immediate_bank_credit")
    proof = next(proof for proof in proofs if proof.settlement_id == case.settlement.id)

    assert case.bank_entries[0].occurred_at == case.settlement.processed_at
    assert proof.status is BankReceiptStatus.PROVEN
    assert proof.bank_entry_ids == (case.bank_entries[0].id,)


def test_reused_settlement_utr_contradicts_both_settlements() -> None:
    seed = 110
    world = generate_world(seed)
    observed = _observed(seed)
    first, second = world.cases[0], world.cases[1]
    assert first.settlement.utr is not None

    settlement_rows = [dict(row) for row in observed.settlement_rows]
    second_row = next(
        row for row in settlement_rows if row["settlement_id"] == str(second.settlement.id)
    )
    second_row["utr"] = first.settlement.utr

    batch, _ = _ingest(replace(observed, settlement_rows=tuple(settlement_rows)))
    by_id = {proof.settlement_id: proof for proof in prove_all_bank_receipts(batch)}

    assert by_id[first.settlement.id].status is BankReceiptStatus.CONTRADICTED
    assert by_id[second.settlement.id].status is BankReceiptStatus.CONTRADICTED
    assert by_id[first.settlement.id].bank_entry_ids == ()
    assert by_id[second.settlement.id].bank_entry_ids == ()
    assert "SETTLEMENT_UTR_REUSED" in by_id[first.settlement.id].reason_codes
    assert "SETTLEMENT_UTR_REUSED" in by_id[second.settlement.id].reason_codes


def test_identical_bank_source_replay_is_idempotent_not_double_counted() -> None:
    seed = 111
    world = generate_world(seed)
    observed = _observed(seed)
    case = next(case for case in world.cases if case.scenario == "clean")
    target = next(
        row for row in observed.bank_rows if row["bank_entry_id"] == str(case.bank_entries[0].id)
    )
    replayed = replace(observed, bank_rows=(*observed.bank_rows, dict(target)))

    batch, _ = _ingest(replayed)
    proof = next(
        proof
        for proof in prove_all_bank_receipts(batch)
        if proof.settlement_id == case.settlement.id
    )

    assert proof.status is BankReceiptStatus.PROVEN
    assert proof.bank_entry_ids == (case.bank_entries[0].id,)
    assert proof.observed_bank_credit == case.settlement.amount


def test_conflicting_duplicate_bank_identity_fails_closed() -> None:
    batch, _ = _ingest(_observed(112))
    original = batch.bank_entries[0]
    conflicting = replace(
        original,
        amount=Money(original.amount.amount_paise + 1, original.amount.currency),
    )
    settlement = next(
        row for row in batch.settlements if row.utr is not None and row.utr == original.utr
    )

    with pytest.raises(BankReceiptProofError, match="conflicting canonical payloads"):
        prove_bank_receipt(
            settlement,
            (*batch.bank_entries, conflicting),
            source_index=batch.source_index(),
        )


def test_missing_bank_source_provenance_fails_closed() -> None:
    batch, _ = _ingest(_observed(113))
    settlement = batch.settlements[0]
    exact_bank = tuple(
        row for row in batch.bank_entries if row.utr is not None and row.utr == settlement.utr
    )
    source_index = batch.source_index()
    for row in exact_bank:
        source_index.pop((SourceKind.BANK, str(row.id)))

    with pytest.raises(BankReceiptProofError, match="missing journal-backed source provenance"):
        prove_bank_receipt(
            settlement,
            batch.bank_entries,
            source_index=source_index,
        )


def test_bank_delay_has_no_arbitrary_upper_time_cutoff() -> None:
    clean_batch, _, clean_proofs = _proofs(114)
    delayed_batch, _, delayed_proofs = _proofs(114, CorruptionKind.BANK_CREDIT_DELAY)

    assert [proof.status for proof in delayed_proofs] == [proof.status for proof in clean_proofs]
    assert [proof.settlement_id for proof in delayed_proofs] == [
        proof.settlement_id for proof in clean_proofs
    ]
    assert len(delayed_batch.bank_entries) == len(clean_batch.bank_entries)


def test_prompt_like_or_noisy_bank_narration_never_changes_bank_identity() -> None:
    _, _, clean = _proofs(115)
    _, _, prompt = _proofs(115, CorruptionKind.PROMPT_LIKE_NARRATION)
    _, _, noisy = _proofs(115, CorruptionKind.BANK_NARRATION_NOISE)

    clean_shape = [(proof.settlement_id, proof.status, proof.bank_entry_ids) for proof in clean]
    assert [(proof.settlement_id, proof.status, proof.bank_entry_ids) for proof in prompt] == (
        clean_shape
    )
    assert [(proof.settlement_id, proof.status, proof.bank_entry_ids) for proof in noisy] == (
        clean_shape
    )


def test_same_amount_settlements_remain_independent_by_utr() -> None:
    seed = 116
    world = generate_world(seed)
    _, _, proofs = _proofs(seed)
    by_id = {proof.settlement_id: proof for proof in proofs}
    index = next(
        index for index, case in enumerate(world.cases) if case.scenario == "same_amount_collision"
    )
    current = world.cases[index]
    previous = world.cases[index - 1]

    assert current.settlement.amount == previous.settlement.amount
    assert current.settlement.utr != previous.settlement.utr
    assert by_id[current.settlement.id].status is BankReceiptStatus.PROVEN
    assert by_id[previous.settlement.id].status is BankReceiptStatus.PROVEN
    assert set(by_id[current.settlement.id].bank_entry_ids).isdisjoint(
        by_id[previous.settlement.id].bank_entry_ids
    )


def test_gate_8_handles_hundreds_of_settlements_without_cross_partition_matching() -> None:
    config = WorldConfig(
        settlement_count=200,
        min_payments=2,
        max_payments=3,
        high_cardinality_payments=3,
    )
    world = generate_world(117, config)
    observed = observe_world(
        world,
        seed=2117,
        plan=CorruptionPlan(kinds=()),
    ).observed
    batch, _ = _ingest(observed)
    proofs = prove_all_bank_receipts(batch)
    by_id = {proof.settlement_id: proof for proof in proofs}

    assert len(proofs) == 200
    for case in world.cases:
        proof = by_id[case.settlement.id]
        if case.scenario == "missing_bank_receipt":
            assert proof.status is BankReceiptStatus.WAITING
        elif case.scenario == "incorrect_bank_amount":
            assert proof.status is BankReceiptStatus.RESIDUAL
        else:
            assert proof.status is BankReceiptStatus.PROVEN
