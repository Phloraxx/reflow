from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from reflow.domain import SourceEnvelopeId, SourceKind
from reflow.ingestion import RawRecord
from reflow.journal import InMemoryJournal, make_source_envelope

from .contracts import (
    AdapterApprovalEvidence,
    ApprovalEvidenceKind,
    CanonicalRecordKind,
    FinancialControlTotal,
)
from .lifecycle import ApprovedAdapterVersion
from .provider import (
    AdapterProposalProvider,
    ProposalEvaluation,
    _propose_and_validate_rows,
)

_UNMAPPED_SCHEMA_VERSION = "gate12-unmapped-source-v1"


@dataclass(frozen=True, slots=True)
class JournaledProposalEvaluation:
    source_envelope_ids: tuple[SourceEnvelopeId, ...]
    proposal: ProposalEvaluation

    def __post_init__(self) -> None:
        if not self.source_envelope_ids:
            raise ValueError("journaled proposal must cite retained raw evidence")
        if len(self.source_envelope_ids) != len(set(self.source_envelope_ids)):
            raise ValueError("journaled proposal contains duplicate envelope identities")


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("received_at must be timezone-aware")


def propose_and_validate_journaled(
    provider: AdapterProposalProvider,
    rows: tuple[RawRecord, ...],
    journal: InMemoryJournal,
    *,
    batch_id: str,
    received_at: datetime,
    adapter_id: str,
    version: int,
    source_kind: SourceKind,
    record_kind: CanonicalRecordKind,
    sample_limit: int = 5,
    financial_control: FinancialControlTotal | None = None,
) -> JournaledProposalEvaluation:
    if not batch_id or batch_id != batch_id.strip():
        raise ValueError("adapter proposal batch id must be non-empty and trimmed")
    if not rows:
        raise ValueError("adapter proposal batch cannot be empty")
    _aware(received_at)

    envelope_ids: list[SourceEnvelopeId] = []
    retained_rows: list[RawRecord] = []
    for index, row in enumerate(rows):
        source_record_id = f"adapter-batch:{batch_id}:row:{index:08d}"
        result = journal.append(
            make_source_envelope(
                source_kind=source_kind,
                source_record_id=source_record_id,
                occurred_at=None,
                received_at=received_at,
                schema_version=_UNMAPPED_SCHEMA_VERSION,
                payload=row,
            )
        )
        envelope_ids.append(result.envelope.id)
        retained = journal.get_by_id(result.envelope.id)
        if retained is None:
            raise AssertionError("journal lost Gate 12 source envelope after append")
        retained_rows.append(retained.payload)

    proposal = _propose_and_validate_rows(
        provider,
        tuple(retained_rows),
        adapter_id=adapter_id,
        version=version,
        source_kind=source_kind,
        record_kind=record_kind,
        sample_limit=sample_limit,
        financial_control=financial_control,
    )
    return JournaledProposalEvaluation(
        source_envelope_ids=tuple(envelope_ids),
        proposal=proposal,
    )


def approve_reviewed_proposal(
    evaluation: JournaledProposalEvaluation,
    *,
    reference: str,
) -> ApprovedAdapterVersion:
    proposal = evaluation.proposal
    if proposal.compiled is None or proposal.sample_report is None:
        raise ValueError("rejected proposal cannot be operator-approved")
    return ApprovedAdapterVersion.from_compiled(
        proposal.compiled,
        proposal.context.profile,
        proposal.sample_report,
        AdapterApprovalEvidence(
            kind=ApprovalEvidenceKind.OPERATOR_REVIEW,
            reference=reference,
        ),
    )
