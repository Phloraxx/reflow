from __future__ import annotations

import hashlib
import json

import pytest

from reflow.evaluation.failure_campaign import (
    CHECKS,
    FAILURE_CAMPAIGN_SCHEMA_VERSION,
    FailureCampaignError,
    verify_failure_campaign_payload,
)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _payload() -> dict[str, object]:
    checks = [
        {
            "check_id": check_id,
            "node_id": node_id,
            "status": "passed",
            "returncode": 0,
            "elapsed_seconds": 0.1,
            "output": f". [100%]\\nPASSED {node_id}",
        }
        for check_id, node_id in CHECKS
    ]
    payload: dict[str, object] = {
        "schema_version": FAILURE_CAMPAIGN_SCHEMA_VERSION,
        "runtime": {"python": "test", "platform": "test", "machine": "test", "cpu_count": 1},
        "check_count": len(checks),
        "passed_count": len(checks),
        "failed_count": 0,
        "checks": checks,
    }
    payload["artifact_sha256"] = _digest(payload)
    return payload


def test_failure_campaign_verifier_accepts_exact_passed_selector_set() -> None:
    verify_failure_campaign_payload(_payload())


def test_failure_campaign_verifier_rejects_tampered_status() -> None:
    payload = _payload()
    payload["checks"][0]["status"] = "failed"  # type: ignore[index]
    unsigned = dict(payload)
    unsigned.pop("artifact_sha256")
    payload["artifact_sha256"] = _digest(unsigned)
    with pytest.raises(FailureCampaignError, match="did not pass"):
        verify_failure_campaign_payload(payload)  # type: ignore[arg-type]
