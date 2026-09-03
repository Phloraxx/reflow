from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from reflow.domain import ReconciliationScopeId
from reflow.operator_audit import (
    OPERATOR_AUDIT_SCHEMA_VERSION,
    OperatorAuditAction,
    OperatorAuditDecision,
    OperatorAuditPersistenceError,
    PostgresOperatorAuditStore,
    principal_subject_sha256,
)

DSN = os.getenv("REFLOW_TEST_POSTGRES_DSN")
NOW = datetime(2026, 9, 3, 18, 0, tzinfo=UTC)
SCOPE = ReconciliationScopeId("scope_operator_audit_test")

pytestmark = pytest.mark.skipif(DSN is None, reason="PostgreSQL test DSN is not configured")


@pytest.fixture
def store() -> PostgresOperatorAuditStore:
    assert DSN is not None
    psycopg = pytest.importorskip("psycopg")
    result = PostgresOperatorAuditStore(DSN)
    with psycopg.connect(DSN) as connection, connection.cursor() as cursor:
        cursor.execute("TRUNCATE reflow_operator_access_audit RESTART IDENTITY")
    return result


def test_principal_subject_digest_is_stable_and_never_raw_identity() -> None:
    subject = "cf-subject-operator-001"
    digest = principal_subject_sha256(subject)
    assert len(digest) == 64
    assert digest == principal_subject_sha256(subject)
    assert subject not in digest


def test_postgres_operator_audit_is_append_only_restart_readable_and_pseudonymous(
    store: PostgresOperatorAuditStore,
) -> None:
    assert DSN is not None
    digest = principal_subject_sha256("cf-subject-viewer")
    first = store.record_access(
        occurred_at=NOW,
        request_id="a" * 32,
        principal_subject_sha256=digest,
        action=OperatorAuditAction.VIEW_SCOPE_OVERVIEW,
        scope_id=SCOPE,
        decision=OperatorAuditDecision.ALLOWED,
    )
    second = store.record_access(
        occurred_at=NOW,
        request_id="b" * 32,
        principal_subject_sha256=digest,
        action=OperatorAuditAction.VIEW_SCOPE_OVERVIEW,
        scope_id=SCOPE,
        decision=OperatorAuditDecision.DENIED,
    )
    assert first.audit_id == 1
    assert second.audit_id == 2
    assert store.integrity_count() == 2

    reopened = PostgresOperatorAuditStore(DSN, initialize=False)
    reopened.check_ready()
    recent = reopened.list_recent(limit=2)
    assert [item.audit_id for item in recent] == [2, 1]
    assert recent[0].principal_subject_sha256 == digest
    assert recent[0].scope_id == SCOPE
    assert recent[0].decision is OperatorAuditDecision.DENIED

    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(DSN) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'reflow_operator_access_audit'
            ORDER BY column_name
            """
        )
        columns = {row[0] for row in cursor.fetchall()}
        cursor.execute(
            "SELECT principal_subject_sha256 FROM reflow_operator_access_audit ORDER BY audit_id"
        )
        stored_digests = [row[0] for row in cursor.fetchall()]
    assert "email" not in columns
    assert "token" not in columns
    assert stored_digests == [digest, digest]


def test_operator_audit_duplicate_request_and_schema_mismatch_fail_closed(
    store: PostgresOperatorAuditStore,
) -> None:
    assert DSN is not None
    digest = principal_subject_sha256("cf-subject-duplicate")
    store.record_access(
        occurred_at=NOW,
        request_id="c" * 32,
        principal_subject_sha256=digest,
        action=OperatorAuditAction.VIEW_EVALUATION,
        scope_id=None,
        decision=OperatorAuditDecision.ALLOWED,
    )
    with pytest.raises(OperatorAuditPersistenceError, match="write failed"):
        store.record_access(
            occurred_at=NOW,
            request_id="c" * 32,
            principal_subject_sha256=digest,
            action=OperatorAuditAction.VIEW_EVALUATION,
            scope_id=None,
            decision=OperatorAuditDecision.ALLOWED,
        )

    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(DSN) as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE reflow_operator_audit_schema_meta SET schema_version = 999 WHERE singleton = 1"
        )
    try:
        with pytest.raises(OperatorAuditPersistenceError, match="schema version mismatch"):
            store.check_ready()
    finally:
        with psycopg.connect(DSN) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE reflow_operator_audit_schema_meta
                SET schema_version = %s
                WHERE singleton = 1
                """,
                (OPERATOR_AUDIT_SCHEMA_VERSION,),
            )
    store.check_ready()
