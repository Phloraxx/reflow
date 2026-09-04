from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from reflow import domain
from reflow.control_tower import (
    ControlTowerCursorError,
    ControlTowerIntegrityError,
    ControlTowerNotFound,
    ControlTowerReader,
)
from reflow.persistence import (
    ArtifactKind,
    ArtifactPage,
    ArtifactPageCursor,
    CurrentPointer,
    PointerKind,
    StoredArtifact,
    canonical_artifact_sha256,
)

NOW = datetime(2026, 9, 1, 17, 30, tzinfo=UTC)
SCOPE_A = domain.ReconciliationScopeId("scope_control_tower_a")
SCOPE_B = domain.ReconciliationScopeId("scope_control_tower_b")


class FakeStore:
    def __init__(
        self,
        artifacts: tuple[StoredArtifact, ...],
        *,
        latest_run_ids: Mapping[str, str] | None = None,
    ) -> None:
        self._by_id = {item.artifact_id: item for item in artifacts}
        if latest_run_ids is None:
            latest_run_ids = {
                str(scope_id): max(
                    (
                        item
                        for item in artifacts
                        if item.kind is ArtifactKind.RECONCILIATION_RUN
                        and item.scope_id == scope_id
                    ),
                    key=lambda item: (
                        item.observed_at or datetime.min.replace(tzinfo=UTC),
                        item.artifact_id,
                    ),
                ).artifact_id
                for scope_id in {
                    item.scope_id
                    for item in artifacts
                    if item.kind is ArtifactKind.RECONCILIATION_RUN and item.scope_id is not None
                }
            }
        self._latest_run_ids = dict(latest_run_ids)

    def artifact(self, artifact_id: str) -> StoredArtifact | None:
        return self._by_id.get(artifact_id)

    def current(self, *, kind: PointerKind, stream_key: str) -> CurrentPointer | None:
        if kind is not PointerKind.LATEST_RUN:
            return None
        artifact_id = self._latest_run_ids.get(stream_key)
        if artifact_id is None:
            return None
        return CurrentPointer(
            kind=kind,
            stream_key=stream_key,
            artifact_id=artifact_id,
            generation=1,
            updated_at=NOW,
        )

    def artifact_page(
        self,
        *,
        kind: ArtifactKind,
        scope_id: domain.ReconciliationScopeId | None,
        limit: int = 100,
        after: ArtifactPageCursor | None = None,
    ) -> ArtifactPage:
        max_time = datetime.max.replace(tzinfo=UTC)
        values = sorted(
            (
                item
                for item in self._by_id.values()
                if item.kind is kind and item.scope_id == scope_id
            ),
            key=lambda item: (
                item.observed_at is None,
                item.observed_at or max_time,
                item.artifact_id,
            ),
        )
        if after is not None:
            after_key = (
                after.observed_at is None,
                after.observed_at or max_time,
                after.artifact_id,
            )
            values = [
                item
                for item in values
                if (
                    item.observed_at is None,
                    item.observed_at or max_time,
                    item.artifact_id,
                )
                > after_key
            ]
        items = tuple(values[:limit])
        next_cursor = None
        if len(values) > limit and items:
            last = items[-1]
            next_cursor = ArtifactPageCursor(last.observed_at, last.artifact_id)
        return ArtifactPage(items=items, next_cursor=next_cursor)

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

    def artifact_count(
        self,
        *,
        kind: ArtifactKind,
        scope_id: domain.ReconciliationScopeId | None,
    ) -> int:
        return sum(
            1 for item in self._by_id.values() if item.kind is kind and item.scope_id == scope_id
        )


def _artifact(
    kind: ArtifactKind,
    artifact_id: str,
    scope_id: domain.ReconciliationScopeId | None,
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
    policy = _artifact(
        ArtifactKind.POLICY_VERSION,
        "policy_ui",
        None,
        {
            "materiality_thresholds_paise": [1_000, 5_000, 20_000],
        },
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
        {
            "status": "not_ready",
            "reason_codes": ["BALANCE_CONTROL_RESIDUAL"],
            "policy_version_id": "policy_ui",
            "manifest_ids": ["manifest_ui_bank", "manifest_ui_recon"],
            "proof_version_ids": ["proofv_ui_break", "proofv_ui_green"],
            "coverage_certificate_id": "coverage_ui",
            "balance_control_id": "balance_ui",
        },
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
            "manifest_ids": ["manifest_ui_bank", "manifest_ui_recon"],
            "proof_version_ids": ["proofv_ui_break", "proofv_ui_green"],
        },
    )
    balance = _artifact(
        ArtifactKind.BALANCE_CONTROL,
        "balance_ui",
        SCOPE_A,
        {
            "scope_id": str(SCOPE_A),
            "policy_version_id": "policy_ui",
            "status": "residual",
            "residual": _money(500),
        },
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
            "policy_version_id": "policy_ui",
            "proof_version_ids": ["proofv_ui_break", "proofv_ui_green"],
            "source_manifest_ids": ["manifest_ui_bank", "manifest_ui_recon"],
            "coverage_certificate_id": "coverage_ui",
            "balance_control_id": "balance_ui",
            "close_readiness_id": "close_ui",
        },
    )
    run_old = _artifact(
        ArtifactKind.RECONCILIATION_RUN,
        "run_ui_old",
        SCOPE_A,
        {
            **{key: value for key, value in run.payload.items() if key != "id"},
            "id": "run_ui_old",
            "completed_at": (NOW - timedelta(hours=4)).isoformat(),
        },
        observed_at=NOW - timedelta(hours=4),
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
            "observed_at": NOW.isoformat(),
        },
        observed_at=NOW,
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
            "as_of": NOW.isoformat(),
            "trace": [{"id": "trace_ui_1"}],
        },
        observed_at=NOW,
    )
    return (
        proof_green,
        proof_break,
        policy,
        manifest_recon,
        manifest_bank,
        close,
        coverage,
        balance,
        run,
        run_old,
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


def test_overview_uses_explicit_latest_run_pointer_not_newer_unpointed_artifact(
    tmp_path: Path,
) -> None:
    artifacts = _base_artifacts()
    current = next(item for item in artifacts if item.artifact_id == "run_ui")
    forged_payload = dict(current.payload)
    forged_payload["id"] = "run_unpointed_newer"
    forged_payload["code_build_sha"] = "unpointed-newer"
    newer = StoredArtifact(
        artifact_id="run_unpointed_newer",
        kind=ArtifactKind.RECONCILIATION_RUN,
        scope_id=SCOPE_A,
        observed_at=NOW + timedelta(days=1),
        payload_sha256=canonical_artifact_sha256(forged_payload),
        payload=forged_payload,
    )
    store = FakeStore(
        (*artifacts, newer),
        latest_run_ids={str(SCOPE_A): "run_ui"},
    )
    reader = ControlTowerReader(store, evaluation_root=tmp_path, now=lambda: NOW)
    overview = reader.overview(SCOPE_A)
    assert overview.run is not None
    assert overview.run.run_id == "run_ui"
    assert overview.run.code_build_sha == "95164be"


def test_control_tower_paged_history_still_fails_closed_on_truncated_store(
    tmp_path: Path,
) -> None:
    class TruncatedPageStore(FakeStore):
        def artifact_page(self, *, kind, scope_id, limit=100, after=None):
            page = super().artifact_page(
                kind=kind, scope_id=scope_id, limit=limit, after=after
            )
            if page.items:
                return ArtifactPage(items=page.items[:1], next_cursor=None)
            return page

    artifacts = (
        _artifact(
            ArtifactKind.INVESTIGATION_TRACE,
            "trace_truncated_a",
            SCOPE_A,
            {"scope_id": str(SCOPE_A)},
        ),
        _artifact(
            ArtifactKind.INVESTIGATION_TRACE,
            "trace_truncated_b",
            SCOPE_A,
            {"scope_id": str(SCOPE_A)},
        ),
    )
    reader = ControlTowerReader(
        TruncatedPageStore(artifacts),
        evaluation_root=tmp_path,
        now=lambda: NOW,
    )
    with pytest.raises(ControlTowerIntegrityError, match="pagination was incomplete"):
        reader._list(ArtifactKind.INVESTIGATION_TRACE, SCOPE_A)


def test_control_tower_scans_artifact_history_beyond_legacy_10000_window(
    tmp_path: Path,
) -> None:
    artifacts = tuple(
        _artifact(
            ArtifactKind.INVESTIGATION_TRACE,
            f"trace_page_{index:05d}",
            SCOPE_A,
            {"scope_id": str(SCOPE_A)},
            observed_at=NOW + timedelta(microseconds=index),
        )
        for index in range(10_001)
    )
    reader = ControlTowerReader(
        FakeStore(artifacts),
        evaluation_root=tmp_path,
        now=lambda: NOW,
    )
    result = reader._list(ArtifactKind.INVESTIGATION_TRACE, SCOPE_A)
    assert len(result) == 10_001
    assert result[0].artifact_id == "trace_page_00000"
    assert result[-1].artifact_id == "trace_page_10000"


def test_overview_rejects_control_packet_that_disagrees_with_current_run(
    tmp_path: Path,
) -> None:
    artifacts = _base_artifacts()
    coverage = next(item for item in artifacts if item.artifact_id == "coverage_ui")
    payload = dict(coverage.payload)
    payload["proof_version_ids"] = ["proofv_ui_green"]
    tampered = StoredArtifact(
        artifact_id=coverage.artifact_id,
        kind=coverage.kind,
        scope_id=coverage.scope_id,
        observed_at=coverage.observed_at,
        payload_sha256=canonical_artifact_sha256(payload),
        payload=payload,
    )
    replaced = tuple(
        tampered if item.artifact_id == coverage.artifact_id else item for item in artifacts
    )
    with pytest.raises(ControlTowerIntegrityError, match="coverage/proofs disagree"):
        _reader(tmp_path, replaced).overview(SCOPE_A)


def test_overview_binds_current_run_controls_and_exact_status_totals(tmp_path: Path) -> None:
    overview = _reader(tmp_path).overview(SCOPE_A)
    assert overview.has_current_run
    assert overview.run is not None
    assert overview.run.run_id == "run_ui"
    assert overview.run.close_status == "not_ready"
    assert overview.run.balance_residual.amount_paise == "500"
    assert overview.run.coverage_certificate_id == "coverage_ui"
    totals = {item.status: (item.count, item.amount.amount_paise) for item in overview.proof_status}
    assert totals["proven_reconciled"] == (1, "10000")
    assert totals["residual"] == (1, "20000")
    assert overview.active_exception_count == 1
    assert overview.active_exception_value is not None
    assert overview.active_exception_value.amount_paise == "20000"


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
    assert detail.composition.residual.amount_paise == "500"
    assert detail.bank.residual.amount_paise == "0"
    assert detail.source_envelope_ids == (
        "src_bank_setl_ui_break",
        "src_recon_setl_ui_break",
    )
    assert detail.reason_codes == ("SETTLEMENT_COMPOSITION_RESIDUAL",)


def test_collection_pages_are_bounded_and_cursor_bound_to_scope_and_collection(
    tmp_path: Path,
) -> None:
    reader = _reader(tmp_path)

    first = reader.proofs_page(SCOPE_A, limit=1)
    assert [item.proof_id for item in first.items] == ["proofv_ui_break"]
    assert first.next_cursor is not None
    second = reader.proofs_page(SCOPE_A, cursor=first.next_cursor, limit=1)
    assert [item.proof_id for item in second.items] == ["proofv_ui_green"]
    assert second.next_cursor is None

    source_first = reader.sources_page(SCOPE_A, limit=1)
    assert len(source_first.items) == 1
    assert source_first.next_cursor is not None
    source_second = reader.sources_page(
        SCOPE_A, cursor=source_first.next_cursor, limit=1
    )
    assert len(source_second.items) == 1
    assert source_second.next_cursor is None
    assert source_first.items[0].manifest_id != source_second.items[0].manifest_id

    with pytest.raises(ControlTowerCursorError, match="binding"):
        reader.sources_page(SCOPE_A, cursor=first.next_cursor, limit=1)
    with pytest.raises(ControlTowerCursorError, match="binding"):
        reader.proofs_page(SCOPE_B, cursor=first.next_cursor, limit=1)
    with pytest.raises(ControlTowerCursorError, match="invalid collection cursor"):
        reader.proofs_page(SCOPE_A, cursor="not-a-valid-cursor", limit=1)
    assert first.next_cursor is not None
    raw = first.next_cursor + "=" * (-len(first.next_cursor) % 4)
    cursor_payload = json.loads(base64.urlsafe_b64decode(raw).decode())
    cursor_payload["v"] = True
    bool_version = base64.urlsafe_b64encode(
        json.dumps(cursor_payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    with pytest.raises(ControlTowerCursorError, match="binding"):
        reader.proofs_page(SCOPE_A, cursor=bool_version, limit=1)
    with pytest.raises(ControlTowerCursorError, match="page limit"):
        reader.proofs_page(SCOPE_A, limit=101)


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


def test_proof_browsing_rejects_orphan_proof_not_referenced_by_scoped_run(tmp_path: Path) -> None:
    orphan = _artifact(
        ArtifactKind.PROOF_VERSION,
        "proofv_orphan_same_scope",
        SCOPE_A,
        _proof(
            "proofv_orphan_same_scope",
            "setl_orphan",
            "proven_reconciled",
            100,
            generated_at=NOW,
        ),
    )
    reader = _reader(tmp_path, (*_base_artifacts(), orphan))
    assert "proofv_orphan_same_scope" not in {item.proof_id for item in reader.proofs(SCOPE_A)}
    with pytest.raises(
        ControlTowerIntegrityError, match="not referenced by any reconciliation run"
    ):
        reader.proof_detail(SCOPE_A, "proofv_orphan_same_scope")


def test_exception_queue_rejects_incident_cluster_without_matching_run_observation(
    tmp_path: Path,
) -> None:
    artifacts = tuple(
        item for item in _base_artifacts() if item.kind is not ArtifactKind.INCIDENT_CLUSTER
    )
    orphan_cluster = _artifact(
        ArtifactKind.INCIDENT_CLUSTER,
        "cluster_orphan_run",
        SCOPE_A,
        {
            "scope_id": str(SCOPE_A),
            "case_ids": ["case_ui_break"],
            "run_id": "run_missing_cluster",
        },
        observed_at=NOW + timedelta(days=1),
    )
    with pytest.raises(ControlTowerIntegrityError, match="incident cluster references missing"):
        _reader(tmp_path, (*artifacts, orphan_cluster)).exceptions(SCOPE_A)


def test_exception_queue_orders_incident_clusters_by_run_time_not_storage_time(
    tmp_path: Path,
) -> None:
    artifacts = _base_artifacts()
    old_cluster = _artifact(
        ArtifactKind.INCIDENT_CLUSTER,
        "cluster_old_forged_new_storage_time",
        SCOPE_A,
        {
            "scope_id": str(SCOPE_A),
            "case_ids": ["case_ui_break"],
            "run_id": "run_ui_old",
        },
        observed_at=NOW + timedelta(days=2),
    )
    item = _reader(tmp_path, (*artifacts, old_cluster)).exceptions(SCOPE_A)[0]
    assert item.incident_cluster_id == "cluster_ui"


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


def test_exception_queue_rejects_observation_financial_facts_that_disagree_with_proof(
    tmp_path: Path,
) -> None:
    artifacts = _base_artifacts()
    current = next(item for item in artifacts if item.artifact_id == "caseobs_ui_latest")
    tampered_payload = dict(current.payload)
    tampered_payload["financial_status"] = "proven_reconciled"
    tampered = StoredArtifact(
        artifact_id=current.artifact_id,
        kind=current.kind,
        scope_id=current.scope_id,
        observed_at=current.observed_at,
        payload_sha256=canonical_artifact_sha256(tampered_payload),
        payload=tampered_payload,
    )
    replaced = tuple(
        tampered if item.artifact_id == current.artifact_id else item for item in artifacts
    )
    with pytest.raises(ControlTowerIntegrityError, match="financial status disagrees"):
        _reader(tmp_path, replaced).exceptions(SCOPE_A)


def test_exception_queue_rejects_observation_source_state_that_disagrees_with_manifest(
    tmp_path: Path,
) -> None:
    artifacts = _base_artifacts()
    current = next(item for item in artifacts if item.artifact_id == "caseobs_ui_latest")
    tampered_payload = dict(current.payload)
    states = [dict(item) for item in tampered_payload["source_states"]]
    states[0]["completeness"] = "complete"
    states[0]["received_late"] = False
    tampered_payload["source_states"] = states
    tampered = StoredArtifact(
        artifact_id=current.artifact_id,
        kind=current.kind,
        scope_id=current.scope_id,
        observed_at=current.observed_at,
        payload_sha256=canonical_artifact_sha256(tampered_payload),
        payload=tampered_payload,
    )
    replaced = tuple(
        tampered if item.artifact_id == current.artifact_id else item for item in artifacts
    )
    with pytest.raises(ControlTowerIntegrityError, match="source state disagrees"):
        _reader(tmp_path, replaced).exceptions(SCOPE_A)


def test_exception_queue_rejects_same_case_id_with_changed_economic_identity(
    tmp_path: Path,
) -> None:
    artifacts = _base_artifacts()
    current = next(item for item in artifacts if item.artifact_id == "caseobs_ui_latest")
    tampered_payload = dict(current.payload)
    tampered_payload.update(
        {
            "proof_version_id": "proofv_ui_green",
            "settlement_id": "setl_ui_green",
            "financial_status": "proven_reconciled",
            "reason_codes": [],
            "affected_amount": _money(10_000),
            "settlement_utr": "UTR-setl_ui_green",
        }
    )
    tampered = StoredArtifact(
        artifact_id=current.artifact_id,
        kind=current.kind,
        scope_id=current.scope_id,
        observed_at=current.observed_at,
        payload_sha256=canonical_artifact_sha256(tampered_payload),
        payload=tampered_payload,
    )
    replaced = tuple(
        tampered if item.artifact_id == current.artifact_id else item for item in artifacts
    )
    with pytest.raises(ControlTowerIntegrityError, match="economic identity changed"):
        _reader(tmp_path, replaced).exceptions(SCOPE_A)


def test_exception_queue_rejects_observation_materiality_that_disagrees_with_policy(
    tmp_path: Path,
) -> None:
    artifacts = _base_artifacts()
    current = next(item for item in artifacts if item.artifact_id == "caseobs_ui_latest")
    tampered_payload = dict(current.payload)
    tampered_payload["materiality_band"] = "low"
    tampered = StoredArtifact(
        artifact_id=current.artifact_id,
        kind=current.kind,
        scope_id=current.scope_id,
        observed_at=current.observed_at,
        payload_sha256=canonical_artifact_sha256(tampered_payload),
        payload=tampered_payload,
    )
    replaced = tuple(
        tampered if item.artifact_id == current.artifact_id else item for item in artifacts
    )
    with pytest.raises(ControlTowerIntegrityError, match="materiality disagrees"):
        _reader(tmp_path, replaced).exceptions(SCOPE_A)


def test_exception_queue_rejects_orphan_disposition_without_case_observation(
    tmp_path: Path,
) -> None:
    artifacts = _base_artifacts()
    orphan = _artifact(
        ArtifactKind.CASE_DISPOSITION,
        "disp_orphan_case",
        SCOPE_A,
        {
            "case_id": "case_missing_orphan",
            "sequence": 1,
            "actor_id": "operator-9",
            "occurred_at": (NOW - timedelta(minutes=10)).isoformat(),
            "kind": "acknowledge",
            "owner": None,
            "note": None,
        },
        observed_at=NOW - timedelta(minutes=10),
    )
    with pytest.raises(ControlTowerIntegrityError, match="disposition has no case observation"):
        _reader(tmp_path, (*artifacts, orphan)).exceptions(SCOPE_A)


def test_exception_queue_rejects_closed_case_transition_without_explicit_reopen(
    tmp_path: Path,
) -> None:
    artifacts = _base_artifacts()
    close = _artifact(
        ArtifactKind.CASE_DISPOSITION,
        "disp_ui_3_close",
        SCOPE_A,
        {
            "case_id": "case_ui_break",
            "sequence": 3,
            "actor_id": "operator-7",
            "occurred_at": (NOW - timedelta(minutes=50)).isoformat(),
            "kind": "close",
            "owner": None,
            "note": None,
        },
        observed_at=NOW - timedelta(minutes=50),
    )
    illegal_ack = _artifact(
        ArtifactKind.CASE_DISPOSITION,
        "disp_ui_4_illegal_ack",
        SCOPE_A,
        {
            "case_id": "case_ui_break",
            "sequence": 4,
            "actor_id": "operator-8",
            "occurred_at": (NOW - timedelta(minutes=40)).isoformat(),
            "kind": "acknowledge",
            "owner": None,
            "note": None,
        },
        observed_at=NOW - timedelta(minutes=40),
    )
    with pytest.raises(ControlTowerIntegrityError, match="explicit reopen"):
        _reader(tmp_path, (*artifacts, close, illegal_ack)).exceptions(SCOPE_A)


def test_exception_queue_rejects_case_observation_economic_identity_drift(tmp_path: Path) -> None:
    artifacts = _base_artifacts()
    latest = next(item for item in artifacts if item.artifact_id == "caseobs_ui_latest")
    drifted_payload = dict(latest.payload)
    drifted_payload["tracking_key"] = "track_other_economics"
    drifted = StoredArtifact(
        artifact_id=latest.artifact_id,
        kind=ArtifactKind.CASE_OBSERVATION,
        scope_id=SCOPE_A,
        observed_at=latest.observed_at,
        payload_sha256=canonical_artifact_sha256(drifted_payload),
        payload=drifted_payload,
    )
    replaced = tuple(
        drifted if item.artifact_id == latest.artifact_id else item for item in artifacts
    )
    with pytest.raises(ControlTowerIntegrityError, match="economic identity"):
        _reader(tmp_path, replaced).exceptions(SCOPE_A)


def test_exception_queue_rejects_ambiguous_case_supersession_chronology(tmp_path: Path) -> None:
    artifacts = _base_artifacts()
    latest = next(item for item in artifacts if item.artifact_id == "caseobs_ui_latest")
    competing_payload = dict(latest.payload)
    competing_payload["id"] = "caseobs_competing_case"
    competing_payload["case_id"] = "case_competing_identity"
    competing_payload["tracking_key"] = "track_competing_identity"
    competing = StoredArtifact(
        artifact_id="caseobs_competing_case",
        kind=ArtifactKind.CASE_OBSERVATION,
        scope_id=SCOPE_A,
        observed_at=latest.observed_at,
        payload_sha256=canonical_artifact_sha256(competing_payload),
        payload=competing_payload,
    )
    with pytest.raises(ControlTowerIntegrityError, match="supersession chronology"):
        _reader(tmp_path, (*artifacts, competing)).exceptions(SCOPE_A)


def test_exception_queue_rejects_disposition_before_case_first_seen(tmp_path: Path) -> None:
    artifacts = tuple(
        item for item in _base_artifacts() if item.kind is not ArtifactKind.CASE_DISPOSITION
    )
    early = _artifact(
        ArtifactKind.CASE_DISPOSITION,
        "disp_ui_early",
        SCOPE_A,
        {
            "case_id": "case_ui_break",
            "sequence": 1,
            "actor_id": "operator-7",
            "occurred_at": (NOW - timedelta(hours=5)).isoformat(),
            "kind": "acknowledge",
            "owner": None,
            "note": None,
        },
        observed_at=NOW - timedelta(hours=5),
    )
    with pytest.raises(ControlTowerIntegrityError, match="predates case"):
        _reader(tmp_path, (*artifacts, early)).exceptions(SCOPE_A)


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


def test_case_file_rejects_investigation_citation_outside_bound_proof(tmp_path: Path) -> None:
    artifacts = tuple(
        item for item in _base_artifacts() if item.kind is not ArtifactKind.INVESTIGATION_RESULT
    )
    invalid = _artifact(
        ArtifactKind.INVESTIGATION_RESULT,
        "invest_foreign_citation",
        SCOPE_A,
        {
            "case_id": "case_ui_break",
            "observation_id": "caseobs_ui_latest",
            "proof_version_id": "proofv_ui_break",
            "status": "validated",
            "next_action": "REQUEST_SOURCE",
            "hypothesis": "Foreign evidence citation",
            "citations": ["src_foreign_not_in_proof"],
            "request_source_kind": "bank",
            "rejection_reason": None,
            "as_of": (NOW - timedelta(minutes=20)).isoformat(),
            "trace": [],
        },
        observed_at=NOW - timedelta(minutes=20),
    )
    with pytest.raises(ControlTowerIntegrityError, match="outside bound proof"):
        _reader(tmp_path, (*artifacts, invalid)).case_file(SCOPE_A, "case_ui_break")


def test_case_file_rejects_investigation_that_predates_bound_observation(tmp_path: Path) -> None:
    artifacts = tuple(
        item for item in _base_artifacts() if item.kind is not ArtifactKind.INVESTIGATION_RESULT
    )
    invalid = _artifact(
        ArtifactKind.INVESTIGATION_RESULT,
        "invest_before_observation",
        SCOPE_A,
        {
            "case_id": "case_ui_break",
            "observation_id": "caseobs_ui_latest",
            "proof_version_id": "proofv_ui_break",
            "status": "validated",
            "next_action": "REQUEST_SOURCE",
            "hypothesis": "Premature investigation",
            "citations": ["src_bank_setl_ui_break"],
            "request_source_kind": "bank",
            "rejection_reason": None,
            "as_of": (NOW - timedelta(hours=2)).isoformat(),
            "trace": [],
        },
        observed_at=NOW - timedelta(hours=2),
    )
    with pytest.raises(ControlTowerIntegrityError, match="predates its bound observation"):
        _reader(tmp_path, (*artifacts, invalid)).case_file(SCOPE_A, "case_ui_break")


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


def test_fastapi_readiness_is_fail_closed_without_probe_and_hides_probe_errors(
    tmp_path: Path,
) -> None:
    from fastapi.testclient import TestClient

    from reflow.control_tower_api import create_control_tower_app

    no_probe = TestClient(create_control_tower_app(_reader(tmp_path)))
    response = no_probe.get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "dependency": "postgresql"}
    assert no_probe.get("/api/v1/health").status_code == 200

    calls = 0

    def ready_probe() -> None:
        nonlocal calls
        calls += 1

    ready = TestClient(create_control_tower_app(_reader(tmp_path), readiness_probe=ready_probe))
    response = ready.get("/api/v1/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "dependency": "postgresql"}
    assert calls == 1

    def failed_probe() -> None:
        raise RuntimeError("postgresql://secret-user:secret-pass@example.invalid/private")

    failed = TestClient(create_control_tower_app(_reader(tmp_path), readiness_probe=failed_probe))
    response = failed.get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "dependency": "postgresql"}
    assert "secret-pass" not in response.text


def test_fastapi_access_boundary_authenticates_and_authorizes_exact_scope(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from reflow.access_auth import (
        AccessAuthBoundary,
        AccessAuthenticationError,
        AuthenticatedPrincipal,
        AuthorizationPolicy,
    )
    from reflow.control_tower_api import create_control_tower_app
    from reflow.operator_audit import OperatorAccessAudit

    class StubVerifier:
        def verify(self, token: str) -> AuthenticatedPrincipal:
            if token == "viewer-token":
                return AuthenticatedPrincipal(subject="sub-viewer", email="viewer@example.com")
            if token == "reviewer-token":
                return AuthenticatedPrincipal(subject="sub-reviewer", email="reviewer@example.com")
            raise AccessAuthenticationError("sensitive-token-detail")

    policy = AuthorizationPolicy.from_mapping(
        {
            "schema_version": 1,
            "principals": [
                {
                    "email": "viewer@example.com",
                    "roles": ["scope_viewer"],
                    "scopes": [str(SCOPE_A)],
                },
                {
                    "email": "reviewer@example.com",
                    "roles": ["scope_viewer", "evaluation_reviewer"],
                    "scopes": [str(SCOPE_A)],
                },
            ],
        }
    )
    boundary = AccessAuthBoundary(verifier=StubVerifier(), policy=policy)  # type: ignore[arg-type]
    source = Path("data/eval/gate17/scale-50-clean.json")
    (tmp_path / source.name).write_text(source.read_text())
    records: list[OperatorAccessAudit] = []
    telemetry: list[dict[str, object]] = []

    class StubAudit:
        def record_access(
            self,
            *,
            occurred_at,
            request_id,
            principal_subject_sha256,
            action,
            scope_id,
            decision,
        ):
            event = OperatorAccessAudit(
                audit_id=len(records) + 1,
                occurred_at=occurred_at,
                request_id=request_id,
                principal_subject_sha256=principal_subject_sha256,
                action=action,
                scope_id=scope_id,
                decision=decision,
            )
            records.append(event)
            return event

    client = TestClient(
        create_control_tower_app(
            _reader(tmp_path),
            auth_boundary=boundary,
            operator_audit=StubAudit(),  # type: ignore[arg-type]
            event_sink=telemetry.append,
        )
    )

    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/ready").status_code == 503
    assert client.get(f"/api/v1/scopes/{SCOPE_A}/overview").status_code == 401
    assert client.get("/api/v1/scopes/not-a-scope/overview").status_code == 401
    bad = client.get(
        f"/api/v1/scopes/{SCOPE_A}/overview",
        headers={"Cf-Access-Jwt-Assertion": "bad-token"},
    )
    assert bad.status_code == 401
    assert bad.json() == {"detail": "authentication required"}
    assert "sensitive-token-detail" not in bad.text

    viewer_headers = {"Cf-Access-Jwt-Assertion": "viewer-token"}
    assert (
        client.get("/api/v1/scopes/not-a-scope/overview", headers=viewer_headers).status_code == 422
    )
    allowed = client.get(f"/api/v1/scopes/{SCOPE_A}/overview", headers=viewer_headers)
    denied = client.get(f"/api/v1/scopes/{SCOPE_B}/overview", headers=viewer_headers)
    cursor_probe = client.get(
        f"/api/v1/scopes/{SCOPE_B}/proofs/page",
        params={"cursor": "not-a-valid-cursor"},
        headers=viewer_headers,
    )
    assert allowed.status_code == 200
    assert denied.status_code == 403
    assert cursor_probe.status_code == 403
    evaluation_denied = client.get("/api/v1/evaluation", headers=viewer_headers)
    assert evaluation_denied.status_code == 403

    reviewer_headers = {"Cf-Access-Jwt-Assertion": "reviewer-token"}
    evaluation_allowed = client.get("/api/v1/evaluation", headers=reviewer_headers)
    assert evaluation_allowed.status_code == 200

    assert len(records) == 5
    assert records[0].request_id == allowed.headers["x-request-id"]
    assert records[0].scope_id == SCOPE_A
    assert records[0].decision.value == "allowed"
    assert records[1].request_id == denied.headers["x-request-id"]
    assert records[1].scope_id == SCOPE_B
    assert records[1].decision.value == "denied"
    assert records[2].request_id == cursor_probe.headers["x-request-id"]
    assert records[2].scope_id == SCOPE_B
    assert records[2].decision.value == "denied"
    assert records[3].request_id == evaluation_denied.headers["x-request-id"]
    assert records[3].scope_id is None
    assert records[3].decision.value == "denied"
    assert records[4].request_id == evaluation_allowed.headers["x-request-id"]
    assert records[4].decision.value == "allowed"
    assert all(len(item.principal_subject_sha256) == 64 for item in records)
    serialized = repr(records) + repr(telemetry)
    assert "viewer@example.com" not in serialized
    assert "reviewer@example.com" not in serialized
    assert "viewer-token" not in serialized
    assert "reviewer-token" not in serialized


def test_fastapi_authenticated_access_requires_durable_operator_audit(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from reflow.access_auth import (
        AccessAuthBoundary,
        AuthenticatedPrincipal,
        AuthorizationPolicy,
    )
    from reflow.control_tower_api import create_control_tower_app

    class StubVerifier:
        def verify(self, _token: str) -> AuthenticatedPrincipal:
            return AuthenticatedPrincipal(
                subject="sub-audit-failure",
                email="viewer@example.com",
            )

    policy = AuthorizationPolicy.from_mapping(
        {
            "schema_version": 1,
            "principals": [
                {
                    "email": "viewer@example.com",
                    "roles": ["scope_viewer"],
                    "scopes": [str(SCOPE_A)],
                }
            ],
        }
    )
    boundary = AccessAuthBoundary(verifier=StubVerifier(), policy=policy)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="requires operator audit persistence"):
        create_control_tower_app(_reader(tmp_path), auth_boundary=boundary)

    class FailingAudit:
        def record_access(self, **_kwargs):
            raise RuntimeError("postgresql://secret-user:secret-pass@example.invalid/private")

    telemetry: list[dict[str, object]] = []
    client = TestClient(
        create_control_tower_app(
            _reader(tmp_path),
            auth_boundary=boundary,
            operator_audit=FailingAudit(),  # type: ignore[arg-type]
            event_sink=telemetry.append,
        )
    )
    response = client.get(
        f"/api/v1/scopes/{SCOPE_A}/overview",
        headers={"Cf-Access-Jwt-Assertion": "viewer-token"},
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "operator audit unavailable"}
    assert "secret-pass" not in response.text
    assert any(
        event.get("event.name") == "reflow.operator.audit.persistence_failure"
        for event in telemetry
    )
    assert "secret-pass" not in repr(telemetry)


def test_fastapi_proof_case_source_and_evaluation_routes(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from reflow.control_tower_api import create_control_tower_app

    source = Path("data/eval/gate17/scale-50-clean.json")
    (tmp_path / source.name).write_text(source.read_text())
    client = TestClient(create_control_tower_app(_reader(tmp_path)))

    assert client.get(f"/api/v1/scopes/{SCOPE_A}/proofs").status_code == 200
    proof_page = client.get(f"/api/v1/scopes/{SCOPE_A}/proofs/page?limit=1")
    assert proof_page.status_code == 200
    assert len(proof_page.json()["items"]) == 1
    assert proof_page.json()["next_cursor"]
    next_proof_page = client.get(
        f"/api/v1/scopes/{SCOPE_A}/proofs/page",
        params={"limit": 1, "cursor": proof_page.json()["next_cursor"]},
    )
    assert next_proof_page.status_code == 200
    assert len(next_proof_page.json()["items"]) == 1
    assert next_proof_page.json()["next_cursor"] is None
    bad_cursor = client.get(
        f"/api/v1/scopes/{SCOPE_A}/proofs/page",
        params={"cursor": "not-a-valid-cursor"},
    )
    assert bad_cursor.status_code == 400
    assert bad_cursor.json()["error"] == "invalid_collection_cursor"

    proof = client.get(f"/api/v1/scopes/{SCOPE_A}/proofs/proofv_ui_break")
    assert proof.status_code == 200
    assert proof.json()["composition"]["residual"]["amount_paise"] == "500"

    queue = client.get(f"/api/v1/scopes/{SCOPE_A}/exceptions")
    assert queue.status_code == 200
    assert queue.json()[0]["workflow_status"] == "awaiting_source"
    queue_page = client.get(f"/api/v1/scopes/{SCOPE_A}/exceptions/page?limit=1")
    assert queue_page.status_code == 200
    assert queue_page.json()["items"][0]["workflow_status"] == "awaiting_source"

    case = client.get(f"/api/v1/scopes/{SCOPE_A}/cases/case_ui_break")
    assert case.status_code == 200
    assert case.json()["investigation"]["next_action"] == "REQUEST_SOURCE"

    sources = client.get(f"/api/v1/scopes/{SCOPE_A}/sources")
    assert sources.status_code == 200
    assert {item["source_kind"] for item in sources.json()} == {"bank", "razorpay_recon"}
    source_page = client.get(f"/api/v1/scopes/{SCOPE_A}/sources/page?limit=1")
    assert source_page.status_code == 200
    assert len(source_page.json()["items"]) == 1
    assert source_page.json()["next_cursor"]

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


def test_fastapi_can_serve_built_spa_without_changing_api_authority(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from reflow.control_tower_api import create_control_tower_app

    web_dist = tmp_path / "dist"
    web_dist.mkdir()
    (web_dist / "index.html").write_text("<html><body>ReFlow Control Tower</body></html>")
    client = TestClient(create_control_tower_app(_reader(tmp_path), web_dist=web_dist))
    root = client.get("/")
    assert root.status_code == 200
    assert "ReFlow Control Tower" in root.text
    client_route = client.get("/exceptions?scope=scope_ui")
    assert client_route.status_code == 200
    assert "ReFlow Control Tower" in client_route.text
    assert client.get("/api/v1/health").json()["mode"] == "read_only"
    assert client.get("/api/v1/not-a-route").status_code == 404


def test_fastapi_serializes_raw_paise_as_exact_decimal_string(tmp_path: Path) -> None:
    from dataclasses import dataclass

    from fastapi.testclient import TestClient

    from reflow.control_tower import MoneyView, _money
    from reflow.control_tower_api import create_control_tower_app

    maximum = 2**63 - 1

    @dataclass(frozen=True)
    class ExactMoneyResponse:
        amount: MoneyView

    class ExactMoneyReader:
        def overview(self, _scope_id):
            return ExactMoneyResponse(
                _money(
                    {"amount_paise": maximum, "currency": "INR"},
                    "third-audit exact money",
                )
            )

    response = TestClient(create_control_tower_app(ExactMoneyReader())).get(
        f"/api/v1/scopes/{SCOPE_A}/overview"
    )
    assert response.status_code == 200
    assert response.json()["amount"]["amount_paise"] == str(maximum)


def test_fastapi_raw_double_slash_api_path_cannot_fall_back_to_spa(tmp_path: Path) -> None:
    from reflow.control_tower_api import create_control_tower_app

    web_dist = tmp_path / "dist"
    web_dist.mkdir()
    (web_dist / "index.html").write_text("<html><body>ReFlow Control Tower</body></html>")
    app = create_control_tower_app(_reader(tmp_path), web_dist=web_dist)
    sent: list[dict[str, object]] = []
    delivered = False

    async def receive() -> dict[str, object]:
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "//api/v1/not-a-route",
        "raw_path": b"//api/v1/not-a-route",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }
    asyncio.run(app(scope, receive, send))
    start = next(item for item in sent if item.get("type") == "http.response.start")
    assert start["status"] == 404
    body = b"".join(
        item.get("body", b"")
        for item in sent
        if item.get("type") == "http.response.body" and isinstance(item.get("body", b""), bytes)
    )
    assert b"ReFlow Control Tower" not in body


def test_exception_queue_rejects_low_level_orphan_observation(tmp_path: Path) -> None:
    artifacts = _base_artifacts()
    template = next(item for item in artifacts if item.artifact_id == "caseobs_ui_latest")
    orphan = _artifact(
        ArtifactKind.CASE_OBSERVATION,
        "caseobs_orphan_low_level",
        SCOPE_A,
        {
            **{key: value for key, value in template.payload.items() if key != "id"},
            "id": "caseobs_orphan_low_level",
            "case_id": "case_orphan_low_level",
            "tracking_key": "track_orphan_low_level",
            "run_id": "run_missing_orphan",
            "settlement_id": "setl_orphan_low_level",
        },
    )
    reader = _reader(tmp_path, (*artifacts, orphan))
    with pytest.raises(ControlTowerIntegrityError, match="references missing reconciliation_run"):
        reader.exceptions(SCOPE_A)


def test_fastapi_case_workflow_write_is_auth_first_scope_bound_and_body_bounded(
    tmp_path: Path,
) -> None:
    from fastapi.testclient import TestClient

    from reflow.access_auth import (
        AccessAuthBoundary,
        AccessAuthenticationError,
        AuthenticatedPrincipal,
        AuthorizationPolicy,
    )
    from reflow.control_tower_api import create_control_tower_app
    from reflow.operator_audit import OperatorAccessAudit, OperatorAuditAction
    from reflow.operator_workflow import CaseDispositionCommandResult

    class StubVerifier:
        def verify(self, token: str) -> AuthenticatedPrincipal:
            if token == "viewer-token":
                return AuthenticatedPrincipal(subject="sub-viewer", email="viewer@example.com")
            if token == "operator-token":
                return AuthenticatedPrincipal(subject="sub-operator", email="operator@example.com")
            raise AccessAuthenticationError("private verifier detail")

    policy = AuthorizationPolicy.from_mapping(
        {
            "schema_version": 1,
            "principals": [
                {
                    "email": "viewer@example.com",
                    "roles": ["scope_viewer"],
                    "scopes": [str(SCOPE_A)],
                },
                {
                    "email": "operator@example.com",
                    "roles": ["scope_viewer", "case_operator"],
                    "scopes": [str(SCOPE_A)],
                },
            ],
        }
    )
    boundary = AccessAuthBoundary(verifier=StubVerifier(), policy=policy)  # type: ignore[arg-type]
    records: list[OperatorAccessAudit] = []

    class StubAudit:
        def record_access(
            self,
            *,
            occurred_at,
            request_id,
            principal_subject_sha256,
            action,
            scope_id,
            decision,
        ):
            event = OperatorAccessAudit(
                audit_id=len(records) + 1,
                occurred_at=occurred_at,
                request_id=request_id,
                principal_subject_sha256=principal_subject_sha256,
                action=action,
                scope_id=scope_id,
                decision=decision,
            )
            records.append(event)
            return event

    calls: list[dict[str, object]] = []

    class StubWorkflow:
        def append_disposition(self, **kwargs):
            calls.append(kwargs)
            return CaseDispositionCommandResult(
                disposition_id="disp_gate52_http",
                case_id=str(kwargs["case_id"]),
                sequence=int(kwargs["expected_generation"]) + 1,
                committed_generation=int(kwargs["expected_generation"]) + 1,
                replayed=False,
                occurred_at="2026-09-04T08:30:00+00:00",
                kind=str(kwargs["kind"].value),
                owner=kwargs["owner"],
                note=kwargs["note"],
            )

    with pytest.raises(RuntimeError, match="require authenticated"):
        create_control_tower_app(
            _reader(tmp_path), case_workflow=StubWorkflow()  # type: ignore[arg-type]
        )

    client = TestClient(
        create_control_tower_app(
            _reader(tmp_path),
            auth_boundary=boundary,
            operator_audit=StubAudit(),  # type: ignore[arg-type]
            case_workflow=StubWorkflow(),  # type: ignore[arg-type]
        )
    )
    path = f"/api/v1/scopes/{SCOPE_A}/cases/case_gate52_http/dispositions"
    malformed = b"{not-json"
    assert client.post(path, content=malformed).status_code == 401
    assert (
        client.post(
            path,
            content=malformed,
            headers={"Cf-Access-Jwt-Assertion": "viewer-token"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/scopes/{SCOPE_B}/cases/case_gate52_http/dispositions",
            content=malformed,
            headers={"Cf-Access-Jwt-Assertion": "operator-token"},
        ).status_code
        == 403
    )

    operator_headers = {
        "Cf-Access-Jwt-Assertion": "operator-token",
        "Idempotency-Key": "gate52-http-command-1",
        "Content-Type": "application/json",
    }
    assert client.post(path, content=malformed, headers=operator_headers).status_code == 422
    oversized = b"{" + b" " * 9000 + b"}"
    assert client.post(path, content=oversized, headers=operator_headers).status_code == 413
    missing_key = client.post(
        path,
        json={"expected_generation": 0, "kind": "acknowledge"},
        headers={"Cf-Access-Jwt-Assertion": "operator-token"},
    )
    assert missing_key.status_code == 422
    assert missing_key.json()["detail"] == "Idempotency-Key is required"

    response = client.post(
        path,
        json={
            "expected_generation": 0,
            "kind": "assign_owner",
            "owner": "finance-team",
            "note": "triaged",
        },
        headers=operator_headers,
    )
    assert response.status_code == 200
    assert response.json()["disposition_id"] == "disp_gate52_http"
    assert response.json()["committed_generation"] == 1
    assert len(calls) == 1
    assert calls[0]["principal_subject"] == "sub-operator"
    assert calls[0]["scope_id"] == SCOPE_A
    assert calls[0]["idempotency_key"] == "gate52-http-command-1"
    assert calls[0]["owner"] == "finance-team"
    assert all(
        item.action is OperatorAuditAction.APPEND_CASE_DISPOSITION for item in records
    )
    assert records[0].decision.value == "denied"
    assert records[1].decision.value == "denied"
    assert records[-1].decision.value == "allowed"
    assert all("@" not in item.principal_subject_sha256 for item in records)


def test_fastapi_case_workflow_route_is_absent_when_writes_are_disabled(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from reflow.access_auth import AccessAuthBoundary, AuthenticatedPrincipal, AuthorizationPolicy
    from reflow.control_tower_api import create_control_tower_app
    from reflow.operator_audit import OperatorAccessAudit

    class StubVerifier:
        def verify(self, _token: str) -> AuthenticatedPrincipal:
            return AuthenticatedPrincipal(subject="sub", email="operator@example.com")

    policy = AuthorizationPolicy.from_mapping(
        {
            "schema_version": 1,
            "principals": [
                {
                    "email": "operator@example.com",
                    "roles": ["scope_viewer", "case_operator"],
                    "scopes": [str(SCOPE_A)],
                }
            ],
        }
    )
    boundary = AccessAuthBoundary(verifier=StubVerifier(), policy=policy)  # type: ignore[arg-type]

    class StubAudit:
        def record_access(self, **kwargs):
            return OperatorAccessAudit(audit_id=1, **kwargs)

    client = TestClient(
        create_control_tower_app(
            _reader(tmp_path),
            auth_boundary=boundary,
            operator_audit=StubAudit(),  # type: ignore[arg-type]
        )
    )
    response = client.post(
        f"/api/v1/scopes/{SCOPE_A}/cases/case_disabled/dispositions",
        json={"expected_generation": 0, "kind": "acknowledge"},
        headers={
            "Cf-Access-Jwt-Assertion": "token",
            "Idempotency-Key": "gate52-disabled",
        },
    )
    assert response.status_code == 404
