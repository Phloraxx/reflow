from reflow.simulator import BankExpectation, WorldConfig, generate_world


def test_world_is_deterministic_by_seed() -> None:
    first = generate_world(20260829)
    second = generate_world(20260829)
    assert first == second


def test_different_seeds_change_world() -> None:
    assert generate_world(1) != generate_world(2)


def test_default_world_covers_required_shapes() -> None:
    world = generate_world(42)
    scenarios = {case.scenario for case in world.cases}
    assert {
        "clean",
        "refund",
        "adjustment",
        "split_bank_credit",
        "missing_bank_receipt",
        "incorrect_bank_amount",
        "cross_period_refund",
        "same_amount_collision",
        "high_cardinality",
        "transfer",
    }.issubset(scenarios)


def test_composition_conservation_holds_across_many_seeds() -> None:
    for seed in range(25):
        generate_world(seed).validate()


def test_cross_period_refund_targets_prior_payment_before_current_settlement() -> None:
    world = generate_world(1234)
    index = next(
        index for index, case in enumerate(world.cases) if case.scenario == "cross_period_refund"
    )
    assert index > 0
    case = world.cases[index]
    prior_payment_ids = {
        event.payment_id for prior in world.cases[:index] for event in prior.payment_events
    }
    current_payment_ids = {event.payment_id for event in case.payment_events}
    assert len(case.refunds) == 1
    refund = case.refunds[0]
    assert refund.payment_id in prior_payment_ids
    assert refund.payment_id not in current_payment_ids
    assert refund.created_at <= case.settlement.processed_at


def test_high_cardinality_case_is_real_not_label_only() -> None:
    config = WorldConfig(high_cardinality_payments=400)
    world = generate_world(7, config)
    case = next(case for case in world.cases if case.scenario == "high_cardinality")
    captured = [event for event in case.payment_events if event.kind.value == "captured"]
    assert len(captured) == 400
    assert len(case.recon_entries) >= 400


def test_large_high_cardinality_events_still_precede_settlement() -> None:
    config = WorldConfig(settlement_count=9, high_cardinality_payments=15_000)
    world = generate_world(70, config)
    case = next(case for case in world.cases if case.scenario == "high_cardinality")
    assert max(event.occurred_at for event in case.payment_events) < case.settlement.processed_at


def test_bank_truth_contains_resolvable_and_exception_cases() -> None:
    world = generate_world(99)
    expectations = {case.bank_expectation for case in world.cases}
    assert BankExpectation.MATCHED in expectations
    assert BankExpectation.SPLIT_MATCHED in expectations
    assert BankExpectation.MISSING in expectations
    assert BankExpectation.MISMATCHED in expectations


def test_same_amount_collision_really_collides() -> None:
    world = generate_world(123)
    collision_index = next(
        index for index, case in enumerate(world.cases) if case.scenario == "same_amount_collision"
    )
    assert collision_index > 0
    assert world.cases[collision_index].settlement.amount == world.cases[
        collision_index - 1
    ].settlement.amount
