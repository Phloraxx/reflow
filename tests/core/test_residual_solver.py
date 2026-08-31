from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from reflow.bank_proof import prove_all_bank_receipts
from reflow.domain import (
    Currency,
    Money,
    ProofVersionId,
    SettlementId,
    SourceEnvelopeId,
)
from reflow.ingestion import CanonicalBatch, ObservedBatch, ingest_observed_batch
from reflow.journal import InMemoryJournal
from reflow.money_graph import build_money_graph
from reflow.reconciliation_proof import InMemoryProofLedger, ReconciliationProofVersion
from reflow.residual_solver import (
    CandidateDisposition,
    ResidualCandidate,
    ResidualCandidateIndex,
    ResidualCandidateKind,
    ResidualExplanationState,
    ResidualScope,
    ResidualSolverError,
    ResidualSolverLimits,
    ResidualTarget,
    _solve_candidate_set,
    enumerate_residual_candidates,
    residual_targets,
    solve_all_residuals,
    solve_residual,
)
from reflow.settlement_proof import prove_all_settlement_compositions
from reflow.simulator import (
    BankExpectation,
    CorruptionKind,
    CorruptionPlan,
    WorldConfig,
    generate_world,
    observe_world,
)

T0 = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)


def _clean(world, seed: int) -> ObservedBatch:
    return observe_world(world, seed=seed, plan=CorruptionPlan(kinds=())).observed


def _prove(observed: ObservedBatch, *, received_at: datetime = T0):
    journal = InMemoryJournal()
    batch = ingest_observed_batch(observed, journal, received_at=received_at)
    graph = build_money_graph(batch)
    composition = prove_all_settlement_compositions(batch, graph)
    bank = prove_all_bank_receipts(batch)
    ledger = InMemoryProofLedger()
    update = ledger.apply_batch(
        batch,
        journal,
        composition,
        bank,
        knowledge_cutoff=received_at,
        generated_at=received_at + timedelta(seconds=1),
    )
    return batch, update.created_versions


def _proof_for(
    proofs: tuple[ReconciliationProofVersion, ...],
    settlement_id: SettlementId,
) -> ReconciliationProofVersion:
    return next(proof for proof in proofs if proof.settlement_id == settlement_id)


def test_wrong_recon_amount_creates_composition_residual_target() -> None:
    world = generate_world(201)
    observed = observe_world(
        world,
        seed=202,
        plan=CorruptionPlan(kinds=(CorruptionKind.WRONG_RECON_AMOUNT,)),
    ).observed
    batch, proofs = _prove(observed)
    proof = next(proof for proof in proofs if not proof.composition.residual.is_zero)
    targets = residual_targets(proof)
    target = next(target for target in targets if target.scope is ResidualScope.COMPOSITION)
    assert target.amount.amount_paise == -111
    assert target.proof_version_id == proof.id
    assert batch.compilation_sha256 == proof.batch_compilation_sha256


def test_amount_only_bank_candidate_is_hypothesis_not_proof() -> None:
    world = generate_world(211)
    case = next(
        case
        for case in world.cases
        if case.bank_expectation is BankExpectation.MATCHED and case.bank_entries
    )
    observed = _clean(world, 212)
    target_bank_id = str(case.bank_entries[0].id)
    original = next(row for row in observed.bank_rows if row["bank_entry_id"] == target_bank_id)
    candidate = dict(original)
    candidate["bank_entry_id"] = "bank_amount_only_candidate"
    candidate["utr"] = "UTR_WRONG_IDENTITY"
    candidate["narration"] = "same amount but not authoritative identity"
    changed = replace(
        observed,
        bank_rows=(
            *(
                row
                for row in observed.bank_rows
                if row["bank_entry_id"] != target_bank_id
            ),
            candidate,
        ),
    )
    batch, proofs = _prove(changed)
    proof = _proof_for(proofs, case.settlement.id)
    target = next(
        target for target in residual_targets(proof) if target.scope is ResidualScope.BANK
    )
    result = solve_residual(proof, batch, target)

    target_candidate = next(
        candidate
        for candidate in result.candidates_considered
        if candidate.source_entity_id == "bank_amount_only_candidate"
    )
    explanation = next(
        item for item in result.explanations if target_candidate.id in item.candidate_ids
    )
    assert explanation.remaining_residual.is_zero
    assert explanation.state is ResidualExplanationState.HYPOTHESIS
    assert "NOT_FINANCIAL_PROOF" in explanation.reason_codes
    assert "AMOUNT_ONLY_NOT_IDENTITY" in explanation.reason_codes
    assert not explanation.uses_blocked_evidence
    assert proof.bank.bank_entry_ids == ()


def test_blocked_late_recon_row_can_only_form_blocked_hypothesis() -> None:
    world = generate_world(221)
    case = next(case for case in world.cases if case.recon_entries)
    observed = _clean(world, 222)
    target_recon = str(case.recon_entries[0].id)
    recon_rows = [dict(row) for row in observed.recon_rows]
    row = next(row for row in recon_rows if row["recon_id"] == target_recon)
    row["occurred_at"] = (case.settlement.processed_at + timedelta(minutes=1)).isoformat()
    batch, proofs = _prove(replace(observed, recon_rows=tuple(recon_rows)))
    proof = _proof_for(proofs, case.settlement.id)
    target = next(
        target for target in residual_targets(proof) if target.scope is ResidualScope.COMPOSITION
    )
    result = solve_residual(proof, batch, target)

    exact = next(
        explanation
        for explanation in result.explanations
        if explanation.remaining_residual.is_zero
    )
    assert exact.uses_blocked_evidence
    assert "USES_BLOCKED_EVIDENCE" in exact.reason_codes
    assert "NOT_FINANCIAL_PROOF" in exact.reason_codes


def _candidate(suffix: str, amount: int) -> ResidualCandidate:
    source = SourceEnvelopeId(f"src_{suffix}")
    money = Money(amount, Currency.INR)
    return ResidualCandidate.create(
        settlement_id=SettlementId("setl_manual"),
        proof_version_id=ProofVersionId("proofv_manual"),
        scope=ResidualScope.BANK,
        kind=ResidualCandidateKind.UNMATCHED_BANK_CREDIT,
        amount=money,
        source_envelope_ids=(source,),
        source_entity_id=f"bank_{suffix}",
        disposition=CandidateDisposition.ADMISSIBLE_HYPOTHESIS,
        reason_codes=("AMOUNT_ONLY_NOT_IDENTITY",),
    )


def test_bounded_solver_finds_exact_two_candidate_combination() -> None:
    target = ResidualTarget(
        settlement_id=SettlementId("setl_manual"),
        proof_version_id=ProofVersionId("proofv_manual"),
        scope=ResidualScope.BANK,
        amount=Money(300, Currency.INR),
    )
    result = _solve_candidate_set(target, (_candidate("a", 100), _candidate("b", 200)))
    assert len(result.explanations) == 1
    assert len(result.explanations[0].candidate_ids) == 2
    assert result.explanations[0].remaining_residual.is_zero
    assert not result.search_budget_exhausted


def test_node_budget_is_deterministic_and_fail_closed() -> None:
    target = ResidualTarget(
        settlement_id=SettlementId("setl_manual"),
        proof_version_id=ProofVersionId("proofv_manual"),
        scope=ResidualScope.BANK,
        amount=Money(999, Currency.INR),
    )
    candidates = tuple(_candidate(str(index), 10 + index) for index in range(10))
    limits = ResidualSolverLimits(max_candidates=10, max_combination_size=3, max_nodes=3)
    first = _solve_candidate_set(target, candidates, limits=limits)
    second = _solve_candidate_set(target, tuple(reversed(candidates)), limits=limits)
    assert first.search_budget_exhausted
    assert first.nodes_visited == 3
    assert first == second


def test_candidate_enumeration_rejects_wrong_canonical_batch() -> None:
    first_world = generate_world(231)
    second_world = generate_world(232)
    first_batch, first_proofs = _prove(_clean(first_world, 233))
    second_batch, _ = _prove(_clean(second_world, 234))
    proof = next(proof for proof in first_proofs if residual_targets(proof))
    target = residual_targets(proof)[0]
    assert first_batch.compilation_sha256 != second_batch.compilation_sha256
    with pytest.raises(ResidualSolverError, match="proof's canonical batch"):
        enumerate_residual_candidates(proof, second_batch, target)


def test_bank_candidate_identified_to_other_settlement_is_blocked() -> None:
    world = generate_world(241)
    target_case = next(
        case for case in world.cases if case.bank_expectation is BankExpectation.MISSING
    )
    other_case = next(
        case
        for case in world.cases
        if case.settlement.id != target_case.settlement.id
        and case.settlement.utr is not None
        and case.bank_entries
    )
    observed = _clean(world, 242)
    template = dict(observed.bank_rows[0])
    template["bank_entry_id"] = "bank_claimed_elsewhere_candidate"
    template["amount_paise"] = 1
    template["utr"] = other_case.settlement.utr
    template["narration"] = "amount candidate already identified elsewhere"
    changed = replace(observed, bank_rows=(*observed.bank_rows, template))
    batch, proofs = _prove(changed)
    proof = _proof_for(proofs, target_case.settlement.id)
    target = next(
        item for item in residual_targets(proof) if item.scope is ResidualScope.BANK
    )
    candidates, _ = enumerate_residual_candidates(proof, batch, target)
    candidate = next(
        item
        for item in candidates
        if item.source_entity_id == "bank_claimed_elsewhere_candidate"
    )
    assert candidate.disposition is CandidateDisposition.BLOCKED_EVIDENCE
    assert "BANK_ENTRY_IDENTIFIED_TO_OTHER_SETTLEMENT" in candidate.reason_codes


def test_reusable_index_keeps_same_source_hypotheses_target_scoped() -> None:
    world = generate_world(251, WorldConfig(settlement_count=20))
    observed = _clean(world, 252)
    template = dict(observed.bank_rows[0])
    template["bank_entry_id"] = "bank_shared_amount_candidate"
    template["amount_paise"] = 1
    template["utr"] = "UTR_UNCLAIMED_SHARED_CANDIDATE"
    template["narration"] = "one amount-only row visible to two residual targets"
    changed = replace(observed, bank_rows=(*observed.bank_rows, template))
    batch, proofs = _prove(changed)
    missing_cases = [
        case for case in world.cases if case.bank_expectation is BankExpectation.MISSING
    ]
    assert len(missing_cases) >= 2
    index = ResidualCandidateIndex(batch)
    ids = []
    for case in missing_cases[:2]:
        proof = _proof_for(proofs, case.settlement.id)
        target = next(
            item for item in residual_targets(proof) if item.scope is ResidualScope.BANK
        )
        candidates, _ = enumerate_residual_candidates(
            proof,
            batch,
            target,
            index=index,
        )
        candidate = next(
            item
            for item in candidates
            if item.source_entity_id == "bank_shared_amount_candidate"
        )
        ids.append(candidate.id)
    assert ids[0] != ids[1]


def test_candidate_index_rejects_unbound_batch() -> None:
    with pytest.raises(ResidualSolverError, match="journal-backed"):
        ResidualCandidateIndex(
            CanonicalBatch(
                orders=(),
                payment_events=(),
                recon_entries=(),
                settlements=(),
                bank_entries=(),
            )
        )


def test_solution_cap_is_reported_as_incomplete_search() -> None:
    target = ResidualTarget(
        settlement_id=SettlementId("setl_manual"),
        proof_version_id=ProofVersionId("proofv_manual"),
        scope=ResidualScope.BANK,
        amount=Money(300, Currency.INR),
    )
    candidates = (
        _candidate("cap_a", 300),
        _candidate("cap_b", 300),
        _candidate("cap_c", 300),
    )
    result = _solve_candidate_set(
        target,
        candidates,
        limits=ResidualSolverLimits(max_solutions=1),
    )
    assert len(result.explanations) == 1
    assert result.solution_limit_reached
    assert not result.search_budget_exhausted

def test_batch_solver_reuses_one_index_and_emits_only_hypotheses() -> None:
    world = generate_world(261, WorldConfig(settlement_count=20))
    batch, proofs = _prove(_clean(world, 262))
    results = solve_all_residuals(proofs, batch)
    expected_targets = sum(len(residual_targets(proof)) for proof in proofs)
    assert len(results) == expected_targets
    assert results
    assert all(
        explanation.state is ResidualExplanationState.HYPOTHESIS
        for result in results
        for explanation in result.explanations
    )


def test_batch_solver_rejects_duplicate_proof_versions() -> None:
    world = generate_world(271)
    batch, proofs = _prove(_clean(world, 272))
    with pytest.raises(ResidualSolverError, match="duplicate proof version"):
        solve_all_residuals((*proofs, proofs[0]), batch)


def test_candidate_identity_binds_proof_version_and_disposition() -> None:
    candidate = _candidate("identity_binding", 100)
    with pytest.raises(ValueError, match="deterministic identity"):
        replace(candidate, proof_version_id=ProofVersionId("proofv_other"))
    with pytest.raises(ValueError, match="deterministic identity"):
        replace(candidate, disposition=CandidateDisposition.BLOCKED_EVIDENCE)


def test_residual_explanation_derives_metadata_from_embedded_candidates() -> None:
    target = ResidualTarget(
        settlement_id=SettlementId("setl_manual"),
        proof_version_id=ProofVersionId("proofv_manual"),
        scope=ResidualScope.BANK,
        amount=Money(300, Currency.INR),
    )
    result = _solve_candidate_set(target, (_candidate("self_a", 100), _candidate("self_b", 200)))
    explanation = result.explanations[0]
    assert explanation.candidate_ids == tuple(candidate.id for candidate in explanation.candidates)
    assert explanation.remaining_residual.is_zero
    assert explanation.source_envelope_ids
    assert "NOT_FINANCIAL_PROOF" in explanation.reason_codes
    with pytest.raises(ValueError, match="exactly close"):
        replace(explanation, candidates=(explanation.candidates[0],))


def test_pre_settlement_bank_amount_candidate_is_blocked() -> None:
    world = generate_world(281)
    target_case = next(
        case for case in world.cases if case.bank_expectation is BankExpectation.MISSING
    )
    observed = _clean(world, 282)
    template = dict(observed.bank_rows[0])
    template["bank_entry_id"] = "bank_pre_settlement_candidate"
    template["amount_paise"] = 1
    template["utr"] = "UTR_PRE_SETTLEMENT_AMOUNT_ONLY"
    template["occurred_at"] = (
        target_case.settlement.processed_at - timedelta(minutes=1)
    ).isoformat()
    template["narration"] = "amount-only credit before settlement processing"
    changed = replace(observed, bank_rows=(*observed.bank_rows, template))
    batch, proofs = _prove(changed)
    proof = _proof_for(proofs, target_case.settlement.id)
    target = next(
        item for item in residual_targets(proof) if item.scope is ResidualScope.BANK
    )
    candidates, _ = enumerate_residual_candidates(proof, batch, target)
    candidate = next(
        item for item in candidates if item.source_entity_id == "bank_pre_settlement_candidate"
    )
    assert candidate.disposition is CandidateDisposition.BLOCKED_EVIDENCE
    assert "BANK_CREDIT_PRECEDES_SETTLEMENT" in candidate.reason_codes

def test_solver_rejects_duplicate_candidate_identity() -> None:
    target = ResidualTarget(
        settlement_id=SettlementId("setl_manual"),
        proof_version_id=ProofVersionId("proofv_manual"),
        scope=ResidualScope.BANK,
        amount=Money(200, Currency.INR),
    )
    candidate = _candidate("duplicate_identity", 100)
    with pytest.raises(ResidualSolverError, match="duplicate identities"):
        _solve_candidate_set(target, (candidate, candidate))


def test_solver_never_double_counts_one_raw_envelope() -> None:
    target = ResidualTarget(
        settlement_id=SettlementId("setl_manual"),
        proof_version_id=ProofVersionId("proofv_manual"),
        scope=ResidualScope.BANK,
        amount=Money(300, Currency.INR),
    )
    shared = SourceEnvelopeId("src_shared_raw_evidence")
    first = ResidualCandidate.create(
        settlement_id=target.settlement_id,
        proof_version_id=target.proof_version_id,
        scope=target.scope,
        kind=ResidualCandidateKind.UNMATCHED_BANK_CREDIT,
        amount=Money(100, Currency.INR),
        source_envelope_ids=(shared,),
        source_entity_id="bank_shared_a",
        disposition=CandidateDisposition.ADMISSIBLE_HYPOTHESIS,
        reason_codes=("AMOUNT_ONLY_NOT_IDENTITY",),
    )
    second = ResidualCandidate.create(
        settlement_id=target.settlement_id,
        proof_version_id=target.proof_version_id,
        scope=target.scope,
        kind=ResidualCandidateKind.UNMATCHED_BANK_CREDIT,
        amount=Money(200, Currency.INR),
        source_envelope_ids=(shared,),
        source_entity_id="bank_shared_b",
        disposition=CandidateDisposition.ADMISSIBLE_HYPOTHESIS,
        reason_codes=("AMOUNT_ONLY_NOT_IDENTITY",),
    )
    result = _solve_candidate_set(target, (first, second))
    assert result.explanations == ()
