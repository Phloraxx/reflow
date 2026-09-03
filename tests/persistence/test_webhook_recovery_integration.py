from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from reflow.persistence import PostgresApplicationStore
from reflow.postgres_recovery import create_logical_backup, restore_and_verify
from reflow.webhook_ingress import (
    PostgresWebhookReceiptStore,
    WebhookProcessingOutcome,
    WebhookReceipt,
    WebhookSecretGeneration,
)

POSTGRES_CLIENT_IMAGE = (
    "postgres:16.15-alpine@sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685"
)
NOW = datetime(2026, 9, 3, 17, 0, tzinfo=UTC)


class DockerPostgresRunner:
    def __call__(
        self,
        command: Sequence[str],
        env: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]:
        tool = Path(command[0]).name
        if tool not in {"pg_dump", "pg_restore"}:
            raise AssertionError(f"unexpected PostgreSQL tool: {tool}")
        docker_command = [
            "docker",
            "run",
            "--rm",
            "--network",
            "host",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
        ]
        for key in sorted(name for name in env if name.startswith("PG")):
            docker_command.extend(["-e", key])
        docker_command.extend(["-v", "/tmp:/tmp", POSTGRES_CLIENT_IMAGE, tool])
        docker_command.extend(command[1:])
        return subprocess.run(
            docker_command,
            env=dict(env),
            check=False,
            capture_output=True,
            text=True,
        )


def _require_ci_drill() -> str:
    if os.getenv("REFLOW_RECOVERY_DOCKER_DRILL") != "1":
        pytest.skip("real PostgreSQL recovery drill is enabled only in CI")
    dsn = os.getenv("REFLOW_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("REFLOW_TEST_POSTGRES_DSN is not configured")
    return dsn


def _database_dsn(admin_dsn: str, database: str) -> str:
    psycopg = pytest.importorskip("psycopg")
    return psycopg.conninfo.make_conninfo(admin_dsn, dbname=database)


def _reset_database(admin_dsn: str, database: str) -> None:
    psycopg = pytest.importorskip("psycopg")
    sql = pytest.importorskip("psycopg.sql")
    with (
        psycopg.connect(admin_dsn, autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(database)
            )
        )
        cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))


def _drop_database(admin_dsn: str, database: str) -> None:
    psycopg = pytest.importorskip("psycopg")
    sql = pytest.importorskip("psycopg.sql")
    with (
        psycopg.connect(admin_dsn, autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(database)
            )
        )


def _seed_webhook_state(dsn: str) -> None:
    PostgresApplicationStore(dsn)
    store = PostgresWebhookReceiptStore(dsn)
    raw = b'{"event":"unsupported.recovery_probe"}'
    receipt = WebhookReceipt(
        provider="razorpay",
        account_id="acc_webhook_recovery_ci",
        event_id="evt_webhook_recovery_ci",
        body_sha256=hashlib.sha256(raw).hexdigest(),
        raw_body=raw,
        signature="b" * 64,
        first_received_at=NOW,
        secret_generation=WebhookSecretGeneration.CURRENT,
    )
    store.append_receipt(receipt)
    store.record_attempt(
        account_id=receipt.account_id,
        event_id=receipt.event_id,
        attempted_at=NOW,
        outcome=WebhookProcessingOutcome.REJECTED,
        outcome_code="provider_payload_rejected",
    )


def test_real_recovery_drill_preserves_webhook_receipts_and_attempts() -> None:
    admin_dsn = _require_ci_drill()
    source_name = "reflow_webhook_recovery_source_ci"
    restore_name = "reflow_webhook_recovery_restore_ci"
    source_dsn = _database_dsn(admin_dsn, source_name)
    restore_dsn = _database_dsn(admin_dsn, restore_name)
    runner = DockerPostgresRunner()

    _reset_database(admin_dsn, source_name)
    _reset_database(admin_dsn, restore_name)
    try:
        _seed_webhook_state(source_dsn)
        with tempfile.TemporaryDirectory(
            dir="/tmp",
            prefix="reflow-webhook-recovery-ci-",
        ) as root:
            archive, manifest_path, _manifest = create_logical_backup(
                dsn=source_dsn,
                output_dir=Path(root),
                readiness_probe=PostgresApplicationStore(
                    source_dsn,
                    initialize=False,
                ).check_ready,
                runner=runner,
                now=NOW,
            )
            restore_and_verify(
                source_dsn=source_dsn,
                restore_dsn=restore_dsn,
                archive=archive,
                manifest_path=manifest_path,
                runner=runner,
            )
            restored = PostgresWebhookReceiptStore(
                restore_dsn,
                initialize=False,
            )
            restored.check_ready()
            assert restored.integrity_counts() == (1, 1)
    finally:
        _drop_database(admin_dsn, restore_name)
        _drop_database(admin_dsn, source_name)
