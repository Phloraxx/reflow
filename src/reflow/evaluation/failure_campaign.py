from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path
from time import perf_counter
from typing import Any

FAILURE_CAMPAIGN_SCHEMA_VERSION = "gate19-failure-campaign-v1"

CHECKS = (
    (
        "source-late-vs-complete",
        "tests/core/test_reconciliation_control_plane.py::test_missing_bank_delivery_differs_from_complete_delivery_missing_credit",
    ),
    (
        "case-auto-close-history",
        "tests/core/test_exception_cases.py::test_later_green_proof_auto_closes_without_rewriting_history",
    ),
    (
        "case-economic-supersession",
        "tests/core/test_exception_cases.py::test_changed_settlement_amount_creates_new_case_and_supersedes_old",
    ),
    (
        "agent-provider-outage",
        "tests/core/test_investigation.py::test_provider_outage_abstains_and_cannot_mutate_case_history",
    ),
    (
        "agent-prompt-injection",
        "tests/core/test_investigation.py::test_prompt_like_source_text_cannot_authorize_hallucinated_number_or_evidence",
    ),
    (
        "agent-hallucinated-citation",
        "tests/core/test_investigation.py::test_hallucinated_citation_is_rejected",
    ),
    (
        "agent-out-of-proof-tool",
        "tests/core/test_openai_investigation_provider.py::test_openai_out_of_proof_source_request_is_traced_safety_rejection",
    ),
    (
        "postgres-journal-conflict",
        "tests/persistence/test_postgres_persistence.py::test_postgres_journal_matches_append_duplicate_and_conflict_semantics",
    ),
    (
        "postgres-restart-idempotency",
        "tests/persistence/test_postgres_persistence.py::test_artifact_write_is_immutable_idempotent_and_restart_safe",
    ),
    (
        "postgres-pointer-cas",
        "tests/persistence/test_postgres_persistence.py::test_current_pointer_compare_and_swap_is_idempotent_and_stale_safe",
    ),
    (
        "ui-spa-api-boundary",
        "tests/control_tower/test_control_tower.py::test_fastapi_can_serve_built_spa_without_changing_api_authority",
    ),
    (
        "ui-source-payload-minimization",
        "tests/control_tower/test_control_tower.py::test_source_lab_contains_metadata_but_no_raw_payload",
    ),
)


class FailureCampaignError(ValueError):
    pass


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def run_failure_campaign(*, repo_root: Path, python: Path) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for check_id, node_id in CHECKS:
        started = perf_counter()
        completed = subprocess.run(
            [str(python), "-m", "pytest", "-q", "-rA", node_id],
            cwd=repo_root,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            check=False,
        )
        elapsed = round(perf_counter() - started, 6)
        output = (completed.stdout + completed.stderr).strip()
        passed = completed.returncode == 0 and f"PASSED {node_id}" in output
        results.append(
            {
                "check_id": check_id,
                "node_id": node_id,
                "status": "passed" if passed else "failed",
                "returncode": completed.returncode,
                "elapsed_seconds": elapsed,
                "output": output[-4000:],
            }
        )
    payload: dict[str, Any] = {
        "schema_version": FAILURE_CAMPAIGN_SCHEMA_VERSION,
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
        },
        "check_count": len(results),
        "passed_count": sum(item["status"] == "passed" for item in results),
        "failed_count": sum(item["status"] != "passed" for item in results),
        "checks": results,
    }
    payload["artifact_sha256"] = _digest(payload)
    verify_failure_campaign_payload(payload)
    return payload


def verify_failure_campaign_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != FAILURE_CAMPAIGN_SCHEMA_VERSION:
        raise FailureCampaignError("failure campaign schema mismatch")
    digest = payload.get("artifact_sha256")
    if not isinstance(digest, str):
        raise FailureCampaignError("failure campaign digest missing")
    unsigned = dict(payload)
    unsigned.pop("artifact_sha256", None)
    if _digest(unsigned) != digest:
        raise FailureCampaignError("failure campaign digest mismatch")
    checks = payload.get("checks")
    if not isinstance(checks, list) or len(checks) != len(CHECKS):
        raise FailureCampaignError("failure campaign check count mismatch")
    expected = list(CHECKS)
    for index, item in enumerate(checks):
        if not isinstance(item, dict):
            raise FailureCampaignError("failure campaign check must be an object")
        if (item.get("check_id"), item.get("node_id")) != expected[index]:
            raise FailureCampaignError("failure campaign selector/order mismatch")
        if item.get("status") != "passed" or item.get("returncode") != 0:
            raise FailureCampaignError(
                f"failure campaign check did not pass: {item.get('check_id')}"
            )
        if f"PASSED {item.get('node_id')}" not in str(item.get("output", "")):
            raise FailureCampaignError("failure campaign check lacks exact pass evidence")
    if payload.get("passed_count") != len(CHECKS) or payload.get("failed_count") != 0:
        raise FailureCampaignError("failure campaign aggregate counts mismatch")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run or verify Gate 19 regression campaign")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.verify is not None:
        payload = json.loads(args.verify.read_text())
        verify_failure_campaign_payload(payload)
        print(json.dumps({"status": "verified", "artifact": str(args.verify)}, sort_keys=True))
        return
    repo_root = Path.cwd()
    python = repo_root / ".venv" / "bin" / "python"
    if not python.is_file():
        raise FailureCampaignError("Gate 19 failure campaign requires .venv/bin/python")
    payload = run_failure_campaign(repo_root=repo_root, python=python)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)


if __name__ == "__main__":
    main()
