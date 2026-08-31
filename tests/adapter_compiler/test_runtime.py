from __future__ import annotations

from datetime import datetime

import pytest

from reflow.adapter_compiler import (
    AdapterRuntimeError,
    apply_approved_adapter,
    approve_reviewed_proposal,
    propose_and_validate_journaled,
)
from reflow.adapter_compiler.benchmark_fixtures import (
    development_adapter_cases,
    development_reference_provider,
)
from reflow.bank_proof import BankReceiptStatus, prove_all_bank_receipts
from reflow.domain import SourceKind
from reflow.ingestion import merge_canonical_batches
from reflow.journal import InMemoryJournal
from reflow.money_graph import build_money_graph
from reflow.settlement_proof import (
    CompositionStatus,
    prove_all_settlement_compositions,
)

_RECEIVED_AT = datetime.fromisoformat("2026-08-31T13:00:00+05:30")


def _case(case_id: str):
    return next(item for item in development_adapter_cases() if item.case_id == case_id)


def _compile_case(case_id: str, journal: InMemoryJournal):
    case = _case(case_id)
    evaluation = propose_and_validate_journaled(
        development_reference_provider(),
        case.rows,
        journal,
        batch_id=f"runtime-{case_id}",
        received_at=_RECEIVED_AT,
        adapter_id=case.adapter_id,
        version=case.version,
        source_kind=case.source_kind,
        record_kind=case.record_kind,
        financial_control=case.financial_control,
    )
    assert not evaluation.proposal.approved
    approved = approve_reviewed_proposal(
        evaluation,
        reference=f"operator-reviewed:{case_id}",
    )
    return evaluation, apply_approved_adapter(
        approved,
        evaluation.source_envelope_ids,
        journal,
    )


def test_gate12_runtime_preserves_raw_and_canonical_source_identity() -> None:
    journal = InMemoryJournal()
    evaluation, batch = _compile_case("bench_bank_no_control", journal)
    bank = batch.bank_entries[0]
    envelope_id = evaluation.source_envelope_ids[0]
    assert batch.source_index()[(SourceKind.BANK, str(bank.id))] == envelope_id
    raw_link = batch.source_links[0]
    assert raw_link.source_record_id.startswith(
        "adapter-batch:runtime-bench_bank_no_control:row:"
    )
    assert raw_link.canonical_record_id == str(bank.id)
    assert batch.raw_source_index()[raw_link.raw_identity] == envelope_id


def test_gate12_fragments_merge_into_existing_proof_pipeline() -> None:
    journal = InMemoryJournal()
    fragments = [
        _compile_case(case_id, journal)[1]
        for case_id in (
            "bench_merchant_rupees",
            "bench_payment_paise",
            "bench_recon_rupees",
            "bench_settlement_rupees",
            "bench_bank_integer_rupees",
        )
    ]
    merged = merge_canonical_batches(*fragments)
    graph = build_money_graph(merged)
    composition = prove_all_settlement_compositions(merged, graph)
    bank = prove_all_bank_receipts(merged)
    assert len(composition) == 1
    assert composition[0].status is CompositionStatus.PROVEN
    assert len(bank) == 1
    assert bank[0].status is BankReceiptStatus.WAITING
    assert len(merged.source_links) == 5


def test_rejected_or_schema_changed_adapter_cannot_enter_runtime() -> None:
    journal = InMemoryJournal()
    evaluation, batch = _compile_case("bench_bank_no_control", journal)
    approved = approve_reviewed_proposal(evaluation, reference="operator-reviewed:bank")
    assert batch.bank_entries
    foreign_case = _case("bench_bank_prompt_data")
    foreign_eval = propose_and_validate_journaled(
        development_reference_provider(),
        foreign_case.rows,
        journal,
        batch_id="runtime-foreign-schema",
        received_at=_RECEIVED_AT,
        adapter_id=foreign_case.adapter_id,
        version=foreign_case.version,
        source_kind=foreign_case.source_kind,
        record_kind=foreign_case.record_kind,
        financial_control=foreign_case.financial_control,
    )
    with pytest.raises(AdapterRuntimeError, match="schema does not match"):
        apply_approved_adapter(approved, foreign_eval.source_envelope_ids, journal)
