from __future__ import annotations

import hashlib
import importlib
import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, Self, cast

from . import domain
from .journal import (
    AppendDisposition,
    AppendResult,
    Journal,
    JournalConflictError,
)

POSTGRES_SCHEMA_VERSION = 3

__all__ = [
    "POSTGRES_SCHEMA_VERSION",
    "ApplicationCapabilities",
    "ArtifactKind",
    "ArtifactPage",
    "ArtifactPageCursor",
    "ArtifactWriteDisposition",
    "ArtifactWriteResult",
    "CaseWorkflowCommandResult",
    "CurrentPointer",
    "PersistenceConflictError",
    "PersistenceError",
    "PersistenceIntegrityError",
    "PointerKind",
    "PostgresApplicationStore",
    "ReflowApplicationService",
    "StalePointerError",
    "StoredArtifact",
    "approved_adapter_artifact_id",
    "canonical_artifact_json",
    "canonical_artifact_sha256",
]


class PersistenceError(RuntimeError):
    """Durable application state violated a Gate 17 persistence invariant."""


class PersistenceConflictError(PersistenceError):
    """One immutable application identity was reused for different content."""


class PersistenceIntegrityError(PersistenceError):
    """Persisted content failed canonical digest or typed reconstruction checks."""


class StalePointerError(PersistenceError):
    """A current-pointer compare-and-swap used a stale generation."""


class ArtifactKind(StrEnum):
    RECONCILIATION_SCOPE = "reconciliation_scope"
    POLICY_VERSION = "policy_version"
    SOURCE_DELIVERY_MANIFEST = "source_delivery_manifest"
    EVIDENCE_COVERAGE = "evidence_coverage"
    BALANCE_CONTROL = "balance_control"
    CLOSE_READINESS = "close_readiness"
    RECONCILIATION_RUN = "reconciliation_run"
    PROOF_VERSION = "proof_version"
    CASE_OBSERVATION = "case_observation"
    CASE_DISPOSITION = "case_disposition"
    INCIDENT_CLUSTER = "incident_cluster"
    APPROVED_ADAPTER = "approved_adapter"
    INVESTIGATION_RESULT = "investigation_result"
    INVESTIGATION_TRACE = "investigation_trace"


class ArtifactWriteDisposition(StrEnum):
    STORED = "stored"
    DUPLICATE = "duplicate"


class PointerKind(StrEnum):
    LATEST_POLICY = "latest_policy"
    LATEST_RUN = "latest_run"
    LATEST_PROOF = "latest_proof"
    LATEST_CASE_OBSERVATION = "latest_case_observation"
    LATEST_CASE_DISPOSITION = "latest_case_disposition"
    LATEST_ADAPTER = "latest_adapter"
    LATEST_INVESTIGATION = "latest_investigation"


_POINTER_ARTIFACT_KIND: dict[PointerKind, ArtifactKind] = {
    PointerKind.LATEST_POLICY: ArtifactKind.POLICY_VERSION,
    PointerKind.LATEST_RUN: ArtifactKind.RECONCILIATION_RUN,
    PointerKind.LATEST_PROOF: ArtifactKind.PROOF_VERSION,
    PointerKind.LATEST_CASE_OBSERVATION: ArtifactKind.CASE_OBSERVATION,
    PointerKind.LATEST_CASE_DISPOSITION: ArtifactKind.CASE_DISPOSITION,
    PointerKind.LATEST_ADAPTER: ArtifactKind.APPROVED_ADAPTER,
    PointerKind.LATEST_INVESTIGATION: ArtifactKind.INVESTIGATION_RESULT,
}


def _aware(value: datetime, label: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{label} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise PersistenceError(f"{label} must be timezone-aware")


def _text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PersistenceError(f"{label} must be a non-empty string")
    if value != value.strip():
        raise PersistenceError(f"{label} must be trimmed")
    return value


def _request_id_digest(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 32
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise PersistenceError("case workflow request id must be lowercase 32-hex")
    return value


def _sha256_digest(value: str, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise PersistenceError(f"{label} must be lowercase SHA-256")
    return value


def _jsonable(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError("persistence payload cannot contain non-finite float")
        return value
    if isinstance(value, datetime):
        _aware(value, "persisted datetime")
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, domain.EntityId):
        return str(value)
    if isinstance(value, Mapping):
        rendered: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("persistence mapping keys must be strings")
            rendered[key] = _jsonable(item)
        return {key: rendered[key] for key in sorted(rendered)}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        items = [_jsonable(item) for item in value]
        return sorted(items, key=lambda item: _canonical_json_bytes(item))
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _jsonable(getattr(value, field.name)) for field in fields(cast(Any, value))
        }
    raise TypeError(f"unsupported persistence payload value {type(value).__name__}")


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        _jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def canonical_artifact_json(value: object) -> str:
    rendered = _jsonable(value)
    if not isinstance(rendered, dict):
        raise TypeError("artifact payload root must be an object")
    return json.dumps(
        rendered,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_artifact_sha256(value: object) -> str:
    return hashlib.sha256(canonical_artifact_json(value).encode()).hexdigest()


def _decode_json_object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, str):
        raise PersistenceIntegrityError(f"{label} JSON must be text")
    try:
        decoded: object = json.loads(value)
    except json.JSONDecodeError as exc:
        raise PersistenceIntegrityError(f"{label} JSON is invalid") from exc
    if not isinstance(decoded, dict) or any(not isinstance(key, str) for key in decoded):
        raise PersistenceIntegrityError(f"{label} JSON root must be an object")
    return decoded


@dataclass(frozen=True, slots=True)
class ArtifactPageCursor:
    observed_at: datetime | None
    artifact_id: str

    def __post_init__(self) -> None:
        if self.observed_at is not None:
            _aware(self.observed_at, "artifact page cursor observed_at")
        _text(self.artifact_id, "artifact page cursor artifact id")


@dataclass(frozen=True, slots=True)
class ArtifactPage:
    items: tuple[StoredArtifact, ...]
    next_cursor: ArtifactPageCursor | None


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    artifact_id: str
    kind: ArtifactKind
    scope_id: domain.ReconciliationScopeId | None
    observed_at: datetime | None
    payload_sha256: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        _text(self.artifact_id, "artifact id")
        if not isinstance(self.kind, ArtifactKind):
            raise TypeError("artifact kind must be ArtifactKind")
        if self.scope_id is not None and not isinstance(
            self.scope_id, domain.ReconciliationScopeId
        ):
            raise TypeError("artifact scope must be ReconciliationScopeId")
        if self.observed_at is not None:
            _aware(self.observed_at, "artifact observed_at")
        if len(self.payload_sha256) != 64:
            raise PersistenceIntegrityError("artifact digest must be SHA-256")
        try:
            int(self.payload_sha256, 16)
        except ValueError as exc:
            raise PersistenceIntegrityError("artifact digest must be hexadecimal") from exc
        if canonical_artifact_sha256(self.payload) != self.payload_sha256:
            raise PersistenceIntegrityError("artifact payload digest does not match stored content")


@dataclass(frozen=True, slots=True)
class ArtifactWriteResult:
    disposition: ArtifactWriteDisposition
    artifact: StoredArtifact


@dataclass(frozen=True, slots=True)
class CaseWorkflowCommandResult:
    artifact: StoredArtifact
    committed_generation: int
    replayed: bool

    def __post_init__(self) -> None:
        if self.artifact.kind is not ArtifactKind.CASE_DISPOSITION:
            raise PersistenceIntegrityError(
                "case workflow command must reference a case disposition"
            )
        if (
            isinstance(self.committed_generation, bool)
            or not isinstance(self.committed_generation, int)
            or self.committed_generation < 1
        ):
            raise PersistenceIntegrityError(
                "case workflow committed generation must be positive"
            )
        if not isinstance(self.replayed, bool):
            raise TypeError("case workflow replayed must be bool")


@dataclass(frozen=True, slots=True)
class CurrentPointer:
    kind: PointerKind
    stream_key: str
    artifact_id: str
    generation: int
    updated_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.kind, PointerKind):
            raise TypeError("pointer kind must be PointerKind")
        _text(self.stream_key, "pointer stream key")
        _text(self.artifact_id, "pointer artifact id")
        if isinstance(self.generation, bool) or not isinstance(self.generation, int):
            raise TypeError("pointer generation must be int")
        if self.generation < 1:
            raise PersistenceIntegrityError("pointer generation must be positive")
        _aware(self.updated_at, "pointer updated_at")


@dataclass(frozen=True, slots=True)
class ApplicationCapabilities:
    database: str
    schema_version: int
    raw_evidence_append_only: bool
    immutable_artifacts: bool
    optimistic_current_pointers: bool
    generic_sql_exposed: bool
    financial_truth_mutation: bool

    def __post_init__(self) -> None:
        if self.database != "postgresql":
            raise PersistenceIntegrityError("Gate 17 durable service must report PostgreSQL")
        if self.schema_version != POSTGRES_SCHEMA_VERSION:
            raise PersistenceIntegrityError("application schema version mismatch")
        if not (
            self.raw_evidence_append_only
            and self.immutable_artifacts
            and self.optimistic_current_pointers
        ):
            raise PersistenceIntegrityError("application durability capabilities are incomplete")
        if self.generic_sql_exposed or self.financial_truth_mutation:
            raise PersistenceIntegrityError("application capability surface is too powerful")


class _Cursor(Protocol):
    def execute(self, query: str, params: object | None = None) -> Self: ...

    def fetchone(self) -> tuple[object, ...] | None: ...

    def fetchall(self) -> list[tuple[object, ...]]: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: object | None,
        exc_value: object | None,
        traceback: object | None,
    ) -> object | None: ...


class _Connection(Protocol):
    def cursor(self) -> _Cursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...


ConnectionFactory = Callable[[str], _Connection]


def _default_connection_factory(dsn: str) -> _Connection:
    try:
        module = importlib.import_module("psycopg")
    except ModuleNotFoundError as exc:
        raise PersistenceError(
            "PostgreSQL support requires the optional 'postgres' dependency"
        ) from exc
    connect = getattr(module, "connect", None)
    if not callable(connect):
        raise PersistenceError("psycopg.connect is unavailable")
    return cast(_Connection, connect(dsn))


_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS reflow_schema_meta (
        singleton SMALLINT PRIMARY KEY CHECK (singleton = 1),
        schema_version INTEGER NOT NULL CHECK (schema_version > 0)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reflow_source_envelopes (
        envelope_id TEXT PRIMARY KEY,
        source_kind TEXT NOT NULL,
        source_record_id TEXT NOT NULL,
        occurred_at TIMESTAMPTZ NULL,
        received_at TIMESTAMPTZ NOT NULL,
        payload_sha256 CHAR(64) NOT NULL,
        schema_version TEXT NOT NULL,
        payload_json JSONB NOT NULL,
        UNIQUE (source_kind, source_record_id, payload_sha256)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reflow_source_identity (
        source_kind TEXT NOT NULL,
        source_record_id TEXT NOT NULL,
        primary_envelope_id TEXT NOT NULL REFERENCES reflow_source_envelopes(envelope_id),
        PRIMARY KEY (source_kind, source_record_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reflow_artifacts (
        artifact_id TEXT PRIMARY KEY,
        artifact_kind TEXT NOT NULL,
        scope_id TEXT NULL,
        observed_at TIMESTAMPTZ NULL,
        payload_sha256 CHAR(64) NOT NULL,
        payload_json JSONB NOT NULL,
        stored_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS reflow_artifacts_kind_scope_idx
        ON reflow_artifacts (artifact_kind, scope_id, observed_at, artifact_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS reflow_current_pointers (
        pointer_kind TEXT NOT NULL,
        stream_key TEXT NOT NULL,
        artifact_id TEXT NOT NULL REFERENCES reflow_artifacts(artifact_id),
        generation BIGINT NOT NULL CHECK (generation > 0),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (pointer_kind, stream_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reflow_case_workflow_commands (
        principal_subject_sha256 CHAR(64) NOT NULL,
        command_key_sha256 CHAR(64) NOT NULL,
        request_sha256 CHAR(64) NOT NULL,
        request_id CHAR(32) NOT NULL,
        scope_id TEXT NOT NULL,
        case_id TEXT NOT NULL,
        disposition_id TEXT NOT NULL REFERENCES reflow_artifacts(artifact_id),
        expected_generation BIGINT NOT NULL CHECK (expected_generation >= 0),
        committed_generation BIGINT NOT NULL CHECK (committed_generation > 0),
        committed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (principal_subject_sha256, command_key_sha256)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS reflow_case_workflow_commands_case_idx
      ON reflow_case_workflow_commands(scope_id, case_id, committed_generation)
    """,
)


def _preflight_v1_latest_proof_pointers(cursor: _Cursor) -> None:
    cursor.execute(
        """
        SELECT pointer.stream_key, artifact.artifact_kind, artifact.scope_id,
               artifact.payload_sha256, artifact.payload_json::text
        FROM reflow_current_pointers AS pointer
        LEFT JOIN reflow_artifacts AS artifact
          ON artifact.artifact_id = pointer.artifact_id
        WHERE pointer.pointer_kind = 'latest_proof'
        ORDER BY pointer.stream_key
        """
    )
    for row in cursor.fetchall():
        if len(row) != 5:
            raise PersistenceIntegrityError(
                "legacy latest_proof pointer cannot be migrated safely"
            )
        stream_key, artifact_kind, scope_id, stored_digest, payload_json = row
        if (
            not isinstance(stream_key, str)
            or artifact_kind != ArtifactKind.PROOF_VERSION.value
            or not isinstance(scope_id, str)
            or not scope_id
            or not isinstance(stored_digest, str)
            or not isinstance(payload_json, str)
        ):
            raise PersistenceIntegrityError(
                "legacy latest_proof pointer cannot be migrated safely"
            )
        payload = _decode_json_object(payload_json, "legacy latest_proof payload")
        if canonical_artifact_sha256(payload) != stored_digest:
            raise PersistenceIntegrityError(
                "legacy latest_proof payload digest does not match stored content"
            )
        settlement_id = payload.get("settlement_id")
        if (
            not isinstance(settlement_id, str)
            or not settlement_id
            or stream_key != settlement_id
        ):
            raise PersistenceIntegrityError(
                "legacy latest_proof pointer cannot be migrated safely"
            )


def _migrate_v1_approved_adapter_identities(cursor: _Cursor) -> None:
    cursor.execute(
        """
        SELECT artifact_id, payload_sha256, payload_json::text
        FROM reflow_artifacts
        WHERE artifact_kind = 'approved_adapter'
        ORDER BY artifact_id
        """
    )
    plans: list[tuple[str, str]] = []
    target_digests: dict[str, str] = {}
    for row in cursor.fetchall():
        if len(row) != 3 or not all(isinstance(value, str) for value in row):
            raise PersistenceIntegrityError(
                "legacy approved_adapter row contains invalid identity fields"
            )
        artifact_id, stored_digest, payload_json = cast(tuple[str, str, str], row)
        payload = _decode_json_object(payload_json, "legacy approved_adapter payload")
        actual_digest = canonical_artifact_sha256(payload)
        if stored_digest != actual_digest:
            raise PersistenceIntegrityError(
                "legacy approved_adapter payload digest does not match stored content"
            )
        target_id = f"adapterv_{actual_digest[:24]}"
        planned_digest = target_digests.get(target_id)
        if planned_digest is not None and planned_digest != actual_digest:
            raise PersistenceIntegrityError(
                "legacy approved_adapter identity cannot be migrated safely"
            )
        target_digests[target_id] = actual_digest
        cursor.execute(
            """
            SELECT artifact_kind, payload_sha256, payload_json::text
            FROM reflow_artifacts
            WHERE artifact_id = %s
            """,
            (target_id,),
        )
        target = cursor.fetchone()
        if target is not None:
            if len(target) != 3 or not all(isinstance(value, str) for value in target):
                raise PersistenceIntegrityError(
                    "legacy approved_adapter canonical target contains invalid fields"
                )
            target_kind, target_digest, target_json = cast(tuple[str, str, str], target)
            target_payload = _decode_json_object(
                target_json, "legacy approved_adapter canonical target payload"
            )
            if (
                target_kind != ArtifactKind.APPROVED_ADAPTER.value
                or target_digest != actual_digest
                or canonical_artifact_sha256(target_payload) != actual_digest
            ):
                raise PersistenceIntegrityError(
                    "legacy approved_adapter identity cannot be migrated safely"
                )
        plans.append((artifact_id, target_id))

    cursor.execute(
        """
        SELECT pointer.pointer_kind, pointer.stream_key, artifact.artifact_kind,
               artifact.payload_json -> 'spec' ->> 'adapter_id'
        FROM reflow_current_pointers AS pointer
        LEFT JOIN reflow_artifacts AS artifact
          ON artifact.artifact_id = pointer.artifact_id
        WHERE pointer.pointer_kind = 'latest_adapter'
           OR artifact.artifact_kind = 'approved_adapter'
        """
    )
    for pointer_row in cursor.fetchall():
        if len(pointer_row) != 4:
            raise PersistenceIntegrityError(
                "legacy approved_adapter pointer cannot be migrated safely"
            )
        pointer_kind, stream_key, artifact_kind, adapter_id = pointer_row
        if (
            pointer_kind != PointerKind.LATEST_ADAPTER.value
            or artifact_kind != ArtifactKind.APPROVED_ADAPTER.value
            or not isinstance(stream_key, str)
            or not isinstance(adapter_id, str)
            or not adapter_id
            or stream_key != adapter_id
        ):
            raise PersistenceIntegrityError(
                "legacy approved_adapter pointer cannot be migrated safely"
            )

    for artifact_id, target_id in plans:
        if artifact_id == target_id:
            continue
        cursor.execute(
            """
            INSERT INTO reflow_artifacts (
                artifact_id, artifact_kind, scope_id, observed_at,
                payload_sha256, payload_json, stored_at
            )
            SELECT %s, artifact_kind, NULL, NULL, payload_sha256, payload_json, stored_at
            FROM reflow_artifacts
            WHERE artifact_id = %s
            ON CONFLICT (artifact_id) DO NOTHING
            """,
            (target_id, artifact_id),
        )
        cursor.execute(
            "UPDATE reflow_current_pointers SET artifact_id = %s WHERE artifact_id = %s",
            (target_id, artifact_id),
        )
        cursor.execute("DELETE FROM reflow_artifacts WHERE artifact_id = %s", (artifact_id,))


def _migrate_v2_case_disposition_pointers(cursor: _Cursor) -> None:
    """Backfill one optimistic-concurrency stream per persisted exception case."""
    cursor.execute(
        """
        SELECT artifact_id, scope_id, payload_sha256, payload_json::text
        FROM reflow_artifacts
        WHERE artifact_kind = 'case_disposition'
        ORDER BY artifact_id
        """
    )
    by_case: dict[str, dict[int, tuple[str, str]]] = {}
    for row in cursor.fetchall():
        if len(row) != 4:
            raise PersistenceIntegrityError(
                "legacy case disposition cannot be migrated safely"
            )
        artifact_id, scope_id, stored_digest, payload_json = row
        if not all(isinstance(value, str) for value in row):
            raise PersistenceIntegrityError(
                "legacy case disposition contains invalid identity fields"
            )
        payload = _decode_json_object(
            cast(str, payload_json), "legacy case disposition payload"
        )
        if canonical_artifact_sha256(payload) != stored_digest:
            raise PersistenceIntegrityError(
                "legacy case disposition payload digest does not match stored content"
            )
        if payload.get("id") != artifact_id:
            raise PersistenceIntegrityError(
                "legacy case disposition artifact identity is inconsistent"
            )
        case_id = payload.get("case_id")
        sequence = payload.get("sequence")
        if (
            not isinstance(case_id, str)
            or not case_id
            or isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence < 1
            or not isinstance(scope_id, str)
            or not scope_id
        ):
            raise PersistenceIntegrityError(
                "legacy case disposition case/sequence/scope is invalid"
            )
        sequence_map = by_case.setdefault(case_id, {})
        existing = sequence_map.get(sequence)
        candidate = (cast(str, artifact_id), scope_id)
        if existing is not None and existing != candidate:
            raise PersistenceIntegrityError(
                "legacy case disposition sequence is duplicated"
            )
        sequence_map[sequence] = candidate

    for case_id, sequence_map in sorted(by_case.items()):
        sequences = tuple(sorted(sequence_map))
        if sequences != tuple(range(1, len(sequences) + 1)):
            raise PersistenceIntegrityError(
                "legacy case disposition sequence is not contiguous"
            )
        scopes = {scope for _, scope in sequence_map.values()}
        if len(scopes) != 1:
            raise PersistenceIntegrityError(
                "legacy case disposition scope changes within one case"
            )
        latest_sequence = sequences[-1]
        latest_artifact_id, _ = sequence_map[latest_sequence]
        cursor.execute(
            """
            SELECT artifact_id, generation
            FROM reflow_current_pointers
            WHERE pointer_kind = 'latest_case_disposition' AND stream_key = %s
            """,
            (case_id,),
        )
        existing_pointer = cursor.fetchone()
        if existing_pointer is not None:
            if existing_pointer != (latest_artifact_id, latest_sequence):
                raise PersistenceIntegrityError(
                    "legacy case disposition pointer is inconsistent"
                )
            continue
        cursor.execute(
            """
            INSERT INTO reflow_current_pointers(
                pointer_kind, stream_key, artifact_id, generation
            ) VALUES ('latest_case_disposition', %s, %s, %s)
            """,
            (case_id, latest_artifact_id, latest_sequence),
        )


_MIGRATION_1_TO_2_STATEMENTS = (
    # These artifact families have no intrinsic domain observation timestamp. Older
    # application callers supplied convenience timestamps; v2 removes that caller
    # metadata so replay equality is based only on durable domain/audit content.
    """
    UPDATE reflow_artifacts
    SET observed_at = NULL
    WHERE artifact_kind IN (
        'reconciliation_scope',
        'policy_version',
        'evidence_coverage',
        'balance_control',
        'close_readiness',
        'approved_adapter'
    )
    """,
    # Policy and approved-adapter definitions are reusable configuration, not
    # reconciliation-scope state. Their immutable IDs are globally unique.
    """
    UPDATE reflow_artifacts
    SET scope_id = NULL
    WHERE artifact_kind IN ('policy_version', 'approved_adapter')
    """,
    # Gate 17 originally keyed latest proofs only by settlement ID. Qualify legacy
    # pointers with the proof artifact's retained scope to avoid cross-scope collisions.
    """
    UPDATE reflow_current_pointers AS pointer
    SET stream_key = artifact.scope_id || ':' || (artifact.payload_json ->> 'settlement_id')
    FROM reflow_artifacts AS artifact
    WHERE pointer.pointer_kind = 'latest_proof'
      AND pointer.artifact_id = artifact.artifact_id
      AND artifact.scope_id IS NOT NULL
      AND artifact.payload_json ? 'settlement_id'
    """,
)


class PostgresApplicationStore(Journal):
    """PostgreSQL-backed Gate 17 raw journal plus immutable application state."""

    def __init__(
        self,
        dsn: str,
        *,
        connection_factory: ConnectionFactory = _default_connection_factory,
        initialize: bool = True,
    ) -> None:
        self._dsn = _text(dsn, "PostgreSQL DSN")
        self._connection_factory = connection_factory
        if initialize:
            self.migrate()

    def _connect(self) -> _Connection:
        return self._connection_factory(self._dsn)

    def check_ready(self) -> None:
        """Fail closed unless PostgreSQL is reachable at the exact supported schema."""
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT schema_version FROM reflow_schema_meta WHERE singleton = 1"
                )
                row = cursor.fetchone()
            if row is None or not isinstance(row[0], int):
                raise PersistenceIntegrityError("persistence schema metadata is missing")
            if row[0] != POSTGRES_SCHEMA_VERSION:
                raise PersistenceIntegrityError(
                    "application schema version mismatch "
                    f"{row[0]} != {POSTGRES_SCHEMA_VERSION}"
                )
        finally:
            connection.close()

    def migrate(self) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                for statement in _SCHEMA_STATEMENTS:
                    cursor.execute(statement)
                cursor.execute("SELECT schema_version FROM reflow_schema_meta WHERE singleton = 1")
                row = cursor.fetchone()
                if row is None:
                    cursor.execute(
                        """
                        SELECT EXISTS (
                            SELECT 1 FROM reflow_source_envelopes
                            UNION ALL
                            SELECT 1 FROM reflow_source_identity
                            UNION ALL
                            SELECT 1 FROM reflow_artifacts
                            UNION ALL
                            SELECT 1 FROM reflow_current_pointers
                        )
                        """
                    )
                    populated = cursor.fetchone()
                    if populated is None or not isinstance(populated[0], bool):
                        raise PersistenceIntegrityError(
                            "persistence schema population check returned invalid data"
                        )
                    if populated[0]:
                        raise PersistenceIntegrityError(
                            "persistence schema metadata is missing for non-empty database"
                        )
                    cursor.execute(
                        """
                        INSERT INTO reflow_schema_meta (singleton, schema_version)
                        VALUES (1, %s)
                        ON CONFLICT (singleton) DO NOTHING
                        """,
                        (POSTGRES_SCHEMA_VERSION,),
                    )
                    cursor.execute(
                        "SELECT schema_version FROM reflow_schema_meta WHERE singleton = 1"
                    )
                    row = cursor.fetchone()
                if row is None or not isinstance(row[0], int):
                    raise PersistenceIntegrityError("persistence schema metadata is missing")
                version = row[0]
                if version == 1 and POSTGRES_SCHEMA_VERSION >= 2:
                    _preflight_v1_latest_proof_pointers(cursor)
                    _migrate_v1_approved_adapter_identities(cursor)
                    for statement in _MIGRATION_1_TO_2_STATEMENTS:
                        cursor.execute(statement)
                    cursor.execute(
                        """
                        SELECT pointer.stream_key
                        FROM reflow_current_pointers AS pointer
                        JOIN reflow_artifacts AS artifact
                          ON artifact.artifact_id = pointer.artifact_id
                        WHERE pointer.pointer_kind = 'latest_proof'
                          AND (
                              artifact.artifact_kind <> 'proof_version'
                              OR artifact.scope_id IS NULL
                              OR artifact.payload_json ->> 'settlement_id' IS NULL
                              OR pointer.stream_key <> (
                                  artifact.scope_id || ':' ||
                                  (artifact.payload_json ->> 'settlement_id')
                              )
                          )
                        LIMIT 1
                        """
                    )
                    if cursor.fetchone() is not None:
                        raise PersistenceIntegrityError(
                            "legacy latest_proof pointer cannot be migrated safely"
                        )
                    cursor.execute(
                        "UPDATE reflow_schema_meta SET schema_version = 2 WHERE singleton = 1"
                    )
                    version = 2
                if version == 2 and POSTGRES_SCHEMA_VERSION >= 3:
                    _migrate_v2_case_disposition_pointers(cursor)
                    cursor.execute(
                        "UPDATE reflow_schema_meta SET schema_version = 3 WHERE singleton = 1"
                    )
                    version = 3
                if version != POSTGRES_SCHEMA_VERSION:
                    raise PersistenceIntegrityError(
                        "unsupported persistence schema version "
                        f"{version} != {POSTGRES_SCHEMA_VERSION}"
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _row_to_envelope(row: tuple[object, ...]) -> domain.SourceEnvelope:
        if len(row) != 8:
            raise PersistenceIntegrityError("source envelope row shape is invalid")
        (
            envelope_id,
            source_kind,
            source_record_id,
            occurred_at,
            received_at,
            payload_sha256,
            schema_version,
            payload_json,
        ) = row
        if not all(
            isinstance(value, str)
            for value in (
                envelope_id,
                source_kind,
                source_record_id,
                payload_sha256,
                schema_version,
                payload_json,
            )
        ):
            raise PersistenceIntegrityError("source envelope row contains invalid text fields")
        if occurred_at is not None and not isinstance(occurred_at, datetime):
            raise PersistenceIntegrityError("source occurred_at is invalid")
        if not isinstance(received_at, datetime):
            raise PersistenceIntegrityError("source received_at is invalid")
        payload = _decode_json_object(payload_json, "source payload")
        try:
            return domain.SourceEnvelope(
                id=domain.SourceEnvelopeId(cast(str, envelope_id)),
                source_kind=domain.SourceKind(cast(str, source_kind)),
                source_record_id=cast(str, source_record_id),
                occurred_at=occurred_at,
                received_at=received_at,
                payload_sha256=cast(str, payload_sha256),
                schema_version=cast(str, schema_version),
                payload=payload,
            )
        except (TypeError, ValueError) as exc:
            raise PersistenceIntegrityError(
                "persisted source envelope failed domain self-validation"
            ) from exc

    @staticmethod
    def _fetch_envelope_by_id(
        cursor: _Cursor, envelope_id: domain.SourceEnvelopeId
    ) -> domain.SourceEnvelope | None:
        cursor.execute(
            """
            SELECT envelope_id, source_kind, source_record_id, occurred_at, received_at,
                   payload_sha256, schema_version, payload_json::text
            FROM reflow_source_envelopes
            WHERE envelope_id = %s
            """,
            (str(envelope_id),),
        )
        row = cursor.fetchone()
        return None if row is None else PostgresApplicationStore._row_to_envelope(row)

    @staticmethod
    def _insert_envelope(cursor: _Cursor, envelope: domain.SourceEnvelope) -> bool:
        payload_json = json.dumps(
            _jsonable(envelope.payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        cursor.execute(
            """
            INSERT INTO reflow_source_envelopes (
                envelope_id, source_kind, source_record_id, occurred_at, received_at,
                payload_sha256, schema_version, payload_json
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (envelope_id) DO NOTHING
            RETURNING envelope_id
            """,
            (
                str(envelope.id),
                envelope.source_kind.value,
                envelope.source_record_id,
                envelope.occurred_at,
                envelope.received_at,
                envelope.payload_sha256,
                envelope.schema_version,
                payload_json,
            ),
        )
        inserted = cursor.fetchone() is not None
        if not inserted:
            existing = PostgresApplicationStore._fetch_envelope_by_id(cursor, envelope.id)
            if existing is None:
                raise PersistenceIntegrityError("existing source envelope row disappeared")
            # Envelope identity deliberately binds source kind/native record identity and
            # raw payload digest. Local receipt time, derived occurrence time and adapter
            # schema version are observation metadata, not a second economic/source fact.
            # Keep the first retained metadata exactly as the in-memory journal does.
            if (
                existing.source_kind is not envelope.source_kind
                or existing.source_record_id != envelope.source_record_id
                or existing.payload_sha256 != envelope.payload_sha256
                or existing.payload != envelope.payload
            ):
                raise PersistenceIntegrityError(
                    "existing source envelope row disagrees with stable evidence identity"
                )
        return inserted

    def append(self, envelope: domain.SourceEnvelope) -> AppendResult:
        if not isinstance(envelope, domain.SourceEnvelope):
            raise TypeError("journal append requires SourceEnvelope")
        connection = self._connect()
        conflict = False
        result: AppendResult | None = None
        try:
            with connection.cursor() as cursor:
                self._insert_envelope(cursor, envelope)
                cursor.execute(
                    """
                    INSERT INTO reflow_source_identity (
                        source_kind, source_record_id, primary_envelope_id
                    )
                    VALUES (%s, %s, %s)
                    ON CONFLICT (source_kind, source_record_id) DO NOTHING
                    RETURNING primary_envelope_id
                    """,
                    (envelope.source_kind.value, envelope.source_record_id, str(envelope.id)),
                )
                inserted_identity = cursor.fetchone() is not None
                cursor.execute(
                    """
                    SELECT primary_envelope_id
                    FROM reflow_source_identity
                    WHERE source_kind = %s AND source_record_id = %s
                    FOR UPDATE
                    """,
                    (envelope.source_kind.value, envelope.source_record_id),
                )
                identity_row = cursor.fetchone()
                if identity_row is None or not isinstance(identity_row[0], str):
                    raise PersistenceIntegrityError("source primary identity row is missing")
                primary_id = domain.SourceEnvelopeId(identity_row[0])
                primary = self._fetch_envelope_by_id(cursor, primary_id)
                if primary is None:
                    raise PersistenceIntegrityError(
                        "source primary identity references missing envelope"
                    )
                if primary.payload_sha256 == envelope.payload_sha256:
                    result = AppendResult(
                        AppendDisposition.STORED
                        if inserted_identity
                        else AppendDisposition.DUPLICATE,
                        primary,
                    )
                else:
                    conflict = True
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        if conflict:
            raise JournalConflictError(
                "same source identity arrived with a different payload hash: "
                f"{envelope.source_kind.value}/{envelope.source_record_id}"
            )
        if result is None:
            raise PersistenceIntegrityError("journal append produced no disposition")
        return result

    def get(
        self, source_kind: domain.SourceKind, source_record_id: str
    ) -> domain.SourceEnvelope | None:
        if not isinstance(source_kind, domain.SourceKind):
            raise TypeError("source kind must be SourceKind")
        source_record_id = _text(source_record_id, "source record id")
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT e.envelope_id, e.source_kind, e.source_record_id,
                           e.occurred_at, e.received_at, e.payload_sha256,
                           e.schema_version, e.payload_json::text
                    FROM reflow_source_identity i
                    JOIN reflow_source_envelopes e
                      ON e.envelope_id = i.primary_envelope_id
                    WHERE i.source_kind = %s AND i.source_record_id = %s
                    """,
                    (source_kind.value, source_record_id),
                )
                row = cursor.fetchone()
                return None if row is None else self._row_to_envelope(row)
        finally:
            connection.close()

    def get_by_id(self, envelope_id: domain.SourceEnvelopeId) -> domain.SourceEnvelope | None:
        if not isinstance(envelope_id, domain.SourceEnvelopeId):
            raise TypeError("envelope id must be SourceEnvelopeId")
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                return self._fetch_envelope_by_id(cursor, envelope_id)
        finally:
            connection.close()

    def entries(self) -> tuple[domain.SourceEnvelope, ...]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT envelope_id, source_kind, source_record_id, occurred_at, received_at,
                           payload_sha256, schema_version, payload_json::text
                    FROM reflow_source_envelopes
                    ORDER BY received_at, source_kind, source_record_id, envelope_id
                    """
                )
                return tuple(self._row_to_envelope(row) for row in cursor.fetchall())
        finally:
            connection.close()

    def __len__(self) -> int:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM reflow_source_envelopes")
                row = cursor.fetchone()
                if row is None or not isinstance(row[0], int):
                    raise PersistenceIntegrityError("source envelope count is invalid")
                return row[0]
        finally:
            connection.close()

    @staticmethod
    def _row_to_artifact(row: tuple[object, ...]) -> StoredArtifact:
        if len(row) != 6:
            raise PersistenceIntegrityError("artifact row shape is invalid")
        artifact_id, artifact_kind, scope_id, observed_at, payload_sha256, payload_json = row
        if not isinstance(artifact_id, str) or not isinstance(artifact_kind, str):
            raise PersistenceIntegrityError("artifact identity fields are invalid")
        if scope_id is not None and not isinstance(scope_id, str):
            raise PersistenceIntegrityError("artifact scope field is invalid")
        if observed_at is not None and not isinstance(observed_at, datetime):
            raise PersistenceIntegrityError("artifact observed_at is invalid")
        if not isinstance(payload_sha256, str) or not isinstance(payload_json, str):
            raise PersistenceIntegrityError("artifact payload fields are invalid")
        payload = _decode_json_object(payload_json, "artifact payload")
        try:
            kind = ArtifactKind(artifact_kind)
            typed_scope = None if scope_id is None else domain.ReconciliationScopeId(scope_id)
        except ValueError as exc:
            raise PersistenceIntegrityError("artifact kind/scope is invalid") from exc
        return StoredArtifact(
            artifact_id=artifact_id,
            kind=kind,
            scope_id=typed_scope,
            observed_at=observed_at,
            payload_sha256=payload_sha256,
            payload=payload,
        )

    @staticmethod
    def _fetch_artifact(cursor: _Cursor, artifact_id: str) -> StoredArtifact | None:
        cursor.execute(
            """
            SELECT artifact_id, artifact_kind, scope_id, observed_at,
                   payload_sha256, payload_json::text
            FROM reflow_artifacts
            WHERE artifact_id = %s
            """,
            (artifact_id,),
        )
        row = cursor.fetchone()
        return None if row is None else PostgresApplicationStore._row_to_artifact(row)

    @staticmethod
    def _put_artifact_cursor(
        cursor: _Cursor,
        *,
        kind: ArtifactKind,
        artifact_id: str,
        payload: object,
        scope_id: domain.ReconciliationScopeId | None,
        observed_at: datetime | None,
    ) -> ArtifactWriteResult:
        artifact_id = _text(artifact_id, "artifact id")
        if not isinstance(kind, ArtifactKind):
            raise TypeError("artifact kind must be ArtifactKind")
        if scope_id is not None and not isinstance(scope_id, domain.ReconciliationScopeId):
            raise TypeError("artifact scope must be ReconciliationScopeId")
        if observed_at is not None:
            _aware(observed_at, "artifact observed_at")
        rendered = canonical_artifact_json(payload)
        digest = hashlib.sha256(rendered.encode()).hexdigest()
        decoded = _decode_json_object(rendered, "artifact payload")
        candidate = StoredArtifact(
            artifact_id=artifact_id,
            kind=kind,
            scope_id=scope_id,
            observed_at=observed_at,
            payload_sha256=digest,
            payload=decoded,
        )
        cursor.execute(
            """
            INSERT INTO reflow_artifacts (
                artifact_id, artifact_kind, scope_id, observed_at,
                payload_sha256, payload_json
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (artifact_id) DO NOTHING
            RETURNING artifact_id
            """,
            (
                artifact_id,
                kind.value,
                None if scope_id is None else str(scope_id),
                observed_at,
                digest,
                rendered,
            ),
        )
        if cursor.fetchone() is not None:
            return ArtifactWriteResult(ArtifactWriteDisposition.STORED, candidate)
        existing = PostgresApplicationStore._fetch_artifact(cursor, artifact_id)
        if existing is None:
            raise PersistenceIntegrityError("artifact conflict row disappeared")
        if existing != candidate:
            raise PersistenceConflictError(
                f"artifact id {artifact_id} already contains different immutable content"
            )
        return ArtifactWriteResult(ArtifactWriteDisposition.DUPLICATE, existing)

    def put_artifact(
        self,
        *,
        kind: ArtifactKind,
        artifact_id: str,
        payload: object,
        scope_id: domain.ReconciliationScopeId | None = None,
        observed_at: datetime | None = None,
    ) -> ArtifactWriteResult:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                result = self._put_artifact_cursor(
                    cursor,
                    kind=kind,
                    artifact_id=artifact_id,
                    payload=payload,
                    scope_id=scope_id,
                    observed_at=observed_at,
                )
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_artifact(self, artifact_id: str) -> StoredArtifact | None:
        artifact_id = _text(artifact_id, "artifact id")
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                return self._fetch_artifact(cursor, artifact_id)
        finally:
            connection.close()

    def list_artifact_page(
        self,
        *,
        kind: ArtifactKind,
        scope_id: domain.ReconciliationScopeId | None,
        limit: int = 100,
        after: ArtifactPageCursor | None = None,
    ) -> ArtifactPage:
        if not isinstance(kind, ArtifactKind):
            raise TypeError("artifact kind must be ArtifactKind")
        if scope_id is not None and not isinstance(scope_id, domain.ReconciliationScopeId):
            raise TypeError("artifact scope must be ReconciliationScopeId")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10_000:
            raise PersistenceError("artifact page limit must be between 1 and 10000")
        if after is not None and not isinstance(after, ArtifactPageCursor):
            raise TypeError("artifact page cursor must be ArtifactPageCursor")

        scope_value = None if scope_id is None else str(scope_id)
        query = """
            SELECT artifact_id, artifact_kind, scope_id, observed_at,
                   payload_sha256, payload_json::text
            FROM reflow_artifacts
            WHERE artifact_kind = %s
              AND scope_id IS NOT DISTINCT FROM %s
        """
        params: list[object] = [kind.value, scope_value]
        if after is not None:
            if after.observed_at is None:
                query += " AND observed_at IS NULL AND artifact_id > %s"
                params.append(after.artifact_id)
            else:
                query += """
                    AND (
                        observed_at > %s
                        OR (observed_at = %s AND artifact_id > %s)
                        OR observed_at IS NULL
                    )
                """
                params.extend((after.observed_at, after.observed_at, after.artifact_id))
        query += " ORDER BY observed_at NULLS LAST, artifact_id LIMIT %s"
        params.append(limit + 1)

        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(query, tuple(params))
                rows = cursor.fetchall()
            artifacts = tuple(self._row_to_artifact(row) for row in rows[:limit])
            next_cursor = None
            if len(rows) > limit and artifacts:
                last = artifacts[-1]
                next_cursor = ArtifactPageCursor(
                    observed_at=last.observed_at,
                    artifact_id=last.artifact_id,
                )
            return ArtifactPage(items=artifacts, next_cursor=next_cursor)
        finally:
            connection.close()

    def list_artifacts(
        self,
        *,
        kind: ArtifactKind,
        scope_id: domain.ReconciliationScopeId | None,
        limit: int = 100,
    ) -> tuple[StoredArtifact, ...]:
        return self.list_artifact_page(
            kind=kind,
            scope_id=scope_id,
            limit=limit,
        ).items

    def count_artifacts(
        self,
        *,
        kind: ArtifactKind,
        scope_id: domain.ReconciliationScopeId | None,
    ) -> int:
        if not isinstance(kind, ArtifactKind):
            raise TypeError("artifact kind must be ArtifactKind")
        if scope_id is not None and not isinstance(scope_id, domain.ReconciliationScopeId):
            raise TypeError("artifact scope must be ReconciliationScopeId")
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM reflow_artifacts
                    WHERE artifact_kind = %s
                      AND scope_id IS NOT DISTINCT FROM %s
                    """,
                    (kind.value, None if scope_id is None else str(scope_id)),
                )
                row = cursor.fetchone()
                if row is None or not isinstance(row[0], int) or isinstance(row[0], bool):
                    raise PersistenceIntegrityError("artifact count query returned invalid data")
                return row[0]
        finally:
            connection.close()

    def manifests_cover_source_ids(
        self,
        *,
        scope_id: domain.ReconciliationScopeId,
        source_ids: tuple[domain.SourceEnvelopeId, ...],
    ) -> bool:
        if not isinstance(scope_id, domain.ReconciliationScopeId):
            raise TypeError("manifest coverage scope must be ReconciliationScopeId")
        if not source_ids or any(
            not isinstance(item, domain.SourceEnvelopeId) for item in source_ids
        ):
            raise PersistenceError("manifest coverage requires SourceEnvelopeId values")
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                for source_id in source_ids:
                    cursor.execute(
                        """
                        SELECT EXISTS (
                            SELECT 1
                            FROM reflow_artifacts
                            WHERE artifact_kind = %s
                              AND scope_id = %s
                              AND payload_json ->> 'scope_id' = %s
                              AND (payload_json -> 'effective_envelope_ids') ? %s
                        )
                        """,
                        (
                            ArtifactKind.SOURCE_DELIVERY_MANIFEST.value,
                            str(scope_id),
                            str(scope_id),
                            str(source_id),
                        ),
                    )
                    row = cursor.fetchone()
                    if row is None or not isinstance(row[0], bool):
                        raise PersistenceIntegrityError(
                            "manifest coverage query returned invalid data"
                        )
                    if not row[0]:
                        return False
                return True
        finally:
            connection.close()

    @staticmethod
    def _row_to_pointer(row: tuple[object, ...]) -> CurrentPointer:
        if len(row) != 5:
            raise PersistenceIntegrityError("pointer row shape is invalid")
        pointer_kind, stream_key, artifact_id, generation, updated_at = row
        if not all(isinstance(value, str) for value in (pointer_kind, stream_key, artifact_id)):
            raise PersistenceIntegrityError("pointer identity fields are invalid")
        if not isinstance(generation, int) or not isinstance(updated_at, datetime):
            raise PersistenceIntegrityError("pointer generation/time is invalid")
        try:
            kind = PointerKind(cast(str, pointer_kind))
        except ValueError as exc:
            raise PersistenceIntegrityError("pointer kind is invalid") from exc
        return CurrentPointer(
            kind=kind,
            stream_key=cast(str, stream_key),
            artifact_id=cast(str, artifact_id),
            generation=generation,
            updated_at=updated_at,
        )

    @staticmethod
    def _fetch_pointer(
        cursor: _Cursor,
        kind: PointerKind,
        stream_key: str,
        *,
        for_update: bool,
    ) -> CurrentPointer | None:
        if for_update:
            cursor.execute(
                """
                SELECT pointer_kind, stream_key, artifact_id, generation, updated_at
                FROM reflow_current_pointers
                WHERE pointer_kind = %s AND stream_key = %s
                FOR UPDATE
                """,
                (kind.value, stream_key),
            )
        else:
            cursor.execute(
                """
                SELECT pointer_kind, stream_key, artifact_id, generation, updated_at
                FROM reflow_current_pointers
                WHERE pointer_kind = %s AND stream_key = %s
                """,
                (kind.value, stream_key),
            )
        row = cursor.fetchone()
        return None if row is None else PostgresApplicationStore._row_to_pointer(row)

    @staticmethod
    def _advance_pointer_cursor(
        cursor: _Cursor,
        *,
        kind: PointerKind,
        stream_key: str,
        artifact_id: str,
        expected_generation: int,
    ) -> CurrentPointer:
        if not isinstance(kind, PointerKind):
            raise TypeError("pointer kind must be PointerKind")
        stream_key = _text(stream_key, "pointer stream key")
        artifact_id = _text(artifact_id, "pointer artifact id")
        if (
            isinstance(expected_generation, bool)
            or not isinstance(expected_generation, int)
            or expected_generation < 0
        ):
            raise PersistenceError("expected pointer generation must be non-negative int")
        cursor.execute(
            "SELECT artifact_kind FROM reflow_artifacts WHERE artifact_id = %s",
            (artifact_id,),
        )
        artifact_row = cursor.fetchone()
        if artifact_row is None or not isinstance(artifact_row[0], str):
            raise PersistenceError("pointer cannot reference missing artifact")
        expected_kind = _POINTER_ARTIFACT_KIND[kind]
        if artifact_row[0] != expected_kind.value:
            raise PersistenceError(f"{kind.value} pointer requires {expected_kind.value} artifact")
        current = PostgresApplicationStore._fetch_pointer(cursor, kind, stream_key, for_update=True)
        if current is not None and current.artifact_id == artifact_id:
            return current
        if current is None:
            if expected_generation != 0:
                raise StalePointerError("new pointer requires expected generation zero")
            cursor.execute(
                """
                INSERT INTO reflow_current_pointers (
                    pointer_kind, stream_key, artifact_id, generation
                )
                VALUES (%s, %s, %s, 1)
                RETURNING pointer_kind, stream_key, artifact_id, generation, updated_at
                """,
                (kind.value, stream_key, artifact_id),
            )
        else:
            if current.generation != expected_generation:
                raise StalePointerError(
                    "current pointer generation changed before compare-and-swap"
                )
            cursor.execute(
                """
                UPDATE reflow_current_pointers
                SET artifact_id = %s,
                    generation = generation + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE pointer_kind = %s AND stream_key = %s AND generation = %s
                RETURNING pointer_kind, stream_key, artifact_id, generation, updated_at
                """,
                (artifact_id, kind.value, stream_key, expected_generation),
            )
        row = cursor.fetchone()
        if row is None:
            raise StalePointerError("current pointer compare-and-swap lost a concurrent race")
        return PostgresApplicationStore._row_to_pointer(row)

    def replay_case_disposition_command(
        self,
        *,
        scope_id: domain.ReconciliationScopeId,
        case_id: str,
        principal_subject_sha256: str,
        command_key_sha256: str,
        request_sha256: str,
        expected_generation: int,
    ) -> CaseWorkflowCommandResult | None:
        if not isinstance(scope_id, domain.ReconciliationScopeId):
            raise TypeError("case workflow command scope must be ReconciliationScopeId")
        case_id = _text(case_id, "case workflow case id")
        principal_subject_sha256 = _sha256_digest(
            principal_subject_sha256, "case workflow principal digest"
        )
        command_key_sha256 = _sha256_digest(
            command_key_sha256, "case workflow idempotency digest"
        )
        request_sha256 = _sha256_digest(request_sha256, "case workflow request digest")
        if (
            isinstance(expected_generation, bool)
            or not isinstance(expected_generation, int)
            or expected_generation < 0
        ):
            raise PersistenceError(
                "case workflow expected generation must be non-negative int"
            )
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT request_sha256, request_id, scope_id, case_id, disposition_id,
                           expected_generation, committed_generation
                    FROM reflow_case_workflow_commands
                    WHERE principal_subject_sha256 = %s AND command_key_sha256 = %s
                    """,
                    (principal_subject_sha256, command_key_sha256),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                if len(row) != 7:
                    raise PersistenceIntegrityError(
                        "case workflow idempotency row shape is invalid"
                    )
                (
                    stored_request_sha256,
                    stored_request_id,
                    stored_scope_id,
                    stored_case_id,
                    disposition_id,
                    stored_expected_generation,
                    committed_generation,
                ) = row
                if (
                    stored_request_sha256,
                    stored_scope_id,
                    stored_case_id,
                    stored_expected_generation,
                ) != (request_sha256, str(scope_id), case_id, expected_generation):
                    raise PersistenceConflictError(
                        "case workflow idempotency key was reused with different content"
                    )
                if (
                    not isinstance(disposition_id, str)
                    or not isinstance(committed_generation, int)
                    or isinstance(committed_generation, bool)
                    or committed_generation != expected_generation + 1
                ):
                    raise PersistenceIntegrityError(
                        "case workflow idempotency generation is invalid"
                    )
                _request_id_digest(cast(str, stored_request_id))
                artifact = self._fetch_artifact(cursor, disposition_id)
                if (
                    artifact is None
                    or artifact.kind is not ArtifactKind.CASE_DISPOSITION
                    or artifact.scope_id != scope_id
                    or artifact.payload.get("case_id") != case_id
                    or artifact.payload.get("actor_id") != principal_subject_sha256
                    or artifact.payload.get("sequence") != committed_generation
                ):
                    raise PersistenceIntegrityError(
                        "case workflow idempotency record references invalid artifact"
                    )
                return CaseWorkflowCommandResult(
                    artifact=artifact,
                    committed_generation=committed_generation,
                    replayed=True,
                )
        finally:
            connection.close()

    def publish_case_disposition_command(
        self,
        *,
        disposition: object,
        scope_id: domain.ReconciliationScopeId,
        principal_subject_sha256: str,
        command_key_sha256: str,
        request_sha256: str,
        request_id: str,
        expected_generation: int,
    ) -> CaseWorkflowCommandResult:
        from .exception_cases import ExceptionCaseDisposition

        if not isinstance(disposition, ExceptionCaseDisposition):
            raise TypeError("case workflow command requires ExceptionCaseDisposition")
        if not isinstance(scope_id, domain.ReconciliationScopeId):
            raise TypeError("case workflow command scope must be ReconciliationScopeId")
        principal_subject_sha256 = _sha256_digest(
            principal_subject_sha256, "case workflow principal digest"
        )
        command_key_sha256 = _sha256_digest(
            command_key_sha256, "case workflow idempotency digest"
        )
        request_sha256 = _sha256_digest(request_sha256, "case workflow request digest")
        request_id = _request_id_digest(request_id)
        if (
            isinstance(expected_generation, bool)
            or not isinstance(expected_generation, int)
            or expected_generation < 0
        ):
            raise PersistenceError(
                "case workflow expected generation must be non-negative int"
            )
        if disposition.sequence != expected_generation + 1:
            raise PersistenceIntegrityError(
                "case workflow disposition sequence disagrees with expected generation"
            )
        if disposition.actor_id != principal_subject_sha256:
            raise PersistenceIntegrityError(
                "case workflow disposition actor must equal authenticated subject digest"
            )
        case_id = str(disposition.case_id)
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT request_sha256, request_id, scope_id, case_id, disposition_id,
                           expected_generation, committed_generation
                    FROM reflow_case_workflow_commands
                    WHERE principal_subject_sha256 = %s AND command_key_sha256 = %s
                    FOR UPDATE
                    """,
                    (principal_subject_sha256, command_key_sha256),
                )
                existing = cursor.fetchone()
                if existing is not None:
                    if len(existing) != 7:
                        raise PersistenceIntegrityError(
                            "case workflow idempotency row shape is invalid"
                        )
                    (
                        stored_request_sha256,
                        stored_request_id,
                        stored_scope_id,
                        stored_case_id,
                        stored_disposition_id,
                        stored_expected_generation,
                        stored_committed_generation,
                    ) = existing
                    expected_binding = (
                        request_sha256,
                        str(scope_id),
                        case_id,
                        expected_generation,
                        expected_generation + 1,
                    )
                    actual_binding = (
                        stored_request_sha256,
                        stored_scope_id,
                        stored_case_id,
                        stored_expected_generation,
                        stored_committed_generation,
                    )
                    if actual_binding != expected_binding:
                        raise PersistenceConflictError(
                            "case workflow idempotency key was reused with different content"
                        )
                    if not isinstance(stored_disposition_id, str):
                        raise PersistenceIntegrityError(
                            "case workflow idempotency disposition identity is invalid"
                        )
                    _request_id_digest(cast(str, stored_request_id))
                    artifact = self._fetch_artifact(cursor, stored_disposition_id)
                    if (
                        artifact is None
                        or artifact.kind is not ArtifactKind.CASE_DISPOSITION
                        or artifact.scope_id != scope_id
                        or artifact.payload.get("case_id") != case_id
                        or artifact.payload.get("actor_id") != principal_subject_sha256
                        or artifact.payload.get("sequence") != expected_generation + 1
                    ):
                        raise PersistenceIntegrityError(
                            "case workflow idempotency record references invalid artifact"
                        )
                    return CaseWorkflowCommandResult(
                        artifact=artifact,
                        committed_generation=expected_generation + 1,
                        replayed=True,
                    )

                artifact_result = self._put_artifact_cursor(
                    cursor,
                    kind=ArtifactKind.CASE_DISPOSITION,
                    artifact_id=str(disposition.id),
                    payload=disposition,
                    scope_id=scope_id,
                    observed_at=disposition.occurred_at,
                )
                pointer = self._advance_pointer_cursor(
                    cursor,
                    kind=PointerKind.LATEST_CASE_DISPOSITION,
                    stream_key=case_id,
                    artifact_id=str(disposition.id),
                    expected_generation=expected_generation,
                )
                if pointer.generation != expected_generation + 1:
                    raise PersistenceIntegrityError(
                        "case workflow pointer generation advanced unexpectedly"
                    )
                cursor.execute(
                    """
                    INSERT INTO reflow_case_workflow_commands(
                        principal_subject_sha256, command_key_sha256, request_sha256,
                        request_id, scope_id, case_id, disposition_id, expected_generation,
                        committed_generation
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        principal_subject_sha256,
                        command_key_sha256,
                        request_sha256,
                        request_id,
                        str(scope_id),
                        case_id,
                        str(disposition.id),
                        expected_generation,
                        pointer.generation,
                    ),
                )
            connection.commit()
            return CaseWorkflowCommandResult(
                artifact=artifact_result.artifact,
                committed_generation=pointer.generation,
                replayed=False,
            )
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_pointer(self, *, kind: PointerKind, stream_key: str) -> CurrentPointer | None:
        if not isinstance(kind, PointerKind):
            raise TypeError("pointer kind must be PointerKind")
        stream_key = _text(stream_key, "pointer stream key")
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                return self._fetch_pointer(cursor, kind, stream_key, for_update=False)
        finally:
            connection.close()

    def advance_pointer(
        self,
        *,
        kind: PointerKind,
        stream_key: str,
        artifact_id: str,
        expected_generation: int,
    ) -> CurrentPointer:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                pointer = self._advance_pointer_cursor(
                    cursor,
                    kind=kind,
                    stream_key=stream_key,
                    artifact_id=artifact_id,
                    expected_generation=expected_generation,
                )
            connection.commit()
            return pointer
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def publish_artifact_and_pointer(
        self,
        *,
        artifact_kind: ArtifactKind,
        artifact_id: str,
        payload: object,
        scope_id: domain.ReconciliationScopeId | None,
        observed_at: datetime | None,
        pointer_kind: PointerKind,
        stream_key: str,
        expected_generation: int,
    ) -> tuple[ArtifactWriteResult, CurrentPointer]:
        if _POINTER_ARTIFACT_KIND[pointer_kind] is not artifact_kind:
            raise PersistenceError("pointer kind does not match artifact kind")
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                artifact = self._put_artifact_cursor(
                    cursor,
                    kind=artifact_kind,
                    artifact_id=artifact_id,
                    payload=payload,
                    scope_id=scope_id,
                    observed_at=observed_at,
                )
                pointer = self._advance_pointer_cursor(
                    cursor,
                    kind=pointer_kind,
                    stream_key=stream_key,
                    artifact_id=artifact_id,
                    expected_generation=expected_generation,
                )
            connection.commit()
            return artifact, pointer
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def capabilities(self) -> ApplicationCapabilities:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT schema_version FROM reflow_schema_meta WHERE singleton = 1")
                row = cursor.fetchone()
                if row is None or not isinstance(row[0], int):
                    raise PersistenceIntegrityError("schema metadata is unavailable")
                version = row[0]
        finally:
            connection.close()
        return ApplicationCapabilities(
            database="postgresql",
            schema_version=version,
            raw_evidence_append_only=True,
            immutable_artifacts=True,
            optimistic_current_pointers=True,
            generic_sql_exposed=False,
            financial_truth_mutation=False,
        )


def _application_artifact_type(kind: ArtifactKind) -> type[object]:
    from .adapter_compiler.lifecycle import ApprovedAdapterVersion
    from .control_plane import (
        BalanceControlProof,
        CloseReadinessCertificate,
        EvidenceCoverageCertificate,
        ReconciliationPolicyVersion,
        ReconciliationRun,
        ReconciliationScope,
        SourceDeliveryManifest,
    )
    from .exception_cases import ExceptionCaseDisposition, ExceptionCaseObservation, IncidentCluster
    from .investigation import InvestigationRunResult, ToolTraceEntry
    from .reconciliation_proof import ReconciliationProofVersion

    return {
        ArtifactKind.RECONCILIATION_SCOPE: ReconciliationScope,
        ArtifactKind.POLICY_VERSION: ReconciliationPolicyVersion,
        ArtifactKind.SOURCE_DELIVERY_MANIFEST: SourceDeliveryManifest,
        ArtifactKind.EVIDENCE_COVERAGE: EvidenceCoverageCertificate,
        ArtifactKind.BALANCE_CONTROL: BalanceControlProof,
        ArtifactKind.CLOSE_READINESS: CloseReadinessCertificate,
        ArtifactKind.RECONCILIATION_RUN: ReconciliationRun,
        ArtifactKind.PROOF_VERSION: ReconciliationProofVersion,
        ArtifactKind.CASE_OBSERVATION: ExceptionCaseObservation,
        ArtifactKind.CASE_DISPOSITION: ExceptionCaseDisposition,
        ArtifactKind.INCIDENT_CLUSTER: IncidentCluster,
        ArtifactKind.APPROVED_ADAPTER: ApprovedAdapterVersion,
        ArtifactKind.INVESTIGATION_RESULT: InvestigationRunResult,
        ArtifactKind.INVESTIGATION_TRACE: ToolTraceEntry,
    }[kind]


def approved_adapter_artifact_id(payload: object) -> str:
    from .adapter_compiler.lifecycle import ApprovedAdapterVersion

    if not isinstance(payload, ApprovedAdapterVersion):
        raise TypeError("approved adapter identity requires ApprovedAdapterVersion")
    return f"adapterv_{canonical_artifact_sha256(payload)[:24]}"


def _application_storage_scope(
    *, kind: ArtifactKind, scope_id: domain.ReconciliationScopeId | None
) -> domain.ReconciliationScopeId | None:
    if kind in {
        ArtifactKind.POLICY_VERSION,
        ArtifactKind.APPROVED_ADAPTER,
    }:
        return None
    return scope_id


def _canonical_application_observed_at(
    *, kind: ArtifactKind, payload: object, observed_at: datetime | None
) -> datetime | None:
    typed = cast(Any, payload)
    intrinsic_name = {
        ArtifactKind.SOURCE_DELIVERY_MANIFEST: "evaluated_at",
        ArtifactKind.RECONCILIATION_RUN: "completed_at",
        ArtifactKind.PROOF_VERSION: "generated_at",
        ArtifactKind.CASE_OBSERVATION: "observed_at",
        ArtifactKind.CASE_DISPOSITION: "occurred_at",
        ArtifactKind.INVESTIGATION_RESULT: "as_of",
    }.get(kind)
    if intrinsic_name is not None:
        expected = cast(datetime, getattr(typed, intrinsic_name))
        if observed_at is not None and observed_at != expected:
            raise PersistenceIntegrityError(
                f"{kind.value} observed_at must equal typed {intrinsic_name}"
            )
        return expected
    if kind in {
        ArtifactKind.RECONCILIATION_SCOPE,
        ArtifactKind.POLICY_VERSION,
        ArtifactKind.EVIDENCE_COVERAGE,
        ArtifactKind.BALANCE_CONTROL,
        ArtifactKind.CLOSE_READINESS,
        ArtifactKind.APPROVED_ADAPTER,
    }:
        return None
    return observed_at


def _validated_application_artifact(
    *,
    kind: ArtifactKind,
    artifact_id: str,
    payload: object,
    scope_id: domain.ReconciliationScopeId | None,
) -> object:
    expected_type = _application_artifact_type(kind)
    if not isinstance(payload, expected_type):
        raise PersistenceError(
            f"{kind.value} application writes require typed self-validating "
            f"{expected_type.__name__}"
        )
    # Re-run top-level dataclass validation so a frozen object altered through unsafe
    # reflection cannot bypass its own immutable-ID/content checks at this boundary.
    try:
        replace(cast(Any, payload))
    except (TypeError, ValueError, OverflowError) as exc:
        raise PersistenceIntegrityError(
            f"{kind.value} artifact failed typed self-validation"
        ) from exc
    intrinsic_id = getattr(payload, "id", None)
    if intrinsic_id is not None and str(intrinsic_id) != artifact_id:
        raise PersistenceIntegrityError(
            f"{kind.value} artifact id disagrees with typed payload identity"
        )
    intrinsic_scope = getattr(payload, "scope_id", None)
    if intrinsic_scope is not None and intrinsic_scope != scope_id:
        raise PersistenceIntegrityError(
            f"{kind.value} artifact scope disagrees with typed payload scope"
        )
    if kind is ArtifactKind.RECONCILIATION_SCOPE and scope_id != cast(Any, payload).id:
        raise PersistenceIntegrityError(
            "reconciliation scope artifact storage scope must equal its typed identity"
        )
    if kind is ArtifactKind.APPROVED_ADAPTER:
        expected_adapter_id = approved_adapter_artifact_id(payload)
        if artifact_id != expected_adapter_id:
            raise PersistenceIntegrityError(
                "approved adapter artifact id must equal deterministic content identity "
                f"{expected_adapter_id!r}"
            )
    return payload


def _expected_application_stream_key(
    *,
    pointer_kind: PointerKind,
    payload: object,
    scope_id: domain.ReconciliationScopeId | None,
) -> str:
    if pointer_kind is PointerKind.LATEST_POLICY:
        if scope_id is None:
            raise PersistenceIntegrityError("latest_policy requires a reconciliation scope")
        return str(scope_id)
    typed = cast(Any, payload)
    if pointer_kind is PointerKind.LATEST_RUN:
        return str(typed.scope_id)
    if pointer_kind is PointerKind.LATEST_PROOF:
        if scope_id is None:
            raise PersistenceIntegrityError("latest_proof requires a reconciliation scope")
        return f"{scope_id}:{typed.settlement_id}"
    if pointer_kind is PointerKind.LATEST_CASE_OBSERVATION:
        return str(typed.case_id)
    if pointer_kind is PointerKind.LATEST_CASE_DISPOSITION:
        return str(typed.case_id)
    if pointer_kind is PointerKind.LATEST_ADAPTER:
        return str(typed.spec.adapter_id)
    if pointer_kind is PointerKind.LATEST_INVESTIGATION:
        return str(typed.case_id)
    raise AssertionError(f"unhandled pointer kind {pointer_kind}")


class _JournalFacade:
    __slots__ = ("__store",)

    def __init__(self, store: PostgresApplicationStore) -> None:
        self.__store = store

    def append(self, envelope: domain.SourceEnvelope) -> AppendResult:
        return self.__store.append(envelope)

    def get(
        self, source_kind: domain.SourceKind, source_record_id: str
    ) -> domain.SourceEnvelope | None:
        return self.__store.get(source_kind, source_record_id)

    def get_by_id(self, envelope_id: domain.SourceEnvelopeId) -> domain.SourceEnvelope | None:
        return self.__store.get_by_id(envelope_id)

    def entries(self) -> tuple[domain.SourceEnvelope, ...]:
        return self.__store.entries()

    def __len__(self) -> int:
        return len(self.__store)


class ReflowApplicationService:
    """Minimal Gate 17 application boundary; deliberately exposes no financial mutation API."""

    def __init__(self, store: PostgresApplicationStore) -> None:
        if not isinstance(store, PostgresApplicationStore):
            raise TypeError("application service requires PostgresApplicationStore")
        self._store = store
        self._journal: Journal = _JournalFacade(store)

    @property
    def journal(self) -> Journal:
        return self._journal

    def append_source(self, envelope: domain.SourceEnvelope) -> AppendResult:
        return self._store.append(envelope)

    def _policy_graph_artifact(self, artifact_id: object, *, label: str) -> StoredArtifact:
        text_id = str(artifact_id)
        artifact = self._store.get_artifact(text_id)
        if artifact is None:
            raise PersistenceIntegrityError(
                f"{label} graph is missing policy_version artifact {text_id}"
            )
        if artifact.kind is not ArtifactKind.POLICY_VERSION:
            raise PersistenceIntegrityError(
                f"{label} graph artifact {text_id} has wrong kind {artifact.kind.value}"
            )
        if artifact.scope_id is not None:
            raise PersistenceIntegrityError(f"{label} graph policy must use global storage scope")
        payload_id = artifact.payload.get("id")
        if payload_id is not None and payload_id != text_id:
            raise PersistenceIntegrityError(
                f"{label} graph policy {text_id} payload identity is inconsistent"
            )
        return artifact

    def _graph_artifact(
        self,
        artifact_id: object,
        *,
        kind: ArtifactKind,
        scope_id: domain.ReconciliationScopeId | None,
        label: str,
    ) -> StoredArtifact:
        text_id = str(artifact_id)
        artifact = self._store.get_artifact(text_id)
        if artifact is None:
            raise PersistenceIntegrityError(
                f"{label} graph is missing {kind.value} artifact {text_id}"
            )
        if artifact.kind is not kind:
            raise PersistenceIntegrityError(
                f"{label} graph artifact {text_id} has wrong kind {artifact.kind.value}"
            )
        if artifact.scope_id != scope_id:
            raise PersistenceIntegrityError(
                f"{label} graph artifact {text_id} has wrong storage scope"
            )
        payload_id = artifact.payload.get("id")
        if payload_id is not None and payload_id != text_id:
            raise PersistenceIntegrityError(
                f"{label} graph artifact {text_id} payload identity is inconsistent"
            )
        payload_scope = artifact.payload.get("scope_id")
        if payload_scope is not None and payload_scope != (
            None if scope_id is None else str(scope_id)
        ):
            raise PersistenceIntegrityError(
                f"{label} graph artifact {text_id} payload scope is inconsistent"
            )
        return artifact

    @staticmethod
    def _graph_ids(artifact: StoredArtifact, key: str, *, label: str) -> tuple[str, ...]:
        value = artifact.payload.get(key)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise PersistenceIntegrityError(f"{label} graph field {key} is invalid")
        return tuple(value)

    def _require_raw_source_evidence(
        self, source_ids: tuple[object, ...], *, label: str
    ) -> None:
        for value in source_ids:
            try:
                envelope_id = (
                    value
                    if isinstance(value, domain.SourceEnvelopeId)
                    else domain.SourceEnvelopeId(str(value))
                )
            except (TypeError, ValueError) as exc:
                raise PersistenceIntegrityError(
                    f"{label} contains invalid raw source evidence identity"
                ) from exc
            if self._store.get_by_id(envelope_id) is None:
                raise PersistenceIntegrityError(
                    f"{label} references missing raw source evidence {envelope_id}"
                )

    @classmethod
    def _validate_proof_manifest_coverage(
        cls,
        proof: StoredArtifact,
        manifests: tuple[StoredArtifact, ...],
        *,
        label: str,
    ) -> None:
        proof_sources = set(cls._graph_ids(proof, "source_envelope_ids", label=label))
        covered: set[str] = set()
        for manifest in manifests:
            covered.update(cls._graph_ids(manifest, "effective_envelope_ids", label=label))
        if not proof_sources or not proof_sources.issubset(covered):
            raise PersistenceIntegrityError(
                f"{label} graph proof evidence is outside its scoped source manifests"
            )

    def _validate_current_run_graph(
        self, payload: object, scope_id: domain.ReconciliationScopeId | None
    ) -> None:
        if scope_id is None:
            raise PersistenceIntegrityError("current run graph requires a reconciliation scope")
        run = cast(Any, payload)
        label = "current run"
        self._policy_graph_artifact(run.policy_version_id, label=label)
        manifests = tuple(
            self._graph_artifact(
                item,
                kind=ArtifactKind.SOURCE_DELIVERY_MANIFEST,
                scope_id=scope_id,
                label=label,
            )
            for item in run.source_manifest_ids
        )
        proofs = tuple(
            self._graph_artifact(
                item,
                kind=ArtifactKind.PROOF_VERSION,
                scope_id=scope_id,
                label=label,
            )
            for item in run.proof_version_ids
        )
        coverage = self._graph_artifact(
            run.coverage_certificate_id,
            kind=ArtifactKind.EVIDENCE_COVERAGE,
            scope_id=scope_id,
            label=label,
        )
        balance = self._graph_artifact(
            run.balance_control_id,
            kind=ArtifactKind.BALANCE_CONTROL,
            scope_id=scope_id,
            label=label,
        )
        close = self._graph_artifact(
            run.close_readiness_id,
            kind=ArtifactKind.CLOSE_READINESS,
            scope_id=scope_id,
            label=label,
        )
        manifest_ids = tuple(str(item) for item in run.source_manifest_ids)
        proof_ids = tuple(str(item) for item in run.proof_version_ids)
        if tuple(item.artifact_id for item in manifests) != manifest_ids:
            raise PersistenceIntegrityError(
                "current run graph source-manifest binding is inconsistent"
            )
        if tuple(item.artifact_id for item in proofs) != proof_ids:
            raise PersistenceIntegrityError("current run graph proof binding is inconsistent")
        for manifest in manifests:
            delivered = self._graph_ids(manifest, "delivered_envelope_ids", label=label)
            effective = self._graph_ids(manifest, "effective_envelope_ids", label=label)
            self._require_raw_source_evidence(
                tuple((*delivered, *effective)), label="current run source manifest"
            )
        for proof in proofs:
            self._validate_proof_manifest_coverage(proof, manifests, label=label)
            self._require_raw_source_evidence(
                tuple(self._graph_ids(proof, "source_envelope_ids", label=label)),
                label="current run proof",
            )
        if self._graph_ids(coverage, "manifest_ids", label=label) != manifest_ids:
            raise PersistenceIntegrityError("current run graph coverage/manifests disagree")
        if self._graph_ids(coverage, "proof_version_ids", label=label) != proof_ids:
            raise PersistenceIntegrityError("current run graph coverage/proofs disagree")
        if coverage.payload.get("scope_id") != str(scope_id):
            raise PersistenceIntegrityError("current run graph coverage scope disagrees")
        if balance.payload.get("scope_id") != str(scope_id) or balance.payload.get(
            "policy_version_id"
        ) != str(run.policy_version_id):
            raise PersistenceIntegrityError("current run graph balance binding disagrees")
        if close.payload.get("policy_version_id") != str(run.policy_version_id):
            raise PersistenceIntegrityError("current run graph close policy disagrees")
        if self._graph_ids(close, "manifest_ids", label=label) != manifest_ids:
            raise PersistenceIntegrityError("current run graph close/manifests disagree")
        if self._graph_ids(close, "proof_version_ids", label=label) != proof_ids:
            raise PersistenceIntegrityError("current run graph close/proofs disagree")
        if close.payload.get("coverage_certificate_id") != str(run.coverage_certificate_id):
            raise PersistenceIntegrityError("current run graph close/coverage disagree")
        if close.payload.get("balance_control_id") != str(run.balance_control_id):
            raise PersistenceIntegrityError("current run graph close/balance disagree")
        if close.payload.get("status") != run.outcome.value:
            raise PersistenceIntegrityError("current run graph close outcome disagrees")

    def _validate_scope_context(
        self,
        *,
        kind: ArtifactKind,
        payload: object,
        scope_id: domain.ReconciliationScopeId | None,
    ) -> None:
        typed = cast(Any, payload)
        if kind is ArtifactKind.SOURCE_DELIVERY_MANIFEST:
            source_ids = tuple((*typed.delivered_envelope_ids, *typed.effective_envelope_ids))
            self._require_raw_source_evidence(source_ids, label="source delivery manifest")
            return
        if kind is not ArtifactKind.PROOF_VERSION:
            return
        if scope_id is None:
            raise PersistenceIntegrityError("proof version application writes require a scope")
        source_ids = tuple(typed.source_envelope_ids)
        self._require_raw_source_evidence(source_ids, label="proof version")
        if not self._store.manifests_cover_source_ids(
            scope_id=scope_id, source_ids=source_ids
        ):
            raise PersistenceIntegrityError(
                "proof evidence is not covered by scoped source manifests"
            )

    def persist_artifact(
        self,
        *,
        kind: ArtifactKind,
        artifact_id: str,
        payload: object,
        scope_id: domain.ReconciliationScopeId | None = None,
        observed_at: datetime | None = None,
    ) -> ArtifactWriteResult:
        validated = _validated_application_artifact(
            kind=kind, artifact_id=artifact_id, payload=payload, scope_id=scope_id
        )
        canonical_observed_at = _canonical_application_observed_at(
            kind=kind, payload=validated, observed_at=observed_at
        )
        self._validate_scope_context(kind=kind, payload=validated, scope_id=scope_id)
        storage_scope = _application_storage_scope(kind=kind, scope_id=scope_id)
        return self._store.put_artifact(
            kind=kind,
            artifact_id=artifact_id,
            payload=validated,
            scope_id=storage_scope,
            observed_at=canonical_observed_at,
        )

    def artifact(self, artifact_id: str) -> StoredArtifact | None:
        return self._store.get_artifact(artifact_id)

    def artifact_page(
        self,
        *,
        kind: ArtifactKind,
        scope_id: domain.ReconciliationScopeId | None,
        limit: int = 100,
        after: ArtifactPageCursor | None = None,
    ) -> ArtifactPage:
        return self._store.list_artifact_page(
            kind=kind,
            scope_id=scope_id,
            limit=limit,
            after=after,
        )

    def artifacts(
        self,
        *,
        kind: ArtifactKind,
        scope_id: domain.ReconciliationScopeId | None,
        limit: int = 100,
    ) -> tuple[StoredArtifact, ...]:
        return self._store.list_artifacts(kind=kind, scope_id=scope_id, limit=limit)

    def artifact_count(
        self,
        *,
        kind: ArtifactKind,
        scope_id: domain.ReconciliationScopeId | None,
    ) -> int:
        return self._store.count_artifacts(kind=kind, scope_id=scope_id)

    def current(self, *, kind: PointerKind, stream_key: str) -> CurrentPointer | None:
        return self._store.get_pointer(kind=kind, stream_key=stream_key)

    def publish_current(
        self,
        *,
        artifact_kind: ArtifactKind,
        artifact_id: str,
        payload: object,
        scope_id: domain.ReconciliationScopeId | None,
        observed_at: datetime | None,
        pointer_kind: PointerKind,
        stream_key: str,
        expected_generation: int,
    ) -> tuple[ArtifactWriteResult, CurrentPointer]:
        validated = _validated_application_artifact(
            kind=artifact_kind, artifact_id=artifact_id, payload=payload, scope_id=scope_id
        )
        if not isinstance(pointer_kind, PointerKind):
            raise TypeError("pointer kind must be PointerKind")
        if _POINTER_ARTIFACT_KIND[pointer_kind] is not artifact_kind:
            raise PersistenceIntegrityError("pointer kind does not match typed artifact kind")
        expected_stream_key = _expected_application_stream_key(
            pointer_kind=pointer_kind, payload=validated, scope_id=scope_id
        )
        if stream_key != expected_stream_key:
            raise PersistenceIntegrityError(
                f"{pointer_kind.value} stream key must equal typed artifact identity "
                f"{expected_stream_key!r}"
            )
        canonical_observed_at = _canonical_application_observed_at(
            kind=artifact_kind, payload=validated, observed_at=observed_at
        )
        self._validate_scope_context(kind=artifact_kind, payload=validated, scope_id=scope_id)
        if pointer_kind is PointerKind.LATEST_RUN:
            self._validate_current_run_graph(validated, scope_id)
        storage_scope = _application_storage_scope(kind=artifact_kind, scope_id=scope_id)
        return self._store.publish_artifact_and_pointer(
            artifact_kind=artifact_kind,
            artifact_id=artifact_id,
            payload=validated,
            scope_id=storage_scope,
            observed_at=canonical_observed_at,
            pointer_kind=pointer_kind,
            stream_key=stream_key,
            expected_generation=expected_generation,
        )

    def replay_case_disposition_command(
        self,
        *,
        scope_id: domain.ReconciliationScopeId,
        case_id: str,
        principal_subject_sha256: str,
        command_key_sha256: str,
        request_sha256: str,
        expected_generation: int,
    ) -> CaseWorkflowCommandResult | None:
        return self._store.replay_case_disposition_command(
            scope_id=scope_id,
            case_id=case_id,
            principal_subject_sha256=principal_subject_sha256,
            command_key_sha256=command_key_sha256,
            request_sha256=request_sha256,
            expected_generation=expected_generation,
        )

    def publish_case_disposition_command(
        self,
        *,
        disposition: object,
        scope_id: domain.ReconciliationScopeId,
        principal_subject_sha256: str,
        command_key_sha256: str,
        request_sha256: str,
        request_id: str,
        expected_generation: int,
    ) -> CaseWorkflowCommandResult:
        validated = _validated_application_artifact(
            kind=ArtifactKind.CASE_DISPOSITION,
            artifact_id=str(cast(Any, disposition).id),
            payload=disposition,
            scope_id=scope_id,
        )
        canonical_observed_at = _canonical_application_observed_at(
            kind=ArtifactKind.CASE_DISPOSITION,
            payload=validated,
            observed_at=cast(Any, validated).occurred_at,
        )
        if canonical_observed_at != cast(Any, validated).occurred_at:
            raise PersistenceIntegrityError(
                "case disposition command timestamp binding is inconsistent"
            )
        return self._store.publish_case_disposition_command(
            disposition=validated,
            scope_id=scope_id,
            principal_subject_sha256=principal_subject_sha256,
            command_key_sha256=command_key_sha256,
            request_sha256=request_sha256,
            request_id=request_id,
            expected_generation=expected_generation,
        )

    def capabilities(self) -> ApplicationCapabilities:
        return self._store.capabilities()
