from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from reflow.simulator import WorldConfig, generate_world, observe_world

from .candidates import CandidateRun
from .harness import EvaluationSourceRejected, evaluate_observation
from .profiles import EvaluationProfile, corruption_plan
from .scoring import EvaluationReport, EvaluationTruth

EVALUATION_SCHEMA_VERSION = "gate11-evaluation-v1"


def _decision_payload(run: CandidateRun) -> dict[str, Any]:
    return {
        "system_name": run.system_name,
        "decisions": [
            {
                "settlement_id": str(item.settlement_id),
                "status": item.status.value,
                "settlement_amount_paise": item.settlement_amount.amount_paise,
                "composition_amount_paise": item.composition_amount.amount_paise,
                "bank_amount_paise": item.bank_amount.amount_paise,
                "currency": item.settlement_amount.currency.value,
                "composition_component_ids": [
                    str(value) for value in item.composition_component_ids
                ],
                "bank_entry_ids": [str(value) for value in item.bank_entry_ids],
                "reason_codes": list(item.reason_codes),
            }
            for item in run.decisions
        ],
    }


def _truth_payload(truth: EvaluationTruth) -> dict[str, Any]:
    return {
        "settlements": [
            {
                "settlement_id": str(item.settlement_id),
                "settlement_amount_paise": item.settlement_amount.amount_paise,
                "currency": item.settlement_amount.currency.value,
                "composition_component_ids": [
                    str(value) for value in item.composition_component_ids
                ],
                "bank_entry_ids": [str(value) for value in item.bank_entry_ids],
                "bank_expectation": item.bank_expectation.value,
            }
            for item in truth.settlements
        ]
    }


def _report_payload(report: EvaluationReport) -> dict[str, Any]:
    return {
        "system_name": report.system_name,
        "settlement_count": report.settlement_count,
        "auto_reconciled": report.auto_reconciled,
        "true_auto_reconciled": report.true_auto_reconciled,
        "false_auto_reconciled": report.false_auto_reconciled,
        "unresolved": report.unresolved,
        "missing_decisions": report.missing_decisions,
        "truth_reconciled": report.truth_reconciled,
        "reconciliation_recall": {
            "numerator": report.reconciliation_recall.numerator,
            "denominator": report.reconciliation_recall.denominator,
        },
        "silent_false_auto_match_rate": {
            "numerator": report.silent_false_auto_match_rate.numerator,
            "denominator": report.silent_false_auto_match_rate.denominator,
        },
        "settlement_amount_correct": {
            "numerator": report.settlement_amount_correct.numerator,
            "denominator": report.settlement_amount_correct.denominator,
        },
        "composition_amount_correct": {
            "numerator": report.composition_amount_correct.numerator,
            "denominator": report.composition_amount_correct.denominator,
        },
        "composition_edges": {
            "tp": report.composition_edges.true_positive,
            "fp": report.composition_edges.false_positive,
            "fn": report.composition_edges.false_negative,
        },
        "bank_edges": {
            "tp": report.bank_edges.true_positive,
            "fp": report.bank_edges.false_positive,
            "fn": report.bank_edges.false_negative,
        },
        "absolute_reported_residual_paise": report.absolute_reported_residual_paise,
    }


def benchmark_payload(
    *,
    world_seed: int,
    observation_seed: int,
    settlement_count: int,
    profile: EvaluationProfile,
) -> dict[str, Any]:
    world = generate_world(world_seed, WorldConfig(settlement_count=settlement_count))
    bundle = observe_world(
        world,
        seed=observation_seed,
        plan=corruption_plan(profile),
    )
    metadata: dict[str, Any] = {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "world_seed": world_seed,
        "observation_seed": observation_seed,
        "settlement_count": settlement_count,
        "profile": profile.value,
        "corruptions": [
            {
                "kind": item.kind,
                "source": item.source,
                "target_id": item.target_id,
                "detail": item.detail,
            }
            for item in bundle.manifest
        ],
    }
    try:
        result = evaluate_observation(world, bundle.observed)
    except EvaluationSourceRejected as exc:
        return {
            **metadata,
            "status": "source_rejected",
            "source_rejection": {
                "error_type": exc.rejection.error_type,
                "message": exc.rejection.message,
                "retained_raw_envelopes": exc.rejection.retained_raw_envelopes,
            },
            "truth": None,
            "runs": [],
            "reports": [],
        }
    return {
        **metadata,
        "status": "evaluated",
        "truth": _truth_payload(result.truth),
        "runs": [_decision_payload(run) for run in result.runs],
        "reports": [_report_payload(report) for report in result.reports],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the deterministic ReFlow Gate 11 benchmark")
    parser.add_argument("--world-seed", type=int, default=401)
    parser.add_argument("--observation-seed", type=int, default=402)
    parser.add_argument("--settlements", type=int, default=50)
    parser.add_argument(
        "--profile",
        choices=[profile.value for profile in EvaluationProfile],
        default=EvaluationProfile.RECONCILIATION_ADVERSARIAL.value,
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = benchmark_payload(
        world_seed=args.world_seed,
        observation_seed=args.observation_seed,
        settlement_count=args.settlements,
        profile=EvaluationProfile(args.profile),
    )
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered)


if __name__ == "__main__":
    main()
