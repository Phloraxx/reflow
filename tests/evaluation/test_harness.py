from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pytest

from reflow import domain
from reflow.evaluation.candidates import (
    CandidateDecision,
    CandidateRun,
    CandidateStatus,
)
from reflow.evaluation.harness import evaluate_observation
from reflow.evaluation.scoring import project_hidden_truth, score_candidate_run
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
                settlement_amount=case.settlement.amount,
                composition_amount=case.settlement.amount,
                bank_amount=case.settlement.amount,
                composition_component_ids=tuple(
                    sorted((entry.id for entry in case.recon_entries), key=str)
                ),
                bank_entry_ids=tuple(sorted(bank_ids, key=str)),
                reason_codes=("INTENTIONALLY_BROKEN_MUTATION",),
            )
        )
    report = score_candidate_run(
        project_hidden_truth(world),
        CandidateRun("broken_reconcile_all", tuple(decisions)),
    )

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
        settlement_amount=first.settlement.amount,
        composition_amount=first.settlement.amount,
        bank_amount=domain.Money.zero(first.settlement.amount.currency),
        composition_component_ids=tuple(entry.id for entry in first.recon_entries),
        bank_entry_ids=(second.bank_entries[0].id,),
        reason_codes=("INTENTIONALLY_WRONG_EDGE",),
    )
    report = score_candidate_run(
        project_hidden_truth(world), CandidateRun("broken_bank_edge", (decision,))
    )
    assert report.bank_edges.false_positive == 1
    assert report.missing_decisions == len(world.cases) - 1




def test_auto_reconciled_with_wrong_bank_identity_is_a_silent_false_match() -> None:
    world, _ = _clean_observation(326)
    first = next(case for case in world.cases if case.bank_entries)
    second = next(
        case
        for case in world.cases
        if case.settlement.id != first.settlement.id and case.bank_entries
    )
    decision = CandidateDecision(
        settlement_id=first.settlement.id,
        status=CandidateStatus.RECONCILED,
        settlement_amount=first.settlement.amount,
        composition_amount=first.settlement.amount,
        bank_amount=first.settlement.amount,
        composition_component_ids=tuple(
            sorted((entry.id for entry in first.recon_entries), key=str)
        ),
        bank_entry_ids=(second.bank_entries[0].id,),
        reason_codes=("INTENTIONALLY_WRONG_AUTO_BANK_EDGE",),
    )
    report = score_candidate_run(
        project_hidden_truth(world), CandidateRun("wrong_auto_edge", (decision,))
    )
    assert report.auto_reconciled == 1
    assert report.true_auto_reconciled == 0
    assert report.false_auto_reconciled == 1
    assert report.silent_false_auto_match_rate.numerator == 1


def test_auto_reconciled_with_correct_ids_but_wrong_bank_amount_is_false() -> None:
    world, _ = _clean_observation(327)
    case = next(case for case in world.cases if case.bank_entries)
    decision = CandidateDecision(
        settlement_id=case.settlement.id,
        status=CandidateStatus.RECONCILED,
        settlement_amount=case.settlement.amount,
        composition_amount=case.settlement.amount,
        bank_amount=domain.Money.zero(case.settlement.amount.currency),
        composition_component_ids=tuple(
            sorted((entry.id for entry in case.recon_entries), key=str)
        ),
        bank_entry_ids=tuple(sorted((entry.id for entry in case.bank_entries), key=str)),
        reason_codes=("INTENTIONALLY_WRONG_AUTO_BANK_AMOUNT",),
    )
    report = score_candidate_run(
        project_hidden_truth(world), CandidateRun("wrong_auto_amount", (decision,))
    )
    assert report.auto_reconciled == 1
    assert report.true_auto_reconciled == 0
    assert report.false_auto_reconciled == 1


def test_evaluation_report_rejects_inconsistent_derived_metrics() -> None:
    from reflow.evaluation.scoring import CountMetric

    world, observed = _clean_observation(328)
    report = evaluate_observation(world, observed).reports[-1]
    with pytest.raises(ValueError, match="reconciliation recall"):
        replace(report, reconciliation_recall=CountMetric(0, report.truth_reconciled))
    if report.auto_reconciled:
        with pytest.raises(ValueError, match="silent false-match rate"):
            replace(
                report,
                silent_false_auto_match_rate=CountMetric(1, report.auto_reconciled),
            )

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


def test_source_schema_failure_is_reported_after_raw_evidence_is_retained() -> None:
    from reflow.evaluation.harness import EvaluationSourceRejected, evaluate_observation
    from reflow.simulator import CorruptionKind

    world = generate_world(351, WorldConfig(settlement_count=20))
    observed = observe_world(
        world,
        seed=352,
        plan=CorruptionPlan(kinds=(CorruptionKind.SCHEMA_RENAME,)),
    ).observed
    with pytest.raises(EvaluationSourceRejected) as caught:
        evaluate_observation(world, observed)
    assert caught.value.rejection.error_type == "AdapterError"
    assert caught.value.rejection.retained_raw_envelopes > 0


def test_benchmark_payload_is_deterministic_for_same_seed_profile() -> None:
    from reflow.evaluation.profiles import EvaluationProfile
    from reflow.evaluation.runner import benchmark_payload

    kwargs = {
        "world_seed": 361,
        "observation_seed": 362,
        "settlement_count": 20,
        "profile": EvaluationProfile.CLEAN,
    }
    first = benchmark_payload(**kwargs)
    second = benchmark_payload(**kwargs)
    assert first == second
    assert first["status"] == "evaluated"
    assert len(first["truth"]["settlements"]) == 20
    assert all("scenario" not in item for item in first["truth"]["settlements"])
    assert len(first["runs"]) == 4
    assert len(first["reports"]) == 4


def test_reconciliation_adversarial_profile_remains_canonicalizable() -> None:
    from reflow.evaluation.profiles import EvaluationProfile
    from reflow.evaluation.runner import benchmark_payload

    payload = benchmark_payload(
        world_seed=371,
        observation_seed=372,
        settlement_count=20,
        profile=EvaluationProfile.RECONCILIATION_ADVERSARIAL,
    )
    assert payload["status"] == "evaluated"
    assert payload["corruptions"]


def test_reflow_core_stays_fail_closed_across_development_seed_matrix() -> None:
    from reflow.evaluation.profiles import EvaluationProfile, corruption_plan

    seed_pairs = ((401, 1401), (402, 1402), (403, 1403), (404, 1404), (405, 1405))
    for world_seed, observation_seed in seed_pairs:
        world = generate_world(world_seed, WorldConfig(settlement_count=12))
        observed = observe_world(
            world,
            seed=observation_seed,
            plan=corruption_plan(EvaluationProfile.RECONCILIATION_ADVERSARIAL),
        ).observed
        reports = {
            report.system_name: report
            for report in evaluate_observation(world, observed).reports
        }
        reflow = reports["ReFlow_Core"]
        assert reflow.false_auto_reconciled == 0
        assert reflow.missing_decisions == 0
        assert reflow.auto_reconciled + reflow.unresolved == len(world.cases)


def test_evaluation_is_invariant_to_source_row_permutation() -> None:
    world, observed = _clean_observation(411, settlements=20)
    permuted = replace(
        observed,
        merchant_rows=tuple(reversed(observed.merchant_rows)),
        razorpay_events=tuple(reversed(observed.razorpay_events)),
        recon_rows=tuple(reversed(observed.recon_rows)),
        settlement_rows=tuple(reversed(observed.settlement_rows)),
        bank_rows=tuple(reversed(observed.bank_rows)),
    )
    assert evaluate_observation(world, observed) == evaluate_observation(world, permuted)


def test_evaluation_is_invariant_to_exact_source_replay() -> None:
    world, observed = _clean_observation(421, settlements=20)
    replayed = replace(
        observed,
        razorpay_events=(*observed.razorpay_events, observed.razorpay_events[0]),
        recon_rows=(*observed.recon_rows, observed.recon_rows[0]),
        bank_rows=(*observed.bank_rows, observed.bank_rows[0]),
    )
    assert evaluate_observation(world, observed) == evaluate_observation(world, replayed)


def test_benchmark_artifact_recomputes_reports_from_truth_and_raw_decisions() -> None:
    from reflow.evaluation.artifact import verify_benchmark_payload
    from reflow.evaluation.profiles import EvaluationProfile
    from reflow.evaluation.runner import benchmark_payload

    payload = benchmark_payload(
        world_seed=431,
        observation_seed=432,
        settlement_count=20,
        profile=EvaluationProfile.RECONCILIATION_ADVERSARIAL,
    )
    recomputed = verify_benchmark_payload(payload)
    assert len(recomputed) == 4


def test_benchmark_artifact_verifier_rejects_tampered_report() -> None:
    from copy import deepcopy

    from reflow.evaluation.artifact import ArtifactVerificationError, verify_benchmark_payload
    from reflow.evaluation.profiles import EvaluationProfile
    from reflow.evaluation.runner import benchmark_payload

    payload = benchmark_payload(
        world_seed=441,
        observation_seed=442,
        settlement_count=20,
        profile=EvaluationProfile.CLEAN,
    )
    tampered = deepcopy(payload)
    tampered["reports"][0]["false_auto_reconciled"] += 1
    with pytest.raises(ArtifactVerificationError, match="recomputed score"):
        verify_benchmark_payload(tampered)


def test_benchmark_artifact_verifier_rejects_tampered_raw_decision() -> None:
    from copy import deepcopy

    from reflow.evaluation.artifact import ArtifactVerificationError, verify_benchmark_payload
    from reflow.evaluation.profiles import EvaluationProfile
    from reflow.evaluation.runner import benchmark_payload

    payload = benchmark_payload(
        world_seed=451,
        observation_seed=452,
        settlement_count=20,
        profile=EvaluationProfile.CLEAN,
    )
    tampered = deepcopy(payload)
    run = next(item for item in tampered["runs"] if item["system_name"] == "ReFlow_Core")
    decision = next(item for item in run["decisions"] if item["bank_entry_ids"])
    decision["bank_entry_ids"] = []
    with pytest.raises(ArtifactVerificationError, match="recomputed score"):
        verify_benchmark_payload(tampered)
