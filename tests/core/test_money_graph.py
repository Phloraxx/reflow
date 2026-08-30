from dataclasses import replace
from datetime import UTC, datetime

import pytest

from reflow.ingestion import adapt_observed_batch, ingest_observed_batch
from reflow.journal import InMemoryJournal
from reflow.money_graph import (
    EdgeKey,
    MoneyGraphError,
    build_money_graph,
    evaluate_edges,
)
from reflow.simulator import CorruptionKind, CorruptionPlan, generate_world, observe_world

RECEIVED = datetime(2026, 8, 29, 18, 0, tzinfo=UTC)


def _expected_edges(seed: int) -> set[EdgeKey]:
    world = generate_world(seed)
    expected: set[EdgeKey] = set()
    for case in world.cases:
        for event in case.payment_events:
            if event.order_id is not None:
                expected.add(
                    ("order_has_payment", str(event.order_id), str(event.payment_id))
                )
        for recon in case.recon_entries:
            expected.add(
                (
                    "entity_has_recon_entry",
                    str(recon.entity_id),
                    str(recon.id),
                )
            )
            expected.add(
                (
                    "recon_entry_contributes_to_settlement",
                    str(recon.id),
                    str(recon.settlement_id),
                )
            )
    return expected


def _observed(seed: int, *corruptions: CorruptionKind):
    return observe_world(
        generate_world(seed),
        seed=seed + 1,
        plan=CorruptionPlan(kinds=tuple(corruptions)),
    ).observed


def _graph(seed: int, *corruptions: CorruptionKind):
    journal = InMemoryJournal()
    canonical = ingest_observed_batch(
        _observed(seed, *corruptions),
        journal,
        received_at=RECEIVED,
    )
    return build_money_graph(canonical)


def test_clean_graph_has_perfect_edge_precision_and_recall() -> None:
    seed = 42
    metrics = evaluate_edges(_graph(seed), _expected_edges(seed))
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0
    assert metrics.false_positive == 0
    assert metrics.false_negative == 0


def test_missing_recon_row_reduces_recall_without_inventing_edges() -> None:
    seed = 43
    metrics = evaluate_edges(
        _graph(seed, CorruptionKind.MISSING_RECON_ROW),
        _expected_edges(seed),
    )
    assert metrics.precision == 1.0
    assert metrics.recall < 1.0
    assert metrics.false_positive == 0
    assert metrics.false_negative == 2


def test_duplicate_economic_recon_row_is_visible_as_false_positive_evidence() -> None:
    seed = 46
    metrics = evaluate_edges(
        _graph(seed, CorruptionKind.DUPLICATE_RECON_ROW),
        _expected_edges(seed),
    )
    assert metrics.precision < 1.0
    assert metrics.recall == 1.0
    assert metrics.false_positive == 2
    assert metrics.false_negative == 0


def test_conflicting_order_identity_cannot_mutate_journal_backed_batch() -> None:
    journal = InMemoryJournal()
    canonical = ingest_observed_batch(_observed(47), journal, received_at=RECEIVED)
    original = canonical.payment_events[0]
    other_order = next(order.id for order in canonical.orders if order.id != original.order_id)
    conflicting = replace(original, order_id=other_order)

    with pytest.raises(ValueError, match="compiled source binding"):
        replace(
            canonical,
            payment_events=(conflicting, *canonical.payment_events[1:]),
        )


def test_adapter_only_batch_cannot_bypass_raw_evidence_journal() -> None:
    canonical = adapt_observed_batch(_observed(48))
    with pytest.raises(MoneyGraphError, match="journal-backed"):
        build_money_graph(canonical)


def test_graph_evidence_ids_resolve_to_raw_source_envelopes() -> None:
    journal = InMemoryJournal()
    canonical = ingest_observed_batch(_observed(49), journal, received_at=RECEIVED)
    graph = build_money_graph(canonical)
    journal_ids = {str(envelope.id) for envelope in journal.entries()}
    assert graph.edges
    for edge in graph.edges:
        assert edge.evidence_ids
        assert set(edge.evidence_ids).issubset(journal_ids)
        assert all(evidence_id.startswith("src_") for evidence_id in edge.evidence_ids)


def test_bank_narration_never_creates_proven_graph_relationship() -> None:
    seed = 44
    clean = _graph(seed)
    hostile = _graph(seed, CorruptionKind.PROMPT_LIKE_NARRATION)
    assert hostile.edge_keys == clean.edge_keys


def test_graph_edges_are_deterministic() -> None:
    first = _graph(45)
    second = _graph(45)
    assert first == second
