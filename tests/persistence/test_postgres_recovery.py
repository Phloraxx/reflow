from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from reflow import domain
from reflow.journal import make_source_envelope
from reflow.persistence import ArtifactKind, PointerKind, PostgresApplicationStore
from reflow.postgres_recovery import (
    BACKUP_SCHEMA_VERSION,
    BackupManifest,
    PostgresRecoveryError,
    RestoreVerification,
    _tool_env,
    create_logical_backup,
    inspect_restored_database,
    load_manifest,
    require_empty_restore_database,
    restore_and_verify,
    verify_archive,
)

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
DSN = os.getenv("REFLOW_TEST_POSTGRES_DSN")


@dataclass
class FakeResult:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


class FakeRunner:
    def __init__(self, *, fail_dump: bool = False) -> None:
        self.fail_dump = fail_dump
        self.calls: list[tuple[tuple[str, ...], dict[str, str]]] = []

    def __call__(self, command, env):
        args = tuple(command)
        copied_env = dict(env)
        self.calls.append((args, copied_env))
        if "--version" in args:
            return FakeResult(stdout="pg_dump (PostgreSQL) 16.15\n")
        output = next(
            (item.removeprefix("--file=") for item in args if item.startswith("--file=")),
            None,
        )
        if output is not None:
            if self.fail_dump:
                return FakeResult(returncode=1, stderr="sensitive detail")
            Path(output).write_bytes(b"PGDMP fake custom archive")
        return FakeResult()


def test_backup_is_private_atomic_and_keeps_credentials_out_of_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PGHOST", "wrong.example")
    monkeypatch.setenv("PGDATABASE", "wrong_database")
    monkeypatch.setenv("PGPASSWORD", "wrong-password")
    monkeypatch.setenv("PGSERVICE", "wrong-service")
    runner = FakeRunner()
    probes = 0

    def ready() -> None:
        nonlocal probes
        probes += 1

    dsn = "postgresql://backup_user:super-secret@example.invalid:5433/reflow"
    archive, manifest_path, manifest = create_logical_backup(
        dsn=dsn,
        output_dir=tmp_path / "backups",
        readiness_probe=ready,
        runner=runner,
        now=NOW,
    )

    assert probes == 1
    assert archive.is_file() and manifest_path.is_file()
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600
    assert stat.S_IMODE(manifest_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(archive.parent.stat().st_mode) == 0o700
    assert manifest.archive_bytes == archive.stat().st_size
    assert json.loads(manifest_path.read_text())["archive_sha256"] == manifest.archive_sha256

    flattened = "\n".join(" ".join(command) for command, _env in runner.calls)
    assert "super-secret" not in flattened
    assert dsn not in flattened
    dump_env = next(
        env for command, env in runner.calls if any(arg.startswith("--file=") for arg in command)
    )
    assert dump_env["PGHOST"] == "example.invalid"
    assert dump_env["PGPORT"] == "5433"
    assert dump_env["PGDATABASE"] == "reflow"
    assert dump_env["PGUSER"] == "backup_user"
    assert dump_env["PGPASSWORD"] == "super-secret"
    assert "PGSERVICE" not in dump_env
    assert "wrong-password" not in dump_env.values()
    assert "super-secret" not in manifest_path.read_text()
    assert "example.invalid" not in manifest_path.read_text()
    assert not list(archive.parent.glob("*.partial-*"))


def test_backup_failure_removes_partial_output(tmp_path: Path) -> None:
    runner = FakeRunner(fail_dump=True)
    with pytest.raises(PostgresRecoveryError, match="pg_dump failed"):
        create_logical_backup(
            dsn="postgresql://u:p@example.invalid/reflow",
            output_dir=tmp_path,
            readiness_probe=lambda: None,
            runner=runner,
            now=NOW,
        )
    assert list(tmp_path.iterdir()) == []


def test_backup_refuses_collision_without_overwriting(tmp_path: Path) -> None:
    runner = FakeRunner()
    archive, manifest_path, _manifest = create_logical_backup(
        dsn="postgresql://u:p@example.invalid/reflow",
        output_dir=tmp_path,
        readiness_probe=lambda: None,
        runner=runner,
        now=NOW,
    )
    original_archive = archive.read_bytes()
    original_manifest = manifest_path.read_bytes()
    with pytest.raises(PostgresRecoveryError, match="collision"):
        create_logical_backup(
            dsn="postgresql://u:p@example.invalid/reflow",
            output_dir=tmp_path,
            readiness_probe=lambda: None,
            runner=runner,
            now=NOW,
        )
    assert archive.read_bytes() == original_archive
    assert manifest_path.read_bytes() == original_manifest


def test_verify_archive_rejects_tampering_before_restore_tool(tmp_path: Path) -> None:
    runner = FakeRunner()
    archive, manifest_path, _manifest = create_logical_backup(
        dsn="postgresql://u:p@example.invalid/reflow",
        output_dir=tmp_path,
        readiness_probe=lambda: None,
        runner=runner,
        now=NOW,
    )
    calls_before = len(runner.calls)
    archive.write_bytes(archive.read_bytes() + b"tampered")
    with pytest.raises(PostgresRecoveryError, match="does not match manifest"):
        verify_archive(archive=archive, manifest_path=manifest_path, runner=runner)
    assert len(runner.calls) == calls_before


def test_restore_uses_separate_empty_target_and_secret_free_argv(tmp_path: Path) -> None:
    backup_runner = FakeRunner()
    archive, manifest_path, _manifest = create_logical_backup(
        dsn="postgresql://source:secret@example.invalid/source",
        output_dir=tmp_path,
        readiness_probe=lambda: None,
        runner=backup_runner,
        now=NOW,
    )
    restore_runner = FakeRunner()
    restore_dsn = "postgresql://restore:other-secret@example.invalid/restore"
    preflight: list[str] = []
    result = restore_and_verify(
        source_dsn="postgresql://source:secret@example.invalid/source",
        restore_dsn=restore_dsn,
        archive=archive,
        manifest_path=manifest_path,
        runner=restore_runner,
        target_preflight=lambda dsn: preflight.append(dsn),
        integrity_probe=lambda _dsn: RestoreVerification(7, 11, 3),
    )
    assert result == RestoreVerification(7, 11, 3)
    assert preflight == [restore_dsn]
    restore_call, restore_env = next(
        (command, env) for command, env in restore_runner.calls if "--exit-on-error" in command
    )
    flattened = " ".join(restore_call)
    assert "--dbname=restore" in restore_call
    assert "other-secret" not in flattened
    assert restore_dsn not in flattened
    assert restore_env["PGDATABASE"] == "restore"
    assert restore_env["PGHOST"] == "example.invalid"
    assert restore_env["PGUSER"] == "restore"
    assert restore_env["PGPASSWORD"] == "other-secret"


def test_restore_refuses_same_database_before_tool_execution(tmp_path: Path) -> None:
    runner = FakeRunner()
    archive, manifest_path, _manifest = create_logical_backup(
        dsn="postgresql://u:p@example.invalid/reflow",
        output_dir=tmp_path,
        readiness_probe=lambda: None,
        runner=runner,
        now=NOW,
    )
    calls_before = len(runner.calls)
    with pytest.raises(PostgresRecoveryError, match="separate from source"):
        restore_and_verify(
            source_dsn="postgresql://source:a@localhost/reflow",
            restore_dsn="postgresql://restore:b@127.0.0.1/reflow",
            archive=archive,
            manifest_path=manifest_path,
            runner=runner,
            target_preflight=lambda _dsn: None,
            integrity_probe=lambda _dsn: RestoreVerification(0, 0, 0),
        )
    assert len(runner.calls) == calls_before


def test_restore_preflight_failure_prevents_restore_command(tmp_path: Path) -> None:
    backup_runner = FakeRunner()
    archive, manifest_path, _manifest = create_logical_backup(
        dsn="postgresql://source:s@example.invalid/source",
        output_dir=tmp_path,
        readiness_probe=lambda: None,
        runner=backup_runner,
        now=NOW,
    )
    restore_runner = FakeRunner()

    def reject(_dsn: str) -> None:
        raise PostgresRecoveryError("restore database must contain zero user tables")

    with pytest.raises(PostgresRecoveryError, match="zero user tables"):
        restore_and_verify(
            source_dsn="postgresql://source:s@example.invalid/source",
            restore_dsn="postgresql://restore:r@example.invalid/restore",
            archive=archive,
            manifest_path=manifest_path,
            runner=restore_runner,
            target_preflight=reject,
            integrity_probe=lambda _dsn: RestoreVerification(0, 0, 0),
        )
    assert not any("--exit-on-error" in command for command, _env in restore_runner.calls)


def test_tool_env_ignores_inherited_postgres_connection_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PGHOST", "wrong.example")
    monkeypatch.setenv("PGDATABASE", "wrong_database")
    monkeypatch.setenv("PGPASSWORD", "wrong-password")
    monkeypatch.setenv("PGSERVICE", "wrong-service")
    env = _tool_env("postgresql://user:secret@example.invalid:5433/reflow")
    assert env["PGHOST"] == "example.invalid"
    assert env["PGPORT"] == "5433"
    assert env["PGDATABASE"] == "reflow"
    assert env["PGUSER"] == "user"
    assert env["PGPASSWORD"] == "secret"
    assert "PGSERVICE" not in env


def test_manifest_rejects_boolean_archive_size(tmp_path: Path) -> None:
    archive = tmp_path / "backup.dump"
    archive.write_bytes(b"x")
    archive.chmod(0o600)
    manifest = BackupManifest(
        schema_version=BACKUP_SCHEMA_VERSION,
        created_at=NOW.isoformat(),
        archive_name=archive.name,
        archive_bytes=1,
        archive_sha256="0" * 64,
        pg_dump_version="pg_dump (PostgreSQL) 16.15",
    )
    manifest_path = tmp_path / "backup.manifest.json"
    payload = json.loads(manifest.to_json())
    payload["archive_bytes"] = True
    manifest_path.write_text(json.dumps(payload))
    manifest_path.chmod(0o600)
    with pytest.raises(PostgresRecoveryError, match="manifest is invalid"):
        load_manifest(manifest_path)


def _require_dsn() -> str:
    if not DSN:
        pytest.skip("REFLOW_TEST_POSTGRES_DSN is not configured")
    return DSN


def test_restored_database_integrity_inventory_uses_public_readback() -> None:
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

    envelope = make_source_envelope(
        source_kind=domain.SourceKind.BANK,
        source_record_id="bank_recovery_probe",
        occurred_at=NOW,
        received_at=NOW,
        schema_version="recovery-probe-v1",
        payload={"amount_paise": 123, "currency": "INR"},
    )
    store.append(envelope)
    store.put_artifact(
        kind=ArtifactKind.POLICY_VERSION,
        artifact_id="policy_recovery_probe",
        payload={"probe": "recovery"},
        scope_id=None,
        observed_at=NOW,
    )
    store.advance_pointer(
        kind=PointerKind.LATEST_POLICY,
        stream_key="scope_recovery_probe",
        artifact_id="policy_recovery_probe",
        expected_generation=0,
    )

    result = inspect_restored_database(dsn)
    assert result == RestoreVerification(1, 1, 1)
    with pytest.raises(PostgresRecoveryError, match="zero user tables"):
        require_empty_restore_database(dsn)
