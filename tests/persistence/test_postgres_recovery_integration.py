from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from reflow import domain
from reflow.journal import make_source_envelope
from reflow.persistence import ArtifactKind, PointerKind, PostgresApplicationStore
from reflow.postgres_recovery import (
    RestoreVerification,
    create_logical_backup,
    restore_and_verify,
)

POSTGRES_CLIENT_IMAGE = (
    "postgres:16.15-alpine@sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685"
)
NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


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
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(database))
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
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(database))
        )


def _seed_source_database(dsn: str) -> None:
    store = PostgresApplicationStore(dsn)
    envelope = make_source_envelope(
        source_kind=domain.SourceKind.BANK,
        source_record_id="bank_ci_recovery_probe",
        occurred_at=NOW,
        received_at=NOW,
        schema_version="recovery-ci-v1",
        payload={"amount_paise": 123, "currency": "INR"},
    )
    store.append(envelope)
    store.put_artifact(
        kind=ArtifactKind.POLICY_VERSION,
        artifact_id="policy_ci_recovery_probe",
        payload={"probe": "recovery-ci"},
        scope_id=None,
        observed_at=NOW,
    )
    store.advance_pointer(
        kind=PointerKind.LATEST_POLICY,
        stream_key="scope_ci_recovery_probe",
        artifact_id="policy_ci_recovery_probe",
        expected_generation=0,
    )


def test_real_postgres16_dump_restore_integrity_drill() -> None:
    admin_dsn = _require_ci_drill()
    source_name = "reflow_recovery_source_ci"
    restore_name = "reflow_recovery_restore_ci"
    source_dsn = _database_dsn(admin_dsn, source_name)
    restore_dsn = _database_dsn(admin_dsn, restore_name)
    runner = DockerPostgresRunner()

    _reset_database(admin_dsn, source_name)
    _reset_database(admin_dsn, restore_name)
    try:
        _seed_source_database(source_dsn)
        with tempfile.TemporaryDirectory(dir="/tmp", prefix="reflow-recovery-ci-") as root:
            backup_dir = Path(root)
            archive, manifest_path, manifest = create_logical_backup(
                dsn=source_dsn,
                output_dir=backup_dir,
                readiness_probe=PostgresApplicationStore(source_dsn, initialize=False).check_ready,
                runner=runner,
                now=NOW,
            )
            assert manifest.archive_bytes == archive.stat().st_size
            result = restore_and_verify(
                source_dsn=source_dsn,
                restore_dsn=restore_dsn,
                archive=archive,
                manifest_path=manifest_path,
                runner=runner,
            )
            assert result == RestoreVerification(
                source_envelope_count=1,
                artifact_count=1,
                pointer_count=1,
            )
    finally:
        _drop_database(admin_dsn, restore_name)
        _drop_database(admin_dsn, source_name)
