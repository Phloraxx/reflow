from dataclasses import replace
from datetime import UTC, datetime, timedelta
from random import Random

import pytest

from reflow.domain import ReconEntryId, SourceKind
from reflow.ingestion import ingest_observed_batch
from reflow.journal import InMemoryJournal
from reflow.money_graph import MoneyGraph, build_money_graph
from reflow.settlement_proof import (
    CompositionProofError,
    CompositionStatus,
    _prove_settlement_composition,
    prove_all_settlement_compositions,
)
from reflow.simulator import CorruptionKind, CorruptionPlan, generate_world, observe_world

RECEIVED = datetime(2026, 8, 29, 18, 0, tzinfo=UTC)


def _observed(seed: int, *corruptions: CorruptionKind):
    return observe_world(
        generate_world(seed),
        seed=seed + 1000,
        plan=CorruptionPlan(kinds=tuple(corruptions)),
    ).observed


def _ingest(observed):
    journal = InMemoryJournal()
    batch = ingest_observed_batch(observed, journal, received_at=RECEIVED)
    return batch, journal


def _ingested(seed: int, *corruptions: CorruptionKind):
    return _ingest(_observed(seed, *corruptions))


def _batch(seed: int, *corruptions: CorruptionKind):
    return _ingested(seed, *corruptions)[0]


def test_clean_world_proves_every_settlement_composition() -> None:
    for seed in range(10):
        batch = _batch(seed)
        graph = build_money_graph(batch)
        proofs = prove_all_settlement_compositions(batch, graph)
        assert len(proofs) == len(batch.settlements)
        assert all(proof.status is CompositionStatus.PROVEN for proof in proofs)
        assert all(proof.residual.is_zero for proof in proofs)
        assert all(proof.reason_codes == () for proof in proofs)
        assert all(proof.source_envelope_ids for proof in proofs)


def test_proof_source_envelopes_resolve_to_raw_journal() -> None:
    batch, journal = _ingested(11)
    graph = build_money_graph(batch)
    journal_ids = {entry.id for entry in journal.entries()}
    for proof in prove_all_settlement_compositions(batch, graph):
        assert set(proof.source_envelope_ids).issubset(journal_ids)
        assert any(
            link.source_kind is SourceKind.RAZORPAY_SETTLEMENT
            and link.source_record_id == str(proof.settlement_id)
            and link.envelope_id in proof.source_envelope_ids
            for link in batch.source_links
        )


def test_missing_recon_row_produces_explicit_residual() -> None:
    batch = _batch(20, CorruptionKind.MISSING_RECON_ROW)
    graph = build_money_graph(batch)
    proofs = prove_all_settlement_compositions(batch, graph)
    residuals = [proof for proof in proofs if proof.status is CompositionStatus.RESIDUAL]
    assert len(residuals) == 1
    assert not residuals[0].residual.is_zero
    assert residuals[0].reason_codes == ("SETTLEMENT_COMPOSITION_RESIDUAL",)


def test_well_formed_wrong_recon_amount_reaches_proof_as_residual() -> None:
    batch = _batch(36, CorruptionKind.WRONG_RECON_AMOUNT)
    graph = build_money_graph(batch)
    proofs = prove_all_settlement_compositions(batch, graph)
    residuals = [proof for proof in proofs if proof.status is CompositionStatus.RESIDUAL]
    assert len(residuals) == 1
    assert residuals[0].residual.amount_paise == -111
    assert residuals[0].reason_codes == ("SETTLEMENT_COMPOSITION_RESIDUAL",)


def test_duplicate_economic_recon_row_is_contradiction_not_double_counted() -> None:
    batch = _batch(21, CorruptionKind.DUPLICATE_RECON_ROW)
    graph = build_money_graph(batch)
    proofs = prove_all_settlement_compositions(batch, graph)
    contradicted = [
        proof for proof in proofs if proof.status is CompositionStatus.CONTRADICTED
    ]
    assert len(contradicted) == 1
    proof = contradicted[0]
    assert proof.reason_codes == ("DUPLICATE_ECONOMIC_ROW",)
    assert len(proof.duplicate_groups) == 1
    # A distinct source row with the same economic movement is not counted twice.
    assert proof.residual.is_zero


def test_exact_replay_of_same_recon_source_row_is_idempotent() -> None:
    observed = _observed(29)
    recon_rows = list(observed.recon_rows)
    recon_rows.append(dict(recon_rows[0]))
    batch, journal = _ingest(replace(observed, recon_rows=tuple(recon_rows)))
    graph = build_money_graph(batch)
    proofs = prove_all_settlement_compositions(batch, graph)
    assert all(proof.status is CompositionStatus.PROVEN for proof in proofs)
    # Raw duplicate delivery collapses to one source envelope identity.
    assert len(batch.source_links) == len(journal)


def test_same_economic_identity_with_conflicting_values_is_contradicted() -> None:
    observed = _observed(30)
    recon_rows = [dict(row) for row in observed.recon_rows]
    target = recon_rows[0]
    conflict = dict(target)
    conflict["recon_id"] = f"{target['recon_id']}_conflict"
    gross = target["gross_amount_paise"]
    effect = target["settlement_effect_paise"]
    assert isinstance(gross, int)
    assert isinstance(effect, int)
    conflict["gross_amount_paise"] = gross + 101
    conflict["settlement_effect_paise"] = effect + 101
    recon_rows.append(conflict)

    batch, _ = _ingest(replace(observed, recon_rows=tuple(recon_rows)))
    graph = build_money_graph(batch)
    proofs = prove_all_settlement_compositions(batch, graph)
    settlement_id = target["settlement_id"]
    proof = next(proof for proof in proofs if str(proof.settlement_id) == settlement_id)
    assert proof.status is CompositionStatus.CONTRADICTED
    assert "ECONOMIC_IDENTITY_CONFLICT" in proof.reason_codes
    assert not proof.duplicate_groups
    assert len(proof.conflicting_groups) == 1


def test_recon_after_settlement_is_contradicted_and_excluded_from_arithmetic() -> None:
    observed = _observed(31)
    recon_rows = [dict(row) for row in observed.recon_rows]
    settlements = {row["settlement_id"]: row for row in observed.settlement_rows}
    target = recon_rows[0]
    settlement_row = settlements[target["settlement_id"]]
    processed = settlement_row["processed_at"]
    assert isinstance(processed, str)
    target["occurred_at"] = (
        datetime.fromisoformat(processed) + timedelta(seconds=1)
    ).isoformat()

    batch, _ = _ingest(replace(observed, recon_rows=tuple(recon_rows)))
    graph = build_money_graph(batch)
    proofs = prove_all_settlement_compositions(batch, graph)
    proof = next(
        proof for proof in proofs if str(proof.settlement_id) == target["settlement_id"]
    )
    assert proof.status is CompositionStatus.CONTRADICTED
    assert "RECON_AFTER_SETTLEMENT" in proof.reason_codes
    assert str(target["recon_id"]) not in {str(row_id) for row_id in proof.component_ids}
    assert any(str(row_id) == target["recon_id"] for row_id in proof.late_component_ids)


def test_same_economic_entity_cannot_belong_to_two_settlements() -> None:
    observed = _observed(32)
    recon_rows = [dict(row) for row in observed.recon_rows]
    payment_rows = [row for row in recon_rows if row["entity_kind"] == "payment"]
    original = payment_rows[0]
    other_settlement = next(
        row for row in observed.settlement_rows if row["settlement_id"] != original["settlement_id"]
    )
    clone = dict(original)
    clone["recon_id"] = f"{original['recon_id']}_other_settlement"
    clone["settlement_id"] = other_settlement["settlement_id"]
    recon_rows.append(clone)

    batch, _ = _ingest(replace(observed, recon_rows=tuple(recon_rows)))
    graph = build_money_graph(batch)
    proofs = prove_all_settlement_compositions(batch, graph)
    affected = [
        proof
        for proof in proofs
        if "ECONOMIC_ENTITY_IN_MULTIPLE_SETTLEMENTS" in proof.reason_codes
    ]
    assert len(affected) == 2
    assert all(proof.status is CompositionStatus.CONTRADICTED for proof in affected)
    expected_conflict_ids = {
        ReconEntryId(str(original["recon_id"])),
        ReconEntryId(str(clone["recon_id"])),
    }
    source_index = batch.source_index()
    expected_conflict_sources = {
        source_index[(SourceKind.RAZORPAY_RECON, str(entry_id))]
        for entry_id in expected_conflict_ids
    }
    for proof in affected:
        assert set(proof.cross_settlement_conflict_ids) == expected_conflict_ids
        assert expected_conflict_sources.issubset(proof.source_envelope_ids)


def test_missing_provenance_makes_zero_residual_incomplete() -> None:
    batch = _batch(22)
    graph = build_money_graph(batch)
    settlement = batch.settlements[0]
    rows = tuple(
        row for row in batch.recon_entries if row.settlement_id == settlement.id
    )
    target = rows[0].id
    damaged_graph = MoneyGraph(
        nodes=graph.nodes,
        edges=tuple(
            edge
            for edge in graph.edges
            if not (
                edge.relationship == "entity_has_recon_entry"
                and str(edge.to_id) == str(target)
            )
        ),
    )
    proof = _prove_settlement_composition(
        settlement,
        rows,
        damaged_graph,
        source_index=batch.source_index(),
        cross_settlement_claims=frozenset(),
    )
    assert proof.status is CompositionStatus.INCOMPLETE
    assert proof.residual.is_zero
    assert proof.reason_codes == ("MISSING_GRAPH_PROVENANCE",)


def test_provenance_edge_with_wrong_raw_evidence_id_is_not_authoritative() -> None:
    batch = _batch(33)
    graph = build_money_graph(batch)
    settlement = batch.settlements[0]
    rows = tuple(
        row for row in batch.recon_entries if row.settlement_id == settlement.id
    )
    target = rows[0]
    damaged_edges = []
    for edge in graph.edges:
        if edge.relationship == "entity_has_recon_entry" and edge.to_id == target.id:
            damaged_edges.append(replace(edge, evidence_ids=(str(target.id),)))
        else:
            damaged_edges.append(edge)
    proof = _prove_settlement_composition(
        settlement,
        rows,
        MoneyGraph(nodes=graph.nodes, edges=tuple(damaged_edges)),
        source_index=batch.source_index(),
        cross_settlement_claims=frozenset(),
    )
    assert proof.status is CompositionStatus.INCOMPLETE
    assert proof.reason_codes == ("MISSING_GRAPH_PROVENANCE",)


def test_missing_settlement_raw_provenance_fails_closed() -> None:
    batch = _batch(34)
    graph = build_money_graph(batch)
    settlement = batch.settlements[0]
    rows = tuple(
        row for row in batch.recon_entries if row.settlement_id == settlement.id
    )
    source_index = batch.source_index()
    source_index.pop((SourceKind.RAZORPAY_SETTLEMENT, str(settlement.id)))
    with pytest.raises(CompositionProofError, match="source provenance"):
        _prove_settlement_composition(
            settlement,
            rows,
            graph,
            source_index=source_index,
            cross_settlement_claims=frozenset(),
        )


def test_recon_row_order_does_not_change_composition_proof() -> None:
    batch = _batch(23)
    graph = build_money_graph(batch)
    settlement = batch.settlements[0]
    rows = [row for row in batch.recon_entries if row.settlement_id == settlement.id]
    first = _prove_settlement_composition(
        settlement,
        tuple(rows),
        graph,
        source_index=batch.source_index(),
        cross_settlement_claims=frozenset(),
    )
    Random(5).shuffle(rows)
    second = _prove_settlement_composition(
        settlement,
        tuple(rows),
        graph,
        source_index=batch.source_index(),
        cross_settlement_claims=frozenset(),
    )
    assert second == first


def test_same_amount_collision_does_not_cross_link_components() -> None:
    batch = _batch(24)
    graph = build_money_graph(batch)
    proofs = prove_all_settlement_compositions(batch, graph)
    by_id = {proof.settlement_id: proof for proof in proofs}
    world = generate_world(24)
    index = next(
        index for index, case in enumerate(world.cases) if case.scenario == "same_amount_collision"
    )
    current = world.cases[index].settlement
    previous = world.cases[index - 1].settlement
    assert current.amount == previous.amount
    assert by_id[current.id].status is CompositionStatus.PROVEN
    assert by_id[previous.id].status is CompositionStatus.PROVEN
    assert set(by_id[current.id].component_ids).isdisjoint(
        by_id[previous.id].component_ids
    )


def test_cross_period_refund_composes_into_current_settlement() -> None:
    seed = 25
    batch = _batch(seed)
    graph = build_money_graph(batch)
    proofs = prove_all_settlement_compositions(batch, graph)
    world = generate_world(seed)
    case = next(case for case in world.cases if case.scenario == "cross_period_refund")
    proof = next(proof for proof in proofs if proof.settlement_id == case.settlement.id)
    assert proof.status is CompositionStatus.PROVEN
    refund_recon_ids = {
        row.id for row in case.recon_entries if row.entity_kind.value == "refund"
    }
    assert refund_recon_ids.issubset(set(proof.component_ids))


def test_bank_shape_does_not_affect_composition_proof() -> None:
    seed = 26
    batch = _batch(seed)
    graph = build_money_graph(batch)
    proofs = prove_all_settlement_compositions(batch, graph)
    world = generate_world(seed)
    for scenario in ("immediate_bank_credit", "missing_bank_receipt", "incorrect_bank_amount"):
        case = next(case for case in world.cases if case.scenario == scenario)
        proof = next(proof for proof in proofs if proof.settlement_id == case.settlement.id)
        assert proof.status is CompositionStatus.PROVEN


def test_journal_backed_batch_cannot_drop_settlement_and_provenance_together() -> None:
    batch = _batch(27)
    removed_id = batch.settlements[0].id
    source_links = tuple(
        link
        for link in batch.source_links
        if not (
            link.source_kind is SourceKind.RAZORPAY_SETTLEMENT
            and link.source_record_id == str(removed_id)
        )
    )

    with pytest.raises(ValueError, match="compiled source binding"):
        replace(
            batch,
            settlements=tuple(row for row in batch.settlements if row.id != removed_id),
            source_links=source_links,
        )


def test_journal_backed_batch_cannot_duplicate_settlement_identity() -> None:
    batch = _batch(28)
    with pytest.raises(ValueError, match="duplicate source identities"):
        replace(batch, settlements=(*batch.settlements, batch.settlements[0]))


def test_single_composition_call_rejects_rows_for_another_settlement() -> None:
    batch = _batch(35)
    graph = build_money_graph(batch)
    settlement = batch.settlements[0]
    foreign_row = next(
        row for row in batch.recon_entries if row.settlement_id != settlement.id
    )

    with pytest.raises(CompositionProofError, match="another settlement"):
        _prove_settlement_composition(
            settlement,
            (foreign_row,),
            graph,
            source_index=batch.source_index(),
        cross_settlement_claims=frozenset(),
        )


def test_batch_composition_builds_one_provenance_index_per_batch(monkeypatch) -> None:
    import reflow.settlement_proof as module

    first_batch = _batch(37)
    second_batch = _batch(38)
    calls = 0
    original = module._provenance_edge_index

    def counted(graph_value):
        nonlocal calls
        calls += 1
        return original(graph_value)

    monkeypatch.setattr(module, "_provenance_edge_index", counted)
    first = module.prove_all_settlement_compositions(first_batch, build_money_graph(first_batch))
    second = module.prove_all_settlement_compositions(second_batch, build_money_graph(second_batch))
    assert len(first) == len(first_batch.settlements)
    assert len(second) == len(second_batch.settlements)
    assert calls == 2
