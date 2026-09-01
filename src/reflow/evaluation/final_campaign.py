from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
from collections.abc import Mapping
from pathlib import Path
from time import perf_counter
from typing import Any

from .artifact import verify_benchmark_payload
from .profiles import EvaluationProfile
from .runner import benchmark_payload

FINAL_CAMPAIGN_SCHEMA_VERSION = "gate19-final-campaign-v1"
HELDOUT_MANIFEST_SCHEMA_VERSION = "gate19-heldout-manifest-v1"
FROZEN_CORE_PATHS = (
    "src/reflow/evaluation/candidates.py",
    "src/reflow/evaluation/scoring.py",
)


class FinalCampaignError(ValueError):
    pass


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise FinalCampaignError(f"{label} must be an integer")
    return value


def _ratio(numerator: int, denominator: int) -> dict[str, object]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": None if denominator == 0 else round(numerator / denominator, 6),
    }


def _manifest(path: Path, *, repo_root: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise FinalCampaignError("held-out manifest must be an object")
    if raw.get("schema_version") != HELDOUT_MANIFEST_SCHEMA_VERSION:
        raise FinalCampaignError("held-out manifest schema mismatch")
    frozen = raw.get("frozen_core_file_sha256")
    if not isinstance(frozen, dict):
        raise FinalCampaignError("held-out manifest is missing frozen core hashes")
    for relative in FROZEN_CORE_PATHS:
        expected = frozen.get(relative)
        if not isinstance(expected, str):
            raise FinalCampaignError(f"held-out manifest is missing hash for {relative}")
        actual = _file_sha256(repo_root / relative)
        if actual != expected:
            raise FinalCampaignError(
                f"frozen evaluation core changed after seed freeze: {relative}"
            )
    cases = raw.get("cases")
    if not isinstance(cases, list) or not cases:
        raise FinalCampaignError("held-out manifest requires cases")
    seen: set[str] = set()
    for item in cases:
        if not isinstance(item, dict):
            raise FinalCampaignError("held-out case must be an object")
        case_id = item.get("case_id")
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise FinalCampaignError("held-out case IDs must be unique non-empty strings")
        seen.add(case_id)
        if item.get("role") not in {"primary_benchmark", "safety_failure"}:
            raise FinalCampaignError(f"invalid held-out role for {case_id}")
        try:
            EvaluationProfile(str(item.get("profile")))
        except ValueError as exc:
            raise FinalCampaignError(f"unknown profile for {case_id}") from exc
        for key in ("settlement_count", "world_seed", "observation_seed"):
            value = item.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise FinalCampaignError(f"{case_id} has invalid {key}")
    return raw


def _systems(case_payloads: list[dict[str, Any]]) -> tuple[str, ...]:
    names: set[str] = set()
    for item in case_payloads:
        benchmark = item["benchmark"]
        if benchmark.get("status") != "evaluated":
            continue
        for report in benchmark.get("reports", []):
            if isinstance(report, dict) and isinstance(report.get("system_name"), str):
                names.add(report["system_name"])
    return tuple(sorted(names))


def _empty_aggregate(requested: int) -> dict[str, Any]:
    return {
        "requested_settlements": requested,
        "evaluated_settlements": 0,
        "source_rejected_cases": 0,
        "source_rejected_settlements": 0,
        "auto_reconciled": 0,
        "true_auto_reconciled": 0,
        "false_auto_reconciled": 0,
        "unresolved_requested": 0,
        "missing_decisions": 0,
        "settlement_amount_correct": {"numerator": 0, "denominator": 0},
        "composition_amount_correct": {"numerator": 0, "denominator": 0},
        "composition_edges": {"tp": 0, "fp": 0, "fn": 0},
        "bank_edges": {"tp": 0, "fp": 0, "fn": 0},
        "decision_status_counts": {
            "reconciled": 0,
            "unresolved": 0,
            "residual": 0,
            "incomplete": 0,
            "contradicted": 0,
        },
        "absolute_reported_residual_paise": 0,
    }


def _sum_report(target: dict[str, Any], report: Mapping[str, object]) -> None:
    for key in (
        "evaluated_settlements",
        "auto_reconciled",
        "true_auto_reconciled",
        "false_auto_reconciled",
        "missing_decisions",
        "absolute_reported_residual_paise",
    ):
        source_key = "settlement_count" if key == "evaluated_settlements" else key
        target[key] += _integer(report[source_key], source_key)
    target["unresolved_requested"] += _integer(report["unresolved"], "unresolved")
    for metric in ("settlement_amount_correct", "composition_amount_correct"):
        value = report[metric]
        assert isinstance(value, Mapping)
        target[metric]["numerator"] += _integer(value["numerator"], f"{metric} numerator")
        target[metric]["denominator"] += _integer(value["denominator"], f"{metric} denominator")
    for metric in ("composition_edges", "bank_edges"):
        value = report[metric]
        assert isinstance(value, Mapping)
        for key in ("tp", "fp", "fn"):
            target[metric][key] += _integer(value[key], f"{metric} {key}")
    counts = report["decision_status_counts"]
    assert isinstance(counts, Mapping)
    for key in target["decision_status_counts"]:
        target["decision_status_counts"][key] += _integer(counts[key], f"status {key}")


def _finalize_aggregate(value: dict[str, Any]) -> dict[str, Any]:
    auto = value["auto_reconciled"]
    true_auto = value["true_auto_reconciled"]
    false_auto = value["false_auto_reconciled"]
    requested = value["requested_settlements"]
    comp = value["composition_edges"]
    bank = value["bank_edges"]
    return {
        **value,
        "safe_match_rate": _ratio(true_auto, requested),
        "auto_match_precision": _ratio(true_auto, auto),
        "silent_false_auto_match_rate": _ratio(false_auto, auto),
        "composition_edge_precision": _ratio(comp["tp"], comp["tp"] + comp["fp"]),
        "composition_edge_recall": _ratio(comp["tp"], comp["tp"] + comp["fn"]),
        "bank_edge_precision": _ratio(bank["tp"], bank["tp"] + bank["fp"]),
        "bank_edge_recall": _ratio(bank["tp"], bank["tp"] + bank["fn"]),
    }


def _primary_aggregates(
    cases: list[dict[str, Any]], manifest: Mapping[str, object]
) -> dict[str, dict[str, Any]]:
    requested = sum(
        int(case["manifest_case"]["settlement_count"])
        for case in cases
        if case["manifest_case"]["role"] == "primary_benchmark"
    )
    expected = _integer(manifest["primary_settlement_count"], "primary settlement count")
    if requested != expected:
        raise FinalCampaignError("primary manifest settlement count does not match cases")
    aggregates = {name: _empty_aggregate(requested) for name in _systems(cases)}
    if not aggregates:
        raise FinalCampaignError("primary campaign emitted no candidate systems")
    for case in cases:
        spec = case["manifest_case"]
        if spec["role"] != "primary_benchmark":
            continue
        benchmark = case["benchmark"]
        count = int(spec["settlement_count"])
        if benchmark["status"] == "source_rejected":
            for value in aggregates.values():
                value["source_rejected_cases"] += 1
                value["source_rejected_settlements"] += count
                value["unresolved_requested"] += count
            continue
        reports = {
            report["system_name"]: report
            for report in benchmark["reports"]
            if isinstance(report, dict)
        }
        if set(reports) != set(aggregates):
            raise FinalCampaignError("candidate system set changed across primary cases")
        for name, value in aggregates.items():
            _sum_report(value, reports[name])
    return {name: _finalize_aggregate(value) for name, value in aggregates.items()}


def _exceptions(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for case in cases:
        spec = case["manifest_case"]
        if spec["role"] != "primary_benchmark":
            continue
        benchmark = case["benchmark"]
        if benchmark["status"] != "evaluated":
            items.append(
                {
                    "case_id": spec["case_id"],
                    "settlement_id": None,
                    "status": "source_rejected",
                    "reason_codes": [benchmark["source_rejection"]["error_type"]],
                    "settlement_amount_paise": None,
                    "composition_amount_paise": None,
                    "bank_amount_paise": None,
                    "composition_evidence_ids": [],
                    "bank_evidence_ids": [],
                }
            )
            continue
        run = next(
            item for item in benchmark["runs"] if item["system_name"] == "ReFlow_Core"
        )
        for decision in run["decisions"]:
            if decision["status"] == "reconciled":
                continue
            items.append(
                {
                    "case_id": spec["case_id"],
                    "settlement_id": decision["settlement_id"],
                    "status": decision["status"],
                    "reason_codes": list(decision["reason_codes"]),
                    "settlement_amount_paise": decision["settlement_amount_paise"],
                    "composition_amount_paise": decision["composition_amount_paise"],
                    "bank_amount_paise": decision["bank_amount_paise"],
                    "composition_evidence_ids": [
                        row["recon_id"] for row in decision["composition_components"]
                    ],
                    "bank_evidence_ids": [
                        row["bank_entry_id"] for row in decision["bank_entries"]
                    ],
                }
            )
    return sorted(items, key=lambda item: (item["case_id"], str(item["settlement_id"])))


def _safety_summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    safety = [case for case in cases if case["manifest_case"]["role"] == "safety_failure"]
    rejected = sum(case["benchmark"]["status"] == "source_rejected" for case in safety)
    emitted = sum(
        sum(len(run.get("decisions", [])) for run in case["benchmark"].get("runs", []))
        for case in safety
    )
    return {
        "case_count": len(safety),
        "source_rejected_cases": rejected,
        "evaluated_cases": len(safety) - rejected,
        "candidate_decisions_emitted": emitted,
        "cases": [
            {
                "case_id": case["manifest_case"]["case_id"],
                "status": case["benchmark"]["status"],
                "corruptions": case["benchmark"]["corruptions"],
                "source_rejection": case["benchmark"].get("source_rejection"),
            }
            for case in safety
        ],
    }


def _build_payload(
    *, manifest: dict[str, Any], manifest_sha256: str, cases: list[dict[str, Any]]
) -> dict[str, Any]:
    primary = [case for case in cases if case["manifest_case"]["role"] == "primary_benchmark"]
    elapsed = round(sum(float(case["elapsed_seconds"]) for case in primary), 6)
    requested = int(manifest["primary_settlement_count"])
    observed_records = sum(int(case["benchmark"]["observed_record_count"]) for case in primary)
    payload: dict[str, Any] = {
        "schema_version": FINAL_CAMPAIGN_SCHEMA_VERSION,
        "manifest_sha256": manifest_sha256,
        "frozen_from_main_sha": manifest["frozen_from_main_sha"],
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
        },
        "primary": {
            "case_count": len(primary),
            "requested_settlements": requested,
            "observed_record_count": observed_records,
            "wall_seconds": elapsed,
            "campaign_settlements_per_second": (
                None if elapsed <= 0 else round(requested / elapsed, 6)
            ),
            "systems": _primary_aggregates(cases, manifest),
            "reflow_exceptions": _exceptions(cases),
        },
        "safety": _safety_summary(cases),
        "cases": cases,
    }
    payload["artifact_sha256"] = _sha256(payload)
    return payload


def run_final_campaign(*, manifest_path: Path, repo_root: Path) -> dict[str, Any]:
    manifest = _manifest(manifest_path, repo_root=repo_root)
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    cases: list[dict[str, Any]] = []
    for spec in manifest["cases"]:
        start = perf_counter()
        benchmark = benchmark_payload(
            world_seed=int(spec["world_seed"]),
            observation_seed=int(spec["observation_seed"]),
            settlement_count=int(spec["settlement_count"]),
            profile=EvaluationProfile(str(spec["profile"])),
        )
        cases.append(
            {
                "manifest_case": dict(spec),
                "elapsed_seconds": round(perf_counter() - start, 6),
                "benchmark": benchmark,
            }
        )
    payload = _build_payload(
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        cases=cases,
    )
    verify_final_campaign_payload(payload, manifest_path=manifest_path, repo_root=repo_root)
    return payload


def verify_final_campaign_payload(
    payload: Mapping[str, object], *, manifest_path: Path, repo_root: Path
) -> None:
    if payload.get("schema_version") != FINAL_CAMPAIGN_SCHEMA_VERSION:
        raise FinalCampaignError("final campaign schema mismatch")
    expected_digest = payload.get("artifact_sha256")
    if not isinstance(expected_digest, str):
        raise FinalCampaignError("final campaign artifact digest missing")
    unsigned = dict(payload)
    unsigned.pop("artifact_sha256", None)
    if _sha256(unsigned) != expected_digest:
        raise FinalCampaignError("final campaign artifact digest mismatch")
    manifest = _manifest(manifest_path, repo_root=repo_root)
    if payload.get("manifest_sha256") != hashlib.sha256(manifest_path.read_bytes()).hexdigest():
        raise FinalCampaignError("final campaign manifest digest mismatch")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list):
        raise FinalCampaignError("final campaign cases must be an array")
    cases: list[dict[str, Any]] = []
    for item in raw_cases:
        if not isinstance(item, dict) or not isinstance(item.get("benchmark"), dict):
            raise FinalCampaignError("final campaign case is malformed")
        verify_benchmark_payload(item["benchmark"])
        cases.append(item)
    rebuilt = _build_payload(
        manifest=manifest,
        manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        cases=cases,
    )
    for key in ("primary", "safety"):
        if rebuilt[key] != payload.get(key):
            raise FinalCampaignError(f"final campaign {key} aggregate mismatch")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run or verify the frozen Gate 19 campaign")
    parser.add_argument(
        "--manifest", type=Path, default=Path("data/eval/gate19/heldout_manifest.json")
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    repo_root = Path.cwd()
    if args.verify is not None:
        payload = json.loads(args.verify.read_text())
        verify_final_campaign_payload(payload, manifest_path=args.manifest, repo_root=repo_root)
        print(json.dumps({"status": "verified", "artifact": str(args.verify)}, sort_keys=True))
        return
    payload = run_final_campaign(manifest_path=args.manifest, repo_root=repo_root)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)


if __name__ == "__main__":
    main()
