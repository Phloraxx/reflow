from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from . import domain
from .ingestion import CanonicalBatch
from .reconciliation_proof import ReconciliationProofVersion

__all__ = [
    "CandidateDisposition",
    "ResidualCandidate",
    "ResidualCandidateKind",
    "ResidualExplanation",
    "ResidualExplanationState",
    "ResidualScope",
    "ResidualSolveResult",
    "ResidualSolverError",
    "ResidualSolverLimits",
    "ResidualTarget",
    "enumerate_residual_candidates",
    "residual_targets",
    "solve_residual",
]


class ResidualScope(StrEnum):
    COMPOSITION = "composition"
    BANK = "bank"


class ResidualCandidateKind(StrEnum):
    UNMATCHED_BANK_CREDIT = "unmatched_bank_credit"
    BLOCKED_RECON_COMPONENT = "blocked_recon_component"


class CandidateDisposition(StrEnum):
    ADMISSIBLE_HYPOTHESIS = "admissible_hypothesis"
    BLOCKED_EVIDENCE = "blocked_evidence"


class ResidualExplanationState(StrEnum):
    HYPOTHESIS = "hypothesis"


class ResidualSolverError(ValueError):
    """Residual explanation inputs violate deterministic solver boundaries."""


@dataclass(frozen=True, slots=True)
class ResidualSolverLimits:
    max_candidates: int = 32
    max_combination_size: int = 3
    max_nodes: int = 2_000
    max_solutions: int = 20

    def __post_init__(self) -> None:
        if self.max_candidates < 1:
            raise ValueError("max_candidates must be positive")
        if self.max_combination_size < 1:
            raise ValueError("max_combination_size must be positive")
        if self.max_nodes < 1:
            raise ValueError("max_nodes must be positive")
        if self.max_solutions < 1:
            raise ValueError("max_solutions must be positive")


@dataclass(frozen=True, slots=True)
class ResidualTarget:
    settlement_id: domain.SettlementId
    proof_version_id: domain.ProofVersionId
    scope: ResidualScope
    amount: domain.Money

    def __post_init__(self) -> None:
        if self.amount.is_zero:
            raise ValueError("residual target must be non-zero")


@dataclass(frozen=True, slots=True)
class ResidualCandidate:
    id: domain.ResidualCandidateId
    settlement_id: domain.SettlementId
    scope: ResidualScope
    kind: ResidualCandidateKind
    amount: domain.Money
    source_envelope_ids: tuple[domain.SourceEnvelopeId, ...]
    source_entity_id: str
    disposition: CandidateDisposition
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.amount.is_zero:
            raise ValueError("residual candidate effect must be non-zero")
        if not self.source_envelope_ids:
            raise ValueError("residual candidate must cite raw evidence")


@dataclass(frozen=True, slots=True)
class ResidualExplanation:
    id: domain.ResidualExplanationId
    target: ResidualTarget
    candidate_ids: tuple[domain.ResidualCandidateId, ...]
    explained_amount: domain.Money
    remaining_residual: domain.Money
    source_envelope_ids: tuple[domain.SourceEnvelopeId, ...]
    uses_blocked_evidence: bool
    reason_codes: tuple[str, ...]
    state: ResidualExplanationState = ResidualExplanationState.HYPOTHESIS

    def __post_init__(self) -> None:
        if not self.candidate_ids:
            raise ValueError("residual explanation requires at least one candidate")
        if self.explained_amount.currency != self.target.amount.currency:
            raise ValueError("explanation currency must match target")
        if self.remaining_residual != self.target.amount - self.explained_amount:
            raise ValueError("remaining residual must equal target minus explanation")
        if not self.remaining_residual.is_zero:
            raise ValueError("published residual explanation must exactly close the target")
        if not self.source_envelope_ids:
            raise ValueError("residual explanation must cite raw evidence")


@dataclass(frozen=True, slots=True)
class ResidualSolveResult:
    target: ResidualTarget
    candidates_considered: tuple[ResidualCandidate, ...]
    explanations: tuple[ResidualExplanation, ...]
    nodes_visited: int
    candidate_space_truncated: bool
    search_budget_exhausted: bool


def residual_targets(proof: ReconciliationProofVersion) -> tuple[ResidualTarget, ...]:
    targets: list[ResidualTarget] = []
    if not proof.composition.residual.is_zero:
        targets.append(
            ResidualTarget(
                settlement_id=proof.settlement_id,
                proof_version_id=proof.id,
                scope=ResidualScope.COMPOSITION,
                amount=proof.composition.residual,
            )
        )
    if not proof.bank.residual.is_zero:
        targets.append(
            ResidualTarget(
                settlement_id=proof.settlement_id,
                proof_version_id=proof.id,
                scope=ResidualScope.BANK,
                amount=proof.bank.residual,
            )
        )
    return tuple(targets)


def _candidate_id(
    kind: ResidualCandidateKind,
    source_entity_id: str,
    amount: domain.Money,
    source_ids: tuple[domain.SourceEnvelopeId, ...],
) -> domain.ResidualCandidateId:
    material = "\0".join(
        (
            kind.value,
            source_entity_id,
            str(amount.amount_paise),
            amount.currency.value,
            *(str(source_id) for source_id in sorted(source_ids, key=str)),
        )
    ).encode()
    return domain.ResidualCandidateId(
        f"rcand_{hashlib.sha256(material).hexdigest()[:24]}"
    )


def _source_id(
    batch: CanonicalBatch,
    source_kind: domain.SourceKind,
    source_record_id: str,
) -> domain.SourceEnvelopeId:
    envelope_id = batch.source_index().get((source_kind, source_record_id))
    if envelope_id is None:
        raise ResidualSolverError(
            f"candidate evidence is missing provenance: {source_kind.value}/{source_record_id}"
        )
    return envelope_id


def _candidate_sort_key(
    target: ResidualTarget,
    candidate: ResidualCandidate,
) -> tuple[int, int, int, str]:
    delta = abs(target.amount.amount_paise - candidate.amount.amount_paise)
    return (
        0 if candidate.amount == target.amount else 1,
        0 if candidate.disposition is CandidateDisposition.ADMISSIBLE_HYPOTHESIS else 1,
        delta,
        str(candidate.id),
    )


def enumerate_residual_candidates(
    proof: ReconciliationProofVersion,
    batch: CanonicalBatch,
    target: ResidualTarget,
    *,
    limits: ResidualSolverLimits | None = None,
) -> tuple[tuple[ResidualCandidate, ...], bool]:
    cfg = limits or ResidualSolverLimits()
    if target.settlement_id != proof.settlement_id or target.proof_version_id != proof.id:
        raise ResidualSolverError("residual target belongs to another proof")
    if batch.compilation_sha256 != proof.batch_compilation_sha256:
        raise ResidualSolverError("candidate enumeration requires the proof's canonical batch")

    candidates: list[ResidualCandidate] = []
    if target.scope is ResidualScope.BANK:
        excluded = {
            *proof.bank.bank_entry_ids,
            *proof.bank.early_bank_entry_ids,
            *proof.bank.reused_bank_utr_ids,
        }
        if target.amount.amount_paise > 0:
            for bank_entry in batch.bank_entries:
                if (
                    bank_entry.id in excluded
                    or bank_entry.amount.currency != target.amount.currency
                ):
                    continue
                if (
                    bank_entry.amount.amount_paise <= 0
                    or bank_entry.amount.amount_paise > target.amount.amount_paise
                ):
                    continue
                source_ids = (
                    _source_id(batch, domain.SourceKind.BANK, str(bank_entry.id)),
                )
                candidates.append(
                    ResidualCandidate(
                        id=_candidate_id(
                            ResidualCandidateKind.UNMATCHED_BANK_CREDIT,
                            str(bank_entry.id),
                            bank_entry.amount,
                            source_ids,
                        ),
                        settlement_id=proof.settlement_id,
                        scope=target.scope,
                        kind=ResidualCandidateKind.UNMATCHED_BANK_CREDIT,
                        amount=bank_entry.amount,
                        source_envelope_ids=source_ids,
                        source_entity_id=str(bank_entry.id),
                        disposition=CandidateDisposition.ADMISSIBLE_HYPOTHESIS,
                        reason_codes=("AMOUNT_ONLY_NOT_IDENTITY",),
                    )
                )
    else:
        included = set(proof.composition.component_ids)
        for recon_entry in batch.recon_entries:
            if (
                recon_entry.settlement_id != proof.settlement_id
                or recon_entry.id in included
            ):
                continue
            if recon_entry.settlement_effect.currency != target.amount.currency:
                continue
            if recon_entry.settlement_effect.is_zero:
                continue
            source_ids = (
                _source_id(
                    batch,
                    domain.SourceKind.RAZORPAY_RECON,
                    str(recon_entry.id),
                ),
            )
            candidates.append(
                ResidualCandidate(
                    id=_candidate_id(
                        ResidualCandidateKind.BLOCKED_RECON_COMPONENT,
                        str(recon_entry.id),
                        recon_entry.settlement_effect,
                        source_ids,
                    ),
                    settlement_id=proof.settlement_id,
                    scope=target.scope,
                    kind=ResidualCandidateKind.BLOCKED_RECON_COMPONENT,
                    amount=recon_entry.settlement_effect,
                    source_envelope_ids=source_ids,
                    source_entity_id=str(recon_entry.id),
                    disposition=CandidateDisposition.BLOCKED_EVIDENCE,
                    reason_codes=("BLOCKED_BY_UPSTREAM_PROOF",),
                )
            )

    ordered = sorted(candidates, key=lambda candidate: _candidate_sort_key(target, candidate))
    truncated = len(ordered) > cfg.max_candidates
    return tuple(ordered[: cfg.max_candidates]), truncated


def _explanation_id(
    target: ResidualTarget,
    candidates: tuple[ResidualCandidate, ...],
) -> domain.ResidualExplanationId:
    material = "\0".join(
        (
            str(target.proof_version_id),
            target.scope.value,
            *(str(candidate.id) for candidate in candidates),
        )
    ).encode()
    return domain.ResidualExplanationId(
        f"rexp_{hashlib.sha256(material).hexdigest()[:24]}"
    )


def _make_explanation(
    target: ResidualTarget,
    candidates: tuple[ResidualCandidate, ...],
) -> ResidualExplanation:
    explained = domain.sum_money(
        [candidate.amount for candidate in candidates],
        target.amount.currency,
    )
    source_ids = tuple(
        sorted(
            {
                source_id
                for candidate in candidates
                for source_id in candidate.source_envelope_ids
            },
            key=str,
        )
    )
    blocked = any(
        candidate.disposition is CandidateDisposition.BLOCKED_EVIDENCE
        for candidate in candidates
    )
    reasons = {"NUMERICALLY_EXACT_HYPOTHESIS", "NOT_FINANCIAL_PROOF"}
    if blocked:
        reasons.add("USES_BLOCKED_EVIDENCE")
    for candidate in candidates:
        reasons.update(candidate.reason_codes)
    return ResidualExplanation(
        id=_explanation_id(target, candidates),
        target=target,
        candidate_ids=tuple(candidate.id for candidate in candidates),
        explained_amount=explained,
        remaining_residual=target.amount - explained,
        source_envelope_ids=source_ids,
        uses_blocked_evidence=blocked,
        reason_codes=tuple(sorted(reasons)),
    )


def solve_residual(
    target: ResidualTarget,
    candidates: tuple[ResidualCandidate, ...],
    *,
    limits: ResidualSolverLimits | None = None,
    candidate_space_truncated: bool = False,
) -> ResidualSolveResult:
    cfg = limits or ResidualSolverLimits()
    for candidate in candidates:
        if candidate.settlement_id != target.settlement_id or candidate.scope is not target.scope:
            raise ResidualSolverError("candidate belongs to another residual target")
        if candidate.amount.currency != target.amount.currency:
            raise ResidualSolverError("candidate currency differs from residual target")

    ordered = tuple(
        sorted(candidates, key=lambda candidate: _candidate_sort_key(target, candidate))
    )
    if len(ordered) > cfg.max_candidates:
        candidate_space_truncated = True
        ordered = ordered[: cfg.max_candidates]

    solutions: list[ResidualExplanation] = []
    nodes = 0
    exhausted = False

    def search(start: int, chosen: tuple[ResidualCandidate, ...], total: int) -> None:
        nonlocal nodes, exhausted
        if exhausted or len(solutions) >= cfg.max_solutions:
            return
        if nodes >= cfg.max_nodes:
            exhausted = True
            return
        nodes += 1
        if chosen and total == target.amount.amount_paise:
            solutions.append(_make_explanation(target, chosen))
            return
        if len(chosen) >= cfg.max_combination_size:
            return
        for index in range(start, len(ordered)):
            if exhausted or len(solutions) >= cfg.max_solutions:
                return
            candidate = ordered[index]
            search(
                index + 1,
                (*chosen, candidate),
                total + candidate.amount.amount_paise,
            )

    search(0, (), 0)
    unique = {explanation.id: explanation for explanation in solutions}
    return ResidualSolveResult(
        target=target,
        candidates_considered=ordered,
        explanations=tuple(sorted(unique.values(), key=lambda item: str(item.id))),
        nodes_visited=nodes,
        candidate_space_truncated=candidate_space_truncated,
        search_budget_exhausted=exhausted,
    )
