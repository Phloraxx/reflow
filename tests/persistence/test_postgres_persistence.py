from __future__ import annotations

import inspect
import os
from datetime import UTC, datetime, timedelta

import pytest

from reflow import domain
from reflow.control_plane import make_reconciliation_scope
from reflow.ingestion import ObservedBatch, ingest_observed_batch
from reflow.journal import AppendDisposition, Journal, JournalConflictError, make_source_envelope
from reflow.persistence import (
    POSTGRES_SCHEMA_VERSION,
    ArtifactKind,
    ArtifactPageCursor,
    ArtifactWriteDisposition,
    PersistenceConflictError,
    PersistenceError,
    PersistenceIntegrityError,
    PointerKind,
    PostgresApplicationStore,
    ReflowApplicationService,
    StalePointerError,
    canonical_artifact_json,
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



def test_postgres_artifact_keyset_page_handles_equal_times_and_null_tail(store) -> None:
    scope = _scope("artifact_page")
    kind = ArtifactKind.INVESTIGATION_TRACE
    for artifact_id, observed_at in (
        ("page_a", NOW),
        ("page_b", NOW),
        ("page_c", NOW + timedelta(seconds=1)),
        ("page_d", None),
        ("page_e", None),
    ):
        store.put_artifact(
            kind=kind,
            artifact_id=artifact_id,
            payload={"id": artifact_id, "scope_id": str(scope)},
            scope_id=scope,
            observed_at=observed_at,
        )

    first = store.list_artifact_page(kind=kind, scope_id=scope, limit=2)
    assert tuple(item.artifact_id for item in first.items) == ("page_a", "page_b")
    assert first.next_cursor == ArtifactPageCursor(observed_at=NOW, artifact_id="page_b")

    second = store.list_artifact_page(
        kind=kind, scope_id=scope, limit=2, after=first.next_cursor
    )
    assert tuple(item.artifact_id for item in second.items) == ("page_c", "page_d")
    assert second.next_cursor == ArtifactPageCursor(observed_at=None, artifact_id="page_d")

    third = store.list_artifact_page(
        kind=kind, scope_id=scope, limit=2, after=second.next_cursor
    )
    assert tuple(item.artifact_id for item in third.items) == ("page_e",)
    assert third.next_cursor is None

    with pytest.raises(PersistenceError, match="page limit"):
        store.list_artifact_page(kind=kind, scope_id=scope, limit=0)

def test_postgres_schema_migration_is_idempotent_and_versioned(store) -> None:
    store.migrate()
    store.migrate()
    assert store.capabilities().schema_version == POSTGRES_SCHEMA_VERSION


def test_postgres_readiness_check_requires_current_schema(store) -> None:
    dsn = _require_dsn()
    psycopg = pytest.importorskip("psycopg")
    store.check_ready()
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE reflow_schema_meta SET schema_version = 999 WHERE singleton = 1")
    try:
        with pytest.raises(PersistenceIntegrityError, match="schema version"):
            store.check_ready()
    finally:
        with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE reflow_schema_meta SET schema_version = %s WHERE singleton = 1",
                (POSTGRES_SCHEMA_VERSION,),
            )
    store.check_ready()


def test_postgres_missing_schema_metadata_initializes_only_when_database_is_empty(store) -> None:
    dsn = _require_dsn()
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute("DELETE FROM reflow_schema_meta WHERE singleton = 1")
    rebuilt = PostgresApplicationStore(dsn)
    assert rebuilt.capabilities().schema_version == POSTGRES_SCHEMA_VERSION


def test_postgres_missing_schema_metadata_fails_closed_for_populated_database(store) -> None:
    dsn = _require_dsn()
    psycopg = pytest.importorskip("psycopg")
    payload = {"id": "policy_missing_schema_meta"}
    rendered = canonical_artifact_json(payload)
    digest = __import__("hashlib").sha256(rendered.encode()).hexdigest()
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO reflow_artifacts (
                artifact_id, artifact_kind, scope_id, observed_at, payload_sha256, payload_json
            ) VALUES (%s, 'policy_version', NULL, %s, %s, %s::jsonb)
            """,
            ("policy_missing_schema_meta", NOW, digest, rendered),
        )
        cursor.execute("DELETE FROM reflow_schema_meta WHERE singleton = 1")
    try:
        with pytest.raises(PersistenceIntegrityError, match="missing for non-empty database"):
            PostgresApplicationStore(dsn)
        with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT schema_version FROM reflow_schema_meta WHERE singleton = 1")
            assert cursor.fetchone() is None
            cursor.execute(
                "SELECT observed_at FROM reflow_artifacts WHERE artifact_id = %s",
                ("policy_missing_schema_meta",),
            )
            assert cursor.fetchone() == (NOW,)
    finally:
        with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM reflow_artifacts WHERE artifact_id = %s",
                ("policy_missing_schema_meta",),
            )
            cursor.execute(
                """
                INSERT INTO reflow_schema_meta (singleton, schema_version)
                VALUES (1, %s)
                ON CONFLICT (singleton) DO UPDATE SET schema_version = EXCLUDED.schema_version
                """,
                (POSTGRES_SCHEMA_VERSION,),
            )


def test_postgres_v1_data_migration_preserves_replay_compatibility(store) -> None:
    dsn = _require_dsn()
    psycopg = pytest.importorskip("psycopg")
    scope_id = _scope("legacy-migration")
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE reflow_schema_meta SET schema_version = 1 WHERE singleton = 1"
        )
        legacy_rows = (
            ("policy_legacy", "policy_version", str(scope_id), NOW, {"id": "policy_legacy"}),
            (
                "adapter_legacy",
                "approved_adapter",
                str(scope_id),
                NOW,
                {"adapter_id": "bank-legacy", "version": 1},
            ),
            (
                "coverage_legacy",
                "evidence_coverage",
                str(scope_id),
                NOW,
                {"id": "coverage_legacy", "scope_id": str(scope_id)},
            ),
            (
                "proofv_legacy",
                "proof_version",
                str(scope_id),
                NOW,
                {"id": "proofv_legacy", "settlement_id": "setl_legacy"},
            ),
        )
        for artifact_id, kind, scope, observed_at, payload in legacy_rows:
            rendered = canonical_artifact_json(payload)
            cursor.execute(
                """
                INSERT INTO reflow_artifacts (
                    artifact_id, artifact_kind, scope_id, observed_at, payload_sha256, payload_json
                ) VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    artifact_id,
                    kind,
                    scope,
                    observed_at,
                    __import__("hashlib").sha256(rendered.encode()).hexdigest(),
                    rendered,
                ),
            )
        cursor.execute(
            """
            INSERT INTO reflow_current_pointers (
                pointer_kind, stream_key, artifact_id, generation
            ) VALUES ('latest_proof', 'setl_legacy', 'proofv_legacy', 1)
            """
        )

    rebuilt = PostgresApplicationStore(dsn)
    assert rebuilt.capabilities().schema_version == POSTGRES_SCHEMA_VERSION
    policy = rebuilt.get_artifact("policy_legacy")
    adapter_payload = {"adapter_id": "bank-legacy", "version": 1}
    adapter_digest = __import__("hashlib").sha256(
        canonical_artifact_json(adapter_payload).encode()
    ).hexdigest()
    adapter = rebuilt.get_artifact(f"adapterv_{adapter_digest[:24]}")
    coverage = rebuilt.get_artifact("coverage_legacy")
    proof = rebuilt.get_artifact("proofv_legacy")
    assert policy is not None and policy.scope_id is None and policy.observed_at is None
    assert rebuilt.get_artifact("adapter_legacy") is None
    assert adapter is not None and adapter.scope_id is None and adapter.observed_at is None
    assert coverage is not None and coverage.scope_id == scope_id and coverage.observed_at is None
    assert proof is not None and proof.scope_id == scope_id and proof.observed_at == NOW
    migrated_pointer = rebuilt.get_pointer(
        kind=PointerKind.LATEST_PROOF, stream_key=f"{scope_id}:setl_legacy"
    )
    assert migrated_pointer is not None and migrated_pointer.generation == 1
    assert rebuilt.get_pointer(kind=PointerKind.LATEST_PROOF, stream_key="setl_legacy") is None

    reopened = PostgresApplicationStore(dsn)
    assert reopened.capabilities().schema_version == POSTGRES_SCHEMA_VERSION
    replayed_pointer = reopened.get_pointer(
        kind=PointerKind.LATEST_PROOF, stream_key=f"{scope_id}:setl_legacy"
    )
    assert replayed_pointer == migrated_pointer


def test_postgres_v1_migration_rejects_latest_proof_digest_mismatch(store) -> None:
    dsn = _require_dsn()
    psycopg = pytest.importorskip("psycopg")
    payload = {"id": "proofv_legacy_bad_digest", "settlement_id": "setl_legacy_bad_digest"}
    rendered = canonical_artifact_json(payload)
    wrong_digest = __import__("hashlib").sha256(b"different-content").hexdigest()
    scope_id = _scope("legacy-bad-proof-digest")
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE reflow_schema_meta SET schema_version = 1 WHERE singleton = 1")
        cursor.execute(
            """
            INSERT INTO reflow_artifacts (
                artifact_id, artifact_kind, scope_id, observed_at, payload_sha256, payload_json
            ) VALUES (%s, 'proof_version', %s, %s, %s, %s::jsonb)
            """,
            ("proofv_legacy_bad_digest", str(scope_id), NOW, wrong_digest, rendered),
        )
        cursor.execute(
            """
            INSERT INTO reflow_current_pointers (
                pointer_kind, stream_key, artifact_id, generation
            ) VALUES ('latest_proof', 'setl_legacy_bad_digest', %s, 1)
            """,
            ("proofv_legacy_bad_digest",),
        )
    try:
        with pytest.raises(PersistenceIntegrityError, match="payload digest does not match"):
            PostgresApplicationStore(dsn)
        with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT schema_version FROM reflow_schema_meta WHERE singleton = 1")
            assert cursor.fetchone() == (1,)
            cursor.execute(
                "SELECT stream_key FROM reflow_current_pointers WHERE artifact_id = %s",
                ("proofv_legacy_bad_digest",),
            )
            assert cursor.fetchone() == ("setl_legacy_bad_digest",)
    finally:
        with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM reflow_current_pointers WHERE artifact_id = %s",
                ("proofv_legacy_bad_digest",),
            )
            cursor.execute(
                "DELETE FROM reflow_artifacts WHERE artifact_id = %s",
                ("proofv_legacy_bad_digest",),
            )
            cursor.execute(
                "UPDATE reflow_schema_meta SET schema_version = %s WHERE singleton = 1",
                (POSTGRES_SCHEMA_VERSION,),
            )


def test_postgres_v1_migration_fails_closed_on_unmigratable_latest_proof_pointer(store) -> None:
    dsn = _require_dsn()
    psycopg = pytest.importorskip("psycopg")
    payload = {"id": "proofv_legacy_unscoped", "settlement_id": "setl_legacy_unscoped"}
    rendered = canonical_artifact_json(payload)
    digest = __import__("hashlib").sha256(rendered.encode()).hexdigest()
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE reflow_schema_meta SET schema_version = 1 WHERE singleton = 1")
        cursor.execute(
            """
            INSERT INTO reflow_artifacts (
                artifact_id, artifact_kind, scope_id, observed_at, payload_sha256, payload_json
            ) VALUES (%s, 'proof_version', NULL, %s, %s, %s::jsonb)
            """,
            ("proofv_legacy_unscoped", NOW, digest, rendered),
        )
        cursor.execute(
            """
            INSERT INTO reflow_current_pointers (
                pointer_kind, stream_key, artifact_id, generation
            ) VALUES ('latest_proof', 'setl_legacy_unscoped', 'proofv_legacy_unscoped', 1)
            """
        )
    try:
        with pytest.raises(PersistenceIntegrityError, match="cannot be migrated safely"):
            PostgresApplicationStore(dsn)
        with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT schema_version FROM reflow_schema_meta WHERE singleton = 1")
            assert cursor.fetchone() == (1,)
    finally:
        with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM reflow_current_pointers WHERE artifact_id = %s",
                ("proofv_legacy_unscoped",),
            )
            cursor.execute(
                "DELETE FROM reflow_artifacts WHERE artifact_id = %s",
                ("proofv_legacy_unscoped",),
            )
            cursor.execute(
                "UPDATE reflow_schema_meta SET schema_version = %s WHERE singleton = 1",
                (POSTGRES_SCHEMA_VERSION,),
            )


def test_postgres_v1_migration_fails_closed_when_legacy_pointer_key_disagrees_with_proof(
    store,
) -> None:
    dsn = _require_dsn()
    psycopg = pytest.importorskip("psycopg")
    scope_id = _scope("legacy-pointer-mismatch")
    payload = {"id": "proofv_legacy_mismatch", "settlement_id": "setl_actual"}
    rendered = canonical_artifact_json(payload)
    digest = __import__("hashlib").sha256(rendered.encode()).hexdigest()
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE reflow_schema_meta SET schema_version = 1 WHERE singleton = 1")
        cursor.execute(
            """
            INSERT INTO reflow_artifacts (
                artifact_id, artifact_kind, scope_id, observed_at, payload_sha256, payload_json
            ) VALUES (%s, 'proof_version', %s, %s, %s, %s::jsonb)
            """,
            ("proofv_legacy_mismatch", str(scope_id), NOW, digest, rendered),
        )
        cursor.execute(
            """
            INSERT INTO reflow_current_pointers (
                pointer_kind, stream_key, artifact_id, generation
            ) VALUES ('latest_proof', 'setl_wrong', 'proofv_legacy_mismatch', 1)
            """
        )
    try:
        with pytest.raises(PersistenceIntegrityError, match="cannot be migrated safely"):
            PostgresApplicationStore(dsn)
        with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT schema_version FROM reflow_schema_meta WHERE singleton = 1")
            assert cursor.fetchone() == (1,)
            cursor.execute(
                """
                SELECT stream_key
                FROM reflow_current_pointers
                WHERE artifact_id = 'proofv_legacy_mismatch'
                """
            )
            assert cursor.fetchone() == ("setl_wrong",)
    finally:
        with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM reflow_current_pointers WHERE artifact_id = %s",
                ("proofv_legacy_mismatch",),
            )
            cursor.execute(
                "DELETE FROM reflow_artifacts WHERE artifact_id = %s",
                ("proofv_legacy_mismatch",),
            )
            cursor.execute(
                "UPDATE reflow_schema_meta SET schema_version = %s WHERE singleton = 1",
                (POSTGRES_SCHEMA_VERSION,),
            )


def _approved_adapter_for_migration(reference: str):
    from reflow.adapter_compiler import (
        ApprovalEvidenceKind,
        ApprovedAdapterVersion,
        compile_adapter,
        profile_rows,
        validate_sample,
    )
    from reflow.adapter_compiler.benchmark_fixtures import (
        _merchant_spec,
        development_adapter_cases,
    )
    from reflow.adapter_compiler.lifecycle import approval_evidence_for_adapter

    case = next(item for item in development_adapter_cases() if "merchant" in item.case_id)
    profile = profile_rows(case.rows)
    compiled = compile_adapter(_merchant_spec(case.adapter_id), profile)
    report = validate_sample(compiled, case.rows)
    return ApprovedAdapterVersion.from_compiled(
        compiled,
        profile,
        report,
        approval_evidence_for_adapter(
            compiled,
            kind=ApprovalEvidenceKind.OPERATOR_REVIEW,
            reference=reference,
        ),
    )


def test_postgres_v1_migration_canonicalizes_approved_adapter_identity_and_pointer(store) -> None:
    from reflow.persistence import approved_adapter_artifact_id

    dsn = _require_dsn()
    psycopg = pytest.importorskip("psycopg")
    approved = _approved_adapter_for_migration("legacy-v1-migration")
    rendered = canonical_artifact_json(approved)
    digest = __import__("hashlib").sha256(rendered.encode()).hexdigest()
    legacy_id = "adapterv_legacy_caller_selected"
    expected_id = approved_adapter_artifact_id(approved)
    scope_id = _scope("legacy-adapter")
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE reflow_schema_meta SET schema_version = 1 WHERE singleton = 1")
        cursor.execute(
            """
            INSERT INTO reflow_artifacts (
                artifact_id, artifact_kind, scope_id, observed_at, payload_sha256, payload_json
            ) VALUES (%s, 'approved_adapter', %s, %s, %s, %s::jsonb)
            """,
            (legacy_id, str(scope_id), NOW, digest, rendered),
        )
        cursor.execute(
            """
            INSERT INTO reflow_current_pointers (
                pointer_kind, stream_key, artifact_id, generation
            ) VALUES ('latest_adapter', %s, %s, 1)
            """,
            (str(approved.spec.adapter_id), legacy_id),
        )

    rebuilt = PostgresApplicationStore(dsn)
    assert rebuilt.get_artifact(legacy_id) is None
    canonical = rebuilt.get_artifact(expected_id)
    assert canonical is not None
    assert canonical.scope_id is None and canonical.observed_at is None
    assert canonical.payload_sha256 == digest
    pointer = rebuilt.get_pointer(
        kind=PointerKind.LATEST_ADAPTER, stream_key=str(approved.spec.adapter_id)
    )
    assert pointer is not None
    assert pointer.artifact_id == expected_id and pointer.generation == 1
    replay = ReflowApplicationService(rebuilt).persist_artifact(
        kind=ArtifactKind.APPROVED_ADAPTER,
        artifact_id=expected_id,
        payload=approved,
        scope_id=None,
        observed_at=NOW + timedelta(hours=1),
    )
    assert replay.disposition is ArtifactWriteDisposition.DUPLICATE


def test_postgres_v1_adapter_migration_rejects_wrong_legacy_pointer_stream_key(store) -> None:
    dsn = _require_dsn()
    psycopg = pytest.importorskip("psycopg")
    approved = _approved_adapter_for_migration("legacy-v1-wrong-key")
    rendered = canonical_artifact_json(approved)
    digest = __import__("hashlib").sha256(rendered.encode()).hexdigest()
    legacy_id = "adapterv_legacy_wrong_stream"
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE reflow_schema_meta SET schema_version = 1 WHERE singleton = 1")
        cursor.execute(
            """
            INSERT INTO reflow_artifacts (
                artifact_id, artifact_kind, scope_id, observed_at, payload_sha256, payload_json
            ) VALUES (%s, 'approved_adapter', NULL, %s, %s, %s::jsonb)
            """,
            (legacy_id, NOW, digest, rendered),
        )
        cursor.execute(
            """
            INSERT INTO reflow_current_pointers (
                pointer_kind, stream_key, artifact_id, generation
            ) VALUES ('latest_adapter', 'wrong-adapter-stream', %s, 1)
            """,
            (legacy_id,),
        )
    try:
        with pytest.raises(PersistenceIntegrityError, match="pointer cannot be migrated safely"):
            PostgresApplicationStore(dsn)
        with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT schema_version FROM reflow_schema_meta WHERE singleton = 1")
            assert cursor.fetchone() == (1,)
            cursor.execute(
                "SELECT stream_key FROM reflow_current_pointers WHERE artifact_id = %s",
                (legacy_id,),
            )
            assert cursor.fetchone() == ("wrong-adapter-stream",)
    finally:
        with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM reflow_current_pointers WHERE artifact_id = %s",
                (legacy_id,),
            )
            cursor.execute("DELETE FROM reflow_artifacts WHERE artifact_id = %s", (legacy_id,))
            cursor.execute(
                "UPDATE reflow_schema_meta SET schema_version = %s WHERE singleton = 1",
                (POSTGRES_SCHEMA_VERSION,),
            )


def test_postgres_v1_adapter_migration_rejects_wrong_kind_pointer_target(store) -> None:
    dsn = _require_dsn()
    psycopg = pytest.importorskip("psycopg")
    payload = {"id": "policy_wrong_adapter_pointer"}
    rendered = canonical_artifact_json(payload)
    digest = __import__("hashlib").sha256(rendered.encode()).hexdigest()
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE reflow_schema_meta SET schema_version = 1 WHERE singleton = 1")
        cursor.execute(
            """
            INSERT INTO reflow_artifacts (
                artifact_id, artifact_kind, scope_id, observed_at, payload_sha256, payload_json
            ) VALUES (%s, 'policy_version', NULL, NULL, %s, %s::jsonb)
            """,
            ("policy_wrong_adapter_pointer", digest, rendered),
        )
        cursor.execute(
            """
            INSERT INTO reflow_current_pointers (
                pointer_kind, stream_key, artifact_id, generation
            ) VALUES ('latest_adapter', 'adapter_should_not_point_to_policy', %s, 1)
            """,
            ("policy_wrong_adapter_pointer",),
        )
    try:
        with pytest.raises(PersistenceIntegrityError, match="pointer cannot be migrated safely"):
            PostgresApplicationStore(dsn)
        with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT schema_version FROM reflow_schema_meta WHERE singleton = 1")
            assert cursor.fetchone() == (1,)
            cursor.execute(
                """
                SELECT pointer_kind, stream_key, artifact_id
                FROM reflow_current_pointers
                WHERE pointer_kind = 'latest_adapter'
                """
            )
            assert cursor.fetchone() == (
                "latest_adapter",
                "adapter_should_not_point_to_policy",
                "policy_wrong_adapter_pointer",
            )
    finally:
        with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM reflow_current_pointers WHERE artifact_id = %s",
                ("policy_wrong_adapter_pointer",),
            )
            cursor.execute(
                "DELETE FROM reflow_artifacts WHERE artifact_id = %s",
                ("policy_wrong_adapter_pointer",),
            )
            cursor.execute(
                "UPDATE reflow_schema_meta SET schema_version = %s WHERE singleton = 1",
                (POSTGRES_SCHEMA_VERSION,),
            )


def test_postgres_v1_adapter_identity_migration_fails_closed_on_target_collision(store) -> None:
    from reflow.persistence import approved_adapter_artifact_id

    dsn = _require_dsn()
    psycopg = pytest.importorskip("psycopg")
    approved = _approved_adapter_for_migration("legacy-v1-collision")
    rendered = canonical_artifact_json(approved)
    digest = __import__("hashlib").sha256(rendered.encode()).hexdigest()
    legacy_id = "adapterv_legacy_collision_source"
    expected_id = approved_adapter_artifact_id(approved)
    collision_payload = {"id": "policy_collision"}
    collision_json = canonical_artifact_json(collision_payload)
    collision_digest = __import__("hashlib").sha256(collision_json.encode()).hexdigest()
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE reflow_schema_meta SET schema_version = 1 WHERE singleton = 1")
        cursor.execute(
            """
            INSERT INTO reflow_artifacts (
                artifact_id, artifact_kind, scope_id, observed_at, payload_sha256, payload_json
            ) VALUES (%s, 'approved_adapter', NULL, %s, %s, %s::jsonb)
            """,
            (legacy_id, NOW, digest, rendered),
        )
        cursor.execute(
            """
            INSERT INTO reflow_artifacts (
                artifact_id, artifact_kind, scope_id, observed_at, payload_sha256, payload_json
            ) VALUES (%s, 'policy_version', NULL, NULL, %s, %s::jsonb)
            """,
            (expected_id, collision_digest, collision_json),
        )
    try:
        with pytest.raises(PersistenceIntegrityError, match="identity cannot be migrated safely"):
            PostgresApplicationStore(dsn)
        with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT schema_version FROM reflow_schema_meta WHERE singleton = 1")
            assert cursor.fetchone() == (1,)
            cursor.execute(
                "SELECT artifact_kind FROM reflow_artifacts WHERE artifact_id = %s",
                (legacy_id,),
            )
            assert cursor.fetchone() == ("approved_adapter",)
    finally:
        with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM reflow_artifacts WHERE artifact_id IN (%s, %s)",
                (legacy_id, expected_id),
            )
            cursor.execute(
                "UPDATE reflow_schema_meta SET schema_version = %s WHERE singleton = 1",
                (POSTGRES_SCHEMA_VERSION,),
            )


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


def test_application_service_rejects_untyped_finance_artifact_payload(store) -> None:
    service = ReflowApplicationService(store)
    scope_id = _scope("typed-boundary")
    with pytest.raises(PersistenceError, match="typed self-validating"):
        service.persist_artifact(
            kind=ArtifactKind.RECONCILIATION_RUN,
            artifact_id="run_forged_application_payload",
            payload={
                "id": "run_forged_application_payload",
                "scope_id": str(scope_id),
                "outcome": "ready",
                "code_build_sha": "forged",
            },
            scope_id=scope_id,
            observed_at=NOW,
        )


def test_application_service_rejects_wrong_semantic_pointer_stream_key(store) -> None:
    from reflow.evaluation.control_tower_demo import build_demo_bundle

    bundle = build_demo_bundle()
    service = ReflowApplicationService(store)
    with pytest.raises(PersistenceIntegrityError, match="latest_proof stream key"):
        service.publish_current(
            artifact_kind=ArtifactKind.PROOF_VERSION,
            artifact_id=str(bundle.proof.id),
            payload=bundle.proof,
            scope_id=bundle.scope.id,
            observed_at=bundle.proof.generated_at,
            pointer_kind=PointerKind.LATEST_PROOF,
            stream_key="setl_wrong_stream",
            expected_generation=0,
        )


def test_manifest_coverage_query_is_not_limited_by_generic_artifact_window(store) -> None:
    from reflow.evaluation.control_tower_demo import build_demo_bundle

    bundle = build_demo_bundle()
    service = ReflowApplicationService(store)
    for envelope in bundle.journal.entries():
        service.append_source(envelope)
    for manifest in bundle.manifests:
        service.persist_artifact(
            kind=ArtifactKind.SOURCE_DELIVERY_MANIFEST,
            artifact_id=str(manifest.id),
            payload=manifest,
            scope_id=bundle.scope.id,
            observed_at=manifest.evaluated_at,
        )
    assert store.manifests_cover_source_ids(
        scope_id=bundle.scope.id,
        source_ids=tuple(bundle.proof.source_envelope_ids),
    )


def test_application_manifest_requires_retained_raw_source_evidence(store) -> None:
    from reflow.evaluation.control_tower_demo import build_demo_bundle

    bundle = build_demo_bundle()
    service = ReflowApplicationService(store)
    manifest = next(item for item in bundle.manifests if item.effective_envelope_ids)
    with pytest.raises(PersistenceIntegrityError, match="raw source evidence"):
        service.persist_artifact(
            kind=ArtifactKind.SOURCE_DELIVERY_MANIFEST,
            artifact_id=str(manifest.id),
            payload=manifest,
            scope_id=bundle.scope.id,
            observed_at=manifest.evaluated_at,
        )


def test_application_proof_requires_retained_raw_source_evidence_even_with_manifest_rows(
    store,
) -> None:
    from reflow.evaluation.control_tower_demo import build_demo_bundle

    bundle = build_demo_bundle()
    service = ReflowApplicationService(store)
    for manifest in bundle.manifests:
        store.put_artifact(
            kind=ArtifactKind.SOURCE_DELIVERY_MANIFEST,
            artifact_id=str(manifest.id),
            payload=manifest,
            scope_id=bundle.scope.id,
            observed_at=manifest.evaluated_at,
        )
    with pytest.raises(PersistenceIntegrityError, match="raw source evidence"):
        service.persist_artifact(
            kind=ArtifactKind.PROOF_VERSION,
            artifact_id=str(bundle.proof.id),
            payload=bundle.proof,
            scope_id=bundle.scope.id,
            observed_at=bundle.proof.generated_at,
        )


def test_application_service_rejects_proof_scope_without_scoped_manifest_evidence(store) -> None:
    from reflow.evaluation.control_tower_demo import build_demo_bundle

    bundle = build_demo_bundle()
    service = ReflowApplicationService(store)
    for envelope in bundle.journal.entries():
        service.append_source(envelope)
    foreign_scope = _scope("foreign-proof-scope")
    with pytest.raises(PersistenceIntegrityError, match="scoped source manifests"):
        service.persist_artifact(
            kind=ArtifactKind.PROOF_VERSION,
            artifact_id=str(bundle.proof.id),
            payload=bundle.proof,
            scope_id=foreign_scope,
            observed_at=bundle.proof.generated_at,
        )


def test_application_service_journal_does_not_expose_generic_store_capabilities(store) -> None:
    service = ReflowApplicationService(store)
    journal = service.journal
    assert isinstance(journal, Journal)
    public = {name for name in dir(journal) if not name.startswith("_")}
    assert public.isdisjoint(
        {"put_artifact", "advance_pointer", "publish_artifact_and_pointer", "execute"}
    )


def test_postgres_artifact_count_matches_scope_filtered_list(store) -> None:
    scope_id = _scope("count")
    for index in range(3):
        store.put_artifact(
            kind=ArtifactKind.RECONCILIATION_RUN,
            artifact_id=f"run_count_{index}",
            payload={"index": index},
            scope_id=scope_id,
            observed_at=NOW + timedelta(seconds=index),
        )
    assert store.count_artifacts(
        kind=ArtifactKind.RECONCILIATION_RUN, scope_id=scope_id
    ) == 3
    assert len(
        store.list_artifacts(kind=ArtifactKind.RECONCILIATION_RUN, scope_id=scope_id)
    ) == 3


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


def test_postgres_duplicate_replay_ignores_local_receipt_metadata(store) -> None:
    first = _source("bank_pg_refetch", received_at=NOW)
    later_refetch = _source("bank_pg_refetch", received_at=NOW + timedelta(hours=1))
    assert first.id == later_refetch.id
    assert store.append(first).disposition is AppendDisposition.STORED
    replay = store.append(later_refetch)
    assert replay.disposition is AppendDisposition.DUPLICATE
    assert replay.envelope == first


def _persist_demo_run_dependencies(service, bundle) -> None:
    for envelope in bundle.journal.entries():
        service.append_source(envelope)
    service.persist_artifact(
        kind=ArtifactKind.RECONCILIATION_SCOPE,
        artifact_id=str(bundle.scope.id),
        payload=bundle.scope,
        scope_id=bundle.scope.id,
        observed_at=None,
    )
    service.persist_artifact(
        kind=ArtifactKind.POLICY_VERSION,
        artifact_id=str(bundle.policy.id),
        payload=bundle.policy,
        scope_id=None,
        observed_at=None,
    )
    for manifest in bundle.manifests:
        service.persist_artifact(
            kind=ArtifactKind.SOURCE_DELIVERY_MANIFEST,
            artifact_id=str(manifest.id),
            payload=manifest,
            scope_id=bundle.scope.id,
            observed_at=manifest.evaluated_at,
        )
    service.persist_artifact(
        kind=ArtifactKind.PROOF_VERSION,
        artifact_id=str(bundle.proof.id),
        payload=bundle.proof,
        scope_id=bundle.scope.id,
        observed_at=bundle.proof.generated_at,
    )
    for kind, artifact in (
        (ArtifactKind.EVIDENCE_COVERAGE, bundle.coverage),
        (ArtifactKind.BALANCE_CONTROL, bundle.balance),
        (ArtifactKind.CLOSE_READINESS, bundle.close),
    ):
        service.persist_artifact(
            kind=kind,
            artifact_id=str(artifact.id),
            payload=artifact,
            scope_id=bundle.scope.id,
            observed_at=None,
        )



def test_application_artifacts_without_intrinsic_time_ignore_caller_timestamp(store) -> None:
    from reflow.evaluation.control_tower_demo import build_demo_bundle

    bundle = build_demo_bundle()
    service = ReflowApplicationService(store)
    cases = (
        (ArtifactKind.RECONCILIATION_SCOPE, bundle.scope, bundle.scope.id),
        (ArtifactKind.POLICY_VERSION, bundle.policy, bundle.scope.id),
        (ArtifactKind.EVIDENCE_COVERAGE, bundle.coverage, bundle.scope.id),
        (ArtifactKind.BALANCE_CONTROL, bundle.balance, bundle.scope.id),
        (ArtifactKind.CLOSE_READINESS, bundle.close, bundle.scope.id),
    )
    for kind, artifact, scope_id in cases:
        first = service.persist_artifact(
            kind=kind,
            artifact_id=str(artifact.id),
            payload=artifact,
            scope_id=scope_id,
            observed_at=NOW,
        )
        replay = service.persist_artifact(
            kind=kind,
            artifact_id=str(artifact.id),
            payload=artifact,
            scope_id=scope_id,
            observed_at=NOW + timedelta(hours=1),
        )
        assert first.artifact.observed_at is None
        assert replay.disposition is ArtifactWriteDisposition.DUPLICATE
        assert replay.artifact == first.artifact


def test_application_proof_artifact_remains_storage_scoped(store) -> None:
    from reflow.evaluation.control_tower_demo import build_demo_bundle

    bundle = build_demo_bundle()
    service = ReflowApplicationService(store)
    _persist_demo_run_dependencies(service, bundle)
    stored = service.artifact(str(bundle.proof.id))
    assert stored is not None
    assert stored.scope_id == bundle.scope.id

def test_application_service_rejects_current_run_until_complete_graph_exists(store) -> None:
    from reflow.evaluation.control_tower_demo import build_demo_bundle

    bundle = build_demo_bundle()
    service = ReflowApplicationService(store)
    with pytest.raises(PersistenceIntegrityError, match="current run graph"):
        service.publish_current(
            artifact_kind=ArtifactKind.RECONCILIATION_RUN,
            artifact_id=str(bundle.run.id),
            payload=bundle.run,
            scope_id=bundle.scope.id,
            observed_at=bundle.run.completed_at,
            pointer_kind=PointerKind.LATEST_RUN,
            stream_key=str(bundle.scope.id),
            expected_generation=0,
        )
    assert service.current(kind=PointerKind.LATEST_RUN, stream_key=str(bundle.scope.id)) is None

    _persist_demo_run_dependencies(service, bundle)
    _, pointer = service.publish_current(
        artifact_kind=ArtifactKind.RECONCILIATION_RUN,
        artifact_id=str(bundle.run.id),
        payload=bundle.run,
        scope_id=bundle.scope.id,
        observed_at=bundle.run.completed_at,
        pointer_kind=PointerKind.LATEST_RUN,
        stream_key=str(bundle.scope.id),
        expected_generation=0,
    )
    assert pointer.artifact_id == str(bundle.run.id)


def test_application_service_can_retain_typed_observation_before_parent_artifacts(store) -> None:
    from reflow.evaluation.control_tower_demo import build_demo_bundle

    bundle = build_demo_bundle()
    service = ReflowApplicationService(store)
    observation = bundle.observations[0]
    result = service.persist_artifact(
        kind=ArtifactKind.CASE_OBSERVATION,
        artifact_id=str(observation.id),
        payload=observation,
        scope_id=bundle.scope.id,
        observed_at=observation.observed_at,
    )
    assert result.artifact.artifact_id == str(observation.id)


def test_application_policy_artifact_is_global_and_reusable_across_scopes(store) -> None:
    from reflow.evaluation.control_tower_demo import build_demo_bundle

    bundle = build_demo_bundle()
    second_scope = _scope("second-policy-scope")
    service = ReflowApplicationService(store)
    for scope_id in (bundle.scope.id, second_scope):
        _, pointer = service.publish_current(
            artifact_kind=ArtifactKind.POLICY_VERSION,
            artifact_id=str(bundle.policy.id),
            payload=bundle.policy,
            scope_id=scope_id,
            observed_at=None,
            pointer_kind=PointerKind.LATEST_POLICY,
            stream_key=str(scope_id),
            expected_generation=0,
        )
        assert pointer.artifact_id == str(bundle.policy.id)
    stored = service.artifact(str(bundle.policy.id))
    assert stored is not None
    assert stored.scope_id is None


def test_application_rejects_caller_chosen_approved_adapter_artifact_id(store) -> None:
    from reflow.adapter_compiler import (
        ApprovalEvidenceKind,
        ApprovedAdapterVersion,
        compile_adapter,
        profile_rows,
        validate_sample,
    )
    from reflow.adapter_compiler.benchmark_fixtures import (
        _merchant_spec,
        development_adapter_cases,
    )
    from reflow.adapter_compiler.lifecycle import approval_evidence_for_adapter

    case = next(item for item in development_adapter_cases() if "merchant" in item.case_id)
    rows = case.rows
    profile = profile_rows(rows)
    compiled = compile_adapter(_merchant_spec(case.adapter_id), profile)
    report = validate_sample(compiled, rows)
    approved = ApprovedAdapterVersion.from_compiled(
        compiled,
        profile,
        report,
        approval_evidence_for_adapter(
            compiled,
            kind=ApprovalEvidenceKind.OPERATOR_REVIEW,
            reference="third-audit-review",
        ),
    )
    from reflow.persistence import approved_adapter_artifact_id

    service = ReflowApplicationService(store)
    with pytest.raises(PersistenceIntegrityError, match="approved adapter artifact id"):
        service.persist_artifact(
            kind=ArtifactKind.APPROVED_ADAPTER,
            artifact_id="adapterv_caller_chosen",
            payload=approved,
            scope_id=None,
            observed_at=None,
        )
    expected = approved_adapter_artifact_id(approved)
    stored = service.persist_artifact(
        kind=ArtifactKind.APPROVED_ADAPTER,
        artifact_id=expected,
        payload=approved,
        scope_id=None,
        observed_at=NOW,
    )
    replay = service.persist_artifact(
        kind=ArtifactKind.APPROVED_ADAPTER,
        artifact_id=expected,
        payload=approved,
        scope_id=None,
        observed_at=NOW + timedelta(hours=1),
    )
    assert stored.artifact.artifact_id == expected
    assert stored.artifact.scope_id is None
    assert stored.artifact.observed_at is None
    assert replay.disposition is ArtifactWriteDisposition.DUPLICATE


def test_application_derives_storage_time_from_typed_artifact_when_omitted(store) -> None:
    from reflow.evaluation.control_tower_demo import build_demo_bundle

    bundle = build_demo_bundle()
    service = ReflowApplicationService(store)
    _persist_demo_run_dependencies(service, bundle)
    stored = service.persist_artifact(
        kind=ArtifactKind.RECONCILIATION_RUN,
        artifact_id=str(bundle.run.id),
        payload=bundle.run,
        scope_id=bundle.scope.id,
        observed_at=None,
    )
    assert stored.artifact.observed_at == bundle.run.completed_at


def test_application_rejects_storage_time_that_disagrees_with_typed_artifact(store) -> None:
    from reflow.evaluation.control_tower_demo import build_demo_bundle, seed_demo

    bundle = build_demo_bundle()
    seed_demo(_require_dsn())
    service = ReflowApplicationService(store)
    with pytest.raises(PersistenceIntegrityError, match="observed_at"):
        service.persist_artifact(
            kind=ArtifactKind.INVESTIGATION_RESULT,
            artifact_id=str(bundle.investigation.id),
            payload=bundle.investigation,
            scope_id=bundle.scope.id,
            observed_at=bundle.investigation.as_of + timedelta(hours=1),
        )
