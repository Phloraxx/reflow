from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

from reflow import domain
from reflow.evaluation.candidates import (
    CandidateDecision,
    CandidateRun,
    CandidateStatus,
)
from reflow.evaluation.harness import evaluate_observation
from reflow.evaluation.scoring import score_candidate_run
from reflow.simulator import CorruptionPlan, WorldConfig, generate_world, observe_world


def _clean_observation(seed: int, *, settlements: int = 20):
    world = generate_world(seed, WorldConfig(settlement_count=settlements))
    observed = observe_world(
        world,
        seed=seed + 1,
        plan=CorruptionPlan(kinds=()),
    ).observed
    return world, observed


def test_candidate_system_module_has_no_hidden_truth_import() -> None:
    path = Path("src/reflow/evaluation/candidates.py")
    tree = ast.parse(path.read_text())
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.append(node.module)
    assert not any(name.startswith("reflow.simulator") for name in imports)
    assert "HiddenWorld" not in path.read_text()


def test_clean_world_runs_all_baselines_and_reflow_without_silent_false_match() -> None:
    world, observed = _clean_observation(301)
    result = evaluate_observation(world, observed)
    reports = {report.system_name: report for report in result.reports}

    assert set(reports) == {
        "B0_naive_1to1",
        "B1_grouped_exact",
        "B2_fuzzy_threshold",
        "ReFlow_Core",
    }
    assert all(report.missing_decisions == 0 for report in reports.values())
    assert reports["ReFlow_Core"].false_auto_reconciled == 0
    assert reports["ReFlow_Core"].true_auto_reconciled == reports["ReFlow_Core"].truth_reconciled
    assert (
        reports["B0_naive_1to1"].true_auto_reconciled
        < reports["ReFlow_Core"].true_auto_reconciled
    )


def test_scorer_catches_intentionally_broken_reconcile_everything_mutation() -> None:
    world, _ = _clean_observation(311)
    decisions = []
    for case in sorted(world.cases, key=lambda item: str(item.settlement.id)):
        bank_ids = tuple(entry.id for entry in case.bank_entries)
        decisions.append(
            CandidateDecision(
                settlement_id=case.settlement.id,
                status=CandidateStatus.RECONCILED,
                composition_amount=case.settlement.amount,
                composition_residual=domain.Money.zero(case.settlement.amount.currency),
                bank_residual=domain.Money.zero(case.settlement.amount.currency),
                composition_component_ids=tuple(entry.id for entry in case.recon_entries),
                bank_entry_ids=bank_ids,
                reason_codes=("INTENTIONALLY_BROKEN_MUTATION",),
            )
        )
    report = score_candidate_run(world, CandidateRun("broken_reconcile_all", tuple(decisions)))

    assert report.false_auto_reconciled > 0
    assert report.silent_false_auto_match_rate.numerator == report.false_auto_reconciled
    assert report.silent_false_auto_match_rate.denominator == len(world.cases)


def test_scorer_catches_wrong_bank_edge_even_when_status_is_unresolved() -> None:
    world, _ = _clean_observation(321)
    first = world.cases[0]
    second = next(case for case in world.cases[1:] if case.bank_entries)
    decision = CandidateDecision(
        settlement_id=first.settlement.id,
        status=CandidateStatus.UNRESOLVED,
        composition_amount=first.settlement.amount,
        composition_residual=domain.Money.zero(first.settlement.amount.currency),
        bank_residual=first.settlement.amount,
        composition_component_ids=tuple(entry.id for entry in first.recon_entries),
        bank_entry_ids=(second.bank_entries[0].id,),
        reason_codes=("INTENTIONALLY_WRONG_EDGE",),
    )
    report = score_candidate_run(world, CandidateRun("broken_bank_edge", (decision,)))
    assert report.bank_edges.false_positive == 1
    assert report.missing_decisions == len(world.cases) - 1


def test_fuzzy_baseline_can_false_match_amount_time_while_reflow_refuses() -> None:
    world, observed = _clean_observation(331, settlements=20)
    target = next(case for case in world.cases if not case.bank_entries)
    template = dict(observed.bank_rows[0])
    template["bank_entry_id"] = "bank_eval_wrong_amount_time_match"
    template["amount_paise"] = target.settlement.amount.amount_paise
    template["currency"] = target.settlement.amount.currency.value
    template["occurred_at"] = target.settlement.processed_at.isoformat()
    template["utr"] = "UTR_WRONG_FOR_TARGET"
    template["narration"] = "RAZORPAY settlement amount candidate"
    changed = replace(observed, bank_rows=(*observed.bank_rows, template))

    reports = {
        report.system_name: report
        for report in evaluate_observation(world, changed).reports
    }
    assert reports["B2_fuzzy_threshold"].false_auto_reconciled >= 1
    assert reports["ReFlow_Core"].false_auto_reconciled == 0


def test_hidden_scenario_position_changes_across_seeds() -> None:
    first = generate_world(341, WorldConfig(settlement_count=20))
    second = generate_world(342, WorldConfig(settlement_count=20))
    assert tuple(case.scenario for case in first.cases) != tuple(
        case.scenario for case in second.cases
    )
