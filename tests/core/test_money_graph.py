from reflow.ingestion import adapt_observed_batch
from reflow.money_graph import EdgeKey, build_money_graph, evaluate_edges
from reflow.simulator import CorruptionKind, CorruptionPlan, generate_world, observe_world


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
                    "movement_in_settlement",
                    str(recon.entity_id),
                    str(recon.settlement_id),
                )
            )
    return expected


def _graph(seed: int, *corruptions: CorruptionKind):
    world = generate_world(seed)
    observed = observe_world(
        world,
        seed=seed + 1,
        plan=CorruptionPlan(kinds=tuple(corruptions)),
    ).observed
    return build_money_graph(adapt_observed_batch(observed))


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
    assert metrics.false_negative == 1


def test_bank_narration_never_creates_proven_graph_relationship() -> None:
    seed = 44
    clean = _graph(seed)
    hostile = _graph(seed, CorruptionKind.PROMPT_LIKE_NARRATION)
    assert hostile.edge_keys == clean.edge_keys


def test_graph_edges_are_deterministic() -> None:
    first = _graph(45)
    second = _graph(45)
    assert first == second
