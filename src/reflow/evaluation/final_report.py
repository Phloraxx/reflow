# ruff: noqa: E501
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .benchmark_artifacts import load_verified_benchmark
from .failure_campaign import verify_failure_campaign_payload
from .final_campaign import verify_final_campaign_payload


def _pct(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "n/a"
    return f"{100 * numerator / denominator:.2f}%"


def _truth_reconciled(payload: dict[str, Any]) -> dict[str, int]:
    result: Counter[str] = Counter()
    for case in payload["cases"]:
        if case["manifest_case"]["role"] != "primary_benchmark":
            continue
        if case["benchmark"]["status"] != "evaluated":
            continue
        for report in case["benchmark"]["reports"]:
            result[report["system_name"]] += report["truth_reconciled"]
    return dict(result)


def _reflow_profile_rows(payload: dict[str, Any]) -> list[tuple[str, dict[str, int]]]:
    rows: list[tuple[str, dict[str, int]]] = []
    for profile in ("clean", "reconciliation_adversarial"):
        total: Counter[str] = Counter()
        for case in payload["cases"]:
            spec = case["manifest_case"]
            if spec["role"] != "primary_benchmark" or spec["profile"] != profile:
                continue
            report = next(
                item
                for item in case["benchmark"]["reports"]
                if item["system_name"] == "ReFlow_Core"
            )
            for key in (
                "settlement_count",
                "auto_reconciled",
                "true_auto_reconciled",
                "false_auto_reconciled",
                "unresolved",
                "truth_reconciled",
            ):
                total[key] += report[key]
        rows.append((profile, dict(total)))
    return rows


def render_evaluation_markdown(
    *,
    final_payload: dict[str, Any],
    failure_payload: dict[str, Any],
    scale_payload: dict[str, Any],
    persistence_payload: dict[str, Any],
) -> str:
    primary = final_payload["primary"]
    systems = primary["systems"]
    truth = _truth_reconciled(final_payload)
    exceptions = primary["reflow_exceptions"]
    status_counts = Counter(item["status"] for item in exceptions)
    reason_counts = Counter(code for item in exceptions for code in item["reason_codes"])

    lines = [
        "# ReFlow Final Evaluation",
        "",
        "> Generated from checked-in, self-verifying artifacts. Do not hand-edit metric values.",
        "",
        "## Evaluation contract",
        "",
        "The Gate 19 held-out seeds were committed before first execution. The existing Gate 11 scorer and candidate systems were frozen by SHA-256 in `data/eval/gate19/heldout_manifest.json`. The first v1 held-out result is preserved unchanged in `data/eval/gate19/final-heldout.json`.",
        "",
        f"- Primary corpus: **{primary['case_count']} cases / {primary['requested_settlements']} settlements / {primary['observed_record_count']:,} observed records**.",
        "- Mix: 4 clean cases and 8 reconciliation-adversarial cases; every case has 64 settlements.",
        f"- Safety corpus: **{final_payload['safety']['case_count']} source-schema adversarial cases** reported separately from headline reconciliation metrics.",
        f"- Held-out artifact digest: `{final_payload['artifact_sha256']}`.",
        f"- Failure-campaign artifact digest: `{failure_payload['artifact_sha256']}`.",
        "",
        "## Primary held-out result",
        "",
        "`Safe match rate` uses all requested settlements as the denominator. `Auto-match precision` asks whether an automatic green decision was actually correct. `Truth-reconciled recall` measures true automatic matches against settlements that are reconciled in hidden truth; corrupted/missing observations can legitimately lower this because ReFlow fails closed rather than guessing.",
        "",
        "| System | Auto matched | True auto | False auto | Safe match rate | Auto-match precision | Truth-reconciled recall | Silent false-match rate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in ("B0_naive_1to1", "B1_grouped_exact", "B2_fuzzy_threshold", "ReFlow_Core"):
        value = systems[name]
        truth_count = truth[name]
        lines.append(
            f"| {name} | {value['auto_reconciled']}/{value['requested_settlements']} | {value['true_auto_reconciled']} | {value['false_auto_reconciled']} | {_pct(value['true_auto_reconciled'], value['requested_settlements'])} | {_pct(value['true_auto_reconciled'], value['auto_reconciled'])} | {_pct(value['true_auto_reconciled'], truth_count)} | {_pct(value['false_auto_reconciled'], value['auto_reconciled'])} |"
        )
    reflow = systems["ReFlow_Core"]
    fuzzy = systems["B2_fuzzy_threshold"]
    grouped = systems["B1_grouped_exact"]
    lines += [
        "",
        "### What the headline means",
        "",
        f"ReFlow automatically reconciled **{reflow['auto_reconciled']}/{reflow['requested_settlements']} ({_pct(reflow['auto_reconciled'], reflow['requested_settlements'])})** settlements. All **{reflow['true_auto_reconciled']}/{reflow['auto_reconciled']}** automatic matches were correct, so the frozen corpus produced **zero silent false auto-matches**.",
        "",
        f"The fuzzy baseline auto-matched {fuzzy['auto_reconciled']} settlements, but {fuzzy['false_auto_reconciled']} were wrong ({_pct(fuzzy['false_auto_reconciled'], fuzzy['auto_reconciled'])} silent false-match rate). ReFlow deliberately leaves those cases unresolved instead of buying coverage with incorrect financial truth.",
        "",
        f"The strong grouped-exact baseline has the same true auto-match count ({grouped['true_auto_reconciled']}) and zero false auto-matches. ReFlow does **not** claim a recall win over that baseline. Its added value is exact provenance validation, typed residual/contradiction states, immutable proof versions, run-level controls, persistent cases, bounded investigation and the operator control tower.",
        "",
        "### Edge evidence",
        "",
        "| System | Composition edge P / R | Bank edge P / R |",
        "|---|---:|---:|",
    ]
    for name in ("B0_naive_1to1", "B1_grouped_exact", "B2_fuzzy_threshold", "ReFlow_Core"):
        value = systems[name]
        c = value["composition_edges"]
        b = value["bank_edges"]
        lines.append(
            f"| {name} | {_pct(c['tp'], c['tp'] + c['fp'])} / {_pct(c['tp'], c['tp'] + c['fn'])} | {_pct(b['tp'], b['tp'] + b['fp'])} / {_pct(b['tp'], b['tp'] + b['fn'])} |"
        )
    lines += ["", "### ReFlow by profile", "", "| Profile | Settlements | Truth reconciled | Auto matched | Precision | Truth-reconciled recall | Unresolved |", "|---|---:|---:|---:|---:|---:|---:|"]
    for profile, row in _reflow_profile_rows(final_payload):
        lines.append(
            f"| {profile} | {row['settlement_count']} | {row['truth_reconciled']} | {row['auto_reconciled']} | {_pct(row['true_auto_reconciled'], row['auto_reconciled'])} | {_pct(row['true_auto_reconciled'], row['truth_reconciled'])} | {row['unresolved']} |"
        )

    lines += [
        "",
        "## Honest ReFlow exception list",
        "",
        f"The primary corpus produced **{len(exceptions)} non-green ReFlow decisions**. Status counts: " + ", ".join(f"`{k}`={v}" for k, v in sorted(status_counts.items())) + ".",
        "",
        "Reason-code occurrences can overlap because one exception may have more than one deterministic reason:",
        "",
    ]
    for reason, count in reason_counts.most_common():
        lines.append(f"- `{reason}` — {count}")
    lines += [
        "",
        "The complete machine-readable exception list—including settlement ID, status, reason codes, amounts, recon evidence IDs and bank evidence IDs—is stored under `primary.reflow_exceptions` in `data/eval/gate19/final-heldout.json`. No exception was manually removed.",
        "",
        "## Source-schema safety campaign",
        "",
        f"All **{final_payload['safety']['source_rejected_cases']}/{final_payload['safety']['case_count']}** frozen source-schema adversarial cases failed closed before candidate decisions, with **{final_payload['safety']['candidate_decisions_emitted']} candidate decisions emitted**. Each rejection retained thousands of raw envelopes before canonical interpretation failed.",
        "",
        "This safety corpus contains malformed-date, schema-rename, rupee/paise and sign traps. It is intentionally reported separately from the headline match-rate denominator.",
        "",
        "## Regression failure campaign",
        "",
        f"The final regression campaign passed **{failure_payload['passed_count']}/{failure_payload['check_count']}** representative failure checks with zero failures. It covers source completeness, case continuity/supersession, model outage, prompt injection, hallucinated evidence, tool-scope denial, PostgreSQL conflict/restart/CAS semantics, SPA routing and source-data minimization.",
        "",
        "## Throughput / scale evidence",
        "",
        f"The frozen four-system held-out campaign processed {primary['requested_settlements']} settlements in {primary['wall_seconds']:.3f}s of recorded primary-case wall time ({primary['campaign_settlements_per_second']:.2f} settlements/s). This includes world observation, four candidate systems and scoring, so it is **not** presented as ReFlow proof-core throughput.",
        "",
        f"For proof-core scale, the independently verified Gate 17 10k clean artifact processed **{scale_payload['metrics']['proof_count']:,} settlements / {scale_payload['metrics']['raw_rows']:,} raw rows** with a proof-pipeline rate of **{scale_payload['metrics']['settlements_per_second_proof_pipeline']:.2f} settlements/s**, total runtime **{scale_payload['metrics']['seconds_total']:.2f}s**, and peak process RSS about **{scale_payload['metrics']['max_rss_kib'] / 1024 / 1024:.2f} GiB** on the disclosed 4-vCPU aarch64 Oracle VM.",
        "",
        f"The separate fine-grained PostgreSQL durability benchmark measured about **{persistence_payload['metrics']['source_cold_ops_per_second']:.1f} cold source writes/s** and **{persistence_payload['metrics']['artifact_cold_ops_per_second']:.1f} cold immutable-artifact writes/s**. It is a durability reference, not a bulk-ingestion throughput claim.",
        "",
        "## AI and real-provider evidence",
        "",
        "No OpenAI/AI provider key was configured on the final Oracle evaluation host, so ReFlow makes **no live-model Gate 16 quality/cost/latency claim**. Gate 16 safety and protocol behavior is covered by deterministic/fake-transport tests and the final failure campaign.",
        "",
        "No Razorpay API key was configured on the final Oracle evaluation host, and the earlier authenticated connected-account check exposed no settlement/recon corpus. ReFlow therefore makes **no REAL_TEST_MODE settlement accuracy claim**. Provider-document fixtures remain explicitly labelled as documentation fixtures.",
        "",
        "## Reproduce / verify",
        "",
        "```bash",
        "python -m reflow.evaluation.final_campaign --manifest data/eval/gate19/heldout_manifest.json --verify data/eval/gate19/final-heldout.json",
        "python -m reflow.evaluation.failure_campaign --verify data/eval/gate19/failure-campaign.json",
        "python -m reflow.evaluation.scale_runner --verify data/eval/gate17/scale-10000-clean.json",
        "python -m reflow.evaluation.persistence_runner --verify data/eval/gate17/postgres-1000-cold-warm.json",
        "python -m reflow.evaluation.final_report --check EVALUATION.md",
        "```",
        "",
        "Re-running the held-out command is possible, but the checked-in v1 result is the **first run** and remains the submission result. A product/scorer change after seeing v1 would require a newly frozen seed manifest rather than overwriting v1.",
        "",
        "## Non-claims",
        "",
        "- This is synthetic/adversarial evaluation, as requested by Track 04; it is not merchant production data.",
        "- 66.67% is a conservative safe automatic match rate over all requested settlements, **not** an accuracy percentage.",
        "- The hidden-truth auto-match precision on v1 is 100% (512/512); truth-reconciled recall is 82.05% (512/624).",
        "- ReFlow does not claim to outperform B1 grouped-exact on auto-match recall in this corpus.",
        "- No 100k/1M scale, HA, production SLO, live-model accuracy, or real Razorpay settlement-accuracy claim is made.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate/check ReFlow final evaluation markdown")
    parser.add_argument("--output", type=Path, default=Path("EVALUATION.md"))
    parser.add_argument("--check", type=Path)
    parser.add_argument("--heldout", type=Path, default=Path("data/eval/gate19/final-heldout.json"))
    parser.add_argument("--manifest", type=Path, default=Path("data/eval/gate19/heldout_manifest.json"))
    parser.add_argument("--failure", type=Path, default=Path("data/eval/gate19/failure-campaign.json"))
    args = parser.parse_args()
    root = Path.cwd()
    final_payload = json.loads(args.heldout.read_text())
    verify_final_campaign_payload(final_payload, manifest_path=args.manifest, repo_root=root)
    failure_payload = json.loads(args.failure.read_text())
    verify_failure_campaign_payload(failure_payload)
    scale = load_verified_benchmark(Path("data/eval/gate17/scale-10000-clean.json"))
    persistence = load_verified_benchmark(Path("data/eval/gate17/postgres-1000-cold-warm.json"))
    rendered = render_evaluation_markdown(
        final_payload=final_payload,
        failure_payload=failure_payload,
        scale_payload=scale,
        persistence_payload=persistence,
    )
    if args.check is not None:
        if args.check.read_text() != rendered:
            raise SystemExit(f"generated evaluation report differs from {args.check}")
        print(json.dumps({"status": "verified", "report": str(args.check)}, sort_keys=True))
        return
    args.output.write_text(rendered)


if __name__ == "__main__":
    main()
