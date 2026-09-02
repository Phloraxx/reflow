from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from reflow.evaluation.benchmark_artifacts import load_verified_benchmark
from reflow.evaluation.final_summary import (
    FinalSummaryError,
    build_final_summary,
    verify_final_summary_payload,
)

ROOT = Path(__file__).resolve().parents[2]
SUMMARY = ROOT / "data" / "eval" / "gate19" / "final-summary.json"
HELDOUT = ROOT / "data" / "eval" / "gate19" / "final-heldout.json"
MANIFEST = ROOT / "data" / "eval" / "gate19" / "heldout_manifest.json"
FAILURE = ROOT / "data" / "eval" / "gate19" / "failure-campaign.json"


def test_checked_summary_matches_frozen_source_artifacts() -> None:
    checked = json.loads(SUMMARY.read_text())
    rebuilt = build_final_summary(
        heldout_path=HELDOUT,
        manifest_path=MANIFEST,
        failure_path=FAILURE,
        repo_root=ROOT,
    )
    assert checked == rebuilt
    assert checked["metrics"]["false_auto_reconciled"] == 0
    assert checked["metrics"]["fuzzy_false_auto_reconciled"] == 9
    assert checked["metrics"]["failure_campaign_passed"] == 12


def test_final_summary_tampering_fails_closed() -> None:
    payload = json.loads(SUMMARY.read_text())
    tampered = copy.deepcopy(payload)
    tampered["metrics"]["false_auto_reconciled"] = 1
    with pytest.raises(FinalSummaryError, match="digest"):
        verify_final_summary_payload(tampered)


def test_generic_verified_benchmark_loader_accepts_final_summary() -> None:
    payload = load_verified_benchmark(SUMMARY)
    assert payload["schema_version"] == "gate19-final-summary-v1"
    assert payload["config"]["settlement_count"] == 768
