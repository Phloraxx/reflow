from __future__ import annotations

import os
from pathlib import Path

import pytest

from reflow.control_tower import ControlTowerReader
from reflow.evaluation.judge_demo import JudgeDemoService
from reflow.persistence import PostgresApplicationStore, ReflowApplicationService

DSN = os.getenv("REFLOW_TEST_POSTGRES_DSN")


def _dsn() -> str:
    if not DSN:
        pytest.skip("REFLOW_TEST_POSTGRES_DSN is not configured")
    return DSN


def _truncate(dsn: str) -> None:
    psycopg = pytest.importorskip("psycopg")
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


def test_judge_demo_runs_real_proof_lifecycle(tmp_path: Path) -> None:
    dsn = _dsn()
    store = PostgresApplicationStore(dsn)
    _truncate(dsn)
    service = ReflowApplicationService(store)
    demo = JudgeDemoService(service)
    reader = ControlTowerReader(service, evaluation_root=tmp_path)

    initial = demo.run_initial()
    by_id = {item.settlement_id: item for item in initial.outcomes}
    assert by_id["setl_demo_green"].amount_display == "₹10,000.00"
    assert by_id["setl_demo_green"].status == "proven_reconciled"
    assert by_id["setl_demo_pending"].amount_display == "₹20,000.00"
    assert by_id["setl_demo_pending"].status == "pending_bank_credit"
    assert by_id["setl_demo_residual"].amount_display == "₹30,000.00"
    assert by_id["setl_demo_residual"].residual_display == "₹500.00"
    assert by_id["setl_demo_residual"].status == "residual"
    assert by_id["setl_demo_contradicted"].amount_display == "₹12,500.00"
    assert by_id["setl_demo_contradicted"].status == "contradicted"

    assert initial.focus_case_id is not None
    assert initial.focus_proof_id is not None
    case_before = reader.case_file(demo.scope_id, initial.focus_case_id)
    assert case_before.case.financial_status == "pending_bank_credit"
    assert case_before.case.workflow_status == "awaiting_source"
    assert case_before.investigation is not None
    assert case_before.investigation.next_action == "REQUEST_SOURCE"
    assert case_before.investigation.request_source_kind == "bank"

    arrival = demo.add_bank_evidence()
    assert arrival.phase == "bank_arrived"
    assert by_id["setl_demo_pending"].status == "pending_bank_credit"

    final = demo.rerun_affected()
    final_pending = next(
        item for item in final.outcomes if item.settlement_id == "setl_demo_pending"
    )
    assert final_pending.status == "proven_reconciled"
    assert final_pending.version == 2
    assert final_pending.residual_display == "₹0.00"

    assert final.focus_proof_id is not None
    proof_after = reader.proof_detail(demo.scope_id, final.focus_proof_id)
    assert proof_after.version == 2
    assert proof_after.status == "proven_reconciled"
    assert proof_after.prior_version_id == initial.focus_proof_id
    assert [(item.version, item.status) for item in proof_after.version_timeline] == [
        (1, "pending_bank_credit"),
        (2, "proven_reconciled"),
    ]

    case_after = reader.case_file(demo.scope_id, initial.focus_case_id)
    assert case_after.case.financial_status == "proven_reconciled"
    assert case_after.case.workflow_status == "closed"
    assert case_after.case.resolution == "proof_reconciled"
    assert case_after.case.observation_count == 2
    assert not case_after.case.is_active
    assert sum(item.is_active for item in reader.exceptions(demo.scope_id)) == 2
