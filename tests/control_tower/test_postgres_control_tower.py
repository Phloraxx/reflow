from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from reflow import domain
from reflow.control_tower import ControlTowerReader
from reflow.persistence import (
    ArtifactKind,
    PointerKind,
    PostgresApplicationStore,
    ReflowApplicationService,
    canonical_artifact_json,
)

DSN = os.getenv("REFLOW_TEST_POSTGRES_DSN")
NOW = datetime(2026, 9, 1, 18, 0, tzinfo=UTC)
SCOPE = domain.ReconciliationScopeId("scope_gate18_postgres")


def _require_dsn() -> str:
    if not DSN:
        pytest.skip("REFLOW_TEST_POSTGRES_DSN is not configured")
    return DSN


def _money(amount: int) -> dict[str, object]:
    return {"amount_paise": amount, "currency": "INR"}


def test_control_tower_reads_scoped_overview_through_real_postgres(tmp_path: Path) -> None:
    store = PostgresApplicationStore(_require_dsn())
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(_require_dsn()) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            TRUNCATE reflow_current_pointers,
                     reflow_artifacts,
                     reflow_source_identity,
                     reflow_source_envelopes
            """
        )

    service = ReflowApplicationService(store)
    policy_id = "policy_gate18_pg"
    manifest_id = "manifest_gate18_pg"
    proof_id = "proofv_gate18_pg"
    close_id = "close_gate18_pg"
    coverage_id = "coverage_gate18_pg"
    balance_id = "balance_gate18_pg"
    run_id = "run_gate18_pg"

    store.put_artifact(
        kind=ArtifactKind.POLICY_VERSION,
        artifact_id=policy_id,
        scope_id=None,
        observed_at=None,
        payload={
            "id": policy_id,
            "version_label": "gate18-pg",
            "materiality_thresholds_paise": [10_000, 100_000, 1_000_000],
        },
    )
    store.put_artifact(
        kind=ArtifactKind.SOURCE_DELIVERY_MANIFEST,
        artifact_id=manifest_id,
        scope_id=SCOPE,
        observed_at=NOW,
        payload={
            "id": manifest_id,
            "scope_id": str(SCOPE),
            "source_kind": "bank",
            "delivery_mode": "snapshot",
            "expected_by": NOW.isoformat(),
            "received_at": NOW.isoformat(),
            "watermark_at": NOW.isoformat(),
            "completeness": "complete",
            "received_late": False,
            "delivered_envelope_ids": ["src_gate18_pg"],
            "effective_envelope_ids": ["src_gate18_pg"],
            "adapter_version": "bank-v1",
            "schema_fingerprint": "bank-schema-v1",
        },
    )
    store.put_artifact(
        kind=ArtifactKind.PROOF_VERSION,
        artifact_id=proof_id,
        scope_id=SCOPE,
        observed_at=NOW,
        payload={
            "id": proof_id,
            "settlement_id": "setl_gate18_pg",
            "version": 1,
            "status": "proven_reconciled",
            "composition": {
                "status": "composition_proven",
                "settlement_amount": _money(12_345),
                "observed_composition": _money(12_345),
                "residual": _money(0),
                "component_ids": ["recon_gate18_pg"],
                "source_envelope_ids": ["src_gate18_pg"],
                "reason_codes": [],
            },
            "bank": {
                "status": "bank_receipt_proven",
                "settlement_utr": "UTR-GATE18-PG",
                "expected_amount": _money(12_345),
                "observed_bank_credit": _money(12_345),
                "residual": _money(0),
                "bank_entry_ids": ["bank_gate18_pg"],
                "source_envelope_ids": ["src_gate18_pg"],
                "reason_codes": [],
            },
            "source_envelope_ids": ["src_gate18_pg"],
            "reason_codes": [],
            "knowledge_cutoff": NOW.isoformat(),
            "generated_at": NOW.isoformat(),
            "prior_version_id": None,
            "reopened": False,
        },
    )
    store.put_artifact(
        kind=ArtifactKind.CLOSE_READINESS,
        artifact_id=close_id,
        scope_id=SCOPE,
        observed_at=NOW,
        payload={
            "id": close_id,
            "status": "ready",
            "reason_codes": [],
            "policy_version_id": policy_id,
            "manifest_ids": [manifest_id],
            "proof_version_ids": [proof_id],
            "coverage_certificate_id": coverage_id,
            "balance_control_id": balance_id,
        },
    )
    store.put_artifact(
        kind=ArtifactKind.EVIDENCE_COVERAGE,
        artifact_id=coverage_id,
        scope_id=SCOPE,
        observed_at=NOW,
        payload={
            "id": coverage_id,
            "scope_id": str(SCOPE),
            "status": "complete",
            "manifest_ids": [manifest_id],
            "proof_version_ids": [proof_id],
            "orphan_count": 0,
            "orphan_known_value": _money(0),
        },
    )
    store.put_artifact(
        kind=ArtifactKind.BALANCE_CONTROL,
        artifact_id=balance_id,
        scope_id=SCOPE,
        observed_at=NOW,
        payload={
            "id": balance_id,
            "scope_id": str(SCOPE),
            "policy_version_id": policy_id,
            "status": "proven",
            "residual": _money(0),
        },
    )
    store.put_artifact(
        kind=ArtifactKind.RECONCILIATION_RUN,
        artifact_id=run_id,
        scope_id=SCOPE,
        observed_at=NOW,
        payload={
            "id": run_id,
            "scope_id": str(SCOPE),
            "policy_version_id": policy_id,
            "outcome": "ready",
            "period_start": NOW.replace(hour=0).isoformat(),
            "period_end": NOW.isoformat(),
            "reporting_timezone": "UTC",
            "knowledge_cutoff": NOW.isoformat(),
            "completed_at": NOW.isoformat(),
            "code_build_sha": "gate18-postgres-test",
            "proof_version_ids": [proof_id],
            "source_manifest_ids": [manifest_id],
            "coverage_certificate_id": coverage_id,
            "balance_control_id": balance_id,
            "close_readiness_id": close_id,
        },
    )

    store.advance_pointer(
        kind=PointerKind.LATEST_RUN,
        stream_key=str(SCOPE),
        artifact_id=run_id,
        expected_generation=0,
    )

    reader = ControlTowerReader(service, evaluation_root=tmp_path, now=lambda: NOW)
    overview = reader.overview(SCOPE)
    assert overview.has_current_run
    assert overview.run is not None
    assert overview.run.run_id == run_id
    assert overview.run.close_status == "ready"
    assert overview.proof_status[0].status == "proven_reconciled"
    assert overview.proof_status[0].amount.amount_paise == "12345"

    rebuilt = ReflowApplicationService(PostgresApplicationStore(_require_dsn()))
    assert ControlTowerReader(rebuilt, evaluation_root=tmp_path).overview(SCOPE) == overview



def test_real_postgres_control_tower_traverses_more_than_10000_artifacts(
    tmp_path: Path,
) -> None:
    dsn = _require_dsn()
    psycopg = pytest.importorskip("psycopg")
    store = PostgresApplicationStore(dsn)
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            TRUNCATE reflow_current_pointers,
                     reflow_artifacts,
                     reflow_source_identity,
                     reflow_source_envelopes
            """
        )
        rows = []
        for index in range(10_001):
            artifact_id = f"trace_long_history_{index:05d}"
            rendered = canonical_artifact_json(
                {"id": artifact_id, "scope_id": str(SCOPE)}
            )
            rows.append(
                (
                    artifact_id,
                    ArtifactKind.INVESTIGATION_TRACE.value,
                    str(SCOPE),
                    NOW,
                    hashlib.sha256(rendered.encode()).hexdigest(),
                    rendered,
                )
            )
        cursor.executemany(
            """
            INSERT INTO reflow_artifacts(
                artifact_id, artifact_kind, scope_id, observed_at,
                payload_sha256, payload_json
            ) VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            """,
            rows,
        )

    reader = ControlTowerReader(
        ReflowApplicationService(store),
        evaluation_root=tmp_path,
        now=lambda: NOW,
    )
    artifacts = reader._list(ArtifactKind.INVESTIGATION_TRACE, SCOPE)
    assert len(artifacts) == 10_001
    assert artifacts[0].artifact_id == "trace_long_history_00000"
    assert artifacts[-1].artifact_id == "trace_long_history_10000"

def test_synthetic_control_tower_demo_seed_is_idempotent_and_readable(tmp_path: Path) -> None:
    from reflow.evaluation.control_tower_demo import seed_demo

    first = seed_demo(_require_dsn())
    second = seed_demo(_require_dsn())
    assert second.scope.id == first.scope.id
    assert second.run.id == first.run.id
    assert second.proof.id == first.proof.id

    service = ReflowApplicationService(PostgresApplicationStore(_require_dsn()))
    reader = ControlTowerReader(service, evaluation_root=tmp_path, now=lambda: NOW)
    overview = reader.overview(first.scope.id)
    assert overview.run is not None
    assert overview.run.close_status == "not_ready"
    assert overview.active_exception_count == 1

    queue = reader.exceptions(first.scope.id)
    assert len(queue) == 1
    assert queue[0].financial_status == "pending_bank_credit"
    assert queue[0].materiality_band == "critical"
    assert queue[0].workflow_status == "awaiting_source"
    assert queue[0].source_blockers == ("bank:late",)

    case = reader.case_file(first.scope.id, queue[0].case_id)
    assert case.investigation is not None
    assert case.investigation.status == "validated"
    assert case.investigation.next_action == "REQUEST_SOURCE"
