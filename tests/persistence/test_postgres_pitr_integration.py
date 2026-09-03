from __future__ import annotations

import os
import subprocess
import time
import uuid

import pytest

POSTGRES_IMAGE = (
    "postgres:16.15-alpine@sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685"
)
DB_USER = "reflow_pitr"
DB_PASSWORD = "reflow_pitr"
DB_NAME = "reflow_pitr"
RESTORE_POINT = "reflow_before_late_change"


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _wait_ready(container: str) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        result = _docker(
            "exec",
            container,
            "psql",
            "-U",
            DB_USER,
            "-d",
            DB_NAME,
            "-At",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "SELECT 1;",
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip() == "1":
            return
        time.sleep(0.5)
    raise AssertionError("PostgreSQL PITR container did not become ready")


def _wait_promoted(container: str) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        result = _docker(
            "exec",
            container,
            "psql",
            "-U",
            DB_USER,
            "-d",
            DB_NAME,
            "-At",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "SELECT pg_is_in_recovery();",
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip() == "f":
            return
        time.sleep(0.25)
    raise AssertionError("PostgreSQL PITR recovery target did not finish promotion")


def _psql(container: str, sql: str) -> str:
    result = _docker(
        "exec",
        container,
        "psql",
        "-U",
        DB_USER,
        "-d",
        DB_NAME,
        "-At",
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        sql,
    )
    return result.stdout.strip().replace("\r", "")


def _wait_archived(container: str, wal_name: str) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        result = _docker(
            "exec",
            container,
            "test",
            "-f",
            f"/archive/{wal_name}",
            check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(0.5)
    raise AssertionError("required WAL segment was not archived")


def _cleanup(containers: tuple[str, ...], volumes: tuple[str, ...]) -> None:
    _docker("rm", "-f", *containers, check=False)
    _docker("volume", "rm", "-f", *volumes, check=False)


def test_real_postgres16_named_restore_point_pitr_drill() -> None:
    if os.getenv("REFLOW_RECOVERY_DOCKER_DRILL") != "1":
        pytest.skip("real PostgreSQL PITR drill is enabled only in CI")

    suffix = uuid.uuid4().hex[:12]
    primary = f"reflow-pitr-primary-{suffix}"
    recovered = f"reflow-pitr-recovered-{suffix}"
    data_volume = f"reflow-pitr-data-{suffix}"
    archive_volume = f"reflow-pitr-archive-{suffix}"
    backup_volume = f"reflow-pitr-backup-{suffix}"
    containers = (primary, recovered)
    volumes = (data_volume, archive_volume, backup_volume)

    _cleanup(containers, volumes)
    try:
        for volume in volumes:
            _docker("volume", "create", volume)
        _docker(
            "run",
            "--rm",
            "--user",
            "0",
            "-v",
            f"{archive_volume}:/archive",
            "-v",
            f"{backup_volume}:/backup",
            POSTGRES_IMAGE,
            "sh",
            "-ec",
            "chown postgres:postgres /archive /backup; chmod 700 /archive /backup",
        )
        _docker(
            "run",
            "-d",
            "--name",
            primary,
            "-e",
            f"POSTGRES_USER={DB_USER}",
            "-e",
            f"POSTGRES_PASSWORD={DB_PASSWORD}",
            "-e",
            f"POSTGRES_DB={DB_NAME}",
            "-v",
            f"{data_volume}:/var/lib/postgresql/data",
            "-v",
            f"{archive_volume}:/archive",
            "-v",
            f"{backup_volume}:/backup",
            POSTGRES_IMAGE,
            "-c",
            "wal_level=replica",
            "-c",
            "archive_mode=on",
            "-c",
            "archive_command=test ! -f /archive/%f && cp %p /archive/%f",
            "-c",
            "archive_timeout=1s",
        )
        _wait_ready(primary)
        _psql(
            primary,
            "CREATE TABLE pitr_probe(id integer primary key, marker text not null); "
            "INSERT INTO pitr_probe VALUES (1, 'baseline');",
        )
        _docker(
            "exec",
            primary,
            "pg_basebackup",
            "-U",
            DB_USER,
            "-D",
            "/backup",
            "-Fp",
            "-X",
            "stream",
            "-c",
            "fast",
        )

        _psql(primary, f"SELECT pg_create_restore_point('{RESTORE_POINT}');")
        wal_before_late = _psql(primary, "SELECT pg_walfile_name(pg_switch_wal());")
        _wait_archived(primary, wal_before_late)

        _psql(primary, "INSERT INTO pitr_probe VALUES (2, 'late');")
        wal_after_late = _psql(primary, "SELECT pg_walfile_name(pg_switch_wal());")
        _wait_archived(primary, wal_after_late)
        assert wal_before_late != wal_after_late

        _docker("stop", primary)
        _docker(
            "run",
            "--rm",
            "--user",
            "0",
            "-v",
            f"{backup_volume}:/var/lib/postgresql/data",
            POSTGRES_IMAGE,
            "sh",
            "-ec",
            "cat >>/var/lib/postgresql/data/postgresql.auto.conf <<'EOF'\n"
            "restore_command = 'cp /archive/%f %p'\n"
            f"recovery_target_name = '{RESTORE_POINT}'\n"
            "recovery_target_action = 'promote'\n"
            "EOF\n"
            "touch /var/lib/postgresql/data/recovery.signal\n"
            "chown postgres:postgres /var/lib/postgresql/data/postgresql.auto.conf "
            "/var/lib/postgresql/data/recovery.signal",
        )
        _docker(
            "run",
            "-d",
            "--name",
            recovered,
            "-v",
            f"{backup_volume}:/var/lib/postgresql/data",
            "-v",
            f"{archive_volume}:/archive:ro",
            POSTGRES_IMAGE,
        )
        _wait_ready(recovered)
        _wait_promoted(recovered)

        rows = _psql(
            recovered,
            "SELECT id || '=' || marker FROM pitr_probe ORDER BY id;",
        )
        assert rows == "1=baseline"
        assert _psql(recovered, "SELECT pg_is_in_recovery();") == "f"
    finally:
        _cleanup(containers, volumes)
