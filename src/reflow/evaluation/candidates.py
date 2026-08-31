from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from reflow import domain
from reflow.bank_proof import prove_all_bank_receipts
from reflow.ingestion import CanonicalBatch
from reflow.journal import InMemoryJournal
from reflow.money_graph import build_money_graph
from reflow.reconciliation_proof import (
    InMemoryProofLedger,
    ReconciliationStatus,
)
from reflow.settlement_proof import prove_all_settlement_compositions


class CandidateStatus(StrEnum):
    RECONCILED = "reconciled"
    UNRESOLVED = "unresolved"
    RESIDUAL = "residual"
    INCOMPLETE = "incomplete"
    CONTRADICTED = "contradicted"


@dataclass(frozen=True, slots=True)
class CandidateDecision:
    settlement_id: domain.SettlementId
    status: CandidateStatus
    composition_amount: domain.Money
    composition_residual: domain.Money
    bank_residual: domain.Money
    composition_component_ids: tuple[domain.ReconEntryId, ...]
    bank_entry_ids: tuple[domain.BankEntryId, ...]
    reason_codes: tuple[str, ...] = ()

    @property
    def auto_reconciled(self) -> bool:
        return self.status is CandidateStatus.RECONCILED


@dataclass(frozen=True, slots=True)
class CandidateRun:
    system_name: str
    decisions: tuple[CandidateDecision, ...]

    def __post_init__(self) -> None:
        ids = [decision.settlement_id for decision in self.decisions]
        if len(set(ids)) != len(ids):
            raise ValueError("candidate run contains duplicate settlement decisions")
        expected = tuple(
            sorted(self.decisions, key=lambda item: str(item.settlement_id))
        )
        if self.decisions != expected:
            raise ValueError("candidate decisions must be sorted by settlement id")


def _sum_recon(
    rows: tuple[domain.SettlementReconEntry, ...],
    currency: domain.Currency,
) -> domain.Money:
    return domain.sum_money([row.settlement_effect for row in rows], currency)


def run_naive_one_to_one(batch: CanonicalBatch) -> CandidateRun:
    decisions: list[CandidateDecision] = []
    for settlement in sorted(batch.settlements, key=lambda item: str(item.id)):
        recon = tuple(
            row
            for row in batch.recon_entries
            if row.settlement_effect == settlement.amount
        )
        bank = tuple(row for row in batch.bank_entries if row.amount == settlement.amount)
        chosen_recon = recon if len(recon) == 1 else ()
        chosen_bank = bank if len(bank) == 1 else ()
        composition_amount = _sum_recon(chosen_recon, settlement.amount.currency)
        bank_amount = domain.sum_money(
            [row.amount for row in chosen_bank], settlement.amount.currency
        )
        reconciled = len(chosen_recon) == 1 and len(chosen_bank) == 1
        decisions.append(
            CandidateDecision(
                settlement_id=settlement.id,
                status=(CandidateStatus.RECONCILED if reconciled else CandidateStatus.UNRESOLVED),
                composition_amount=composition_amount,
                composition_residual=settlement.amount - composition_amount,
                bank_residual=settlement.amount - bank_amount,
                composition_component_ids=tuple(row.id for row in chosen_recon),
                bank_entry_ids=tuple(row.id for row in chosen_bank),
                reason_codes=(() if reconciled else ("NO_UNIQUE_ONE_TO_ONE_MATCH",)),
            )
        )
    return CandidateRun("B0_naive_1to1", tuple(decisions))


def _grouped_recon(batch: CanonicalBatch, settlement_id: domain.SettlementId):
    return tuple(
        sorted(
            (row for row in batch.recon_entries if row.settlement_id == settlement_id),
            key=lambda row: str(row.id),
        )
    )


def run_grouped_exact(batch: CanonicalBatch) -> CandidateRun:
    decisions: list[CandidateDecision] = []
    for settlement in sorted(batch.settlements, key=lambda item: str(item.id)):
        recon = _grouped_recon(batch, settlement.id)
        composition_amount = _sum_recon(recon, settlement.amount.currency)
        exact_bank = tuple(
            row
            for row in batch.bank_entries
            if settlement.utr is not None
            and row.utr == settlement.utr
            and row.occurred_at >= settlement.processed_at
        )
        accepted_bank = exact_bank if len(exact_bank) == 1 else ()
        bank_amount = domain.sum_money(
            [row.amount for row in accepted_bank], settlement.amount.currency
        )
        composition_ok = composition_amount == settlement.amount
        bank_ok = len(accepted_bank) == 1 and bank_amount == settlement.amount
        if composition_ok and bank_ok:
            status = CandidateStatus.RECONCILED
        elif not composition_ok or (bool(accepted_bank) and bank_amount != settlement.amount):
            status = CandidateStatus.RESIDUAL
        else:
            status = CandidateStatus.UNRESOLVED
        decisions.append(
            CandidateDecision(
                settlement_id=settlement.id,
                status=status,
                composition_amount=composition_amount,
                composition_residual=settlement.amount - composition_amount,
                bank_residual=settlement.amount - bank_amount,
                composition_component_ids=tuple(row.id for row in recon),
                bank_entry_ids=tuple(row.id for row in accepted_bank),
                reason_codes=(),
            )
        )
    return CandidateRun("B1_grouped_exact", tuple(decisions))


def _fuzzy_bank_score(settlement: domain.Settlement, row: domain.BankEntry) -> int:
    score = 0
    if row.amount == settlement.amount:
        score += 4
    delta = row.occurred_at - settlement.processed_at
    if timedelta(0) <= delta <= timedelta(days=3):
        score += 2
    if "razorpay" in row.narration.casefold():
        score += 1
    if settlement.utr is not None and row.utr == settlement.utr:
        score += 10
    return score


def run_fuzzy_threshold(batch: CanonicalBatch, *, threshold: int = 6) -> CandidateRun:
    decisions: list[CandidateDecision] = []
    for settlement in sorted(batch.settlements, key=lambda item: str(item.id)):
        recon = _grouped_recon(batch, settlement.id)
        composition_amount = _sum_recon(recon, settlement.amount.currency)
        ranked = sorted(
            (
                (_fuzzy_bank_score(settlement, row), str(row.id), row)
                for row in batch.bank_entries
                if row.amount.currency == settlement.amount.currency
            ),
            key=lambda item: (-item[0], item[1]),
        )
        chosen = () if not ranked or ranked[0][0] < threshold else (ranked[0][2],)
        bank_amount = domain.sum_money([row.amount for row in chosen], settlement.amount.currency)
        composition_ok = composition_amount == settlement.amount
        bank_ok = bool(chosen) and bank_amount == settlement.amount
        status = (
            CandidateStatus.RECONCILED
            if composition_ok and bank_ok
            else CandidateStatus.UNRESOLVED
        )
        decisions.append(
            CandidateDecision(
                settlement_id=settlement.id,
                status=status,
                composition_amount=composition_amount,
                composition_residual=settlement.amount - composition_amount,
                bank_residual=settlement.amount - bank_amount,
                composition_component_ids=tuple(row.id for row in recon),
                bank_entry_ids=tuple(row.id for row in chosen),
                reason_codes=(("FUZZY_BANK_THRESHOLD",) if chosen else ("NO_FUZZY_BANK_MATCH",)),
            )
        )
    return CandidateRun("B2_fuzzy_threshold", tuple(decisions))


def run_reflow_core(
    batch: CanonicalBatch,
    journal: InMemoryJournal,
    *,
    knowledge_cutoff: datetime,
) -> CandidateRun:
    graph = build_money_graph(batch)
    compositions = prove_all_settlement_compositions(batch, graph)
    banks = prove_all_bank_receipts(batch)
    ledger = InMemoryProofLedger()
    update = ledger.apply_batch(
        batch,
        journal,
        compositions,
        banks,
        knowledge_cutoff=knowledge_cutoff,
        generated_at=knowledge_cutoff + timedelta(microseconds=1),
    )
    status_map = {
        ReconciliationStatus.PROVEN_RECONCILED: CandidateStatus.RECONCILED,
        ReconciliationStatus.PENDING_BANK_CREDIT: CandidateStatus.UNRESOLVED,
        ReconciliationStatus.RESIDUAL: CandidateStatus.RESIDUAL,
        ReconciliationStatus.INCOMPLETE: CandidateStatus.INCOMPLETE,
        ReconciliationStatus.CONTRADICTED: CandidateStatus.CONTRADICTED,
    }
    decisions = tuple(
        CandidateDecision(
            settlement_id=proof.settlement_id,
            status=status_map[proof.status],
            composition_amount=proof.composition.observed_composition,
            composition_residual=proof.composition.residual,
            bank_residual=proof.bank.residual,
            composition_component_ids=proof.composition.component_ids,
            bank_entry_ids=proof.bank.bank_entry_ids,
            reason_codes=proof.reason_codes,
        )
        for proof in sorted(update.created_versions, key=lambda item: str(item.settlement_id))
    )
    return CandidateRun("ReFlow_Core", decisions)
