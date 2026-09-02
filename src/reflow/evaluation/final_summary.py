from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .failure_campaign import verify_failure_campaign_payload
from .final_campaign import verify_final_campaign_payload

FINAL_SUMMARY_SCHEMA_VERSION = "gate19-final-summary-v1"


class FinalSummaryError(ValueError):
    pass


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _digest(payload: Mapping[str, object]) -> str:
    material = dict(payload)
    material.pop("artifact_sha256", None)
    return hashlib.sha256(_canonical_bytes(material)).hexdigest()


def _dict(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FinalSummaryError(f"{label} must be an object")
    return value


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FinalSummaryError(f"{label} must be an integer")
    return value


def _truth_reconciled(heldout: Mapping[str, object]) -> int:
    total = 0
    cases = heldout.get("cases")
    if not isinstance(cases, list):
        raise FinalSummaryError("held-out cases are unavailable")
    for case in cases:
        spec = _dict(_dict(case, "held-out case").get("manifest_case"), "manifest case")
        if spec.get("role") != "primary_benchmark":
            continue
        benchmark = _dict(_dict(case, "held-out case").get("benchmark"), "benchmark")
        reports = benchmark.get("reports")
        if not isinstance(reports, list):
            raise FinalSummaryError("benchmark reports are unavailable")
        report = next(
            (
                item
                for item in reports
                if isinstance(item, dict) and item.get("system_name") == "ReFlow_Core"
            ),
            None,
        )
        if report is None:
            raise FinalSummaryError("ReFlow report is missing from a primary case")
        total += _integer(report.get("truth_reconciled"), "truth reconciled count")
    return total


def build_final_summary(
    *,
    heldout_path: Path,
    manifest_path: Path,
    failure_path: Path,
    repo_root: Path,
) -> dict[str, Any]:
    heldout = _dict(json.loads(heldout_path.read_text()), "held-out artifact")
    failure = _dict(json.loads(failure_path.read_text()), "failure campaign")
    verify_final_campaign_payload(heldout, manifest_path=manifest_path, repo_root=repo_root)
    verify_failure_campaign_payload(failure)

    primary = _dict(heldout.get("primary"), "primary aggregate")
    systems = _dict(primary.get("systems"), "primary systems")
    reflow = _dict(systems.get("ReFlow_Core"), "ReFlow aggregate")
    fuzzy = _dict(systems.get("B2_fuzzy_threshold"), "fuzzy aggregate")
    safety = _dict(heldout.get("safety"), "safety aggregate")
    runtime = _dict(heldout.get("runtime"), "held-out runtime")
    status_counts = _dict(reflow.get("decision_status_counts"), "ReFlow status counts")

    requested = _integer(reflow.get("requested_settlements"), "requested settlements")
    auto = _integer(reflow.get("auto_reconciled"), "auto reconciled")
    true_auto = _integer(reflow.get("true_auto_reconciled"), "true auto reconciled")
    false_auto = _integer(reflow.get("false_auto_reconciled"), "false auto reconciled")
    unresolved = _integer(reflow.get("unresolved_requested"), "unresolved requested")
    truth_reconciled = _truth_reconciled(heldout)
    if auto + unresolved != requested or true_auto + false_auto != auto:
        raise FinalSummaryError("ReFlow aggregate partition is inconsistent")

    payload: dict[str, Any] = {
        "schema_version": FINAL_SUMMARY_SCHEMA_VERSION,
        "source_heldout_artifact_sha256": heldout.get("artifact_sha256"),
        "source_failure_artifact_sha256": failure.get("artifact_sha256"),
        "source_manifest_sha256": heldout.get("manifest_sha256"),
        "config": {
            "case_count": _integer(primary.get("case_count"), "primary case count"),
            "settlement_count": requested,
            "observed_record_count": _integer(
                primary.get("observed_record_count"), "observed record count"
            ),
            "truth_reconciled_settlements": truth_reconciled,
        },
        "hardware": dict(runtime),
        "metrics": {
            "auto_reconciled": auto,
            "true_auto_reconciled": true_auto,
            "false_auto_reconciled": false_auto,
            "non_green_decisions": unresolved,
            "safe_match_rate": None if requested == 0 else round(true_auto / requested, 6),
            "auto_match_precision": None if auto == 0 else round(true_auto / auto, 6),
            "truth_reconciled_recall": (
                None if truth_reconciled == 0 else round(true_auto / truth_reconciled, 6)
            ),
            "silent_false_auto_match_rate": (
                None if auto == 0 else round(false_auto / auto, 6)
            ),
            "fuzzy_false_auto_reconciled": _integer(
                fuzzy.get("false_auto_reconciled"), "fuzzy false auto reconciled"
            ),
            "source_schema_case_count": _integer(safety.get("case_count"), "safety case count"),
            "source_schema_fail_closed_cases": _integer(
                safety.get("source_rejected_cases"), "source rejected cases"
            ),
            "source_schema_candidate_decisions": _integer(
                safety.get("candidate_decisions_emitted"), "safety candidate decisions"
            ),
            "failure_campaign_check_count": _integer(
                failure.get("check_count"), "failure campaign check count"
            ),
            "failure_campaign_passed": _integer(
                failure.get("passed_count"), "failure campaign passed count"
            ),
            "failure_campaign_failed": _integer(
                failure.get("failed_count"), "failure campaign failed count"
            ),
        },
        "status_counts": dict(status_counts),
    }
    payload["artifact_sha256"] = _digest(payload)
    verify_final_summary_payload(payload)
    return payload


def verify_final_summary_payload(payload: object) -> None:
    value = _dict(payload, "final summary")
    if value.get("schema_version") != FINAL_SUMMARY_SCHEMA_VERSION:
        raise FinalSummaryError("final summary schema version mismatch")
    digest = value.get("artifact_sha256")
    if not isinstance(digest, str) or digest != _digest(value):
        raise FinalSummaryError("final summary artifact digest mismatch")
    for key in (
        "source_heldout_artifact_sha256",
        "source_failure_artifact_sha256",
        "source_manifest_sha256",
    ):
        item = value.get(key)
        if not isinstance(item, str) or len(item) != 64:
            raise FinalSummaryError(f"final summary {key} is invalid")
    config = _dict(value.get("config"), "final summary config")
    metrics = _dict(value.get("metrics"), "final summary metrics")
    status_counts = _dict(value.get("status_counts"), "final summary status counts")
    requested = _integer(config.get("settlement_count"), "summary settlement count")
    auto = _integer(metrics.get("auto_reconciled"), "summary auto reconciled")
    true_auto = _integer(metrics.get("true_auto_reconciled"), "summary true auto")
    false_auto = _integer(metrics.get("false_auto_reconciled"), "summary false auto")
    non_green = _integer(metrics.get("non_green_decisions"), "summary non-green decisions")
    if auto + non_green != requested or true_auto + false_auto != auto:
        raise FinalSummaryError("final summary reconciliation partition is invalid")
    failed_checks = _integer(metrics.get("failure_campaign_failed"), "summary failed checks")
    passed_checks = _integer(metrics.get("failure_campaign_passed"), "summary passed checks")
    check_count = _integer(metrics.get("failure_campaign_check_count"), "summary check count")
    if failed_checks != 0 or passed_checks + failed_checks != check_count:
        raise FinalSummaryError("final summary failure-campaign partition is invalid")
    schema_cases = _integer(metrics.get("source_schema_case_count"), "summary schema case count")
    schema_failed_closed = _integer(
        metrics.get("source_schema_fail_closed_cases"), "summary schema fail-closed count"
    )
    if schema_failed_closed > schema_cases:
        raise FinalSummaryError("final summary schema fail-closed count exceeds case count")
    if sum(_integer(item, "summary status count") for item in status_counts.values()) != requested:
        raise FinalSummaryError("final summary status counts do not cover requested settlements")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build or verify the compact Gate 19 summary")
    parser.add_argument("--heldout", type=Path, default=Path("data/eval/gate19/final-heldout.json"))
    parser.add_argument(
        "--manifest", type=Path, default=Path("data/eval/gate19/heldout_manifest.json")
    )
    parser.add_argument(
        "--failure", type=Path, default=Path("data/eval/gate19/failure-campaign.json")
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", type=Path)
    args = parser.parse_args()
    expected = build_final_summary(
        heldout_path=args.heldout,
        manifest_path=args.manifest,
        failure_path=args.failure,
        repo_root=Path.cwd(),
    )
    if args.check is not None:
        actual = _dict(json.loads(args.check.read_text()), "checked final summary")
        verify_final_summary_payload(actual)
        if actual != expected:
            raise FinalSummaryError("checked final summary does not match frozen source artifacts")
        print(json.dumps({"status": "verified", "artifact": str(args.check)}, sort_keys=True))
        return
    rendered = json.dumps(expected, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)


if __name__ == "__main__":
    main()
