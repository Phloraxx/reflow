from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from . import domain
from .ingestion import CanonicalBatch, SourceIdentity

INSTANT_SETTLEMENT_BANK_RULESET_VERSION = "gate51-instant-bank-v1"

__all__ = [
    "INSTANT_SETTLEMENT_BANK_RULESET_VERSION",
    "InstantPayoutReceiptProof",
    "InstantSettlementBankProof",
    "InstantSettlementProofError",
    "InstantSettlementReceiptStatus",
    "prove_all_instant_settlement_receipts",
]


class InstantSettlementReceiptStatus(StrEnum):
    PROVEN = "instant_bank_receipt_proven"
    WAITING = "instant_bank_receipt_waiting"
    RESIDUAL = "instant_bank_receipt_residual"
    INCOMPLETE = "instant_bank_receipt_incomplete"
    CONTRADICTED = "instant_bank_receipt_contradicted"


class InstantSettlementProofError(ValueError):
    """Instant Settlement inputs cannot support a trustworthy payout proof."""


@dataclass(frozen=True, slots=True)
class InstantPayoutReceiptProof:
    payout_id: domain.InstantSettlementPayoutId
    instant_settlement_id: domain.InstantSettlementId
    status: InstantSettlementReceiptStatus
    payout_utr: str | None
    expected_amount: domain.Money
    observed_bank_credit: domain.Money
    residual: domain.Money
    bank_entry_ids: tuple[domain.BankEntryId, ...]
    source_envelope_ids: tuple[domain.SourceEnvelopeId, ...]
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.observed_bank_credit.currency != self.expected_amount.currency:
            raise ValueError("instant payout proof currencies must match")
        if self.residual != self.expected_amount - self.observed_bank_credit:
            raise ValueError("instant payout residual must equal expected minus observed")
        if not self.source_envelope_ids:
            raise ValueError("instant payout proof must cite raw source envelopes")
        if self.status is InstantSettlementReceiptStatus.PROVEN:
            if len(self.bank_entry_ids) != 1:
                raise ValueError("proven instant payout requires exactly one bank entry")
            if not self.residual.is_zero or self.reason_codes:
                raise ValueError("proven instant payout cannot retain residual/reasons")


@dataclass(frozen=True, slots=True)
class InstantSettlementBankProof:
    instant_settlement_id: domain.InstantSettlementId
    status: InstantSettlementReceiptStatus
    expected_amount: domain.Money
    observed_bank_credit: domain.Money
    residual: domain.Money
    payout_proofs: tuple[InstantPayoutReceiptProof, ...]
    bank_entry_ids: tuple[domain.BankEntryId, ...]
    source_envelope_ids: tuple[domain.SourceEnvelopeId, ...]
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.observed_bank_credit.currency != self.expected_amount.currency:
            raise ValueError("instant settlement proof currencies must match")
        if self.residual != self.expected_amount - self.observed_bank_credit:
            raise ValueError("instant settlement residual must equal expected minus observed")
        if not self.source_envelope_ids:
            raise ValueError("instant settlement proof must cite raw source envelopes")
        if self.status is InstantSettlementReceiptStatus.PROVEN:
            if not self.payout_proofs or any(
                item.status is not InstantSettlementReceiptStatus.PROVEN
                for item in self.payout_proofs
            ):
                raise ValueError("proven instant settlement requires every payout proven")
            if not self.residual.is_zero or self.reason_codes:
                raise ValueError("proven instant settlement cannot retain residual/reasons")


def _require_source(
    source_index: dict[SourceIdentity, domain.SourceEnvelopeId],
    source_kind: domain.SourceKind,
    record_id: str,
) -> domain.SourceEnvelopeId:
    envelope_id = source_index.get((source_kind, record_id))
    if envelope_id is None:
        raise InstantSettlementProofError(
            "Instant Settlement proof is missing journal-backed source provenance: "
            f"{source_kind.value}/{record_id}"
        )
    return envelope_id


def _deduplicate_bank_entries(
    entries: tuple[domain.BankEntry, ...],
) -> tuple[domain.BankEntry, ...]:
    by_id: dict[domain.BankEntryId, domain.BankEntry] = {}
    for entry in entries:
        prior = by_id.get(entry.id)
        if prior is None:
            by_id[entry.id] = entry
        elif prior != entry:
            raise InstantSettlementProofError(
                f"bank entry id {entry.id} has conflicting canonical payloads"
            )
    return tuple(sorted(by_id.values(), key=lambda item: str(item.id)))


def _payout_proof(
    payout: domain.InstantSettlementPayout,
    *,
    parent_source_id: domain.SourceEnvelopeId,
    source_index: dict[SourceIdentity, domain.SourceEnvelopeId],
    bank_by_utr: dict[str, tuple[domain.BankEntry, ...]],
    reused_payout_utrs: frozenset[str],
    conflicting_payout_source_ids: tuple[domain.SourceEnvelopeId, ...],
) -> InstantPayoutReceiptProof:
    payout_source_id = _require_source(
        source_index,
        domain.SourceKind.RAZORPAY_INSTANT_SETTLEMENT,
        str(payout.id),
    )
    source_ids: set[domain.SourceEnvelopeId] = {
        parent_source_id,
        payout_source_id,
        *conflicting_payout_source_ids,
    }
    reason_codes: set[str] = set()
    accepted: tuple[domain.BankEntry, ...] = ()

    if payout.status != "processed":
        status = InstantSettlementReceiptStatus.INCOMPLETE
        reason_codes.add("INSTANT_PAYOUT_NOT_PROCESSED")
    elif payout.processed_at is None:
        status = InstantSettlementReceiptStatus.INCOMPLETE
        reason_codes.add("INSTANT_PAYOUT_PROCESSED_AT_MISSING")
    elif payout.utr is None:
        status = InstantSettlementReceiptStatus.INCOMPLETE
        reason_codes.add("INSTANT_PAYOUT_UTR_MISSING")
    elif payout.amount_settled.amount_paise <= 0:
        status = InstantSettlementReceiptStatus.INCOMPLETE
        reason_codes.add("INSTANT_PAYOUT_SETTLED_AMOUNT_MISSING")
    else:
        exact = bank_by_utr.get(payout.utr, ())
        for entry in exact:
            source_ids.add(
                _require_source(source_index, domain.SourceKind.BANK, str(entry.id))
            )
        if payout.utr in reused_payout_utrs:
            status = InstantSettlementReceiptStatus.CONTRADICTED
            reason_codes.add("INSTANT_PAYOUT_UTR_REUSED")
        elif len(exact) > 1:
            status = InstantSettlementReceiptStatus.CONTRADICTED
            reason_codes.add("BANK_UTR_REUSED_ACROSS_ENTRIES")
        elif exact and exact[0].occurred_at < payout.processed_at:
            status = InstantSettlementReceiptStatus.CONTRADICTED
            reason_codes.add("BANK_CREDIT_PRECEDES_INSTANT_PAYOUT")
        elif not exact:
            status = InstantSettlementReceiptStatus.WAITING
            reason_codes.add("BANK_RECEIPT_NOT_OBSERVED")
        else:
            accepted = exact
            if exact[0].amount.currency != payout.amount_settled.currency:
                raise InstantSettlementProofError(
                    "instant payout and exact-UTR bank currencies differ"
                )
            if exact[0].amount == payout.amount_settled:
                status = InstantSettlementReceiptStatus.PROVEN
            else:
                status = InstantSettlementReceiptStatus.RESIDUAL
                reason_codes.add("BANK_AMOUNT_MISMATCH")

    observed = domain.sum_money(
        [entry.amount for entry in accepted], payout.amount_settled.currency
    )
    return InstantPayoutReceiptProof(
        payout_id=payout.id,
        instant_settlement_id=payout.instant_settlement_id,
        status=status,
        payout_utr=payout.utr,
        expected_amount=payout.amount_settled,
        observed_bank_credit=observed,
        residual=payout.amount_settled - observed,
        bank_entry_ids=tuple(entry.id for entry in accepted),
        source_envelope_ids=tuple(sorted(source_ids, key=str)),
        reason_codes=tuple(sorted(reason_codes)),
    )


def _parent_status(
    child_statuses: tuple[InstantSettlementReceiptStatus, ...],
) -> InstantSettlementReceiptStatus:
    for status in (
        InstantSettlementReceiptStatus.CONTRADICTED,
        InstantSettlementReceiptStatus.INCOMPLETE,
        InstantSettlementReceiptStatus.RESIDUAL,
        InstantSettlementReceiptStatus.WAITING,
    ):
        if status in child_statuses:
            return status
    return InstantSettlementReceiptStatus.PROVEN


def prove_all_instant_settlement_receipts(
    batch: CanonicalBatch,
) -> tuple[InstantSettlementBankProof, ...]:
    if not batch.source_links:
        raise InstantSettlementProofError(
            "Instant Settlement proof requires journal-backed source provenance"
        )
    source_index = batch.source_index()

    parents: dict[domain.InstantSettlementId, domain.InstantSettlement] = {}
    for parent in batch.instant_settlements:
        if parent.id in parents:
            raise InstantSettlementProofError(f"duplicate Instant Settlement id {parent.id}")
        parents[parent.id] = parent

    payouts: dict[domain.InstantSettlementPayoutId, domain.InstantSettlementPayout] = {}
    payout_utr_owners: dict[str, set[domain.InstantSettlementPayoutId]] = {}
    for payout in batch.instant_settlement_payouts:
        if payout.id in payouts:
            raise InstantSettlementProofError(f"duplicate Instant Settlement payout id {payout.id}")
        payouts[payout.id] = payout
        if payout.utr is not None:
            payout_utr_owners.setdefault(payout.utr, set()).add(payout.id)

    referenced_payout_ids: set[domain.InstantSettlementPayoutId] = set()
    for parent in parents.values():
        for payout_id in parent.payout_ids:
            child = payouts.get(payout_id)
            if child is None:
                raise InstantSettlementProofError(
                    f"Instant Settlement {parent.id} references missing payout {payout_id}"
                )
            if child.instant_settlement_id != parent.id:
                raise InstantSettlementProofError(
                    "Instant Settlement payout parent identity disagrees with parent"
                )
            referenced_payout_ids.add(payout_id)
    orphan_ids = set(payouts) - referenced_payout_ids
    if orphan_ids:
        raise InstantSettlementProofError(
            "Instant Settlement batch contains payout not referenced by its parent"
        )

    reused_payout_utrs = frozenset(
        utr for utr, owners in payout_utr_owners.items() if len(owners) > 1
    )
    conflicting_payout_sources: dict[
        domain.InstantSettlementPayoutId, tuple[domain.SourceEnvelopeId, ...]
    ] = {}
    for payout_id, payout in payouts.items():
        if payout.utr is None:
            conflicting_payout_sources[payout_id] = ()
            continue
        conflicting_payout_sources[payout_id] = tuple(
            sorted(
                (
                    _require_source(
                        source_index,
                        domain.SourceKind.RAZORPAY_INSTANT_SETTLEMENT,
                        str(other_id),
                    )
                    for other_id in payout_utr_owners.get(payout.utr, set())
                    if other_id != payout_id
                ),
                key=str,
            )
        )
    bank_entries = _deduplicate_bank_entries(batch.bank_entries)
    bank_by_utr: dict[str, list[domain.BankEntry]] = {}
    for entry in bank_entries:
        if entry.utr is not None:
            bank_by_utr.setdefault(entry.utr, []).append(entry)
    bank_index = {
        utr: tuple(sorted(values, key=lambda item: str(item.id)))
        for utr, values in bank_by_utr.items()
    }

    result: list[InstantSettlementBankProof] = []
    for parent_id in sorted(parents, key=str):
        parent = parents[parent_id]
        parent_source_id = _require_source(
            source_index,
            domain.SourceKind.RAZORPAY_INSTANT_SETTLEMENT,
            str(parent.id),
        )
        child_proofs = tuple(
            _payout_proof(
                payouts[payout_id],
                parent_source_id=parent_source_id,
                source_index=source_index,
                bank_by_utr=bank_index,
                reused_payout_utrs=reused_payout_utrs,
                conflicting_payout_source_ids=conflicting_payout_sources[payout_id],
            )
            for payout_id in parent.payout_ids
        )
        reason_codes: set[str] = set(
            code for proof in child_proofs for code in proof.reason_codes
        )
        payout_expected = domain.sum_money(
            [proof.expected_amount for proof in child_proofs],
            parent.amount_settled.currency,
        )
        observed = domain.sum_money(
            [proof.observed_bank_credit for proof in child_proofs],
            parent.amount_settled.currency,
        )
        if not child_proofs:
            status = InstantSettlementReceiptStatus.INCOMPLETE
            reason_codes.add("INSTANT_SETTLEMENT_PAYOUTS_MISSING")
        elif parent.status != "processed":
            status = InstantSettlementReceiptStatus.INCOMPLETE
            reason_codes.add("INSTANT_SETTLEMENT_NOT_PROCESSED")
        elif payout_expected != parent.amount_settled:
            status = InstantSettlementReceiptStatus.CONTRADICTED
            reason_codes.add("INSTANT_SETTLEMENT_PAYOUT_TOTAL_MISMATCH")
        else:
            status = _parent_status(tuple(proof.status for proof in child_proofs))
        source_ids = {parent_source_id}
        bank_ids: set[domain.BankEntryId] = set()
        for proof in child_proofs:
            source_ids.update(proof.source_envelope_ids)
            bank_ids.update(proof.bank_entry_ids)
        result.append(
            InstantSettlementBankProof(
                instant_settlement_id=parent.id,
                status=status,
                expected_amount=parent.amount_settled,
                observed_bank_credit=observed,
                residual=parent.amount_settled - observed,
                payout_proofs=child_proofs,
                bank_entry_ids=tuple(sorted(bank_ids, key=str)),
                source_envelope_ids=tuple(sorted(source_ids, key=str)),
                reason_codes=tuple(sorted(reason_codes)),
            )
        )
    return tuple(result)
