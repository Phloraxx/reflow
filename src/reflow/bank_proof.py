from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from . import domain, ingestion
from .ingestion import CanonicalBatch


class BankReceiptStatus(StrEnum):
    PROVEN = "bank_receipt_proven"
    WAITING = "bank_receipt_waiting"
    RESIDUAL = "bank_receipt_residual"
    INCOMPLETE = "bank_receipt_incomplete"
    CONTRADICTED = "bank_receipt_contradicted"


class BankReceiptProofError(ValueError):
    """Bank-proof inputs are structurally inconsistent and cannot be trusted."""


@dataclass(frozen=True, slots=True)
class BankReceiptProof:
    settlement_id: domain.SettlementId
    status: BankReceiptStatus
    settlement_utr: str | None
    expected_amount: domain.Money
    observed_bank_credit: domain.Money
    residual: domain.Money
    bank_entry_ids: tuple[domain.BankEntryId, ...]
    source_envelope_ids: tuple[domain.SourceEnvelopeId, ...]
    early_bank_entry_ids: tuple[domain.BankEntryId, ...]
    reused_bank_utr_ids: tuple[domain.BankEntryId, ...]
    rejected_same_amount_ids: tuple[domain.BankEntryId, ...]
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.observed_bank_credit.currency != self.expected_amount.currency:
            raise ValueError("bank proof currencies must match")
        if self.residual.currency != self.expected_amount.currency:
            raise ValueError("bank residual currency must match settlement")
        if self.residual != self.expected_amount - self.observed_bank_credit:
            raise ValueError("bank residual must equal settlement minus bank credit")
        if not self.source_envelope_ids:
            raise ValueError("bank proof must cite raw source envelopes")
        if self.status is BankReceiptStatus.PROVEN:
            if len(self.bank_entry_ids) != 1:
                raise ValueError("standard settlement proof requires exactly one bank entry")
            if not self.residual.is_zero:
                raise ValueError("proven bank receipt must have zero residual")
            if self.early_bank_entry_ids or self.reused_bank_utr_ids:
                raise ValueError("proven bank receipt cannot contain bank identity conflicts")
            if self.reason_codes:
                raise ValueError("proven bank receipt cannot carry failure reason codes")


type BankPayload = tuple[int, str, str, str, str | None]


def _bank_payload(entry: domain.BankEntry) -> BankPayload:
    return (
        entry.amount.amount_paise,
        entry.amount.currency.value,
        entry.occurred_at.isoformat(),
        entry.narration,
        entry.utr,
    )


def _deduplicate_bank_entries(
    entries: tuple[domain.BankEntry, ...],
) -> tuple[domain.BankEntry, ...]:
    by_id: dict[domain.BankEntryId, domain.BankEntry] = {}
    for entry in entries:
        existing = by_id.get(entry.id)
        if existing is None:
            by_id[entry.id] = entry
        elif _bank_payload(existing) != _bank_payload(entry):
            raise BankReceiptProofError(
                f"bank entry id {entry.id} has conflicting canonical payloads"
            )
    return tuple(sorted(by_id.values(), key=lambda row: str(row.id)))


def _require_source_envelope(
    source_index: dict[ingestion.SourceIdentity, domain.SourceEnvelopeId],
    source_kind: domain.SourceKind,
    source_record_id: str,
) -> domain.SourceEnvelopeId:
    envelope_id = source_index.get((source_kind, source_record_id))
    if envelope_id is None:
        raise BankReceiptProofError(
            "bank proof input is missing journal-backed source provenance: "
            f"{source_kind.value}/{source_record_id}"
        )
    return envelope_id


def _prove_from_candidates(
    settlement: domain.Settlement,
    exact_utr_entries: tuple[domain.BankEntry, ...],
    rejected_same_amount_entries: tuple[domain.BankEntry, ...],
    *,
    source_index: dict[ingestion.SourceIdentity, domain.SourceEnvelopeId],
    settlement_utr_reused: bool,
) -> BankReceiptProof:
    settlement_source_id = _require_source_envelope(
        source_index,
        domain.SourceKind.RAZORPAY_SETTLEMENT,
        str(settlement.id),
    )

    source_envelope_ids: set[domain.SourceEnvelopeId] = {settlement_source_id}
    for entry in (*exact_utr_entries, *rejected_same_amount_entries):
        source_envelope_ids.add(
            _require_source_envelope(
                source_index,
                domain.SourceKind.BANK,
                str(entry.id),
            )
        )

    for entry in exact_utr_entries:
        if entry.amount.currency != settlement.amount.currency:
            raise BankReceiptProofError("settlement and exact-UTR bank currencies differ")

    reused_bank_utr_entries = (
        tuple(sorted(exact_utr_entries, key=lambda row: str(row.id)))
        if len(exact_utr_entries) > 1
        else ()
    )
    early_entries = tuple(
        sorted(
            (
                entry
                for entry in exact_utr_entries
                if entry.occurred_at < settlement.processed_at
            ),
            key=lambda row: str(row.id),
        )
    )
    accepted_entries = (
        ()
        if reused_bank_utr_entries
        else tuple(
            entry
            for entry in exact_utr_entries
            if entry.occurred_at >= settlement.processed_at
        )
    )

    observed = domain.sum_money(
        [entry.amount for entry in accepted_entries],
        settlement.amount.currency,
    )
    residual = settlement.amount - observed

    reason_codes: set[str] = set()
    if settlement_utr_reused:
        reason_codes.add("SETTLEMENT_UTR_REUSED")
    if reused_bank_utr_entries:
        reason_codes.add("BANK_UTR_REUSED_ACROSS_ENTRIES")
    if early_entries:
        reason_codes.add("BANK_CREDIT_PRECEDES_SETTLEMENT")

    if settlement_utr_reused or reused_bank_utr_entries or early_entries:
        status = BankReceiptStatus.CONTRADICTED
    elif settlement.utr is None:
        status = BankReceiptStatus.INCOMPLETE
        reason_codes.add("SETTLEMENT_UTR_MISSING")
        if rejected_same_amount_entries:
            reason_codes.add("SAME_AMOUNT_NOT_IDENTITY")
    elif not exact_utr_entries:
        status = BankReceiptStatus.WAITING
        reason_codes.add("BANK_RECEIPT_NOT_OBSERVED")
        if rejected_same_amount_entries:
            reason_codes.add("SAME_AMOUNT_NOT_IDENTITY")
    elif residual.is_zero:
        status = BankReceiptStatus.PROVEN
    else:
        status = BankReceiptStatus.RESIDUAL
        reason_codes.add("BANK_AMOUNT_MISMATCH")

    return BankReceiptProof(
        settlement_id=settlement.id,
        status=status,
        settlement_utr=settlement.utr,
        expected_amount=settlement.amount,
        observed_bank_credit=observed,
        residual=residual,
        bank_entry_ids=tuple(entry.id for entry in accepted_entries),
        source_envelope_ids=tuple(sorted(source_envelope_ids, key=str)),
        early_bank_entry_ids=tuple(entry.id for entry in early_entries),
        reused_bank_utr_ids=tuple(entry.id for entry in reused_bank_utr_entries),
        rejected_same_amount_ids=tuple(
            sorted((entry.id for entry in rejected_same_amount_entries), key=str)
        ),
        reason_codes=tuple(sorted(reason_codes)),
    )


def prove_bank_receipt(
    settlement: domain.Settlement,
    bank_entries: tuple[domain.BankEntry, ...],
    *,
    source_index: dict[ingestion.SourceIdentity, domain.SourceEnvelopeId],
    settlement_utr_reused: bool = False,
) -> BankReceiptProof:
    """Prove one standard settlement against bank evidence using exact UTR identity."""
    unique_bank_entries = _deduplicate_bank_entries(bank_entries)
    exact_utr_entries = (
        ()
        if settlement.utr is None
        else tuple(entry for entry in unique_bank_entries if entry.utr == settlement.utr)
    )
    exact_ids = {entry.id for entry in exact_utr_entries}
    rejected_same_amount_entries = tuple(
        entry
        for entry in unique_bank_entries
        if entry.id not in exact_ids
        and entry.amount == settlement.amount
        and entry.occurred_at >= settlement.processed_at
    )
    return _prove_from_candidates(
        settlement,
        exact_utr_entries,
        rejected_same_amount_entries,
        source_index=source_index,
        settlement_utr_reused=settlement_utr_reused,
    )


def prove_all_bank_receipts(batch: CanonicalBatch) -> tuple[BankReceiptProof, ...]:
    if not batch.source_links:
        raise BankReceiptProofError("bank proof requires journal-backed source provenance")
    source_index = batch.source_index()

    settlements: dict[domain.SettlementId, domain.Settlement] = {}
    settlement_ids_by_utr: dict[str, set[domain.SettlementId]] = {}
    for settlement in batch.settlements:
        if settlement.id in settlements:
            raise BankReceiptProofError(f"duplicate settlement id {settlement.id}")
        settlements[settlement.id] = settlement
        if settlement.utr is not None:
            settlement_ids_by_utr.setdefault(settlement.utr, set()).add(settlement.id)

    reused_utrs = frozenset(
        utr for utr, settlement_ids in settlement_ids_by_utr.items() if len(settlement_ids) > 1
    )

    bank_entries = _deduplicate_bank_entries(batch.bank_entries)
    bank_by_utr: dict[str, list[domain.BankEntry]] = {}
    bank_by_amount: dict[tuple[int, str], list[domain.BankEntry]] = {}
    for entry in bank_entries:
        if entry.utr is not None:
            bank_by_utr.setdefault(entry.utr, []).append(entry)
        bank_by_amount.setdefault(
            (entry.amount.amount_paise, entry.amount.currency.value), []
        ).append(entry)

    proofs: list[BankReceiptProof] = []
    for settlement_id in sorted(settlements, key=str):
        settlement = settlements[settlement_id]
        exact_entries = (
            ()
            if settlement.utr is None
            else tuple(bank_by_utr.get(settlement.utr, ()))
        )
        exact_ids = {entry.id for entry in exact_entries}
        same_amount_entries = tuple(
            entry
            for entry in bank_by_amount.get(
                (settlement.amount.amount_paise, settlement.amount.currency.value),
                (),
            )
            if entry.id not in exact_ids and entry.occurred_at >= settlement.processed_at
        )
        proofs.append(
            _prove_from_candidates(
                settlement,
                exact_entries,
                same_amount_entries,
                source_index=source_index,
                settlement_utr_reused=(
                    settlement.utr is not None and settlement.utr in reused_utrs
                ),
            )
        )

    return tuple(proofs)
