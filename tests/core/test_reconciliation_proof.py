from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from reflow.bank_proof import BankReceiptStatus, prove_all_bank_receipts
from reflow.domain import ProofVersionId, SourceEnvelopeId
from reflow.ingestion import ObservedBatch, ingest_observed_batch
from reflow.journal import InMemoryJournal
from reflow.money_graph import build_money_graph
from reflow.reconciliation_proof import (
    InMemoryProofLedger,
    ReconciliationProofError,
    ReconciliationStatus,
    diff_proof_versions,
)
from reflow.settlement_proof import prove_all_settlement_compositions
from reflow.simulator import (
    BankExpectation,
    CorruptionPlan,
    generate_world,
    observe_world,
)

T0 = datetime(2026, 8, 30, 7, 0, tzinfo=UTC)


def _clean_observed(world, seed: int) -> ObservedBatch:
    return observe_world(
        world,
        seed=seed,
        plan=CorruptionPlan(kinds=()),
    ).observed


def _prove(batch):
    graph = build_money_graph(batch)
    return (
        prove_all_settlement_compositions(batch, graph),
        prove_all_bank_receipts(batch),
    )


def _ingest(observed: ObservedBatch, journal: InMemoryJournal, received_at: datetime):
    batch = ingest_observed_batch(observed, journal, received_at=received_at)
    composition, bank = _prove(batch)
    return batch, composition, bank


def _matched_target(seed: int = 901):
    world = generate_world(seed)
    case = next(
        case
        for case in world.cases
        if case.bank_expectation is BankExpectation.MATCHED and case.bank_entries
    )
    observed = _clean_observed(world, seed + 1)
    return world, case, observed


def _remove_bank_row(observed: ObservedBatch, bank_entry_id: str) -> ObservedBatch:
    return replace(
        observed,
        bank_rows=tuple(
            row for row in observed.bank_rows if row["bank_entry_id"] != bank_entry_id
        ),
    )


def _append_unrelated_bank_row(
    observed: ObservedBatch,
    template_id: str,
    *,
    bank_entry_id: str,
    utr: str,
) -> ObservedBatch:
    template = next(row for row in observed.bank_rows if row["bank_entry_id"] == template_id)
    added = dict(template)
    added["bank_entry_id"] = bank_entry_id
    added["utr"] = utr
    added["narration"] = "unrelated diagnostic credit"
    return replace(observed, bank_rows=(*observed.bank_rows, added))


def test_first_batch_creates_one_immutable_version_per_settlement() -> None:
    observed = _clean_observed(generate_world(44), 45)
    journal = InMemoryJournal()
    batch, composition, bank = _ingest(observed, journal, T0)
    ledger = InMemoryProofLedger()

    update = ledger.apply_batch(
        batch,
        journal,
        composition,
        bank,
        knowledge_cutoff=T0,
        generated_at=T0 + timedelta(seconds=1),
    )

    assert len(update.created_versions) == len(batch.settlements)
    assert update.unchanged_settlement_ids == ()
    assert all(version.version == 1 for version in update.created_versions)
    assert all(isinstance(version.id, ProofVersionId) for version in update.created_versions)
    for version in update.created_versions:
        assert ledger.history(version.settlement_id) == (version,)
        assert version.batch_compilation_sha256 == batch.compilation_sha256


def test_same_financial_evidence_does_not_create_time_only_versions() -> None:
    observed = _clean_observed(generate_world(51), 52)
    journal = InMemoryJournal()
    batch, composition, bank = _ingest(observed, journal, T0)
    ledger = InMemoryProofLedger()
    first = ledger.apply_batch(
        batch,
        journal,
        composition,
        bank,
        knowledge_cutoff=T0,
        generated_at=T0 + timedelta(seconds=1),
    )

    second = ledger.apply_batch(
        batch,
        journal,
        composition,
        bank,
        knowledge_cutoff=T0 + timedelta(hours=1),
        generated_at=T0 + timedelta(hours=1, seconds=1),
    )

    assert len(first.created_versions) == len(batch.settlements)
    assert second.created_versions == ()
    assert set(second.unchanged_settlement_ids) == {row.id for row in batch.settlements}
    assert all(len(ledger.history(row.id)) == 1 for row in batch.settlements)


def test_unrelated_same_amount_bank_diagnostic_does_not_version_financial_truth() -> None:
    _, target, observed = _matched_target(71)
    journal = InMemoryJournal()
    batch1, comp1, bank1 = _ingest(observed, journal, T0)
    ledger = InMemoryProofLedger()
    ledger.apply_batch(
        batch1,
        journal,
        comp1,
        bank1,
        knowledge_cutoff=T0,
        generated_at=T0 + timedelta(seconds=1),
    )

    changed_observed = _append_unrelated_bank_row(
        observed,
        str(target.bank_entries[0].id),
        bank_entry_id="bank_unrelated_same_amount",
        utr="UTR_UNRELATED_DIAGNOSTIC",
    )
    batch2, comp2, bank2 = _ingest(changed_observed, journal, T0 + timedelta(hours=1))
    update = ledger.apply_batch(
        batch2,
        journal,
        comp2,
        bank2,
        knowledge_cutoff=T0 + timedelta(hours=1),
        generated_at=T0 + timedelta(hours=1, seconds=1),
    )

    target_bank1 = next(row for row in bank1 if row.settlement_id == target.settlement.id)
    target_bank2 = next(row for row in bank2 if row.settlement_id == target.settlement.id)
    assert target_bank2.same_amount_nonidentity_count > target_bank1.same_amount_nonidentity_count
    assert batch2.compilation_sha256 != batch1.compilation_sha256
    assert update.created_versions == ()
    assert all(len(ledger.history(row.id)) == 1 for row in batch1.settlements)


def test_late_exact_bank_credit_versions_only_affected_settlement() -> None:
    _, target, observed = _matched_target(81)
    target_bank_id = str(target.bank_entries[0].id)
    partial = _remove_bank_row(observed, target_bank_id)
    journal = InMemoryJournal()
    batch1, comp1, bank1 = _ingest(partial, journal, T0)
    ledger = InMemoryProofLedger()
    first = ledger.apply_batch(
        batch1,
        journal,
        comp1,
        bank1,
        knowledge_cutoff=T0,
        generated_at=T0 + timedelta(seconds=1),
    )
    v1 = ledger.latest(target.settlement.id)
    assert v1 is not None
    assert v1.status is ReconciliationStatus.PENDING_BANK_CREDIT
    target_bank_proof = next(
        proof for proof in bank1 if proof.settlement_id == target.settlement.id
    )
    assert target_bank_proof.status is BankReceiptStatus.WAITING

    later = T0 + timedelta(hours=2)
    batch2, comp2, bank2 = _ingest(observed, journal, later)
    second = ledger.apply_batch(
        batch2,
        journal,
        comp2,
        bank2,
        knowledge_cutoff=later,
        generated_at=later + timedelta(seconds=1),
    )
    v2 = ledger.latest(target.settlement.id)
    assert v2 is not None

    assert len(first.created_versions) == len(batch1.settlements)
    assert [row.settlement_id for row in second.created_versions] == [target.settlement.id]
    assert v2.version == 2
    assert v2.prior_version_id == v1.id
    assert v2.status is ReconciliationStatus.PROVEN_RECONCILED
    assert not v2.reopened
    assert batch2.compilation_sha256 != batch1.compilation_sha256
    assert all(
        len(ledger.history(row.id)) == (2 if row.id == target.settlement.id else 1)
        for row in batch2.settlements
    )

    diff = diff_proof_versions(v1, v2)
    assert diff.changed_fragments == ("bank",)
    assert diff.status_before is ReconciliationStatus.PENDING_BANK_CREDIT
    assert diff.status_after is ReconciliationStatus.PROVEN_RECONCILED
    assert diff.added_source_envelope_ids


def test_new_bank_contradiction_reopens_previously_proven_settlement() -> None:
    _, target, observed = _matched_target(91)
    target_bank_id = str(target.bank_entries[0].id)
    journal = InMemoryJournal()
    batch1, comp1, bank1 = _ingest(observed, journal, T0)
    ledger = InMemoryProofLedger()
    ledger.apply_batch(
        batch1,
        journal,
        comp1,
        bank1,
        knowledge_cutoff=T0,
        generated_at=T0 + timedelta(seconds=1),
    )
    v1 = ledger.latest(target.settlement.id)
    assert v1 is not None
    assert v1.status is ReconciliationStatus.PROVEN_RECONCILED

    target_row = next(row for row in observed.bank_rows if row["bank_entry_id"] == target_bank_id)
    duplicate = dict(target_row)
    duplicate["bank_entry_id"] = "bank_new_conflicting_utr_owner"
    contradicted_observed = replace(observed, bank_rows=(*observed.bank_rows, duplicate))
    later = T0 + timedelta(hours=2)
    batch2, comp2, bank2 = _ingest(contradicted_observed, journal, later)
    update = ledger.apply_batch(
        batch2,
        journal,
        comp2,
        bank2,
        knowledge_cutoff=later,
        generated_at=later + timedelta(seconds=1),
    )
    v2 = ledger.latest(target.settlement.id)
    assert v2 is not None

    assert [row.settlement_id for row in update.created_versions] == [target.settlement.id]
    assert v2.status is ReconciliationStatus.CONTRADICTED
    assert v2.reopened
    assert "REOPENED_AFTER_PROVEN" in v2.reason_codes
    assert "BANK:BANK_UTR_REUSED_ACROSS_ENTRIES" in v2.reason_codes
    diff = diff_proof_versions(v1, v2)
    assert diff.changed_fragments == ("bank",)
    assert diff.reopened


def test_proof_cannot_cite_evidence_received_after_knowledge_cutoff() -> None:
    observed = _clean_observed(generate_world(101), 102)
    journal = InMemoryJournal()
    received = T0 + timedelta(hours=1)
    batch, composition, bank = _ingest(observed, journal, received)

    with pytest.raises(ReconciliationProofError, match="after knowledge cutoff"):
        InMemoryProofLedger().apply_batch(
            batch,
            journal,
            composition,
            bank,
            knowledge_cutoff=T0,
            generated_at=received + timedelta(seconds=1),
        )


def test_authoritative_evidence_cannot_disappear_from_later_version() -> None:
    _, target, observed = _matched_target(111)
    target_bank_id = str(target.bank_entries[0].id)
    journal = InMemoryJournal()
    batch1, comp1, bank1 = _ingest(observed, journal, T0)
    ledger = InMemoryProofLedger()
    ledger.apply_batch(
        batch1,
        journal,
        comp1,
        bank1,
        knowledge_cutoff=T0,
        generated_at=T0 + timedelta(seconds=1),
    )

    later = T0 + timedelta(hours=1)
    reduced = _remove_bank_row(observed, target_bank_id)
    batch2, comp2, bank2 = _ingest(reduced, journal, later)
    with pytest.raises(ReconciliationProofError, match="authoritative evidence disappeared"):
        ledger.apply_batch(
            batch2,
            journal,
            comp2,
            bank2,
            knowledge_cutoff=later,
            generated_at=later + timedelta(seconds=1),
        )


def test_gate9_requires_complete_batch_safe_fragment_sets() -> None:
    observed = _clean_observed(generate_world(121), 122)
    journal = InMemoryJournal()
    batch, composition, bank = _ingest(observed, journal, T0)

    with pytest.raises(ReconciliationProofError, match="exactly one Gate 7 and Gate 8"):
        InMemoryProofLedger().apply_batch(
            batch,
            journal,
            composition[:-1],
            bank,
            knowledge_cutoff=T0,
            generated_at=T0 + timedelta(seconds=1),
        )


def test_proof_diff_rejects_different_settlement_series() -> None:
    observed = _clean_observed(generate_world(131), 132)
    journal = InMemoryJournal()
    batch, composition, bank = _ingest(observed, journal, T0)
    ledger = InMemoryProofLedger()
    update = ledger.apply_batch(
        batch,
        journal,
        composition,
        bank,
        knowledge_cutoff=T0,
        generated_at=T0 + timedelta(seconds=1),
    )
    first, second = update.created_versions[:2]
    assert first.settlement_id != second.settlement_id
    with pytest.raises(ReconciliationProofError, match="different settlements"):
        diff_proof_versions(first, second)

def test_batch_failure_is_atomic_and_does_not_partially_append_versions() -> None:
    observed = _clean_observed(generate_world(141), 142)
    journal = InMemoryJournal()
    batch, composition, bank = _ingest(observed, journal, T0)
    ledger = InMemoryProofLedger()
    last_settlement_id = sorted((row.id for row in batch.settlements), key=str)[-1]
    damaged_bank = tuple(
        replace(
            proof,
            source_envelope_ids=(SourceEnvelopeId("src_not_in_batch"),),
        )
        if proof.settlement_id == last_settlement_id
        else proof
        for proof in bank
    )

    with pytest.raises(ReconciliationProofError, match="outside canonical batch"):
        ledger.apply_batch(
            batch,
            journal,
            composition,
            damaged_bank,
            knowledge_cutoff=T0,
            generated_at=T0 + timedelta(seconds=1),
        )

    assert all(ledger.history(row.id) == () for row in batch.settlements)


def _matched_target_with_multiple_recon(seed: int):
    world = generate_world(seed)
    case = next(
        case
        for case in world.cases
        if case.bank_expectation is BankExpectation.MATCHED
        and case.bank_entries
        and len(case.recon_entries) > 1
    )
    return world, case, _clean_observed(world, seed + 1)


def _remove_recon_row(observed: ObservedBatch, recon_id: str) -> ObservedBatch:
    return replace(
        observed,
        recon_rows=tuple(row for row in observed.recon_rows if row["recon_id"] != recon_id),
    )


def test_late_recon_component_versions_only_affected_settlement() -> None:
    _, target, observed = _matched_target_with_multiple_recon(151)
    removed_id = str(target.recon_entries[0].id)
    partial = _remove_recon_row(observed, removed_id)
    journal = InMemoryJournal()
    batch1, comp1, bank1 = _ingest(partial, journal, T0)
    ledger = InMemoryProofLedger()
    ledger.apply_batch(
        batch1,
        journal,
        comp1,
        bank1,
        knowledge_cutoff=T0,
        generated_at=T0 + timedelta(seconds=1),
    )
    v1 = ledger.latest(target.settlement.id)
    assert v1 is not None
    assert v1.status is ReconciliationStatus.RESIDUAL

    later = T0 + timedelta(hours=2)
    batch2, comp2, bank2 = _ingest(observed, journal, later)
    update = ledger.apply_batch(
        batch2,
        journal,
        comp2,
        bank2,
        knowledge_cutoff=later,
        generated_at=later + timedelta(seconds=1),
    )
    v2 = ledger.latest(target.settlement.id)
    assert v2 is not None

    assert [proof.settlement_id for proof in update.created_versions] == [target.settlement.id]
    assert v2.status is ReconciliationStatus.PROVEN_RECONCILED
    assert not v2.reopened
    diff = diff_proof_versions(v1, v2)
    assert diff.changed_fragments == ("composition",)
    assert diff.added_source_envelope_ids


def test_new_duplicate_recon_evidence_reopens_proven_settlement() -> None:
    _, target, observed = _matched_target_with_multiple_recon(161)
    journal = InMemoryJournal()
    batch1, comp1, bank1 = _ingest(observed, journal, T0)
    ledger = InMemoryProofLedger()
    ledger.apply_batch(
        batch1,
        journal,
        comp1,
        bank1,
        knowledge_cutoff=T0,
        generated_at=T0 + timedelta(seconds=1),
    )
    v1 = ledger.latest(target.settlement.id)
    assert v1 is not None
    assert v1.status is ReconciliationStatus.PROVEN_RECONCILED

    original_id = str(target.recon_entries[0].id)
    original = next(row for row in observed.recon_rows if row["recon_id"] == original_id)
    duplicate = dict(original)
    duplicate["recon_id"] = f"{original_id}_late_duplicate"
    changed = replace(observed, recon_rows=(*observed.recon_rows, duplicate))
    later = T0 + timedelta(hours=2)
    batch2, comp2, bank2 = _ingest(changed, journal, later)
    update = ledger.apply_batch(
        batch2,
        journal,
        comp2,
        bank2,
        knowledge_cutoff=later,
        generated_at=later + timedelta(seconds=1),
    )
    v2 = ledger.latest(target.settlement.id)
    assert v2 is not None

    assert [proof.settlement_id for proof in update.created_versions] == [target.settlement.id]
    assert v2.status is ReconciliationStatus.CONTRADICTED
    assert v2.reopened
    assert "REOPENED_AFTER_PROVEN" in v2.reason_codes
    assert "COMPOSITION:DUPLICATE_ECONOMIC_ROW" in v2.reason_codes
    diff = diff_proof_versions(v1, v2)
    assert diff.changed_fragments == ("composition",)
    assert diff.reopened


def test_proof_identity_is_invariant_to_raw_delivery_order() -> None:
    observed = _clean_observed(generate_world(171), 172)
    reversed_observed = replace(
        observed,
        merchant_rows=tuple(reversed(observed.merchant_rows)),
        razorpay_events=tuple(reversed(observed.razorpay_events)),
        recon_rows=tuple(reversed(observed.recon_rows)),
        settlement_rows=tuple(reversed(observed.settlement_rows)),
        bank_rows=tuple(reversed(observed.bank_rows)),
    )

    journal1 = InMemoryJournal()
    batch1, comp1, bank1 = _ingest(observed, journal1, T0)
    update1 = InMemoryProofLedger().apply_batch(
        batch1,
        journal1,
        comp1,
        bank1,
        knowledge_cutoff=T0,
        generated_at=T0 + timedelta(seconds=1),
    )

    journal2 = InMemoryJournal()
    batch2, comp2, bank2 = _ingest(reversed_observed, journal2, T0)
    update2 = InMemoryProofLedger().apply_batch(
        batch2,
        journal2,
        comp2,
        bank2,
        knowledge_cutoff=T0,
        generated_at=T0 + timedelta(minutes=5),
    )

    assert batch1.compilation_sha256 == batch2.compilation_sha256
    assert [proof.id for proof in update1.created_versions] == [
        proof.id for proof in update2.created_versions
    ]
    assert [proof.scoped_input_sha256 for proof in update1.created_versions] == [
        proof.scoped_input_sha256 for proof in update2.created_versions
    ]


def test_global_batch_hash_cannot_claim_cutoff_before_unrelated_evidence() -> None:
    _, target, observed = _matched_target(181)
    journal = InMemoryJournal()
    _ingest(observed, journal, T0)
    changed = _append_unrelated_bank_row(
        observed,
        str(target.bank_entries[0].id),
        bank_entry_id="bank_future_unrelated",
        utr="UTR_FUTURE_UNRELATED",
    )
    later = T0 + timedelta(hours=2)
    batch2, comp2, bank2 = _ingest(changed, journal, later)

    with pytest.raises(ReconciliationProofError, match="batch contains evidence after"):
        InMemoryProofLedger().apply_batch(
            batch2,
            journal,
            comp2,
            bank2,
            knowledge_cutoff=T0,
            generated_at=later + timedelta(seconds=1),
        )
