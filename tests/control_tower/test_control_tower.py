from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from reflow import domain
from reflow.control_tower import (
    ControlTowerIntegrityError,
    ControlTowerNotFound,
    ControlTowerReader,
)
from reflow.persistence import ArtifactKind, StoredArtifact, canonical_artifact_sha256

NOW = datetime(2026, 9, 1, 17, 30, tzinfo=UTC)
SCOPE_A = domain.ReconciliationScopeId("scope_control_tower_a")
SCOPE_B = domain.ReconciliationScopeId("scope_control_tower_b")


class FakeStore:
    def __init__(self, artifacts: tuple[StoredArtifact, ...]) -> None:
        self._by_id = {item.artifact_id: item for item in artifacts}

    def artifact(self, artifact_id: str) -> StoredArtifact | None:
        return self._by_id.get(artifact_id)

    def artifacts(
        self,
        *,
        kind: ArtifactKind,
        scope_id: domain.ReconciliationScopeId | None,
        limit: int = 100,
    ) -> tuple[StoredArtifact, ...]:
        values = tuple(
            item for item in self._by_id.values() if item.kind is kind and item.scope_id == scope_id
        )
        return tuple(sorted(values, key=lambda item: item.artifact_id))[:limit]


def _artifact(
    kind: ArtifactKind,
    artifact_id: str,
    scope_id: domain.ReconciliationScopeId,
    payload: Mapping[str, object],
    *,
    observed_at: datetime = NOW,
) -> StoredArtifact:
    complete = {"id": artifact_id, **payload}
    return StoredArtifact(
        artifact_id=artifact_id,
        kind=kind,
        scope_id=scope_id,
        observed_at=observed_at,
        payload_sha256=canonical_artifact_sha256(complete),
        payload=complete,
    )


def _money(amount: int, currency: str = "INR") -> dict[str, object]:
    return {"amount_paise": amount, "currency": currency}


def _proof(
    proof_id: str,
    settlement_id: str,
    status: str,
    amount: int,
    *,
    generated_at: datetime,
    currency: str = "INR",
    reason_codes: tuple[str, ...] = (),
    version: int = 1,
    prior_version_id: str | None = None,
    reopened: bool = False,
) -> dict[str, object]:
    composition_status = (
        "composition_proven" if status != "contradicted" else "composition_contradicted"
    )
    composition_residual = 0 if status not in {"residual", "contradicted"} else 500
    bank_status = "bank_receipt_proven"
    bank_residual = 0
    if status == "pending_bank_credit":
        bank_status = "bank_receipt_waiting"
        bank_residual = amount
    return {
        "settlement_id": settlement_id,
        "version": version,
        "status": status,
        "composition": {
            "status": composition_status,
            "settlement_amount": _money(amount, currency),
            "observed_composition": _money(amount - composition_residual, currency),
            "residual": _money(composition_residual, currency),
            "component_ids": [f"recon_{settlement_id}"],
            "source_envelope_ids": [f"src_recon_{settlement_id}"],
            "reason_codes": list(reason_codes if composition_residual else ()),
        },
        "bank": {
            "status": bank_status,
            "settlement_utr": f"UTR-{settlement_id}",
            "expected_amount": _money(amount, currency),
            "observed_bank_credit": _money(amount - bank_residual, currency),
            "residual": _money(bank_residual, currency),
            "bank_entry_ids": [] if bank_residual else [f"bank_{settlement_id}"],
            "source_envelope_ids": [f"src_bank_{settlement_id}"],
            "reason_codes": ["BANK_CREDIT_NOT_OBSERVED"] if bank_residual else [],
        },
        "source_envelope_ids": [f"src_bank_{settlement_id}", f"src_recon_{settlement_id}"],
        "reason_codes": list(reason_codes),
        "knowledge_cutoff": (generated_at - timedelta(seconds=1)).isoformat(),
        "generated_at": generated_at.isoformat(),
        "prior_version_id": prior_version_id,
        "reopened": reopened,
    }


def _manifest(
    manifest_id: str,
    source_kind: str,
    completeness: str,
    *,
    late: bool = False,
) -> dict[str, object]:
    return {
        "scope_id": str(SCOPE_A),
        "source_kind": source_kind,
        "delivery_mode": "snapshot",
        "expected_by": (NOW - timedelta(hours=2)).isoformat(),
        "received_at": (NOW - timedelta(hours=1)).isoformat()
        if completeness not in {"waiting", "late"}
        else None,
        "watermark_at": (NOW - timedelta(hours=2)).isoformat()
        if completeness not in {"waiting", "late"}
        else None,
        "completeness": completeness,
        "received_late": late,
        "delivered_envelope_ids": [f"src_{manifest_id}"],
        "effective_envelope_ids": [f"src_{manifest_id}"],
        "adapter_version": "adapter-v1",
        "schema_fingerprint": f"schema-{source_kind}-v1",
    }


def _base_artifacts(*, second_currency: str = "INR") -> tuple[StoredArtifact, ...]:
    proof_green = _artifact(
        ArtifactKind.PROOF_VERSION,
        "proofv_ui_green",
        SCOPE_A,
        _proof(
            "proofv_ui_green",
            "setl_ui_green",
            "proven_reconciled",
            10_000,
            generated_at=NOW - timedelta(minutes=20),
        ),
        observed_at=NOW - timedelta(minutes=20),
    )
    proof_break = _artifact(
        ArtifactKind.PROOF_VERSION,
        "proofv_ui_break",
        SCOPE_A,
        _proof(
            "proofv_ui_break",
            "setl_ui_break",
            "residual",
            20_000,
            generated_at=NOW - timedelta(minutes=10),
            currency=second_currency,
            reason_codes=("SETTLEMENT_COMPOSITION_RESIDUAL",),
        ),
        observed_at=NOW - timedelta(minutes=10),
    )
    manifest_recon = _artifact(
        ArtifactKind.SOURCE_DELIVERY_MANIFEST,
        "manifest_ui_recon",
        SCOPE_A,
        _manifest("manifest_ui_recon", "razorpay_recon", "complete"),
    )
    manifest_bank = _artifact(
        ArtifactKind.SOURCE_DELIVERY_MANIFEST,
        "manifest_ui_bank",
        SCOPE_A,
        _manifest("manifest_ui_bank", "bank", "late", late=True),
    )
    close = _artifact(
        ArtifactKind.CLOSE_READINESS,
        "close_ui",
        SCOPE_A,
        {"status": "not_ready", "reason_codes": ["BALANCE_CONTROL_RESIDUAL"]},
    )
    coverage = _artifact(
        ArtifactKind.EVIDENCE_COVERAGE,
        "coverage_ui",
        SCOPE_A,
        {
            "scope_id": str(SCOPE_A),
            "status": "complete",
            "orphan_count": 0,
            "orphan_known_value": _money(0),
        },
    )
    balance = _artifact(
        ArtifactKind.BALANCE_CONTROL,
        "balance_ui",
        SCOPE_A,
        {"scope_id": str(SCOPE_A), "status": "residual", "residual": _money(500)},
    )
    run = _artifact(
        ArtifactKind.RECONCILIATION_RUN,
        "run_ui",
        SCOPE_A,
        {
            "scope_id": str(SCOPE_A),
            "outcome": "not_ready",
            "period_start": (NOW - timedelta(days=1)).isoformat(),
            "period_end": NOW.isoformat(),
            "reporting_timezone": "Asia/Kolkata",
            "knowledge_cutoff": (NOW - timedelta(minutes=5)).isoformat(),
            "completed_at": NOW.isoformat(),
            "code_build_sha": "95164be",
            "proof_version_ids": ["proofv_ui_break", "proofv_ui_green"],
            "source_manifest_ids": ["manifest_ui_bank", "manifest_ui_recon"],
            "coverage_certificate_id": "coverage_ui",
            "balance_control_id": "balance_ui",
            "close_readiness_id": "close_ui",
        },
    )
    observation_old = _artifact(
        ArtifactKind.CASE_OBSERVATION,
        "caseobs_ui_old",
        SCOPE_A,
        {
            "scope_id": str(SCOPE_A),
            "case_id": "case_ui_break",
            "tracking_key": "track_ui_break",
            "run_id": "run_ui_old",
            "proof_version_id": "proofv_ui_break",
            "policy_version_id": "policy_ui",
            "settlement_id": "setl_ui_break",
            "financial_status": "residual",
            "reason_codes": ["SETTLEMENT_COMPOSITION_RESIDUAL"],
            "affected_amount": _money(20_000, second_currency),
            "materiality_band": "high",
            "settlement_utr": "UTR-setl_ui_break",
            "source_states": [
                {
                    "source_kind": "bank",
                    "completeness": "late",
                    "received_late": True,
                    "manifest_id": "manifest_ui_bank",
                },
                {
                    "source_kind": "razorpay_recon",
                    "completeness": "complete",
                    "received_late": False,
                    "manifest_id": "manifest_ui_recon",
                },
            ],
            "incident_fingerprint_id": "incident_ui_break",
            "observed_at": (NOW - timedelta(hours=4)).isoformat(),
        },
        observed_at=NOW - timedelta(hours=4),
    )
    observation_latest = _artifact(
        ArtifactKind.CASE_OBSERVATION,
        "caseobs_ui_latest",
        SCOPE_A,
        {
            **{key: value for key, value in observation_old.payload.items() if key != "id"},
            "id": "caseobs_ui_latest",
            "run_id": "run_ui",
            "observed_at": (NOW - timedelta(hours=1)).isoformat(),
        },
        observed_at=NOW - timedelta(hours=1),
    )
    assign = _artifact(
        ArtifactKind.CASE_DISPOSITION,
        "disp_ui_1",
        SCOPE_A,
        {
            "case_id": "case_ui_break",
            "sequence": 1,
            "actor_id": "operator-7",
            "occurred_at": (NOW - timedelta(hours=3)).isoformat(),
            "kind": "assign_owner",
            "owner": "finance-ops",
            "note": None,
        },
        observed_at=NOW - timedelta(hours=3),
    )
    request_source = _artifact(
        ArtifactKind.CASE_DISPOSITION,
        "disp_ui_2",
        SCOPE_A,
        {
            "case_id": "case_ui_break",
            "sequence": 2,
            "actor_id": "operator-7",
            "occurred_at": (NOW - timedelta(hours=2)).isoformat(),
            "kind": "request_source_correction",
            "owner": None,
            "note": "Bank delivery is late",
        },
        observed_at=NOW - timedelta(hours=2),
    )
    cluster = _artifact(
        ArtifactKind.INCIDENT_CLUSTER,
        "cluster_ui",
        SCOPE_A,
        {
            "scope_id": str(SCOPE_A),
            "case_ids": ["case_ui_break"],
            "run_id": "run_ui",
        },
    )
    investigation = _artifact(
        ArtifactKind.INVESTIGATION_RESULT,
        "invest_ui",
        SCOPE_A,
        {
            "case_id": "case_ui_break",
            "observation_id": "caseobs_ui_latest",
            "proof_version_id": "proofv_ui_break",
            "status": "validated",
            "next_action": "REQUEST_SOURCE",
            "hypothesis": "Bank source delivery is incomplete.",
            "citations": ["src_bank_setl_ui_break"],
            "request_source_kind": "bank",
            "rejection_reason": None,
            "as_of": (NOW - timedelta(minutes=30)).isoformat(),
            "trace": [{"id": "trace_ui_1"}],
        },
        observed_at=NOW - timedelta(minutes=30),
    )
    return (
        proof_green,
        proof_break,
        manifest_recon,
        manifest_bank,
        close,
        coverage,
        balance,
        run,
        observation_old,
        observation_latest,
        assign,
        request_source,
        cluster,
        investigation,
    )


def _reader(
    tmp_path: Path, artifacts: tuple[StoredArtifact, ...] | None = None
) -> ControlTowerReader:
    return ControlTowerReader(
        FakeStore(_base_artifacts() if artifacts is None else artifacts),
        evaluation_root=tmp_path,
        now=lambda: NOW,
    )


def test_overview_binds_current_run_controls_and_exact_status_totals(tmp_path: Path) -> None:
    overview = _reader(tmp_path).overview(SCOPE_A)
    assert overview.has_current_run
    assert overview.run is not None
    assert overview.run.run_id == "run_ui"
    assert overview.run.close_status == "not_ready"
    assert overview.run.balance_residual.amount_paise == 500
    assert overview.run.coverage_certificate_id == "coverage_ui"
    totals = {item.status: (item.count, item.amount.amount_paise) for item in overview.proof_status}
    assert totals["proven_reconciled"] == (1, 10_000)
    assert totals["residual"] == (1, 20_000)
    assert overview.active_exception_count == 1
    assert overview.active_exception_value is not None
    assert overview.active_exception_value.amount_paise == 20_000


def test_overview_mixed_currency_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ControlTowerIntegrityError, match="mixed currencies"):
        _reader(tmp_path, _base_artifacts(second_currency="USD")).overview(SCOPE_A)


def test_overview_without_run_is_explicit_empty_not_ready_state(tmp_path: Path) -> None:
    source_only = tuple(
        item for item in _base_artifacts() if item.kind is ArtifactKind.SOURCE_DELIVERY_MANIFEST
    )
    overview = _reader(tmp_path, source_only).overview(SCOPE_A)
    assert not overview.has_current_run
    assert overview.run is None
    assert overview.proof_status == ()


def test_proof_list_and_detail_retain_exact_financial_fragments(tmp_path: Path) -> None:
    reader = _reader(tmp_path)
    proofs = reader.proofs(SCOPE_A)
    assert [item.proof_id for item in proofs] == ["proofv_ui_break", "proofv_ui_green"]
    detail = reader.proof_detail(SCOPE_A, "proofv_ui_break")
    assert detail.status == "residual"
    assert detail.composition.residual.amount_paise == 500
    assert detail.bank.residual.amount_paise == 0
    assert detail.source_envelope_ids == (
        "src_bank_setl_ui_break",
        "src_recon_setl_ui_break",
    )
    assert detail.reason_codes == ("SETTLEMENT_COMPOSITION_RESIDUAL",)


def test_proof_detail_rejects_cross_scope_artifact(tmp_path: Path) -> None:
    foreign = _artifact(
        ArtifactKind.PROOF_VERSION,
        "proofv_foreign",
        SCOPE_B,
        _proof(
            "proofv_foreign",
            "setl_foreign",
            "proven_reconciled",
            100,
            generated_at=NOW,
        ),
    )
    reader = _reader(tmp_path, (*_base_artifacts(), foreign))
    with pytest.raises(ControlTowerIntegrityError, match="another reconciliation scope"):
        reader.proof_detail(SCOPE_A, "proofv_foreign")


def test_exception_queue_derives_workflow_owner_source_blocker_and_age(tmp_path: Path) -> None:
    queue = _reader(tmp_path).exceptions(SCOPE_A)
    assert len(queue) == 1
    item = queue[0]
    assert item.case_id == "case_ui_break"
    assert item.owner == "finance-ops"
    assert item.workflow_status == "awaiting_source"
    assert item.source_blockers == ("bank:late:late",)
    assert item.incident_cluster_id == "cluster_ui"
    assert item.age_seconds == 4 * 60 * 60
    assert item.is_active


def test_case_file_binds_only_matching_latest_investigation(tmp_path: Path) -> None:
    case = _reader(tmp_path).case_file(SCOPE_A, "case_ui_break")
    assert [item.observation_id for item in case.observations] == [
        "caseobs_ui_old",
        "caseobs_ui_latest",
    ]
    assert [item.sequence for item in case.dispositions] == [1, 2]
    assert case.proof.proof_id == "proofv_ui_break"
    assert case.investigation is not None
    assert case.investigation.next_action == "REQUEST_SOURCE"
    assert case.investigation.trace_count == 1


def test_case_file_ignores_investigation_bound_to_another_proof(tmp_path: Path) -> None:
    artifacts = tuple(
        item for item in _base_artifacts() if item.kind is not ArtifactKind.INVESTIGATION_RESULT
    )
    wrong = _artifact(
        ArtifactKind.INVESTIGATION_RESULT,
        "invest_wrong",
        SCOPE_A,
        {
            "case_id": "case_ui_break",
            "observation_id": "caseobs_ui_latest",
            "proof_version_id": "proofv_ui_green",
            "status": "validated",
            "next_action": "RECHECK",
            "hypothesis": "Wrong proof binding",
            "citations": [],
            "request_source_kind": None,
            "rejection_reason": None,
            "as_of": NOW.isoformat(),
            "trace": [],
        },
    )
    assert (
        _reader(tmp_path, (*artifacts, wrong)).case_file(SCOPE_A, "case_ui_break").investigation
        is None
    )


def test_source_lab_contains_metadata_but_no_raw_payload(tmp_path: Path) -> None:
    sources = _reader(tmp_path).sources(SCOPE_A)
    assert [item.source_kind for item in sources] == ["bank", "razorpay_recon"]
    assert sources[0].completeness == "late"
    assert not hasattr(sources[0], "payload")
    assert not hasattr(sources[0], "source_account_id")


def test_unknown_case_and_proof_are_not_found(tmp_path: Path) -> None:
    reader = _reader(tmp_path)
    with pytest.raises(ControlTowerNotFound):
        reader.case_file(SCOPE_A, "case_missing")
    with pytest.raises(ControlTowerNotFound):
        reader.proof_detail(SCOPE_A, "proofv_missing")


def test_evaluation_lab_verifies_checked_in_artifact(tmp_path: Path) -> None:
    source = Path("data/eval/gate17/scale-50-clean.json")
    (tmp_path / source.name).write_text(source.read_text())
    lab = _reader(tmp_path).evaluation()
    assert len(lab.artifacts) == 1
    assert lab.artifacts[0].schema_version == "gate17-scale-benchmark-v1"
    assert lab.artifacts[0].metrics["proof_count"] == 50


def test_evaluation_lab_rejects_tampered_artifact(tmp_path: Path) -> None:
    payload = json.loads(Path("data/eval/gate17/scale-50-clean.json").read_text())
    payload["metrics"]["proof_count"] = 999
    (tmp_path / "tampered.json").write_text(json.dumps(payload))
    with pytest.raises(ControlTowerIntegrityError, match="failed verification"):
        _reader(tmp_path).evaluation()


def test_control_tower_module_has_no_simulator_import() -> None:
    source = Path("src/reflow/control_tower.py").read_text()
    assert "reflow.simulator" not in source
    assert "simulator.truth" not in source
    assert "MARK_RECONCILED" not in source


def test_fastapi_surface_is_read_only_and_scope_explicit(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from reflow.control_tower_api import create_control_tower_app

    app = create_control_tower_app(_reader(tmp_path))
    client = TestClient(app)
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["financial_truth_mutation"] is False

    overview = client.get(f"/api/v1/scopes/{SCOPE_A}/overview")
    assert overview.status_code == 200
    assert overview.json()["run"]["run_id"] == "run_ui"

    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert "/api/v1/scopes/{scope_id}/overview" in paths
    assert not any("mark" in path or "reconcile" in path or "sql" in path for path in paths)
    for route in app.routes:
        methods = getattr(route, "methods", None)
        if route.path.startswith("/api/v1") and methods:
            assert not ({"POST", "PUT", "PATCH", "DELETE"} & methods)


def test_fastapi_proof_case_source_and_evaluation_routes(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from reflow.control_tower_api import create_control_tower_app

    source = Path("data/eval/gate17/scale-50-clean.json")
    (tmp_path / source.name).write_text(source.read_text())
    client = TestClient(create_control_tower_app(_reader(tmp_path)))

    assert client.get(f"/api/v1/scopes/{SCOPE_A}/proofs").status_code == 200
    proof = client.get(f"/api/v1/scopes/{SCOPE_A}/proofs/proofv_ui_break")
    assert proof.status_code == 200
    assert proof.json()["composition"]["residual"]["amount_paise"] == 500

    queue = client.get(f"/api/v1/scopes/{SCOPE_A}/exceptions")
    assert queue.status_code == 200
    assert queue.json()[0]["workflow_status"] == "awaiting_source"

    case = client.get(f"/api/v1/scopes/{SCOPE_A}/cases/case_ui_break")
    assert case.status_code == 200
    assert case.json()["investigation"]["next_action"] == "REQUEST_SOURCE"

    sources = client.get(f"/api/v1/scopes/{SCOPE_A}/sources")
    assert sources.status_code == 200
    assert {item["source_kind"] for item in sources.json()} == {"bank", "razorpay_recon"}

    evaluation = client.get("/api/v1/evaluation")
    assert evaluation.status_code == 200
    assert evaluation.json()["artifacts"][0]["metrics"]["proof_count"] == 50


def test_fastapi_invalid_scope_and_missing_artifact_status_codes(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from reflow.control_tower_api import create_control_tower_app

    client = TestClient(create_control_tower_app(_reader(tmp_path)))
    assert client.get("/api/v1/scopes/not-a-scope/overview").status_code == 422
    missing = client.get(f"/api/v1/scopes/{SCOPE_A}/proofs/proofv_missing")
    assert missing.status_code == 404


def test_fastapi_cross_scope_integrity_failure_is_not_404_fallback(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from reflow.control_tower_api import create_control_tower_app

    foreign = _artifact(
        ArtifactKind.PROOF_VERSION,
        "proofv_foreign_api",
        SCOPE_B,
        _proof(
            "proofv_foreign_api",
            "setl_foreign_api",
            "proven_reconciled",
            100,
            generated_at=NOW,
        ),
    )
    client = TestClient(create_control_tower_app(_reader(tmp_path, (*_base_artifacts(), foreign))))
    response = client.get(f"/api/v1/scopes/{SCOPE_A}/proofs/proofv_foreign_api")
    assert response.status_code == 409
    assert response.json()["error"] == "control_tower_integrity_error"
