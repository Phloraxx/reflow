from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from reflow.evaluation.final_campaign import (
    FinalCampaignError,
    run_final_campaign,
    verify_final_campaign_payload,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(tmp_path: Path, repo_root: Path) -> Path:
    path = tmp_path / "manifest.json"
    payload = {
        "schema_version": "gate19-heldout-manifest-v1",
        "frozen_from_main_sha": "test-base",
        "seed_derivation": "test-only",
        "primary_case_count": 2,
        "primary_settlement_count": 4,
        "safety_case_count": 1,
        "safety_settlement_count": 2,
        "frozen_core_file_sha256": {
            name: _sha(repo_root / name)
            for name in (
                "src/reflow/evaluation/candidates.py",
                "src/reflow/evaluation/scoring.py",
            )
        },
        "cases": [
            {
                "case_id": "clean",
                "role": "primary_benchmark",
                "profile": "clean",
                "settlement_count": 2,
                "world_seed": 101,
                "observation_seed": 201,
            },
            {
                "case_id": "adv",
                "role": "primary_benchmark",
                "profile": "reconciliation_adversarial",
                "settlement_count": 2,
                "world_seed": 102,
                "observation_seed": 202,
            },
            {
                "case_id": "source",
                "role": "safety_failure",
                "profile": "source_schema_adversarial",
                "settlement_count": 2,
                "world_seed": 103,
                "observation_seed": 203,
            },
        ],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def test_final_campaign_aggregates_identical_cases_and_lists_reflow_exceptions(
    tmp_path: Path,
) -> None:
    repo_root = Path.cwd()
    manifest = _manifest(tmp_path, repo_root)
    payload = run_final_campaign(manifest_path=manifest, repo_root=repo_root)
    assert payload["primary"]["requested_settlements"] == 4
    assert payload["primary"]["observed_record_count"] >= 4
    systems = payload["primary"]["systems"]
    assert set(systems) == {
        "B0_naive_1to1",
        "B1_grouped_exact",
        "B2_fuzzy_threshold",
        "ReFlow_Core",
    }
    assert systems["ReFlow_Core"]["requested_settlements"] == 4
    assert systems["ReFlow_Core"]["safe_match_rate"]["denominator"] == 4
    assert isinstance(payload["primary"]["reflow_exceptions"], list)
    verify_final_campaign_payload(payload, manifest_path=manifest, repo_root=repo_root)


def test_source_schema_campaign_fails_closed_without_candidate_decisions(tmp_path: Path) -> None:
    repo_root = Path.cwd()
    manifest = _manifest(tmp_path, repo_root)
    payload = run_final_campaign(manifest_path=manifest, repo_root=repo_root)
    assert payload["safety"]["case_count"] == 1
    assert payload["safety"]["source_rejected_cases"] == 1
    assert payload["safety"]["candidate_decisions_emitted"] == 0
    assert payload["safety"]["cases"][0]["source_rejection"]["retained_raw_envelopes"] > 0


def test_final_campaign_detects_aggregate_tampering(tmp_path: Path) -> None:
    repo_root = Path.cwd()
    manifest = _manifest(tmp_path, repo_root)
    payload = run_final_campaign(manifest_path=manifest, repo_root=repo_root)
    payload["primary"]["systems"]["ReFlow_Core"]["true_auto_reconciled"] += 1
    unsigned = dict(payload)
    unsigned.pop("artifact_sha256")
    payload["artifact_sha256"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    with pytest.raises(FinalCampaignError, match="aggregate mismatch"):
        verify_final_campaign_payload(payload, manifest_path=manifest, repo_root=repo_root)


def test_final_campaign_refuses_changed_frozen_core(tmp_path: Path) -> None:
    repo_root = Path.cwd()
    manifest = _manifest(tmp_path, repo_root)
    raw = json.loads(manifest.read_text())
    raw["frozen_core_file_sha256"]["src/reflow/evaluation/scoring.py"] = "0" * 64
    manifest.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n")
    with pytest.raises(FinalCampaignError, match="frozen evaluation core changed"):
        run_final_campaign(manifest_path=manifest, repo_root=repo_root)
