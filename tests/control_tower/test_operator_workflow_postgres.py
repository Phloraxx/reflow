from __future__ import annotations

import hashlib
import os
from datetime import timedelta
from pathlib import Path

import pytest

from reflow.control_tower import ControlTowerReader
from reflow.evaluation.control_tower_demo import RUN_COMPLETED_AT, seed_demo
from reflow.exception_cases import DispositionKind
from reflow.operator_workflow import OperatorCaseWorkflowService, OperatorWorkflowConflict
from reflow.persistence import PointerKind, PostgresApplicationStore, ReflowApplicationService

DSN = os.environ.get("REFLOW_TEST_POSTGRES_DSN")


def _dsn() -> str:
    if not DSN:
        pytest.skip("REFLOW_TEST_POSTGRES_DSN is not configured")
    return DSN


def _clean() -> None:
    dsn = _dsn()
    psycopg = pytest.importorskip("psycopg")
    PostgresApplicationStore(dsn)
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            TRUNCATE reflow_case_workflow_commands,
                     reflow_current_pointers,
                     reflow_artifacts,
                     reflow_source_identity,
                     reflow_source_envelopes
            """
        )


@pytest.fixture(autouse=True)
def _isolated_database() -> None:
    _clean()
    yield
    _clean()


def test_real_postgres_case_workflow_updates_control_tower_and_replays_idempotently() -> None:
    dsn = _dsn()
    bundle = seed_demo(dsn)
    application = ReflowApplicationService(PostgresApplicationStore(dsn))
    reader = ControlTowerReader(
        application,
        evaluation_root=Path("data/eval/gate17"),
        now=lambda: RUN_COMPLETED_AT + timedelta(minutes=10),
    )
    case_id = str(bundle.observations[0].case_id)
    before = reader.case_file(bundle.scope.id, case_id)
    assert before.case.disposition_count == 2
    assert before.case.workflow_status == "awaiting_source"
    pointer = application.current(kind=PointerKind.LATEST_CASE_DISPOSITION, stream_key=case_id)
    assert pointer is not None and pointer.generation == 2

    subject = "cloudflare-subject-gate52"
    workflow = OperatorCaseWorkflowService(
        reader,
        application,
        clock=lambda: RUN_COMPLETED_AT + timedelta(minutes=4),
    )
    first = workflow.append_disposition(
        scope_id=bundle.scope.id,
        case_id=case_id,
        principal_subject=subject,
        idempotency_key="gate52-real-command-1",
        request_id="1" * 32,
        expected_generation=2,
        kind=DispositionKind.DEFER,
        owner=None,
        note="Wait for corrected source delivery",
    )
    assert first.sequence == 3
    assert first.committed_generation == 3
    assert first.replayed is False

    after = reader.case_file(bundle.scope.id, case_id)
    assert after.case.disposition_count == 3
    assert after.case.workflow_status == "deferred"
    assert after.dispositions[-1].disposition_id == first.disposition_id
    assert after.dispositions[-1].actor_id == hashlib.sha256(subject.encode()).hexdigest()
    assert "cloudflare-subject" not in after.dispositions[-1].actor_id

    replay = workflow.append_disposition(
        scope_id=bundle.scope.id,
        case_id=case_id,
        principal_subject=subject,
        idempotency_key="gate52-real-command-1",
        request_id="2" * 32,
        expected_generation=2,
        kind=DispositionKind.DEFER,
        owner=None,
        note="Wait for corrected source delivery",
    )
    assert replay.replayed is True
    assert replay.disposition_id == first.disposition_id
    assert reader.case_file(bundle.scope.id, case_id).case.disposition_count == 3

    with pytest.raises(OperatorWorkflowConflict, match="conflicted"):
        workflow.append_disposition(
            scope_id=bundle.scope.id,
            case_id=case_id,
            principal_subject=subject,
            idempotency_key="gate52-real-command-1",
            request_id="3" * 32,
            expected_generation=2,
            kind=DispositionKind.DEFER,
            owner=None,
            note="different content under same key",
        )
    with pytest.raises(OperatorWorkflowConflict, match="stale"):
        workflow.append_disposition(
            scope_id=bundle.scope.id,
            case_id=case_id,
            principal_subject=subject,
            idempotency_key="gate52-real-command-2",
            request_id="4" * 32,
            expected_generation=2,
            kind=DispositionKind.ACKNOWLEDGE,
            owner=None,
            note=None,
        )
