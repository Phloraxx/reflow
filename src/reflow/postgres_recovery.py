from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from .persistence import _POINTER_ARTIFACT_KIND, PointerKind, PostgresApplicationStore

BACKUP_SCHEMA_VERSION = "reflow-postgres-logical-backup-v1"
MAX_MANIFEST_BYTES = 256 * 1024


class PostgresRecoveryError(RuntimeError):
    """A logical backup or restore verification failed closed."""


@dataclass(frozen=True, slots=True)
class BackupManifest:
    schema_version: str
    created_at: str
    archive_name: str
    archive_bytes: int
    archive_sha256: str
    pg_dump_version: str

    def to_json(self) -> str:
        return (
            json.dumps(
                asdict(self),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        )


@dataclass(frozen=True, slots=True)
class RestoreVerification:
    source_envelope_count: int
    artifact_count: int
    pointer_count: int


class CompletedTool(Protocol):
    returncode: int
    stdout: str
    stderr: str


ToolRunner = Callable[[Sequence[str], Mapping[str, str]], CompletedTool]


def _default_runner(command: Sequence[str], env: Mapping[str, str]) -> CompletedTool:
    return subprocess.run(
        list(command),
        env=dict(env),
        check=False,
        capture_output=True,
        text=True,
    )


def _private_file(path: Path) -> None:
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError as exc:
        raise PostgresRecoveryError("could not secure recovery output permissions") from exc


def _fsync_file(path: Path) -> None:
    try:
        with path.open("rb") as handle:
            os.fsync(handle.fileno())
    except OSError as exc:
        raise PostgresRecoveryError("could not sync recovery output") from exc


def _fsync_dir(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise PostgresRecoveryError("could not sync recovery directory") from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise PostgresRecoveryError("could not read recovery archive") from exc
    return digest.hexdigest()


_CONNINFO_ENV = {
    "host": "PGHOST",
    "hostaddr": "PGHOSTADDR",
    "port": "PGPORT",
    "dbname": "PGDATABASE",
    "user": "PGUSER",
    "password": "PGPASSWORD",
    "connect_timeout": "PGCONNECT_TIMEOUT",
    "sslmode": "PGSSLMODE",
    "sslcert": "PGSSLCERT",
    "sslkey": "PGSSLKEY",
    "sslrootcert": "PGSSLROOTCERT",
    "sslcrl": "PGSSLCRL",
    "sslcrldir": "PGSSLCRLDIR",
    "target_session_attrs": "PGTARGETSESSIONATTRS",
}


def _conninfo_params(dsn: str) -> dict[str, str]:
    if not isinstance(dsn, str) or not dsn or dsn != dsn.strip():
        raise PostgresRecoveryError("PostgreSQL DSN must be non-empty and trimmed")
    try:
        from psycopg.conninfo import conninfo_to_dict

        raw = conninfo_to_dict(dsn)
    except Exception as exc:
        raise PostgresRecoveryError("PostgreSQL DSN is invalid") from exc
    unsupported = set(raw) - set(_CONNINFO_ENV)
    if unsupported:
        raise PostgresRecoveryError("PostgreSQL DSN contains unsupported recovery options")
    return {key: str(value) for key, value in raw.items() if value is not None}


def _tool_env(dsn: str) -> dict[str, str]:
    params = _conninfo_params(dsn)
    env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    for key, value in params.items():
        env[_CONNINFO_ENV[key]] = value
    return env


def _database_identity(dsn: str) -> tuple[str, str, str]:
    params = _conninfo_params(dsn)
    database = params.get("dbname")
    if not database:
        raise PostgresRecoveryError("PostgreSQL recovery DSN must name a database")
    host = params.get("hostaddr") or params.get("host", "")
    return (host.lower(), params.get("port", "5432"), database)


def _run_checked(
    command: Sequence[str],
    *,
    env: Mapping[str, str],
    runner: ToolRunner,
    label: str,
) -> CompletedTool:
    try:
        result = runner(command, env)
    except OSError as exc:
        raise PostgresRecoveryError(f"{label} is unavailable") from exc
    if result.returncode != 0:
        raise PostgresRecoveryError(f"{label} failed")
    return result


def _tool_version(binary: str, *, runner: ToolRunner) -> str:
    if not isinstance(binary, str) or not binary or binary != binary.strip() or "\x00" in binary:
        raise PostgresRecoveryError("PostgreSQL tool path is invalid")
    result = _run_checked(
        [binary, "--version"],
        env={key: value for key, value in os.environ.items() if not key.startswith("PG")},
        runner=runner,
        label="PostgreSQL tool version check",
    )
    version = result.stdout.strip()
    if not version or len(version) > 256:
        raise PostgresRecoveryError("PostgreSQL tool version output is invalid")
    return version


def _secure_output_directory(output_dir: Path) -> None:
    if output_dir.exists() and output_dir.is_symlink():
        raise PostgresRecoveryError("backup output directory cannot be a symlink")
    try:
        output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        output_dir.chmod(0o700)
    except OSError as exc:
        raise PostgresRecoveryError("could not create secure backup output directory") from exc
    if not output_dir.is_dir():
        raise PostgresRecoveryError("backup output path must be a directory")


def _publish_no_replace(partial: Path, target: Path) -> None:
    if target.exists() or target.is_symlink():
        raise PostgresRecoveryError("backup output collision")
    try:
        os.link(partial, target)
        partial.unlink()
    except FileExistsError as exc:
        raise PostgresRecoveryError("backup output collision") from exc
    except OSError as exc:
        raise PostgresRecoveryError("could not publish recovery output") from exc
    _private_file(target)
    _fsync_dir(target.parent)


def create_logical_backup(
    *,
    dsn: str,
    output_dir: Path,
    readiness_probe: Callable[[], None],
    pg_dump_bin: str = "pg_dump",
    pg_restore_bin: str = "pg_restore",
    runner: ToolRunner = _default_runner,
    now: datetime | None = None,
) -> tuple[Path, Path, BackupManifest]:
    if not callable(readiness_probe):
        raise PostgresRecoveryError("backup readiness probe is invalid")
    try:
        readiness_probe()
    except Exception as exc:
        raise PostgresRecoveryError("PostgreSQL readiness check failed") from exc
    _secure_output_directory(output_dir)

    observed_at = now or datetime.now(tz=UTC)
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise PostgresRecoveryError("backup timestamp must be timezone-aware")
    stamp = observed_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    archive = output_dir / f"reflow-postgres-{stamp}.dump"
    manifest_path = archive.with_suffix(".manifest.json")
    partial = output_dir / f".{archive.name}.partial-{os.getpid()}"
    manifest_tmp = output_dir / f".{manifest_path.name}.partial-{os.getpid()}"
    if any(
        path.exists() or path.is_symlink()
        for path in (archive, manifest_path, partial, manifest_tmp)
    ):
        raise PostgresRecoveryError("backup output collision")

    version = _tool_version(pg_dump_bin, runner=runner)
    env = _tool_env(dsn)
    archive_published = False
    try:
        partial.touch(mode=0o600, exist_ok=False)
        _private_file(partial)
        _run_checked(
            [
                pg_dump_bin,
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                f"--file={partial}",
            ],
            env=env,
            runner=runner,
            label="pg_dump",
        )
        if not partial.is_file() or partial.stat().st_size < 1:
            raise PostgresRecoveryError("pg_dump did not produce a non-empty archive")
        _private_file(partial)
        _fsync_file(partial)
        _run_checked(
            [pg_restore_bin, "--list", str(partial)],
            env={key: value for key, value in os.environ.items() if not key.startswith("PG")},
            runner=runner,
            label="pg_restore archive verification",
        )
        _publish_no_replace(partial, archive)
        archive_published = True

        manifest = BackupManifest(
            schema_version=BACKUP_SCHEMA_VERSION,
            created_at=observed_at.astimezone(UTC).isoformat(),
            archive_name=archive.name,
            archive_bytes=archive.stat().st_size,
            archive_sha256=_sha256_file(archive),
            pg_dump_version=version,
        )
        manifest_tmp.write_text(manifest.to_json(), encoding="utf-8")
        _private_file(manifest_tmp)
        _fsync_file(manifest_tmp)
        _publish_no_replace(manifest_tmp, manifest_path)
        return archive, manifest_path, manifest
    except Exception:
        partial.unlink(missing_ok=True)
        manifest_tmp.unlink(missing_ok=True)
        if archive_published and not manifest_path.exists():
            archive.unlink(missing_ok=True)
            with suppress(PostgresRecoveryError):
                _fsync_dir(output_dir)
        raise


def _mode_is_private(path: Path) -> bool:
    return stat.S_IMODE(path.stat().st_mode) & 0o077 == 0


def load_manifest(path: Path) -> BackupManifest:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
            raise PostgresRecoveryError("backup manifest is invalid")
        if not _mode_is_private(path):
            raise PostgresRecoveryError("backup manifest permissions are too broad")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PostgresRecoveryError("backup manifest is invalid") from exc
    expected = {
        "schema_version",
        "created_at",
        "archive_name",
        "archive_bytes",
        "archive_sha256",
        "pg_dump_version",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise PostgresRecoveryError("backup manifest is invalid")
    if (
        not isinstance(payload["schema_version"], str)
        or not isinstance(payload["created_at"], str)
        or not isinstance(payload["archive_name"], str)
        or isinstance(payload["archive_bytes"], bool)
        or not isinstance(payload["archive_bytes"], int)
        or not isinstance(payload["archive_sha256"], str)
        or not isinstance(payload["pg_dump_version"], str)
    ):
        raise PostgresRecoveryError("backup manifest is invalid")
    manifest = BackupManifest(**payload)
    if manifest.schema_version != BACKUP_SCHEMA_VERSION:
        raise PostgresRecoveryError("backup manifest schema version is unsupported")
    if Path(manifest.archive_name).name != manifest.archive_name or not manifest.archive_name:
        raise PostgresRecoveryError("backup manifest archive name is invalid")
    if manifest.archive_bytes < 1:
        raise PostgresRecoveryError("backup manifest archive size is invalid")
    if len(manifest.archive_sha256) != 64 or any(
        char not in "0123456789abcdef" for char in manifest.archive_sha256
    ):
        raise PostgresRecoveryError("backup manifest checksum is invalid")
    try:
        created_at = datetime.fromisoformat(manifest.created_at)
    except ValueError as exc:
        raise PostgresRecoveryError("backup manifest timestamp is invalid") from exc
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise PostgresRecoveryError("backup manifest timestamp is invalid")
    if not manifest.pg_dump_version or len(manifest.pg_dump_version) > 256:
        raise PostgresRecoveryError("backup manifest tool version is invalid")
    return manifest


def verify_archive(
    *,
    archive: Path,
    manifest_path: Path,
    pg_restore_bin: str = "pg_restore",
    runner: ToolRunner = _default_runner,
) -> BackupManifest:
    manifest = load_manifest(manifest_path)
    try:
        if archive.is_symlink() or not archive.is_file():
            raise PostgresRecoveryError("backup archive does not match manifest")
        if not _mode_is_private(archive):
            raise PostgresRecoveryError("backup archive permissions are too broad")
        size = archive.stat().st_size
    except OSError as exc:
        raise PostgresRecoveryError("backup archive is unavailable") from exc
    if archive.name != manifest.archive_name or size != manifest.archive_bytes:
        raise PostgresRecoveryError("backup archive does not match manifest")
    if _sha256_file(archive) != manifest.archive_sha256:
        raise PostgresRecoveryError("backup archive checksum does not match manifest")
    _run_checked(
        [pg_restore_bin, "--list", str(archive)],
        env={key: value for key, value in os.environ.items() if not key.startswith("PG")},
        runner=runner,
        label="pg_restore archive verification",
    )
    return manifest


def require_empty_restore_database(dsn: str) -> None:
    try:
        import psycopg

        with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                """
            )
            row = cursor.fetchone()
    except Exception as exc:
        raise PostgresRecoveryError("restore database preflight failed") from exc
    if row is None or isinstance(row[0], bool) or not isinstance(row[0], int):
        raise PostgresRecoveryError("restore database preflight returned invalid data")
    if row[0] != 0:
        raise PostgresRecoveryError("restore database must contain zero user tables")


def inspect_restored_database(dsn: str) -> RestoreVerification:
    store = PostgresApplicationStore(dsn, initialize=False)
    try:
        store.check_ready()
        envelopes = store.entries()
        envelope_ids = {str(item.id) for item in envelopes}
        identities: set[tuple[object, str]] = set()
        for envelope in envelopes:
            if store.get_by_id(envelope.id) != envelope:
                raise PostgresRecoveryError("restored source envelope failed exact readback")
            identity = (envelope.source_kind, envelope.source_record_id)
            if identity not in identities:
                primary = store.get(envelope.source_kind, envelope.source_record_id)
                if primary is None or str(primary.id) not in envelope_ids:
                    raise PostgresRecoveryError("restored source identity is unresolved")
                identities.add(identity)

        connection = store._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT artifact_id FROM reflow_artifacts ORDER BY artifact_id")
                artifact_rows = cursor.fetchall()
                cursor.execute(
                    """
                    SELECT pointer_kind, stream_key, artifact_id
                    FROM reflow_current_pointers
                    ORDER BY pointer_kind, stream_key
                    """
                )
                pointer_rows = cursor.fetchall()
                cursor.execute("SELECT COUNT(*) FROM reflow_source_identity")
                identity_row = cursor.fetchone()
        finally:
            connection.close()

        if (
            identity_row is None
            or isinstance(identity_row[0], bool)
            or not isinstance(identity_row[0], int)
            or identity_row[0] != len(identities)
        ):
            raise PostgresRecoveryError("restored source identity inventory is inconsistent")

        artifact_count = 0
        for row in artifact_rows:
            if len(row) != 1 or not isinstance(row[0], str):
                raise PostgresRecoveryError("restored artifact inventory is invalid")
            if store.get_artifact(row[0]) is None:
                raise PostgresRecoveryError("restored artifact failed exact readback")
            artifact_count += 1

        pointer_count = 0
        for row in pointer_rows:
            if len(row) != 3:
                raise PostgresRecoveryError("restored pointer inventory is invalid")
            kind_value, stream_key, artifact_id = row
            if (
                not isinstance(kind_value, str)
                or not isinstance(stream_key, str)
                or not isinstance(artifact_id, str)
            ):
                raise PostgresRecoveryError("restored pointer inventory is invalid")
            try:
                kind = PointerKind(kind_value)
            except ValueError as exc:
                raise PostgresRecoveryError("restored pointer kind is invalid") from exc
            pointer = store.get_pointer(kind=kind, stream_key=stream_key)
            if pointer is None or pointer.artifact_id != artifact_id:
                raise PostgresRecoveryError("restored pointer failed exact readback")
            target = store.get_artifact(pointer.artifact_id)
            if target is None or target.kind is not _POINTER_ARTIFACT_KIND[kind]:
                raise PostgresRecoveryError("restored pointer target kind is invalid")
            pointer_count += 1

        return RestoreVerification(len(envelopes), artifact_count, pointer_count)
    except PostgresRecoveryError:
        raise
    except Exception as exc:
        raise PostgresRecoveryError("restored database integrity verification failed") from exc


def restore_and_verify(
    *,
    source_dsn: str,
    restore_dsn: str,
    archive: Path,
    manifest_path: Path,
    pg_restore_bin: str = "pg_restore",
    runner: ToolRunner = _default_runner,
    target_preflight: Callable[[str], None] = require_empty_restore_database,
    integrity_probe: Callable[[str], RestoreVerification] = inspect_restored_database,
) -> RestoreVerification:
    source_identity = _database_identity(source_dsn)
    restore_identity = _database_identity(restore_dsn)
    if source_identity == restore_identity or source_identity[2] == restore_identity[2]:
        raise PostgresRecoveryError("restore database must be separate from source database")
    verify_archive(
        archive=archive,
        manifest_path=manifest_path,
        pg_restore_bin=pg_restore_bin,
        runner=runner,
    )
    if not callable(target_preflight) or not callable(integrity_probe):
        raise PostgresRecoveryError("restore verification probe is invalid")
    try:
        target_preflight(restore_dsn)
    except PostgresRecoveryError:
        raise
    except Exception as exc:
        raise PostgresRecoveryError("restore database preflight failed") from exc

    restore_params = _conninfo_params(restore_dsn)
    database = restore_params.get("dbname")
    if not database:
        raise PostgresRecoveryError("restore database name is required")
    _run_checked(
        [
            pg_restore_bin,
            "--exit-on-error",
            "--no-owner",
            "--no-privileges",
            f"--dbname={database}",
            str(archive),
        ],
        env=_tool_env(restore_dsn),
        runner=runner,
        label="pg_restore",
    )
    try:
        return integrity_probe(restore_dsn)
    except PostgresRecoveryError:
        raise
    except Exception as exc:
        raise PostgresRecoveryError("restored database integrity verification failed") from exc


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip() or value != value.strip():
        raise PostgresRecoveryError(f"{name} must be configured")
    return value


def _tool_path(env_name: str, default: str) -> str:
    value = os.getenv(env_name, default)
    if not value or value != value.strip() or "\x00" in value:
        raise PostgresRecoveryError(f"{env_name} is invalid")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create and restore-test ReFlow PostgreSQL logical backups"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    backup = sub.add_parser("backup", help="create an atomic custom-format logical backup")
    backup.add_argument("--output-dir", type=Path, required=True)
    restore = sub.add_parser("restore-verify", help="restore into a separate empty database")
    restore.add_argument("--archive", type=Path, required=True)
    restore.add_argument("--manifest", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    pg_restore_bin = _tool_path("REFLOW_PG_RESTORE_BIN", "pg_restore")
    try:
        source_dsn = _required_env("REFLOW_POSTGRES_DSN")
        if args.command == "backup":
            store = PostgresApplicationStore(source_dsn, initialize=False)
            archive, manifest_path, manifest = create_logical_backup(
                dsn=source_dsn,
                output_dir=args.output_dir,
                readiness_probe=store.check_ready,
                pg_dump_bin=_tool_path("REFLOW_PG_DUMP_BIN", "pg_dump"),
                pg_restore_bin=pg_restore_bin,
            )
            print(
                json.dumps(
                    {
                        "status": "backup_verified",
                        "archive": str(archive),
                        "manifest": str(manifest_path),
                        "archive_bytes": manifest.archive_bytes,
                        "archive_sha256": manifest.archive_sha256,
                    },
                    sort_keys=True,
                )
            )
            return

        restore_dsn = _required_env("REFLOW_RESTORE_POSTGRES_DSN")
        result = restore_and_verify(
            source_dsn=source_dsn,
            restore_dsn=restore_dsn,
            archive=args.archive,
            manifest_path=args.manifest,
            pg_restore_bin=pg_restore_bin,
        )
        print(
            json.dumps(
                {
                    "status": "restore_verified",
                    "source_envelope_count": result.source_envelope_count,
                    "artifact_count": result.artifact_count,
                    "pointer_count": result.pointer_count,
                },
                sort_keys=True,
            )
        )
    except PostgresRecoveryError as exc:
        raise SystemExit(f"recovery error: {exc}") from None


if __name__ == "__main__":
    main()
