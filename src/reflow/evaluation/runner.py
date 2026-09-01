from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from reflow.simulator import WorldConfig, generate_world, observe_world

from .artifact import (
    EVALUATION_SCHEMA_VERSION,
    decision_payload,
    report_payload,
    truth_payload,
    verify_benchmark_payload,
)
from .harness import EvaluationSourceRejected, evaluate_observation
from .profiles import EvaluationProfile, corruption_plan


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
    observed_record_count = sum(
        len(rows)
        for rows in (
            bundle.observed.merchant_rows,
            bundle.observed.razorpay_events,
            bundle.observed.recon_rows,
            bundle.observed.settlement_rows,
            bundle.observed.bank_rows,
        )
    )
    metadata: dict[str, Any] = {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "observed_record_count": observed_record_count,
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
        payload = {
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
        verify_benchmark_payload(payload)
        return payload

    payload = {
        **metadata,
        "status": "evaluated",
        "truth": truth_payload(result.truth),
        "runs": [decision_payload(run) for run in result.runs],
        "reports": [report_payload(report) for report in result.reports],
    }
    verify_benchmark_payload(payload)
    return payload


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
