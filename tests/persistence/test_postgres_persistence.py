from __future__ import annotations

import inspect
import os
from datetime import UTC, datetime, timedelta

import pytest

from reflow import domain
from reflow.control_plane import make_reconciliation_scope
from reflow.ingestion import ObservedBatch, ingest_observed_batch
from reflow.journal import AppendDisposition, JournalConflictError, make_source_envelope
from reflow.persistence import (
    POSTGRES_SCHEMA_VERSION,
    ArtifactKind,
    ArtifactWriteDisposition,
    PersistenceConflictError,
    PersistenceError,
    PersistenceIntegrityError,
    PointerKind,
    PostgresApplicationStore,
    ReflowApplicationService,
    StalePointerError,
)

DSN = os.environ.get("REFLOW_TEST_POSTGRES_DSN")
NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _require_dsn() -> str:
    if not DSN:
        pytest.skip("REFLOW_TEST_POSTGRES_DSN is not configured")
    return DSN


@pytest.fixture
def store():
    dsn = _require_dsn()
    psycopg = pytest.importorskip("psycopg")
    result = PostgresApplicationStore(dsn)
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
                TRUNCATE reflow_current_pointers,
                         reflow_artifacts,
                         reflow_source_identity,
                         reflow_source_envelopes
                """
        )
    return result


def _scope(suffix: str) -> domain.ReconciliationScopeId:
    return make_reconciliation_scope(
        merchant_account_id=f"merchant_{suffix}",
        provider="razorpay",
        provider_account_id=f"rzp_{suffix}",
        bank_account_id=f"bank_{suffix}",
        currency=domain.Currency.INR,
        channel="payments",
    ).id


def _source(record_id: str, *, amount: int = 12345, received_at: datetime = NOW):
    return make_source_envelope(
        source_kind=domain.SourceKind.BANK,
        source_record_id=record_id,
        occurred_at=received_at - timedelta(minutes=1),
        received_at=received_at,
        schema_version="bank-test-v1",
        payload={
            "entry_id": record_id,
            "amount_paise": amount,
            "currency": "INR",
            "narration": "Razorpay settlement",
        },
    )


def test_postgres_schema_migration_is_idempotent_and_versioned(store) -> None:
    store.migrate()
    store.migrate()
    assert store.capabilities().schema_version == POSTGRES_SCHEMA_VERSION


def test_postgres_journal_matches_append_duplicate_and_conflict_semantics(store) -> None:
    first = _source("bank_pg_conflict")
    assert store.append(first).disposition is AppendDisposition.STORED
    replay = store.append(first)
    assert replay.disposition is AppendDisposition.DUPLICATE
    assert replay.envelope == first

    conflict = _source("bank_pg_conflict", amount=54321)
    with pytest.raises(JournalConflictError, match="different payload hash"):
        store.append(conflict)

    assert len(store) == 2
    assert store.get(domain.SourceKind.BANK, "bank_pg_conflict") == first
    assert store.get_by_id(conflict.id) == conflict


def test_postgres_journal_survives_store_reconstruction_and_orders_entries(store) -> None:
    later = _source("bank_later", received_at=NOW + timedelta(minutes=2))
    earlier = _source("bank_earlier", received_at=NOW)
    store.append(later)
    store.append(earlier)

    rebuilt = PostgresApplicationStore(_require_dsn())
    assert rebuilt.get_by_id(earlier.id) == earlier
    assert rebuilt.get(domain.SourceKind.BANK, "bank_later") == later
    assert rebuilt.entries() == (earlier, later)


def test_existing_ingestion_path_accepts_postgres_journal_contract(store) -> None:
    observed = ObservedBatch(
        merchant_rows=(
            {
                "order_id": "order_pg_ingestion",
                "amount_paise": 2500,
                "currency": "INR",
                "created_at": NOW.isoformat(),
                "external_reference": "pg-ingestion",
            },
        ),
        razorpay_events=(),
        recon_rows=(),
        settlement_rows=(),
        bank_rows=(),
    )
    batch = ingest_observed_batch(observed, store, received_at=NOW + timedelta(seconds=1))
    assert len(batch.orders) == 1
    assert len(batch.source_links) == 1
    assert len(store) == 1
    assert store.get_by_id(batch.source_links[0].envelope_id) is not None


def test_artifact_write_is_immutable_idempotent_and_restart_safe(store) -> None:
    scope_id = _scope("artifact")
    payload = {"proof_version_id": "proofv_pg_artifact", "status": "residual"}
    first = store.put_artifact(
        kind=ArtifactKind.PROOF_VERSION,
        artifact_id="proofv_pg_artifact",
        payload=payload,
        scope_id=scope_id,
        observed_at=NOW,
    )
    assert first.disposition is ArtifactWriteDisposition.STORED
    replay = store.put_artifact(
        kind=ArtifactKind.PROOF_VERSION,
        artifact_id="proofv_pg_artifact",
        payload=payload,
        scope_id=scope_id,
        observed_at=NOW,
    )
    assert replay.disposition is ArtifactWriteDisposition.DUPLICATE
    assert replay.artifact == first.artifact

    with pytest.raises(PersistenceConflictError, match="different immutable content"):
        store.put_artifact(
            kind=ArtifactKind.PROOF_VERSION,
            artifact_id="proofv_pg_artifact",
            payload={"proof_version_id": "proofv_pg_artifact", "status": "proven_reconciled"},
            scope_id=scope_id,
            observed_at=NOW,
        )

    rebuilt = PostgresApplicationStore(_require_dsn())
    assert rebuilt.get_artifact("proofv_pg_artifact") == first.artifact


def test_artifact_queries_are_explicitly_scope_filtered(store) -> None:
    scope_a = _scope("a")
    scope_b = _scope("b")
    store.put_artifact(
        kind=ArtifactKind.RECONCILIATION_RUN,
        artifact_id="run_scope_a",
        payload={"run_id": "run_scope_a"},
        scope_id=scope_a,
        observed_at=NOW,
    )
    store.put_artifact(
        kind=ArtifactKind.RECONCILIATION_RUN,
        artifact_id="run_scope_b",
        payload={"run_id": "run_scope_b"},
        scope_id=scope_b,
        observed_at=NOW,
    )
    assert tuple(
        item.artifact_id
        for item in store.list_artifacts(kind=ArtifactKind.RECONCILIATION_RUN, scope_id=scope_a)
    ) == ("run_scope_a",)
    assert tuple(
        item.artifact_id
        for item in store.list_artifacts(kind=ArtifactKind.RECONCILIATION_RUN, scope_id=scope_b)
    ) == ("run_scope_b",)


def test_artifact_payload_tampering_is_detected_on_read(store) -> None:
    psycopg = pytest.importorskip("psycopg")
    scope_id = _scope("tamper")
    store.put_artifact(
        kind=ArtifactKind.PROOF_VERSION,
        artifact_id="proofv_pg_tamper",
        payload={"status": "residual"},
        scope_id=scope_id,
        observed_at=NOW,
    )
    with psycopg.connect(_require_dsn()) as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE reflow_artifacts SET payload_json = %s::jsonb WHERE artifact_id = %s",
            ('{"status":"proven_reconciled"}', "proofv_pg_tamper"),
        )
    with pytest.raises(PersistenceIntegrityError, match="digest"):
        store.get_artifact("proofv_pg_tamper")


def test_current_pointer_compare_and_swap_is_idempotent_and_stale_safe(store) -> None:
    scope_id = _scope("pointer")
    for artifact_id in ("proofv_pg_pointer_1", "proofv_pg_pointer_2"):
        store.put_artifact(
            kind=ArtifactKind.PROOF_VERSION,
            artifact_id=artifact_id,
            payload={"proof_version_id": artifact_id},
            scope_id=scope_id,
            observed_at=NOW,
        )
    first = store.advance_pointer(
        kind=PointerKind.LATEST_PROOF,
        stream_key="setl_pg_pointer",
        artifact_id="proofv_pg_pointer_1",
        expected_generation=0,
    )
    assert first.generation == 1
    replay = store.advance_pointer(
        kind=PointerKind.LATEST_PROOF,
        stream_key="setl_pg_pointer",
        artifact_id="proofv_pg_pointer_1",
        expected_generation=0,
    )
    assert replay == first

    with pytest.raises(StalePointerError, match="generation"):
        store.advance_pointer(
            kind=PointerKind.LATEST_PROOF,
            stream_key="setl_pg_pointer",
            artifact_id="proofv_pg_pointer_2",
            expected_generation=0,
        )
    assert store.get_pointer(kind=PointerKind.LATEST_PROOF, stream_key="setl_pg_pointer") == first

    second = store.advance_pointer(
        kind=PointerKind.LATEST_PROOF,
        stream_key="setl_pg_pointer",
        artifact_id="proofv_pg_pointer_2",
        expected_generation=1,
    )
    assert second.generation == 2
    assert second.artifact_id == "proofv_pg_pointer_2"


def test_pointer_cannot_reference_missing_or_wrong_kind_artifact(store) -> None:
    with pytest.raises(PersistenceError, match="missing artifact"):
        store.advance_pointer(
            kind=PointerKind.LATEST_PROOF,
            stream_key="setl_missing",
            artifact_id="proofv_missing_pg",
            expected_generation=0,
        )
    store.put_artifact(
        kind=ArtifactKind.RECONCILIATION_RUN,
        artifact_id="run_wrong_pointer_kind",
        payload={"run_id": "run_wrong_pointer_kind"},
        scope_id=_scope("wrongkind"),
        observed_at=NOW,
    )
    with pytest.raises(PersistenceError, match="requires proof_version"):
        store.advance_pointer(
            kind=PointerKind.LATEST_PROOF,
            stream_key="setl_wrong_kind",
            artifact_id="run_wrong_pointer_kind",
            expected_generation=0,
        )


def test_atomic_artifact_pointer_publish_rolls_back_new_artifact_on_stale_cas(store) -> None:
    scope_id = _scope("atomic")
    _, first_pointer = store.publish_artifact_and_pointer(
        artifact_kind=ArtifactKind.PROOF_VERSION,
        artifact_id="proofv_atomic_1",
        payload={"version": 1},
        scope_id=scope_id,
        observed_at=NOW,
        pointer_kind=PointerKind.LATEST_PROOF,
        stream_key="setl_atomic",
        expected_generation=0,
    )
    assert first_pointer.generation == 1

    with pytest.raises(StalePointerError):
        store.publish_artifact_and_pointer(
            artifact_kind=ArtifactKind.PROOF_VERSION,
            artifact_id="proofv_atomic_2",
            payload={"version": 2},
            scope_id=scope_id,
            observed_at=NOW + timedelta(seconds=1),
            pointer_kind=PointerKind.LATEST_PROOF,
            stream_key="setl_atomic",
            expected_generation=0,
        )
    assert store.get_artifact("proofv_atomic_2") is None
    assert (
        store.get_pointer(kind=PointerKind.LATEST_PROOF, stream_key="setl_atomic") == first_pointer
    )


def test_application_service_is_read_store_publish_only(store) -> None:
    service = ReflowApplicationService(store)
    capabilities = service.capabilities()
    assert capabilities.database == "postgresql"
    assert capabilities.raw_evidence_append_only
    assert capabilities.immutable_artifacts
    assert capabilities.optimistic_current_pointers
    assert not capabilities.generic_sql_exposed
    assert not capabilities.financial_truth_mutation

    public = {name for name in dir(ReflowApplicationService) if not name.startswith("_")}
    forbidden = {
        "execute",
        "mark_reconciled",
        "append_disposition",
        "approve_adapter",
        "refund",
        "payout",
        "transfer",
    }
    assert public.isdisjoint(forbidden)
    source = inspect.getsource(ReflowApplicationService)
    assert "simulator.truth" not in source
    assert "MARK_RECONCILED" not in source


def test_persistence_module_has_no_simulator_or_distributed_infrastructure() -> None:
    import reflow.persistence as module

    source = inspect.getsource(module)
    for forbidden in ("simulator.truth", "kafka", "celery", "redis", "kubernetes"):
        assert forbidden not in source.casefold()
