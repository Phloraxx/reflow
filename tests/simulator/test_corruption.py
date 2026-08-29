from reflow.simulator.corrupt import CorruptionPlan, observe_world
from reflow.simulator.truth import generate_world


def test_corruption_is_deterministic_by_seed() -> None:
    world = generate_world(17)
    first = observe_world(world, seed=91)
    second = observe_world(world, seed=91)
    assert first == second


def test_corruption_does_not_mutate_hidden_truth() -> None:
    world = generate_world(18)
    before = repr(world)
    observe_world(world, seed=92)
    assert repr(world) == before
    world.validate()


def test_observed_records_do_not_expose_truth_labels() -> None:
    observed = observe_world(generate_world(19), seed=93).observed
    forbidden = {"scenario", "bank_expectation", "expected_outcome", "hidden_truth"}
    groups = (
        observed.merchant_rows,
        observed.razorpay_events,
        observed.recon_rows,
        observed.settlement_rows,
        observed.bank_rows,
    )
    for rows in groups:
        for row in rows:
            assert forbidden.isdisjoint(row)


def test_default_plan_exercises_all_declared_corruptions() -> None:
    bundle = observe_world(generate_world(20), seed=94)
    applied = {record.kind for record in bundle.manifest}
    expected = {kind.value for kind in CorruptionPlan().kinds}
    assert applied == expected


def test_empty_plan_is_a_clean_observation_without_manifest() -> None:
    bundle = observe_world(generate_world(21), seed=95, plan=CorruptionPlan(kinds=()))
    assert bundle.manifest == ()
    assert bundle.observed.record_count > 0
