from __future__ import annotations

import hashlib
import importlib
import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields, is_dataclass
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

POSTGRES_SCHEMA_VERSION = 1

__all__ = [
    "POSTGRES_SCHEMA_VERSION",
    "ApplicationCapabilities",
    "ArtifactKind",
    "ArtifactWriteDisposition",
    "ArtifactWriteResult",
    "CurrentPointer",
    "PersistenceConflictError",
    "PersistenceError",
    "PersistenceIntegrityError",
    "PointerKind",
    "PostgresApplicationStore",
    "ReflowApplicationService",
    "StalePointerError",
    "StoredArtifact",
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
    LATEST_ADAPTER = "latest_adapter"
    LATEST_INVESTIGATION = "latest_investigation"


_POINTER_ARTIFACT_KIND: dict[PointerKind, ArtifactKind] = {
    PointerKind.LATEST_POLICY: ArtifactKind.POLICY_VERSION,
    PointerKind.LATEST_RUN: ArtifactKind.RECONCILIATION_RUN,
    PointerKind.LATEST_PROOF: ArtifactKind.PROOF_VERSION,
    PointerKind.LATEST_CASE_OBSERVATION: ArtifactKind.CASE_OBSERVATION,
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

    def migrate(self) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                for statement in _SCHEMA_STATEMENTS:
                    cursor.execute(statement)
                cursor.execute(
                    """
                    INSERT INTO reflow_schema_meta (singleton, schema_version)
                    VALUES (1, %s)
                    ON CONFLICT (singleton) DO NOTHING
                    """,
                    (POSTGRES_SCHEMA_VERSION,),
                )
                cursor.execute("SELECT schema_version FROM reflow_schema_meta WHERE singleton = 1")
                row = cursor.fetchone()
                if row is None or not isinstance(row[0], int):
                    raise PersistenceIntegrityError("persistence schema metadata is missing")
                if row[0] != POSTGRES_SCHEMA_VERSION:
                    raise PersistenceIntegrityError(
                        "unsupported persistence schema version "
                        f"{row[0]} != {POSTGRES_SCHEMA_VERSION}"
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
            if existing != envelope:
                raise PersistenceIntegrityError(
                    "existing source envelope row differs from immutable envelope identity"
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

    def list_artifacts(
        self,
        *,
        kind: ArtifactKind,
        scope_id: domain.ReconciliationScopeId | None,
        limit: int = 100,
    ) -> tuple[StoredArtifact, ...]:
        if not isinstance(kind, ArtifactKind):
            raise TypeError("artifact kind must be ArtifactKind")
        if scope_id is not None and not isinstance(scope_id, domain.ReconciliationScopeId):
            raise TypeError("artifact scope must be ReconciliationScopeId")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10_000:
            raise PersistenceError("artifact query limit must be between 1 and 10000")
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT artifact_id, artifact_kind, scope_id, observed_at,
                           payload_sha256, payload_json::text
                    FROM reflow_artifacts
                    WHERE artifact_kind = %s
                      AND scope_id IS NOT DISTINCT FROM %s
                    ORDER BY observed_at NULLS LAST, artifact_id
                    LIMIT %s
                    """,
                    (kind.value, None if scope_id is None else str(scope_id), limit),
                )
                return tuple(self._row_to_artifact(row) for row in cursor.fetchall())
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
        suffix = " FOR UPDATE" if for_update else ""
        cursor.execute(
            """
            SELECT pointer_kind, stream_key, artifact_id, generation, updated_at
            FROM reflow_current_pointers
            WHERE pointer_kind = %s AND stream_key = %s
            """
            + suffix,
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


class ReflowApplicationService:
    """Minimal Gate 17 application boundary; deliberately exposes no financial mutation API."""

    def __init__(self, store: PostgresApplicationStore) -> None:
        if not isinstance(store, PostgresApplicationStore):
            raise TypeError("application service requires PostgresApplicationStore")
        self._store = store

    @property
    def journal(self) -> Journal:
        return self._store

    def append_source(self, envelope: domain.SourceEnvelope) -> AppendResult:
        return self._store.append(envelope)

    def persist_artifact(
        self,
        *,
        kind: ArtifactKind,
        artifact_id: str,
        payload: object,
        scope_id: domain.ReconciliationScopeId | None = None,
        observed_at: datetime | None = None,
    ) -> ArtifactWriteResult:
        return self._store.put_artifact(
            kind=kind,
            artifact_id=artifact_id,
            payload=payload,
            scope_id=scope_id,
            observed_at=observed_at,
        )

    def artifact(self, artifact_id: str) -> StoredArtifact | None:
        return self._store.get_artifact(artifact_id)

    def artifacts(
        self,
        *,
        kind: ArtifactKind,
        scope_id: domain.ReconciliationScopeId | None,
        limit: int = 100,
    ) -> tuple[StoredArtifact, ...]:
        return self._store.list_artifacts(kind=kind, scope_id=scope_id, limit=limit)

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
        return self._store.publish_artifact_and_pointer(
            artifact_kind=artifact_kind,
            artifact_id=artifact_id,
            payload=payload,
            scope_id=scope_id,
            observed_at=observed_at,
            pointer_kind=pointer_kind,
            stream_key=stream_key,
            expected_generation=expected_generation,
        )

    def capabilities(self) -> ApplicationCapabilities:
        return self._store.capabilities()
