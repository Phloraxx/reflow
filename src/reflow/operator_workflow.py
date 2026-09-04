from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from . import domain
from .control_tower import ControlTowerReader
from .exception_cases import (
    CaseResolution,
    CaseWorkflowStatus,
    DispositionKind,
    ExceptionCaseError,
    build_exception_case_disposition,
)
from .operator_audit import principal_subject_sha256
from .persistence import (
    CaseWorkflowCommandResult,
    PersistenceConflictError,
    PersistenceIntegrityError,
    PointerKind,
    ReflowApplicationService,
    StalePointerError,
)

MAX_IDEMPOTENCY_KEY_BYTES = 256
MAX_CASE_OWNER_BYTES = 320
MAX_CASE_NOTE_BYTES = 4096


class OperatorWorkflowError(RuntimeError):
    """Authenticated operator workflow command cannot be accepted."""


class OperatorWorkflowConflict(OperatorWorkflowError):
    """Operator command conflicts with current workflow state or idempotency history."""


class OperatorWorkflowIntegrityError(OperatorWorkflowError):
    """Persisted workflow state is internally inconsistent."""


@dataclass(frozen=True, slots=True)
class CaseDispositionCommandResult:
    disposition_id: str
    case_id: str
    sequence: int
    committed_generation: int
    replayed: bool
    occurred_at: str
    kind: str
    owner: str | None
    note: str | None


def _aware_iso(value: str, label: str) -> datetime:
    if not isinstance(value, str):
        raise OperatorWorkflowIntegrityError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise OperatorWorkflowIntegrityError(f"{label} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OperatorWorkflowIntegrityError(f"{label} must be timezone-aware")
    return parsed


def _bounded_optional_text(value: str | None, *, label: str, max_bytes: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise OperatorWorkflowError(f"{label} must be non-empty and trimmed")
    if "\x00" in value or len(value.encode("utf-8")) > max_bytes:
        raise OperatorWorkflowError(f"{label} is too large")
    return value


def _idempotency_digest(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
        or len(value.encode("utf-8")) > MAX_IDEMPOTENCY_KEY_BYTES
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
    ):
        raise OperatorWorkflowError("Idempotency-Key is invalid")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _request_digest(
    *,
    scope_id: domain.ReconciliationScopeId,
    case_id: domain.ExceptionCaseId,
    expected_generation: int,
    kind: DispositionKind,
    owner: str | None,
    note: str | None,
) -> str:
    material = {
        "contract": "gate52-case-disposition-command-v1",
        "scope_id": str(scope_id),
        "case_id": str(case_id),
        "expected_generation": expected_generation,
        "kind": kind.value,
        "owner": owner,
        "note": note,
    }
    encoded = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _result_from_storage(result: CaseWorkflowCommandResult) -> CaseDispositionCommandResult:
    payload: Mapping[str, object] = result.artifact.payload
    values = {
        "id": payload.get("id"),
        "case_id": payload.get("case_id"),
        "sequence": payload.get("sequence"),
        "occurred_at": payload.get("occurred_at"),
        "kind": payload.get("kind"),
        "owner": payload.get("owner"),
        "note": payload.get("note"),
    }
    if (
        not isinstance(values["id"], str)
        or not isinstance(values["case_id"], str)
        or isinstance(values["sequence"], bool)
        or not isinstance(values["sequence"], int)
        or not isinstance(values["occurred_at"], str)
        or not isinstance(values["kind"], str)
        or (values["owner"] is not None and not isinstance(values["owner"], str))
        or (values["note"] is not None and not isinstance(values["note"], str))
    ):
        raise OperatorWorkflowIntegrityError("stored case disposition payload is invalid")
    return CaseDispositionCommandResult(
        disposition_id=values["id"],
        case_id=values["case_id"],
        sequence=values["sequence"],
        committed_generation=result.committed_generation,
        replayed=result.replayed,
        occurred_at=values["occurred_at"],
        kind=values["kind"],
        owner=values["owner"],
        note=values["note"],
    )


class OperatorCaseWorkflowService:
    """Authenticated exception-workflow mutation boundary with no finance-truth authority."""

    def __init__(
        self,
        reader: ControlTowerReader,
        application: ReflowApplicationService,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(reader, ControlTowerReader):
            raise TypeError("operator workflow requires ControlTowerReader")
        if not isinstance(application, ReflowApplicationService):
            raise TypeError("operator workflow requires ReflowApplicationService")
        self._reader = reader
        self._application = application
        self._clock = clock if clock is not None else lambda: datetime.now(tz=UTC)

    def append_disposition(
        self,
        *,
        scope_id: domain.ReconciliationScopeId,
        case_id: str,
        principal_subject: str,
        idempotency_key: str,
        request_id: str,
        expected_generation: int,
        kind: DispositionKind,
        owner: str | None,
        note: str | None,
    ) -> CaseDispositionCommandResult:
        if not isinstance(scope_id, domain.ReconciliationScopeId):
            raise TypeError("operator workflow scope must be ReconciliationScopeId")
        try:
            typed_case_id = domain.ExceptionCaseId(case_id)
        except (TypeError, ValueError) as exc:
            raise OperatorWorkflowError("case id is invalid") from exc
        if (
            isinstance(expected_generation, bool)
            or not isinstance(expected_generation, int)
            or expected_generation < 0
        ):
            raise OperatorWorkflowError("expected generation must be a non-negative integer")
        if not isinstance(kind, DispositionKind):
            raise TypeError("operator workflow kind must be DispositionKind")
        owner = _bounded_optional_text(
            owner, label="case owner", max_bytes=MAX_CASE_OWNER_BYTES
        )
        note = _bounded_optional_text(note, label="case note", max_bytes=MAX_CASE_NOTE_BYTES)
        actor_digest = principal_subject_sha256(principal_subject)
        command_digest = _idempotency_digest(idempotency_key)
        request_digest = _request_digest(
            scope_id=scope_id,
            case_id=typed_case_id,
            expected_generation=expected_generation,
            kind=kind,
            owner=owner,
            note=note,
        )
        try:
            replay = self._application.replay_case_disposition_command(
                scope_id=scope_id,
                case_id=str(typed_case_id),
                principal_subject_sha256=actor_digest,
                command_key_sha256=command_digest,
                request_sha256=request_digest,
                expected_generation=expected_generation,
            )
            if replay is not None:
                return _result_from_storage(replay)

            case_file = self._reader.case_file(scope_id, str(typed_case_id))
            case = case_file.case
            if case.case_id != str(typed_case_id):
                raise OperatorWorkflowIntegrityError("case projection identity changed")
            if case.disposition_count != expected_generation:
                raise OperatorWorkflowConflict("case disposition generation is stale")
            pointer = self._application.current(
                kind=PointerKind.LATEST_CASE_DISPOSITION,
                stream_key=str(typed_case_id),
            )
            if expected_generation == 0:
                if pointer is not None or case_file.dispositions:
                    raise OperatorWorkflowIntegrityError(
                        "case disposition pointer/history bootstrap is inconsistent"
                    )
                prior_at = None
            else:
                if (
                    pointer is None
                    or pointer.generation != expected_generation
                    or len(case_file.dispositions) != expected_generation
                    or pointer.artifact_id != case_file.dispositions[-1].disposition_id
                ):
                    raise OperatorWorkflowIntegrityError(
                        "case disposition pointer/history is inconsistent"
                    )
                prior_at = _aware_iso(
                    case_file.dispositions[-1].occurred_at,
                    "latest case disposition time",
                )
            occurred_at = self._clock()
            if (
                not isinstance(occurred_at, datetime)
                or occurred_at.tzinfo is None
                or occurred_at.utcoffset() is None
            ):
                raise OperatorWorkflowIntegrityError("operator workflow clock is invalid")
            disposition = build_exception_case_disposition(
                case_id=typed_case_id,
                sequence=expected_generation + 1,
                actor_id=actor_digest,
                occurred_at=occurred_at,
                kind=kind,
                case_first_seen_at=_aware_iso(case.first_seen_at, "case first seen time"),
                current_workflow_status=CaseWorkflowStatus(case.workflow_status),
                current_resolution=(
                    None if case.resolution is None else CaseResolution(case.resolution)
                ),
                prior_disposition_count=expected_generation,
                prior_disposition_at=prior_at,
                owner=owner,
                note=note,
            )
            stored = self._application.publish_case_disposition_command(
                disposition=disposition,
                scope_id=scope_id,
                principal_subject_sha256=actor_digest,
                command_key_sha256=command_digest,
                request_sha256=request_digest,
                request_id=request_id,
                expected_generation=expected_generation,
            )
            return _result_from_storage(stored)
        except (PersistenceConflictError, StalePointerError) as exc:
            raise OperatorWorkflowConflict("case workflow command conflicted") from exc
        except PersistenceIntegrityError as exc:
            raise OperatorWorkflowIntegrityError(
                "case workflow persistence is inconsistent"
            ) from exc
        except ExceptionCaseError as exc:
            raise OperatorWorkflowConflict(str(exc)) from exc
