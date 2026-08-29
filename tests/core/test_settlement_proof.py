from dataclasses import replace
from random import Random

import pytest

from reflow.ingestion import adapt_observed_batch
from reflow.money_graph import MoneyGraph, build_money_graph
from reflow.settlement_proof import (
    CompositionProofError,
    CompositionStatus,
    prove_all_settlement_compositions,
    prove_settlement_composition,
)
from reflow.simulator import CorruptionKind, CorruptionPlan, generate_world, observe_world


def _batch(seed: int, *corruptions: CorruptionKind):
    observed = observe_world(
        generate_world(seed),
        seed=seed + 1000,
        plan=CorruptionPlan(kinds=tuple(corruptions)),
    ).observed
    return adapt_observed_batch(observed)


def test_clean_world_proves_every_settlement_composition() -> None:
    for seed in range(10):
        batch = _batch(seed)
        graph = build_money_graph(batch)
        proofs = prove_all_settlement_compositions(batch, graph)
        assert len(proofs) == len(batch.settlements)
        assert all(proof.status is CompositionStatus.PROVEN for proof in proofs)
        assert all(proof.residual.is_zero for proof in proofs)
        assert all(proof.reason_codes == () for proof in proofs)


def test_missing_recon_row_produces_explicit_residual() -> None:
    batch = _batch(20, CorruptionKind.MISSING_RECON_ROW)
    graph = build_money_graph(batch)
    proofs = prove_all_settlement_compositions(batch, graph)
    residuals = [proof for proof in proofs if proof.status is CompositionStatus.RESIDUAL]
    assert len(residuals) == 1
    assert not residuals[0].residual.is_zero
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
    # The duplicate is not counted twice. A zero residual cannot override contradiction.
    assert proof.residual.is_zero


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
    proof = prove_settlement_composition(settlement, rows, damaged_graph)
    assert proof.status is CompositionStatus.INCOMPLETE
    assert proof.residual.is_zero
    assert proof.reason_codes == ("MISSING_GRAPH_PROVENANCE",)


def test_recon_row_order_does_not_change_composition_proof() -> None:
    batch = _batch(23)
    graph = build_money_graph(batch)
    settlement = batch.settlements[0]
    rows = [row for row in batch.recon_entries if row.settlement_id == settlement.id]
    first = prove_settlement_composition(settlement, tuple(rows), graph)
    Random(5).shuffle(rows)
    second = prove_settlement_composition(settlement, tuple(rows), graph)
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
    for scenario in ("split_bank_credit", "missing_bank_receipt", "incorrect_bank_amount"):
        case = next(case for case in world.cases if case.scenario == scenario)
        proof = next(proof for proof in proofs if proof.settlement_id == case.settlement.id)
        assert proof.status is CompositionStatus.PROVEN


def test_recon_for_unknown_settlement_fails_closed() -> None:
    batch = _batch(27)
    graph = build_money_graph(batch)
    removed_id = batch.settlements[0].id
    malformed = replace(
        batch,
        settlements=tuple(row for row in batch.settlements if row.id != removed_id),
    )
    with pytest.raises(CompositionProofError, match="unknown settlement"):
        prove_all_settlement_compositions(malformed, graph)


def test_duplicate_settlement_identity_fails_closed() -> None:
    batch = _batch(28)
    graph = build_money_graph(batch)
    malformed = replace(batch, settlements=(*batch.settlements, batch.settlements[0]))
    with pytest.raises(CompositionProofError, match="duplicate settlement id"):
        prove_all_settlement_compositions(malformed, graph)
