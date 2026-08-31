from __future__ import annotations

from datetime import datetime

import pytest

from reflow.adapter_compiler import (
    CanonicalRecordKind,
    FinancialControlTotal,
    propose_and_validate_journaled,
)
from reflow.adapter_compiler.benchmark_fixtures import (
    WrongUnitMutationProvider,
    development_adapter_cases,
    development_reference_provider,
)
from reflow.domain import SourceKind
from reflow.journal import InMemoryJournal, JournalConflictError


def _bank_case():
    return next(
        item
        for item in development_adapter_cases()
        if item.case_id == "bench_bank_integer_rupees"
    )


def test_supported_gate12_path_journals_before_proposal_validation() -> None:
    case = _bank_case()
    provider = WrongUnitMutationProvider(
        development_reference_provider(),
        case.adapter_id,
    )
    journal = InMemoryJournal()
    result = propose_and_validate_journaled(
        provider,
        case.rows,
        journal,
        batch_id="gate12-test-batch-1",
        received_at=datetime.fromisoformat("2026-08-31T12:00:00+05:30"),
        adapter_id=case.adapter_id,
        version=case.version,
        source_kind=SourceKind.BANK,
        record_kind=CanonicalRecordKind.BANK_ENTRY,
        financial_control=FinancialControlTotal(
            target_field="amount_paise",
            expected_total_paise=10000,
            expected_row_count=1,
            evidence_label="test control",
        ),
    )
    assert len(journal) == len(case.rows)
    assert result.source_envelope_ids
    assert not result.proposal.approved


def test_changed_replay_under_same_batch_identity_is_retained_then_rejected() -> None:
    case = _bank_case()
    journal = InMemoryJournal()
    received_at = datetime.fromisoformat("2026-08-31T12:00:00+05:30")
    propose_and_validate_journaled(
        development_reference_provider(),
        case.rows,
        journal,
        batch_id="gate12-conflict-batch",
        received_at=received_at,
        adapter_id=case.adapter_id,
        version=case.version,
        source_kind=SourceKind.BANK,
        record_kind=CanonicalRecordKind.BANK_ENTRY,
    )
    changed = ({**case.rows[0], "Credit": "101"},)
    with pytest.raises(JournalConflictError):
        propose_and_validate_journaled(
            development_reference_provider(),
            changed,
            journal,
            batch_id="gate12-conflict-batch",
            received_at=received_at,
            adapter_id=case.adapter_id,
            version=case.version,
            source_kind=SourceKind.BANK,
            record_kind=CanonicalRecordKind.BANK_ENTRY,
        )
    assert len(journal) == 2
