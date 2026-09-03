from __future__ import annotations

import hashlib
import importlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, cast

from .domain import ReconciliationScopeId

OPERATOR_AUDIT_SCHEMA_VERSION = 1
MAX_OPERATOR_AUDIT_LIST_LIMIT = 500
_REQUEST_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class OperatorAuditError(RuntimeError):
    """Operator audit input or durable state is invalid."""


class OperatorAuditPersistenceError(OperatorAuditError):
    """Operator audit persistence is unavailable or inconsistent."""


class OperatorAuditAction(StrEnum):
    VIEW_SCOPE_OVERVIEW = "view_scope_overview"
    LIST_SCOPE_PROOFS = "list_scope_proofs"
    VIEW_SCOPE_PROOF = "view_scope_proof"
    LIST_SCOPE_EXCEPTIONS = "list_scope_exceptions"
    VIEW_SCOPE_CASE = "view_scope_case"
    LIST_SCOPE_SOURCES = "list_scope_sources"
    VIEW_EVALUATION = "view_evaluation"


class OperatorAuditDecision(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"


_SCOPE_ACTIONS = frozenset(
    {
        OperatorAuditAction.VIEW_SCOPE_OVERVIEW,
        OperatorAuditAction.LIST_SCOPE_PROOFS,
        OperatorAuditAction.VIEW_SCOPE_PROOF,
        OperatorAuditAction.LIST_SCOPE_EXCEPTIONS,
        OperatorAuditAction.VIEW_SCOPE_CASE,
        OperatorAuditAction.LIST_SCOPE_SOURCES,
    }
)


@dataclass(frozen=True, slots=True)
class OperatorAccessAudit:
    audit_id: int
    occurred_at: datetime
    request_id: str
    principal_subject_sha256: str
    action: OperatorAuditAction
    scope_id: ReconciliationScopeId | None
    decision: OperatorAuditDecision


class OperatorAuditRecorder(Protocol):
    def record_access(
        self,
        *,
        occurred_at: datetime,
        request_id: str,
        principal_subject_sha256: str,
        action: OperatorAuditAction,
        scope_id: ReconciliationScopeId | None,
        decision: OperatorAuditDecision,
    ) -> OperatorAccessAudit: ...


def principal_subject_sha256(subject: str) -> str:
    if (
        not isinstance(subject, str)
        or not subject
        or subject != subject.strip()
        or "\x00" in subject
        or len(subject.encode("utf-8")) > 4096
    ):
        raise OperatorAuditError("operator principal subject is invalid")
    return hashlib.sha256(subject.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise OperatorAuditError("operator audit timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _request_id(value: str) -> str:
    if not isinstance(value, str) or _REQUEST_ID_RE.fullmatch(value) is None:
        raise OperatorAuditError("operator audit request id is invalid")
    return value


def _subject_digest(value: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise OperatorAuditError("operator audit principal digest is invalid")
    return value


def _validate_binding(action: OperatorAuditAction, scope_id: ReconciliationScopeId | None) -> None:
    if action in _SCOPE_ACTIONS and scope_id is None:
        raise OperatorAuditError("scope operator audit action requires a scope")
    if action not in _SCOPE_ACTIONS and scope_id is not None:
        raise OperatorAuditError("non-scope operator audit action cannot bind a scope")


class _Cursor(Protocol):
    def execute(self, query: str, params: object | None = None) -> None: ...

    def fetchone(self) -> tuple[object, ...] | None: ...

    def fetchall(self) -> list[tuple[object, ...]]: ...

    def __enter__(self) -> _Cursor: ...

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
        raise OperatorAuditPersistenceError(
            "PostgreSQL operator audit requires the optional 'postgres' dependency"
        ) from exc
    connect = getattr(module, "connect", None)
    if not callable(connect):
        raise OperatorAuditPersistenceError("psycopg.connect is unavailable")
    return cast(_Connection, connect(dsn))


_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS reflow_operator_audit_schema_meta (
        singleton SMALLINT PRIMARY KEY CHECK (singleton = 1),
        schema_version INTEGER NOT NULL CHECK (schema_version > 0)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reflow_operator_access_audit (
        audit_id BIGSERIAL PRIMARY KEY,
        occurred_at TIMESTAMPTZ NOT NULL,
        request_id CHAR(32) NOT NULL UNIQUE,
        principal_subject_sha256 CHAR(64) NOT NULL,
        action TEXT NOT NULL,
        scope_id TEXT NULL,
        decision TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS reflow_operator_access_audit_time_idx
      ON reflow_operator_access_audit (occurred_at DESC, audit_id DESC)
    """,
)


class PostgresOperatorAuditStore:
    """Append-only authenticated operator authorization audit trail."""

    def __init__(
        self,
        dsn: str,
        *,
        connection_factory: ConnectionFactory = _default_connection_factory,
        initialize: bool = True,
    ) -> None:
        if not isinstance(dsn, str) or not dsn or dsn != dsn.strip():
            raise OperatorAuditPersistenceError("PostgreSQL operator audit DSN is invalid")
        self._dsn = dsn
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
                    "SELECT schema_version FROM reflow_operator_audit_schema_meta "
                    "WHERE singleton = 1"
                )
                row = cursor.fetchone()
                if row is None:
                    cursor.execute("SELECT EXISTS (SELECT 1 FROM reflow_operator_access_audit)")
                    populated = cursor.fetchone()
                    if populated is None or not isinstance(populated[0], bool):
                        raise OperatorAuditPersistenceError(
                            "operator audit schema population check returned invalid data"
                        )
                    if populated[0]:
                        raise OperatorAuditPersistenceError(
                            "operator audit schema metadata is missing for non-empty audit trail"
                        )
                    cursor.execute(
                        """
                        INSERT INTO reflow_operator_audit_schema_meta(singleton, schema_version)
                        VALUES (1, %s)
                        ON CONFLICT (singleton) DO NOTHING
                        """,
                        (OPERATOR_AUDIT_SCHEMA_VERSION,),
                    )
                    cursor.execute(
                        "SELECT schema_version FROM reflow_operator_audit_schema_meta "
                        "WHERE singleton = 1"
                    )
                    row = cursor.fetchone()
                if row is None or not isinstance(row[0], int):
                    raise OperatorAuditPersistenceError("operator audit schema metadata is missing")
                if row[0] != OPERATOR_AUDIT_SCHEMA_VERSION:
                    raise OperatorAuditPersistenceError(
                        "unsupported operator audit schema version "
                        f"{row[0]} != {OPERATOR_AUDIT_SCHEMA_VERSION}"
                    )
            connection.commit()
        except OperatorAuditError:
            connection.rollback()
            raise
        except Exception as exc:
            connection.rollback()
            raise OperatorAuditPersistenceError("operator audit migration failed") from exc
        finally:
            connection.close()

    def check_ready(self) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT schema_version FROM reflow_operator_audit_schema_meta "
                    "WHERE singleton = 1"
                )
                row = cursor.fetchone()
            if row is None or not isinstance(row[0], int):
                raise OperatorAuditPersistenceError("operator audit schema metadata is missing")
            if row[0] != OPERATOR_AUDIT_SCHEMA_VERSION:
                raise OperatorAuditPersistenceError("operator audit schema version mismatch")
        except OperatorAuditError:
            raise
        except Exception as exc:
            raise OperatorAuditPersistenceError("operator audit readiness failed") from exc
        finally:
            connection.close()

    @staticmethod
    def _row_to_event(row: tuple[object, ...]) -> OperatorAccessAudit:
        if len(row) != 7:
            raise OperatorAuditPersistenceError("operator audit row shape is invalid")
        audit_id, occurred_at, request_id_value, digest, action, scope_id, decision = row
        if not isinstance(audit_id, int) or not isinstance(occurred_at, datetime):
            raise OperatorAuditPersistenceError("operator audit identity/time is invalid")
        if not all(
            isinstance(value, str) for value in (request_id_value, digest, action, decision)
        ):
            raise OperatorAuditPersistenceError("operator audit text fields are invalid")
        try:
            typed_action = OperatorAuditAction(cast(str, action))
            typed_decision = OperatorAuditDecision(cast(str, decision))
            typed_scope = None if scope_id is None else ReconciliationScopeId(cast(str, scope_id))
            event = OperatorAccessAudit(
                audit_id=audit_id,
                occurred_at=_aware(occurred_at),
                request_id=_request_id(cast(str, request_id_value)),
                principal_subject_sha256=_subject_digest(cast(str, digest)),
                action=typed_action,
                scope_id=typed_scope,
                decision=typed_decision,
            )
            _validate_binding(event.action, event.scope_id)
            return event
        except (TypeError, ValueError, OperatorAuditError) as exc:
            raise OperatorAuditPersistenceError("operator audit row is invalid") from exc

    def record_access(
        self,
        *,
        occurred_at: datetime,
        request_id: str,
        principal_subject_sha256: str,
        action: OperatorAuditAction,
        scope_id: ReconciliationScopeId | None,
        decision: OperatorAuditDecision,
    ) -> OperatorAccessAudit:
        if not isinstance(action, OperatorAuditAction) or not isinstance(
            decision, OperatorAuditDecision
        ):
            raise OperatorAuditError("operator audit enum value is invalid")
        occurred_at = _aware(occurred_at)
        request_id = _request_id(request_id)
        principal_subject_sha256 = _subject_digest(principal_subject_sha256)
        _validate_binding(action, scope_id)
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO reflow_operator_access_audit(
                        occurred_at, request_id, principal_subject_sha256,
                        action, scope_id, decision
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING audit_id, occurred_at, request_id,
                              principal_subject_sha256, action, scope_id, decision
                    """,
                    (
                        occurred_at,
                        request_id,
                        principal_subject_sha256,
                        action.value,
                        None if scope_id is None else str(scope_id),
                        decision.value,
                    ),
                )
                row = cursor.fetchone()
                if row is None:
                    raise OperatorAuditPersistenceError("operator audit row was not retained")
                event = self._row_to_event(row)
            connection.commit()
            return event
        except OperatorAuditError:
            connection.rollback()
            raise
        except Exception as exc:
            connection.rollback()
            raise OperatorAuditPersistenceError("operator audit write failed") from exc
        finally:
            connection.close()

    def list_recent(self, *, limit: int = 50) -> tuple[OperatorAccessAudit, ...]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MAX_OPERATOR_AUDIT_LIST_LIMIT
        ):
            raise OperatorAuditError("operator audit list limit is invalid")
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT audit_id, occurred_at, request_id, principal_subject_sha256,
                           action, scope_id, decision
                    FROM reflow_operator_access_audit
                    ORDER BY audit_id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
            return tuple(self._row_to_event(row) for row in rows)
        except OperatorAuditError:
            raise
        except Exception as exc:
            raise OperatorAuditPersistenceError("operator audit read failed") from exc
        finally:
            connection.close()

    def integrity_count(self) -> int:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM reflow_operator_access_audit")
                row = cursor.fetchone()
            if row is None or not isinstance(row[0], int) or row[0] < 0:
                raise OperatorAuditPersistenceError("operator audit integrity count is invalid")
            return row[0]
        except OperatorAuditError:
            raise
        except Exception as exc:
            raise OperatorAuditPersistenceError("operator audit integrity read failed") from exc
        finally:
            connection.close()
