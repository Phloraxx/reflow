from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta

import pytest

from reflow import domain
from reflow.control_plane import make_reconciliation_scope
from reflow.exception_cases import (
    CaseWorkflowStatus,
    DispositionKind,
    build_exception_case_disposition,
)
from reflow.persistence import (
    POSTGRES_SCHEMA_VERSION,
    ArtifactKind,
    PersistenceConflictError,
    PointerKind,
    PostgresApplicationStore,
    ReflowApplicationService,
    StalePointerError,
)

DSN = os.environ.get("REFLOW_TEST_POSTGRES_DSN")
NOW = datetime(2026, 9, 4, 8, 30, tzinfo=UTC)


def _dsn() -> str:
    if not DSN:
        pytest.skip("REFLOW_TEST_POSTGRES_DSN is not configured")
    return DSN


@pytest.fixture
def store() -> PostgresApplicationStore:
    dsn = _dsn()
    psycopg = pytest.importorskip("psycopg")
    result = PostgresApplicationStore(dsn)
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            TRUNCATE reflow_case_workflow_commands,
                     reflow_current_pointers,
                     reflow_artifacts,
                     reflow_source_identity,
                     reflow_source_envelopes
            """
        )
    return result


def _scope() -> domain.ReconciliationScopeId:
    return make_reconciliation_scope(
        merchant_account_id="merchant_gate52",
        provider="razorpay",
        provider_account_id="rzp_gate52",
        bank_account_id="bank_gate52",
        currency=domain.Currency.INR,
        channel="payments",
    ).id


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _disposition(
    *,
    case_id: domain.ExceptionCaseId,
    sequence: int,
    actor: str,
    occurred_at: datetime,
    kind: DispositionKind,
    prior_count: int,
    prior_at: datetime | None,
    status: CaseWorkflowStatus,
    owner: str | None = None,
    note: str | None = None,
):
    return build_exception_case_disposition(
        case_id=case_id,
        sequence=sequence,
        actor_id=actor,
        occurred_at=occurred_at,
        kind=kind,
        case_first_seen_at=NOW,
        current_workflow_status=status,
        current_resolution=None,
        prior_disposition_count=prior_count,
        prior_disposition_at=prior_at,
        owner=owner,
        note=note,
    )


def test_case_workflow_command_is_atomic_idempotent_and_generation_safe(store) -> None:
    scope = _scope()
    service = ReflowApplicationService(store)
    case_id = domain.ExceptionCaseId("case_gate52_atomic")
    actor = _digest("subject-gate52")
    first = _disposition(
        case_id=case_id,
        sequence=1,
        actor=actor,
        occurred_at=NOW + timedelta(minutes=1),
        kind=DispositionKind.ACKNOWLEDGE,
        prior_count=0,
        prior_at=None,
        status=CaseWorkflowStatus.OPEN,
        note="triaged",
    )
    command_key = _digest("idempotency-gate52-1")
    request_digest = _digest("request-gate52-1")

    stored = service.publish_case_disposition_command(
        disposition=first,
        scope_id=scope,
        principal_subject_sha256=actor,
        command_key_sha256=command_key,
        request_sha256=request_digest,
        request_id="1" * 32,
        expected_generation=0,
    )
    assert stored.replayed is False
    assert stored.committed_generation == 1
    pointer = service.current(kind=PointerKind.LATEST_CASE_DISPOSITION, stream_key=str(case_id))
    assert pointer is not None
    assert pointer.generation == 1
    assert pointer.artifact_id == str(first.id)

    retry_candidate = _disposition(
        case_id=case_id,
        sequence=1,
        actor=actor,
        occurred_at=NOW + timedelta(minutes=2),
        kind=DispositionKind.ACKNOWLEDGE,
        prior_count=0,
        prior_at=None,
        status=CaseWorkflowStatus.OPEN,
        note="triaged",
    )
    replay = service.publish_case_disposition_command(
        disposition=retry_candidate,
        scope_id=scope,
        principal_subject_sha256=actor,
        command_key_sha256=command_key,
        request_sha256=request_digest,
        request_id="2" * 32,
        expected_generation=0,
    )
    assert replay.replayed is True
    assert replay.artifact.artifact_id == str(first.id)
    assert service.artifact(str(retry_candidate.id)) is None

    with pytest.raises(PersistenceConflictError, match="idempotency key"):
        service.replay_case_disposition_command(
            scope_id=scope,
            case_id=str(case_id),
            principal_subject_sha256=actor,
            command_key_sha256=command_key,
            request_sha256=_digest("different-request"),
            expected_generation=0,
        )

    stale = _disposition(
        case_id=case_id,
        sequence=1,
        actor=actor,
        occurred_at=NOW + timedelta(minutes=3),
        kind=DispositionKind.DEFER,
        prior_count=0,
        prior_at=None,
        status=CaseWorkflowStatus.OPEN,
        note="later",
    )
    with pytest.raises(StalePointerError):
        service.publish_case_disposition_command(
            disposition=stale,
            scope_id=scope,
            principal_subject_sha256=actor,
            command_key_sha256=_digest("idempotency-stale"),
            request_sha256=_digest("request-stale"),
            request_id="3" * 32,
            expected_generation=0,
        )
    assert service.artifact(str(stale.id)) is None

    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(_dsn()) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM reflow_case_workflow_commands")
        assert cursor.fetchone() == (1,)


def test_v2_migration_backfills_latest_case_disposition_pointer(store) -> None:
    dsn = _dsn()
    psycopg = pytest.importorskip("psycopg")
    service = ReflowApplicationService(store)
    scope = _scope()
    case_id = domain.ExceptionCaseId("case_gate52_migration")
    first_time = NOW + timedelta(minutes=1)
    first = _disposition(
        case_id=case_id,
        sequence=1,
        actor="legacy-operator",
        occurred_at=first_time,
        kind=DispositionKind.ACKNOWLEDGE,
        prior_count=0,
        prior_at=None,
        status=CaseWorkflowStatus.OPEN,
    )
    second = _disposition(
        case_id=case_id,
        sequence=2,
        actor="legacy-operator",
        occurred_at=first_time + timedelta(minutes=1),
        kind=DispositionKind.DEFER,
        prior_count=1,
        prior_at=first_time,
        status=CaseWorkflowStatus.ACKNOWLEDGED,
        note="legacy deferral",
    )
    for disposition in (first, second):
        service.persist_artifact(
            kind=ArtifactKind.CASE_DISPOSITION,
            artifact_id=str(disposition.id),
            payload=disposition,
            scope_id=scope,
            observed_at=disposition.occurred_at,
        )
    assert (
        service.current(
            kind=PointerKind.LATEST_CASE_DISPOSITION, stream_key=str(case_id)
        )
        is None
    )
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE reflow_schema_meta SET schema_version = 2 WHERE singleton = 1")

    migrated = PostgresApplicationStore(dsn)
    assert migrated.capabilities().schema_version == POSTGRES_SCHEMA_VERSION
    pointer = migrated.get_pointer(
        kind=PointerKind.LATEST_CASE_DISPOSITION,
        stream_key=str(case_id),
    )
    assert pointer is not None
    assert pointer.generation == 2
    assert pointer.artifact_id == str(second.id)
