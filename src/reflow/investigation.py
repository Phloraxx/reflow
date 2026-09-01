from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from . import domain
from .control_plane import SourceCompleteness
from .exception_cases import (
    CaseWorkflowStatus,
    ExceptionCaseObservation,
    ExceptionCaseState,
    SourceStateSnapshot,
)
from .journal import Journal
from .reconciliation_proof import ReconciliationProofVersion, ReconciliationStatus

GATE16_INVESTIGATION_RULESET_VERSION = "gate16-investigation-v1"
MAX_INVESTIGATION_TOOL_CALLS = 16
MAX_INVESTIGATION_SOURCE_IDS = 64
MAX_INVESTIGATION_HYPOTHESIS_CHARS = 600

__all__ = [
    "GATE16_INVESTIGATION_RULESET_VERSION",
    "MAX_INVESTIGATION_HYPOTHESIS_CHARS",
    "MAX_INVESTIGATION_SOURCE_IDS",
    "MAX_INVESTIGATION_TOOL_CALLS",
    "CaseInvestigationView",
    "FinancialFactKind",
    "InvestigationAction",
    "InvestigationContext",
    "InvestigationError",
    "InvestigationProvider",
    "InvestigationRunResult",
    "InvestigationRunStatus",
    "InvestigationToolError",
    "InvestigationToolName",
    "InvestigationToolOutcome",
    "MoneyClaim",
    "ProofInvestigationView",
    "ReadOnlyInvestigationTools",
    "SourceEvidenceView",
    "ToolTraceEntry",
    "UntrustedTextField",
    "parse_investigation_proposal",
    "run_investigation",
]


class InvestigationError(ValueError):
    """Gate 16 target or provider output violates the bounded investigation contract."""


class InvestigationToolError(InvestigationError):
    """A read-only Gate 16 tool request exceeded the bound investigation packet."""


class InvestigationAction(StrEnum):
    WAIT = "WAIT"
    RECHECK = "RECHECK"
    REQUEST_SOURCE = "REQUEST_SOURCE"
    REQUEST_HUMAN_REVIEW = "REQUEST_HUMAN_REVIEW"
    ABSTAIN = "ABSTAIN"


class InvestigationRunStatus(StrEnum):
    VALIDATED = "validated"
    ABSTAINED = "abstained"
    REJECTED = "rejected"
    PROVIDER_ERROR = "provider_error"


class InvestigationToolName(StrEnum):
    CASE_SNAPSHOT = "CASE_SNAPSHOT"
    PROOF_SNAPSHOT = "PROOF_SNAPSHOT"
    SOURCE_EVIDENCE = "SOURCE_EVIDENCE"


class InvestigationToolOutcome(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"


class FinancialFactKind(StrEnum):
    AFFECTED_AMOUNT = "affected_amount"
    SETTLEMENT_AMOUNT = "settlement_amount"
    COMPOSITION_OBSERVED = "composition_observed"
    COMPOSITION_RESIDUAL = "composition_residual"
    BANK_EXPECTED_AMOUNT = "bank_expected_amount"
    BANK_OBSERVED_CREDIT = "bank_observed_credit"
    BANK_RESIDUAL = "bank_residual"


def _aware(value: datetime, label: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{label} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvestigationError(f"{label} must be timezone-aware")


def _text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvestigationError(f"{label} must be a non-empty string")
    if value != value.strip():
        raise InvestigationError(f"{label} must be trimmed")
    return value


def _canonical_jsonable(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, domain.EntityId):
        return str(value)
    if isinstance(value, domain.Money):
        return {"amount_paise": value.amount_paise, "currency": value.currency.value}
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_jsonable(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_canonical_jsonable(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return {
            name: _canonical_jsonable(getattr(value, name)) for name in value.__dataclass_fields__
        }
    raise TypeError(f"unsupported investigation digest value {type(value).__name__}")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        _canonical_jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _content_id(prefix: str, value: object) -> str:
    return f"{prefix}{_sha256(value)[:24]}"


@dataclass(frozen=True, slots=True)
class UntrustedTextField:
    path: str
    value: str

    def __post_init__(self) -> None:
        _text(self.path, "untrusted text path")
        if not isinstance(self.value, str):
            raise TypeError("untrusted text value must be string")
        if len(self.value) > 240:
            raise InvestigationError("untrusted text value exceeds bounded length")


@dataclass(frozen=True, slots=True)
class CaseInvestigationView:
    case_id: domain.ExceptionCaseId
    observation_id: domain.ExceptionCaseObservationId
    proof_version_id: domain.ProofVersionId
    settlement_id: domain.SettlementId
    financial_status: ReconciliationStatus
    reason_codes: tuple[str, ...]
    affected_amount: domain.Money
    materiality_band: str
    workflow_status: str
    source_states: tuple[SourceStateSnapshot, ...]
    first_seen_at: datetime
    last_seen_at: datetime
    age_seconds: int

    def __post_init__(self) -> None:
        if isinstance(self.age_seconds, bool) or not isinstance(self.age_seconds, int):
            raise TypeError("case age_seconds must be int")
        if self.age_seconds < 0:
            raise InvestigationError("case age cannot be negative")


@dataclass(frozen=True, slots=True)
class ProofInvestigationView:
    proof_version_id: domain.ProofVersionId
    settlement_id: domain.SettlementId
    status: ReconciliationStatus
    reason_codes: tuple[str, ...]
    settlement_amount: domain.Money
    composition_observed: domain.Money
    composition_residual: domain.Money
    bank_expected_amount: domain.Money
    bank_observed_credit: domain.Money
    bank_residual: domain.Money
    settlement_utr: str | None
    source_envelope_ids: tuple[domain.SourceEnvelopeId, ...]
    knowledge_cutoff: datetime
    generated_at: datetime


@dataclass(frozen=True, slots=True)
class SourceEvidenceView:
    source_envelope_id: domain.SourceEnvelopeId
    source_kind: domain.SourceKind
    source_record_id: str
    occurred_at: datetime | None
    received_at: datetime
    schema_version: str
    payload_sha256: str
    trust_label: str
    untrusted_text_fields: tuple[UntrustedTextField, ...]

    def __post_init__(self) -> None:
        if self.trust_label != "UNTRUSTED_SOURCE_DATA":
            raise InvestigationError("source evidence must be explicitly labelled untrusted")


@dataclass(frozen=True, slots=True)
class ToolTraceEntry:
    id: domain.InvestigationTraceEntryId
    sequence: int
    tool: InvestigationToolName
    request_ref: str
    outcome: InvestigationToolOutcome
    returned_refs: tuple[str, ...]
    result_sha256: str
    error_code: str | None
    ruleset_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, domain.InvestigationTraceEntryId):
            raise TypeError("trace id must be InvestigationTraceEntryId")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise TypeError("trace sequence must be int")
        if self.sequence < 1:
            raise InvestigationError("trace sequence must be positive")
        if not isinstance(self.tool, InvestigationToolName):
            raise TypeError("trace tool must be InvestigationToolName")
        _text(self.request_ref, "trace request ref")
        if not isinstance(self.outcome, InvestigationToolOutcome):
            raise TypeError("trace outcome must be InvestigationToolOutcome")
        if tuple(sorted(set(self.returned_refs))) != self.returned_refs:
            raise InvestigationError("trace returned refs must be unique and canonical-sorted")
        if len(self.result_sha256) != 64:
            raise InvestigationError("trace result digest must be SHA-256")
        try:
            int(self.result_sha256, 16)
        except ValueError as exc:
            raise InvestigationError("trace result digest must be hexadecimal") from exc
        if self.outcome is InvestigationToolOutcome.ALLOWED and self.error_code is not None:
            raise InvestigationError("allowed tool trace cannot carry error code")
        if self.outcome is InvestigationToolOutcome.DENIED and not self.error_code:
            raise InvestigationError("denied tool trace requires error code")
        if self.ruleset_version != GATE16_INVESTIGATION_RULESET_VERSION:
            raise InvestigationError("trace ruleset version does not match Gate 16")
        material = {
            "contract": GATE16_INVESTIGATION_RULESET_VERSION,
            "sequence": self.sequence,
            "tool": self.tool.value,
            "request_ref": self.request_ref,
            "outcome": self.outcome.value,
            "returned_refs": list(self.returned_refs),
            "result_sha256": self.result_sha256,
            "error_code": self.error_code,
        }
        expected = domain.InvestigationTraceEntryId(_content_id("trace_", material))
        if self.id != expected:
            raise InvestigationError("trace id does not match immutable content")


@dataclass(frozen=True, slots=True)
class MoneyClaim:
    fact: FinancialFactKind
    amount: domain.Money

    def __post_init__(self) -> None:
        if not isinstance(self.fact, FinancialFactKind):
            raise TypeError("claim fact must be FinancialFactKind")
        if not isinstance(self.amount, domain.Money):
            raise TypeError("claim amount must be Money")


@dataclass(frozen=True, slots=True)
class InvestigationProposal:
    case_id: domain.ExceptionCaseId
    observation_id: domain.ExceptionCaseObservationId
    proof_version_id: domain.ProofVersionId
    hypothesis: str | None
    citations: tuple[domain.SourceEnvelopeId, ...]
    financial_claims: tuple[MoneyClaim, ...]
    next_action: InvestigationAction
    request_source_kind: domain.SourceKind | None


@dataclass(frozen=True, slots=True)
class InvestigationContext:
    case_id: domain.ExceptionCaseId
    observation_id: domain.ExceptionCaseObservationId
    proof_version_id: domain.ProofVersionId
    financial_status: ReconciliationStatus
    reason_codes: tuple[str, ...]
    source_states: tuple[SourceStateSnapshot, ...]
    available_source_envelope_ids: tuple[domain.SourceEnvelopeId, ...]
    allowed_actions: tuple[InvestigationAction, ...]
    available_financial_facts: tuple[FinancialFactKind, ...]
    as_of: datetime
    age_seconds: int
    ruleset_version: str

    def __post_init__(self) -> None:
        _aware(self.as_of, "investigation as_of")
        if self.ruleset_version != GATE16_INVESTIGATION_RULESET_VERSION:
            raise InvestigationError("context ruleset version does not match Gate 16")
        if tuple(sorted(set(self.available_source_envelope_ids), key=str)) != (
            self.available_source_envelope_ids
        ):
            raise InvestigationError("context source IDs must be unique and canonical-sorted")


class InvestigationProvider(Protocol):
    def propose(
        self,
        context: InvestigationContext,
        tools: ReadOnlyInvestigationTools,
    ) -> Mapping[str, object]: ...


def _trace_entry(
    *,
    sequence: int,
    tool: InvestigationToolName,
    request_ref: str,
    outcome: InvestigationToolOutcome,
    returned_refs: tuple[str, ...],
    result_value: object,
    error_code: str | None,
) -> ToolTraceEntry:
    digest = _sha256(result_value)
    material = {
        "contract": GATE16_INVESTIGATION_RULESET_VERSION,
        "sequence": sequence,
        "tool": tool.value,
        "request_ref": request_ref,
        "outcome": outcome.value,
        "returned_refs": list(returned_refs),
        "result_sha256": digest,
        "error_code": error_code,
    }
    return ToolTraceEntry(
        id=domain.InvestigationTraceEntryId(_content_id("trace_", material)),
        sequence=sequence,
        tool=tool,
        request_ref=request_ref,
        outcome=outcome,
        returned_refs=returned_refs,
        result_sha256=digest,
        error_code=error_code,
        ruleset_version=GATE16_INVESTIGATION_RULESET_VERSION,
    )


def _extract_untrusted_text(payload: Mapping[str, object]) -> tuple[UntrustedTextField, ...]:
    found: list[UntrustedTextField] = []

    def walk(value: object, path: str) -> None:
        if len(found) >= 16:
            return
        if isinstance(value, str):
            bounded = value[:240]
            found.append(UntrustedTextField(path=path, value=bounded))
            return
        if isinstance(value, Mapping):
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
                walk(item, f"{path}.{key}")
                if len(found) >= 16:
                    return
        elif isinstance(value, (tuple, list)):
            for index, item in enumerate(value[:16]):
                walk(item, f"{path}[{index}]")
                if len(found) >= 16:
                    return

    walk(payload, "payload")
    return tuple(found)


class ReadOnlyInvestigationTools:
    """Read-only, target-scoped evidence capabilities for one Gate 16 investigation."""

    def __init__(
        self,
        *,
        case_state: ExceptionCaseState,
        observation: ExceptionCaseObservation,
        proof: ReconciliationProofVersion,
        journal: Journal,
        as_of: datetime,
    ) -> None:
        if not isinstance(case_state, ExceptionCaseState):
            raise TypeError("case_state must be ExceptionCaseState")
        if not isinstance(observation, ExceptionCaseObservation):
            raise TypeError("observation must be ExceptionCaseObservation")
        if not isinstance(proof, ReconciliationProofVersion):
            raise TypeError("proof must be ReconciliationProofVersion")
        if not isinstance(journal, Journal):
            raise TypeError("journal must satisfy Journal")
        _aware(as_of, "investigation as_of")
        if case_state.workflow_status is CaseWorkflowStatus.CLOSED:
            raise InvestigationError("closed/resolved exception case is not investigation-active")
        if case_state.financial_status is ReconciliationStatus.PROVEN_RECONCILED:
            raise InvestigationError("financially reconciled case is not investigation-active")
        if case_state.latest_observation_id != observation.id:
            raise InvestigationError("case state does not bind the supplied latest observation")
        if case_state.latest_proof_version_id != proof.id:
            raise InvestigationError("case state does not bind the supplied proof version")
        if observation.case_id != case_state.case_id:
            raise InvestigationError("observation belongs to another case")
        if observation.proof_version_id != proof.id:
            raise InvestigationError("observation belongs to another proof version")
        if observation.settlement_id != proof.settlement_id:
            raise InvestigationError("case observation/proof settlement identity mismatch")
        if observation.affected_amount != proof.composition.settlement_amount:
            raise InvestigationError("case observation/proof settlement amount mismatch")
        if observation.financial_status is not proof.status:
            raise InvestigationError("case observation/proof financial status mismatch")
        if observation.reason_codes != proof.reason_codes:
            raise InvestigationError("case observation/proof reason codes mismatch")
        if observation.settlement_utr != proof.bank.settlement_utr:
            raise InvestigationError("case observation/proof settlement UTR mismatch")
        if as_of < case_state.first_seen_at:
            raise InvestigationError("investigation as_of predates case first seen")
        if len(proof.source_envelope_ids) > MAX_INVESTIGATION_SOURCE_IDS:
            raise InvestigationError("proof exceeds bounded investigation source-evidence budget")
        for envelope_id in proof.source_envelope_ids:
            if journal.get_by_id(envelope_id) is None:
                raise InvestigationError(
                    f"proof cites source evidence absent from supplied journal: {envelope_id}"
                )
        self._case_state = case_state
        self._observation = observation
        self._proof = proof
        self._journal = journal
        self._as_of = as_of
        self._trace: list[ToolTraceEntry] = []
        self._allowed_source_ids = frozenset(proof.source_envelope_ids)
        self._accessed_source_ids: set[domain.SourceEnvelopeId] = set()

    @property
    def context(self) -> InvestigationContext:
        return InvestigationContext(
            case_id=self._case_state.case_id,
            observation_id=self._observation.id,
            proof_version_id=self._proof.id,
            financial_status=self._proof.status,
            reason_codes=self._proof.reason_codes,
            source_states=self._observation.source_states,
            available_source_envelope_ids=tuple(sorted(self._allowed_source_ids, key=str)),
            allowed_actions=tuple(InvestigationAction),
            available_financial_facts=tuple(FinancialFactKind),
            as_of=self._as_of,
            age_seconds=self._case_state.age_seconds(self._as_of),
            ruleset_version=GATE16_INVESTIGATION_RULESET_VERSION,
        )

    @property
    def trace(self) -> tuple[ToolTraceEntry, ...]:
        return tuple(self._trace)

    @property
    def accessed_source_envelope_ids(self) -> frozenset[domain.SourceEnvelopeId]:
        return frozenset(self._accessed_source_ids)

    def _record(
        self,
        *,
        tool: InvestigationToolName,
        request_ref: str,
        outcome: InvestigationToolOutcome,
        returned_refs: tuple[str, ...],
        result_value: object,
        error_code: str | None = None,
    ) -> None:
        if len(self._trace) >= MAX_INVESTIGATION_TOOL_CALLS:
            raise InvestigationToolError("investigation tool-call budget exhausted")
        self._trace.append(
            _trace_entry(
                sequence=len(self._trace) + 1,
                tool=tool,
                request_ref=request_ref,
                outcome=outcome,
                returned_refs=returned_refs,
                result_value=result_value,
                error_code=error_code,
            )
        )

    def case_snapshot(self) -> CaseInvestigationView:
        view = CaseInvestigationView(
            case_id=self._case_state.case_id,
            observation_id=self._observation.id,
            proof_version_id=self._proof.id,
            settlement_id=self._case_state.settlement_id,
            financial_status=self._proof.status,
            reason_codes=self._proof.reason_codes,
            affected_amount=self._case_state.affected_amount,
            materiality_band=self._case_state.materiality_band.value,
            workflow_status=self._case_state.workflow_status.value,
            source_states=self._observation.source_states,
            first_seen_at=self._case_state.first_seen_at,
            last_seen_at=self._case_state.last_seen_at,
            age_seconds=self._case_state.age_seconds(self._as_of),
        )
        self._record(
            tool=InvestigationToolName.CASE_SNAPSHOT,
            request_ref=str(self._case_state.case_id),
            outcome=InvestigationToolOutcome.ALLOWED,
            returned_refs=tuple(sorted((str(self._observation.id), str(self._case_state.case_id)))),
            result_value=view,
        )
        return view

    def proof_snapshot(self) -> ProofInvestigationView:
        view = ProofInvestigationView(
            proof_version_id=self._proof.id,
            settlement_id=self._proof.settlement_id,
            status=self._proof.status,
            reason_codes=self._proof.reason_codes,
            settlement_amount=self._proof.composition.settlement_amount,
            composition_observed=self._proof.composition.observed_composition,
            composition_residual=self._proof.composition.residual,
            bank_expected_amount=self._proof.bank.expected_amount,
            bank_observed_credit=self._proof.bank.observed_bank_credit,
            bank_residual=self._proof.bank.residual,
            settlement_utr=self._proof.bank.settlement_utr,
            source_envelope_ids=self._proof.source_envelope_ids,
            knowledge_cutoff=self._proof.knowledge_cutoff,
            generated_at=self._proof.generated_at,
        )
        self._record(
            tool=InvestigationToolName.PROOF_SNAPSHOT,
            request_ref=str(self._proof.id),
            outcome=InvestigationToolOutcome.ALLOWED,
            returned_refs=(str(self._proof.id),),
            result_value=view,
        )
        return view

    def source_evidence(
        self,
        envelope_id: domain.SourceEnvelopeId,
    ) -> SourceEvidenceView:
        if not isinstance(envelope_id, domain.SourceEnvelopeId):
            raise TypeError("source evidence id must be SourceEnvelopeId")
        if envelope_id not in self._allowed_source_ids:
            self._record(
                tool=InvestigationToolName.SOURCE_EVIDENCE,
                request_ref=str(envelope_id),
                outcome=InvestigationToolOutcome.DENIED,
                returned_refs=(),
                result_value={"denied": "SOURCE_OUTSIDE_BOUND_PROOF"},
                error_code="SOURCE_OUTSIDE_BOUND_PROOF",
            )
            raise InvestigationToolError("source evidence is outside the bound proof")
        envelope = self._journal.get_by_id(envelope_id)
        if envelope is None:
            self._record(
                tool=InvestigationToolName.SOURCE_EVIDENCE,
                request_ref=str(envelope_id),
                outcome=InvestigationToolOutcome.DENIED,
                returned_refs=(),
                result_value={"denied": "SOURCE_NOT_RETAINED"},
                error_code="SOURCE_NOT_RETAINED",
            )
            raise InvestigationToolError("source evidence is not retained")
        view = SourceEvidenceView(
            source_envelope_id=envelope.id,
            source_kind=envelope.source_kind,
            source_record_id=envelope.source_record_id,
            occurred_at=envelope.occurred_at,
            received_at=envelope.received_at,
            schema_version=envelope.schema_version,
            payload_sha256=envelope.payload_sha256,
            trust_label="UNTRUSTED_SOURCE_DATA",
            untrusted_text_fields=_extract_untrusted_text(envelope.payload),
        )
        self._accessed_source_ids.add(envelope.id)
        self._record(
            tool=InvestigationToolName.SOURCE_EVIDENCE,
            request_ref=str(envelope.id),
            outcome=InvestigationToolOutcome.ALLOWED,
            returned_refs=(str(envelope.id),),
            result_value=view,
        )
        return view


def _required_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise InvestigationError(f"{label} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise InvestigationError(f"{label} keys must be strings")
    return value


def _required_string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise InvestigationError(f"{label} must be string")
    return _text(value, label)


def _optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _required_string(value, label)


def parse_investigation_proposal(payload: Mapping[str, object]) -> InvestigationProposal:
    root = _required_mapping(payload, "investigation proposal")
    allowed_keys = {
        "case_id",
        "observation_id",
        "proof_version_id",
        "hypothesis",
        "citations",
        "financial_claims",
        "next_action",
        "request_source_kind",
    }
    extras = set(root) - allowed_keys
    missing = allowed_keys - set(root)
    if extras or missing:
        raise InvestigationError(
            "investigation proposal fields mismatch: "
            f"missing={sorted(missing)} extra={sorted(extras)}"
        )
    try:
        case_id = domain.ExceptionCaseId(_required_string(root["case_id"], "case_id"))
        observation_id = domain.ExceptionCaseObservationId(
            _required_string(root["observation_id"], "observation_id")
        )
        proof_version_id = domain.ProofVersionId(
            _required_string(root["proof_version_id"], "proof_version_id")
        )
    except (TypeError, ValueError) as exc:
        raise InvestigationError("proposal contains invalid bound artifact ID") from exc
    hypothesis = _optional_string(root["hypothesis"], "hypothesis")
    citations_raw = root["citations"]
    if not isinstance(citations_raw, list):
        raise InvestigationError("citations must be an array")
    try:
        citations = tuple(
            domain.SourceEnvelopeId(_required_string(value, "citation")) for value in citations_raw
        )
    except (TypeError, ValueError) as exc:
        raise InvestigationError("proposal contains invalid source citation") from exc
    claims_raw = root["financial_claims"]
    if not isinstance(claims_raw, list):
        raise InvestigationError("financial_claims must be an array")
    claims: list[MoneyClaim] = []
    for raw_claim in claims_raw:
        claim = _required_mapping(raw_claim, "financial claim")
        if set(claim) != {"fact", "amount_paise", "currency"}:
            raise InvestigationError("financial claim fields must be fact/amount_paise/currency")
        try:
            fact = FinancialFactKind(_required_string(claim["fact"], "financial fact"))
            currency = domain.Currency(_required_string(claim["currency"], "claim currency"))
        except ValueError as exc:
            raise InvestigationError("unsupported financial claim fact/currency") from exc
        amount = claim["amount_paise"]
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise InvestigationError("claim amount_paise must be exact integer")
        claims.append(MoneyClaim(fact=fact, amount=domain.Money(amount, currency)))
    try:
        action = InvestigationAction(_required_string(root["next_action"], "next_action"))
    except ValueError as exc:
        raise InvestigationError("unsupported investigation action") from exc
    request_source_raw = root["request_source_kind"]
    if request_source_raw is None:
        request_source_kind = None
    else:
        try:
            request_source_kind = domain.SourceKind(
                _required_string(request_source_raw, "request_source_kind")
            )
        except ValueError as exc:
            raise InvestigationError("unsupported request source kind") from exc
    return InvestigationProposal(
        case_id=case_id,
        observation_id=observation_id,
        proof_version_id=proof_version_id,
        hypothesis=hypothesis,
        citations=citations,
        financial_claims=tuple(claims),
        next_action=action,
        request_source_kind=request_source_kind,
    )


def _expected_facts(
    case_state: ExceptionCaseState,
    proof: ReconciliationProofVersion,
) -> dict[FinancialFactKind, domain.Money]:
    return {
        FinancialFactKind.AFFECTED_AMOUNT: case_state.affected_amount,
        FinancialFactKind.SETTLEMENT_AMOUNT: proof.composition.settlement_amount,
        FinancialFactKind.COMPOSITION_OBSERVED: proof.composition.observed_composition,
        FinancialFactKind.COMPOSITION_RESIDUAL: proof.composition.residual,
        FinancialFactKind.BANK_EXPECTED_AMOUNT: proof.bank.expected_amount,
        FinancialFactKind.BANK_OBSERVED_CREDIT: proof.bank.observed_bank_credit,
        FinancialFactKind.BANK_RESIDUAL: proof.bank.residual,
    }


def _validate_proposal(
    proposal: InvestigationProposal,
    *,
    tools: ReadOnlyInvestigationTools,
) -> None:
    context = tools.context
    if proposal.case_id != context.case_id:
        raise InvestigationError("proposal case id does not match target")
    if proposal.observation_id != context.observation_id:
        raise InvestigationError("proposal observation id does not match target")
    if proposal.proof_version_id != context.proof_version_id:
        raise InvestigationError("proposal proof id does not match target")
    if (
        proposal.hypothesis is not None
        and len(proposal.hypothesis) > MAX_INVESTIGATION_HYPOTHESIS_CHARS
    ):
        raise InvestigationError("hypothesis exceeds bounded length")
    if len(proposal.citations) > MAX_INVESTIGATION_SOURCE_IDS:
        raise InvestigationError("proposal exceeds bounded citation count")
    if len(proposal.financial_claims) > len(FinancialFactKind):
        raise InvestigationError("proposal exceeds bounded financial-claim count")
    if tuple(sorted(set(proposal.citations), key=str)) != proposal.citations:
        raise InvestigationError("proposal citations must be unique and canonical-sorted")
    facts = tuple(claim.fact for claim in proposal.financial_claims)
    if tuple(sorted(set(facts), key=lambda value: value.value)) != facts:
        raise InvestigationError("financial claims must be unique and canonical-sorted")
    if proposal.next_action is InvestigationAction.ABSTAIN:
        if (
            proposal.hypothesis is not None
            or proposal.citations
            or proposal.financial_claims
            or proposal.request_source_kind is not None
        ):
            raise InvestigationError(
                "ABSTAIN proposal must not carry unsupported hypothesis claims"
            )
        return
    if proposal.hypothesis is None:
        raise InvestigationError("non-abstain proposal requires hypothesis text")
    if re.search(r"\d", proposal.hypothesis):
        raise InvestigationError(
            "hypothesis prose cannot contain digits; use typed financial claims"
        )
    if not proposal.citations:
        raise InvestigationError("non-abstain proposal requires at least one source citation")
    allowed_ids = frozenset(context.available_source_envelope_ids)
    for citation in proposal.citations:
        if citation not in allowed_ids:
            raise InvestigationError("proposal cites evidence outside the bound proof")
        if citation not in tools.accessed_source_envelope_ids:
            raise InvestigationError("proposal cites proof evidence that was not retrieved")
    expected = _expected_facts(tools._case_state, tools._proof)
    for claim in proposal.financial_claims:
        if claim.amount != expected[claim.fact]:
            raise InvestigationError(f"financial claim does not match exact {claim.fact.value}")
    if proposal.next_action is InvestigationAction.REQUEST_SOURCE:
        if proposal.request_source_kind is None:
            raise InvestigationError("REQUEST_SOURCE requires one source kind")
        current_kinds = {state.source_kind for state in context.source_states}
        if proposal.request_source_kind not in current_kinds:
            raise InvestigationError("REQUEST_SOURCE names source outside current case packet")
    elif proposal.request_source_kind is not None:
        raise InvestigationError("request_source_kind is only valid for REQUEST_SOURCE")
    if proposal.next_action is InvestigationAction.WAIT:
        source_wait = any(
            state.completeness
            in {SourceCompleteness.WAITING, SourceCompleteness.LATE, SourceCompleteness.PARTIAL}
            for state in context.source_states
        )
        if (
            context.financial_status is not ReconciliationStatus.PENDING_BANK_CREDIT
            and not source_wait
        ):
            raise InvestigationError("WAIT has no deterministic pending/waiting condition")


@dataclass(frozen=True, slots=True)
class InvestigationRunResult:
    id: domain.InvestigationResultId
    status: InvestigationRunStatus
    case_id: domain.ExceptionCaseId
    observation_id: domain.ExceptionCaseObservationId
    proof_version_id: domain.ProofVersionId
    as_of: datetime
    next_action: InvestigationAction
    hypothesis: str | None
    citations: tuple[domain.SourceEnvelopeId, ...]
    financial_claims: tuple[MoneyClaim, ...]
    request_source_kind: domain.SourceKind | None
    trace: tuple[ToolTraceEntry, ...]
    rejection_reason: str | None
    ruleset_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, domain.InvestigationResultId):
            raise TypeError("investigation result id must be InvestigationResultId")
        if not isinstance(self.status, InvestigationRunStatus):
            raise TypeError("investigation result status must be InvestigationRunStatus")
        _aware(self.as_of, "investigation result as_of")
        if any(not isinstance(item, ToolTraceEntry) for item in self.trace):
            raise TypeError("investigation trace must contain ToolTraceEntry")
        if tuple(item.sequence for item in self.trace) != tuple(range(1, len(self.trace) + 1)):
            raise InvestigationError("investigation trace sequence must be contiguous")
        if self.ruleset_version != GATE16_INVESTIGATION_RULESET_VERSION:
            raise InvestigationError("result ruleset version does not match Gate 16")
        if self.status is InvestigationRunStatus.VALIDATED:
            if self.next_action is InvestigationAction.ABSTAIN:
                raise InvestigationError("validated non-abstain result cannot use ABSTAIN")
            if self.hypothesis is None or self.rejection_reason is not None:
                raise InvestigationError(
                    "validated result hypothesis/rejection relationship invalid"
                )
        elif self.status is InvestigationRunStatus.ABSTAINED:
            if (
                self.next_action is not InvestigationAction.ABSTAIN
                or self.rejection_reason is not None
            ):
                raise InvestigationError("abstained result must be clean ABSTAIN")
            if self.hypothesis is not None or self.citations or self.financial_claims:
                raise InvestigationError("abstained result cannot carry hypothesis claims")
        else:
            if self.next_action is not InvestigationAction.ABSTAIN:
                raise InvestigationError("rejected/provider-error result must ABSTAIN")
            if self.rejection_reason is None:
                raise InvestigationError("rejected/provider-error result requires reason")
            if self.hypothesis is not None or self.citations or self.financial_claims:
                raise InvestigationError(
                    "rejected/provider-error result cannot carry accepted claims"
                )
        material = {
            "contract": GATE16_INVESTIGATION_RULESET_VERSION,
            "status": self.status.value,
            "case_id": str(self.case_id),
            "observation_id": str(self.observation_id),
            "proof_version_id": str(self.proof_version_id),
            "as_of": self.as_of.isoformat(),
            "next_action": self.next_action.value,
            "hypothesis": self.hypothesis,
            "citations": [str(value) for value in self.citations],
            "financial_claims": [
                {
                    "fact": claim.fact.value,
                    "amount_paise": claim.amount.amount_paise,
                    "currency": claim.amount.currency.value,
                }
                for claim in self.financial_claims
            ],
            "request_source_kind": (
                None if self.request_source_kind is None else self.request_source_kind.value
            ),
            "trace_ids": [str(value.id) for value in self.trace],
            "rejection_reason": self.rejection_reason,
        }
        expected = domain.InvestigationResultId(_content_id("invest_", material))
        if self.id != expected:
            raise InvestigationError("investigation result id does not match immutable content")


def _make_result(
    *,
    status: InvestigationRunStatus,
    context: InvestigationContext,
    next_action: InvestigationAction,
    hypothesis: str | None,
    citations: tuple[domain.SourceEnvelopeId, ...],
    financial_claims: tuple[MoneyClaim, ...],
    request_source_kind: domain.SourceKind | None,
    trace: tuple[ToolTraceEntry, ...],
    rejection_reason: str | None,
) -> InvestigationRunResult:
    material = {
        "contract": GATE16_INVESTIGATION_RULESET_VERSION,
        "status": status.value,
        "case_id": str(context.case_id),
        "observation_id": str(context.observation_id),
        "proof_version_id": str(context.proof_version_id),
        "as_of": context.as_of.isoformat(),
        "next_action": next_action.value,
        "hypothesis": hypothesis,
        "citations": [str(value) for value in citations],
        "financial_claims": [
            {
                "fact": claim.fact.value,
                "amount_paise": claim.amount.amount_paise,
                "currency": claim.amount.currency.value,
            }
            for claim in financial_claims
        ],
        "request_source_kind": None if request_source_kind is None else request_source_kind.value,
        "trace_ids": [str(value.id) for value in trace],
        "rejection_reason": rejection_reason,
    }
    return InvestigationRunResult(
        id=domain.InvestigationResultId(_content_id("invest_", material)),
        status=status,
        case_id=context.case_id,
        observation_id=context.observation_id,
        proof_version_id=context.proof_version_id,
        as_of=context.as_of,
        next_action=next_action,
        hypothesis=hypothesis,
        citations=citations,
        financial_claims=financial_claims,
        request_source_kind=request_source_kind,
        trace=trace,
        rejection_reason=rejection_reason,
        ruleset_version=GATE16_INVESTIGATION_RULESET_VERSION,
    )


def run_investigation(
    provider: InvestigationProvider,
    *,
    case_state: ExceptionCaseState,
    observation: ExceptionCaseObservation,
    proof: ReconciliationProofVersion,
    journal: Journal,
    as_of: datetime,
) -> InvestigationRunResult:
    tools = ReadOnlyInvestigationTools(
        case_state=case_state,
        observation=observation,
        proof=proof,
        journal=journal,
        as_of=as_of,
    )
    context = tools.context
    try:
        raw = provider.propose(context, tools)
    except InvestigationToolError as exc:
        return _make_result(
            status=InvestigationRunStatus.REJECTED,
            context=context,
            next_action=InvestigationAction.ABSTAIN,
            hypothesis=None,
            citations=(),
            financial_claims=(),
            request_source_kind=None,
            trace=tools.trace,
            rejection_reason=f"tool_rejected:{type(exc).__name__}:{exc}",
        )
    except Exception as exc:  # provider outage/failure must remain non-authoritative
        return _make_result(
            status=InvestigationRunStatus.PROVIDER_ERROR,
            context=context,
            next_action=InvestigationAction.ABSTAIN,
            hypothesis=None,
            citations=(),
            financial_claims=(),
            request_source_kind=None,
            trace=tools.trace,
            rejection_reason=f"provider_error:{type(exc).__name__}",
        )
    try:
        proposal = parse_investigation_proposal(raw)
        _validate_proposal(proposal, tools=tools)
    except (InvestigationError, TypeError, ValueError) as exc:
        return _make_result(
            status=InvestigationRunStatus.REJECTED,
            context=context,
            next_action=InvestigationAction.ABSTAIN,
            hypothesis=None,
            citations=(),
            financial_claims=(),
            request_source_kind=None,
            trace=tools.trace,
            rejection_reason=f"validation_rejected:{type(exc).__name__}:{exc}",
        )
    if proposal.next_action is InvestigationAction.ABSTAIN:
        return _make_result(
            status=InvestigationRunStatus.ABSTAINED,
            context=context,
            next_action=proposal.next_action,
            hypothesis=None,
            citations=(),
            financial_claims=(),
            request_source_kind=None,
            trace=tools.trace,
            rejection_reason=None,
        )
    return _make_result(
        status=InvestigationRunStatus.VALIDATED,
        context=context,
        next_action=proposal.next_action,
        hypothesis=proposal.hypothesis,
        citations=proposal.citations,
        financial_claims=proposal.financial_claims,
        request_source_kind=proposal.request_source_kind,
        trace=tools.trace,
        rejection_reason=None,
    )
