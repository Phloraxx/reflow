from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum

from . import domain
from .bank_proof import BANK_RULESET_VERSION, BankReceiptProof, BankReceiptStatus
from .ingestion import CanonicalBatch
from .journal import InMemoryJournal
from .settlement_proof import (
    COMPOSITION_RULESET_VERSION,
    CompositionStatus,
    SettlementCompositionProof,
)

GATE9_RULESET_VERSION = "gate9-reconciliation-v1"

__all__ = [
    "GATE9_RULESET_VERSION",
    "InMemoryProofLedger",
    "ProofUpdate",
    "ProofVersionDiff",
    "ReconciliationProofError",
    "ReconciliationProofVersion",
    "ReconciliationStatus",
    "diff_proof_versions",
]


class ReconciliationStatus(StrEnum):
    PROVEN_RECONCILED = "proven_reconciled"
    PENDING_BANK_CREDIT = "pending_bank_credit"
    RESIDUAL = "residual"
    INCOMPLETE = "incomplete"
    CONTRADICTED = "contradicted"


class ReconciliationProofError(ValueError):
    """Full-proof inputs violate an audited Gate 9 invariant."""


@dataclass(frozen=True, slots=True)
class ReconciliationProofVersion:
    id: domain.ProofVersionId
    settlement_id: domain.SettlementId
    version: int
    status: ReconciliationStatus
    composition: SettlementCompositionProof
    bank: BankReceiptProof
    source_envelope_ids: tuple[domain.SourceEnvelopeId, ...]
    scoped_input_sha256: str
    batch_compilation_sha256: str
    composition_ruleset_version: str
    bank_ruleset_version: str
    combiner_ruleset_version: str
    knowledge_cutoff: datetime
    generated_at: datetime
    prior_version_id: domain.ProofVersionId | None
    reopened: bool
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("proof version must be positive")
        if self.composition.settlement_id != self.settlement_id:
            raise ValueError("composition proof belongs to another settlement")
        if self.bank.settlement_id != self.settlement_id:
            raise ValueError("bank proof belongs to another settlement")
        if self.composition.settlement_amount != self.bank.expected_amount:
            raise ValueError("proof fragments disagree on authoritative settlement amount")
        if not self.source_envelope_ids:
            raise ValueError("full proof must cite authoritative raw evidence")
        expected_sources = _source_envelope_ids(self.composition, self.bank)
        if self.source_envelope_ids != expected_sources:
            raise ValueError("full proof source evidence must equal its fragment evidence union")
        _require_sha256(self.scoped_input_sha256, "scoped input hash")
        _require_sha256(self.batch_compilation_sha256, "batch compilation hash")
        expected_scoped_hash = _scoped_input_sha256(self.composition, self.bank)
        if self.scoped_input_sha256 != expected_scoped_hash:
            raise ValueError("scoped input hash does not match its proof fragments")
        if self.composition_ruleset_version != COMPOSITION_RULESET_VERSION:
            raise ValueError("composition ruleset metadata does not match Gate 7")
        if self.bank_ruleset_version != BANK_RULESET_VERSION:
            raise ValueError("bank ruleset metadata does not match Gate 8")
        if self.combiner_ruleset_version != GATE9_RULESET_VERSION:
            raise ValueError("combiner ruleset metadata does not match Gate 9")
        _require_aware(self.knowledge_cutoff, "knowledge cutoff")
        _require_aware(self.generated_at, "generated at")
        if self.generated_at < self.knowledge_cutoff:
            raise ValueError("proof cannot be generated before its knowledge cutoff")
        expected_status = _derive_status(self.composition.status, self.bank.status)
        if self.status is not expected_status:
            raise ValueError("full proof status does not match its proof fragments")
        expected_reasons = _combined_reason_codes(
            self.composition,
            self.bank,
            reopened=self.reopened,
        )
        if self.reason_codes != expected_reasons:
            raise ValueError("full proof reason codes do not match its proof fragments")
        expected_id = _proof_version_id(
            self.settlement_id,
            self.version,
            self.scoped_input_sha256,
        )
        if self.id != expected_id:
            raise ValueError("proof version id does not match its deterministic identity")
        if self.version == 1 and self.prior_version_id is not None:
            raise ValueError("first proof version cannot have a predecessor")
        if self.version == 1 and self.reopened:
            raise ValueError("first proof version cannot be reopened")
        if self.version > 1 and self.prior_version_id is None:
            raise ValueError("later proof version requires a predecessor")
        if self.reopened and self.status is ReconciliationStatus.PROVEN_RECONCILED:
            raise ValueError("reopened proof version cannot already be reconciled")


@dataclass(frozen=True, slots=True)
class ProofUpdate:
    created_versions: tuple[ReconciliationProofVersion, ...]
    unchanged_settlement_ids: tuple[domain.SettlementId, ...]


@dataclass(frozen=True, slots=True)
class ProofVersionDiff:
    settlement_id: domain.SettlementId
    from_version_id: domain.ProofVersionId
    to_version_id: domain.ProofVersionId
    status_before: ReconciliationStatus
    status_after: ReconciliationStatus
    reopened: bool
    changed_fragments: tuple[str, ...]
    added_reason_codes: tuple[str, ...]
    removed_reason_codes: tuple[str, ...]
    added_source_envelope_ids: tuple[domain.SourceEnvelopeId, ...]
    composition_residual_before: domain.Money
    composition_residual_after: domain.Money
    bank_residual_before: domain.Money
    bank_residual_after: domain.Money


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _require_sha256(value: str, label: str) -> None:
    if len(value) != 64:
        raise ValueError(f"{label} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{label} must be a SHA-256 hex digest") from exc


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"unsupported proof hash value {type(value).__name__}")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_json_default,
    ).encode()


def _authoritative_bank_payload(proof: BankReceiptProof) -> dict[str, object]:
    payload = asdict(proof)
    # Same-amount rows are diagnostic candidate counts, never authoritative identity evidence.
    payload.pop("same_amount_nonidentity_count", None)
    return payload


def _scoped_input_sha256(
    composition: SettlementCompositionProof,
    bank: BankReceiptProof,
) -> str:
    payload = {
        "composition_ruleset": COMPOSITION_RULESET_VERSION,
        "bank_ruleset": BANK_RULESET_VERSION,
        "combiner_ruleset": GATE9_RULESET_VERSION,
        "composition": asdict(composition),
        "bank": _authoritative_bank_payload(bank),
    }
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _proof_version_id(
    settlement_id: domain.SettlementId,
    version: int,
    scoped_input_sha256: str,
) -> domain.ProofVersionId:
    material = f"{settlement_id}\0{version}\0{scoped_input_sha256}".encode()
    suffix = hashlib.sha256(material).hexdigest()[:24]
    return domain.ProofVersionId(f"proofv_{suffix}")


def _derive_status(
    composition: CompositionStatus,
    bank: BankReceiptStatus,
) -> ReconciliationStatus:
    if composition is CompositionStatus.CONTRADICTED or bank is BankReceiptStatus.CONTRADICTED:
        return ReconciliationStatus.CONTRADICTED
    if composition is CompositionStatus.INCOMPLETE or bank is BankReceiptStatus.INCOMPLETE:
        return ReconciliationStatus.INCOMPLETE
    if composition is CompositionStatus.RESIDUAL or bank is BankReceiptStatus.RESIDUAL:
        return ReconciliationStatus.RESIDUAL
    if composition is CompositionStatus.PROVEN and bank is BankReceiptStatus.WAITING:
        return ReconciliationStatus.PENDING_BANK_CREDIT
    if composition is CompositionStatus.PROVEN and bank is BankReceiptStatus.PROVEN:
        return ReconciliationStatus.PROVEN_RECONCILED
    raise ReconciliationProofError(
        "unsupported proof-fragment combination: "
        f"composition={composition.value}, bank={bank.value}"
    )


def _combined_reason_codes(
    composition: SettlementCompositionProof,
    bank: BankReceiptProof,
    *,
    reopened: bool,
) -> tuple[str, ...]:
    reasons = {f"COMPOSITION:{reason}" for reason in composition.reason_codes}
    reasons.update(f"BANK:{reason}" for reason in bank.reason_codes)
    if reopened:
        reasons.add("REOPENED_AFTER_PROVEN")
    return tuple(sorted(reasons))


def _source_envelope_ids(
    composition: SettlementCompositionProof,
    bank: BankReceiptProof,
) -> tuple[domain.SourceEnvelopeId, ...]:
    return tuple(
        sorted(
            set(composition.source_envelope_ids) | set(bank.source_envelope_ids),
            key=str,
        )
    )


def _index_fragments[T](
    fragments: tuple[T, ...],
    *,
    settlement_id_of: Callable[[T], domain.SettlementId],
    label: str,
) -> dict[domain.SettlementId, T]:
    indexed: dict[domain.SettlementId, T] = {}
    for fragment in fragments:
        settlement_id = settlement_id_of(fragment)
        if settlement_id in indexed:
            raise ReconciliationProofError(f"duplicate {label} for {settlement_id}")
        indexed[settlement_id] = fragment
    return indexed


class InMemoryProofLedger:
    """Append-only reference ledger for immutable settlement proof versions."""

    def __init__(self) -> None:
        self._history: dict[
            domain.SettlementId, list[ReconciliationProofVersion]
        ] = {}

    def history(
        self,
        settlement_id: domain.SettlementId,
    ) -> tuple[ReconciliationProofVersion, ...]:
        return tuple(self._history.get(settlement_id, ()))

    def latest(
        self,
        settlement_id: domain.SettlementId,
    ) -> ReconciliationProofVersion | None:
        history = self._history.get(settlement_id)
        return history[-1] if history else None

    def apply_batch(
        self,
        batch: CanonicalBatch,
        journal: InMemoryJournal,
        composition_proofs: tuple[SettlementCompositionProof, ...],
        bank_proofs: tuple[BankReceiptProof, ...],
        *,
        knowledge_cutoff: datetime,
        generated_at: datetime,
    ) -> ProofUpdate:
        _require_aware(knowledge_cutoff, "knowledge cutoff")
        _require_aware(generated_at, "generated at")
        if generated_at < knowledge_cutoff:
            raise ReconciliationProofError(
                "proof cannot be generated before its knowledge cutoff"
            )
        if not batch.source_links or batch.compilation_sha256 is None:
            raise ReconciliationProofError(
                "Gate 9 requires a journal-backed canonical compilation"
            )
        batch_compilation_sha256 = batch.compilation_sha256
        for link in batch.source_links:
            envelope = journal.get_by_id(link.envelope_id)
            if envelope is None:
                raise ReconciliationProofError(
                    f"canonical batch cites unretained evidence {link.envelope_id}"
                )
            if envelope.received_at > knowledge_cutoff:
                raise ReconciliationProofError(
                    "canonical batch contains evidence after knowledge cutoff"
                )

        settlements: dict[domain.SettlementId, domain.Settlement] = {}
        for settlement in batch.settlements:
            if settlement.id in settlements:
                raise ReconciliationProofError(f"duplicate settlement {settlement.id}")
            settlements[settlement.id] = settlement

        compositions = _index_fragments(
            composition_proofs,
            settlement_id_of=lambda proof: proof.settlement_id,
            label="composition proof",
        )
        banks = _index_fragments(
            bank_proofs,
            settlement_id_of=lambda proof: proof.settlement_id,
            label="bank proof",
        )
        expected_ids = set(settlements)
        if set(compositions) != expected_ids or set(banks) != expected_ids:
            raise ReconciliationProofError(
                "Gate 9 requires exactly one Gate 7 and Gate 8 proof per settlement"
            )

        batch_source_ids = {link.envelope_id for link in batch.source_links}
        created: list[ReconciliationProofVersion] = []
        unchanged: list[domain.SettlementId] = []

        for settlement_id in sorted(expected_ids, key=str):
            settlement = settlements[settlement_id]
            composition = compositions[settlement_id]
            bank = banks[settlement_id]
            if composition.settlement_amount != settlement.amount:
                raise ReconciliationProofError(
                    f"composition amount differs from settlement {settlement_id}"
                )
            if bank.expected_amount != settlement.amount or bank.settlement_utr != settlement.utr:
                raise ReconciliationProofError(
                    f"bank proof identity/value differs from settlement {settlement_id}"
                )

            source_ids = _source_envelope_ids(composition, bank)
            if not set(source_ids).issubset(batch_source_ids):
                raise ReconciliationProofError(
                    f"proof for {settlement_id} cites evidence outside canonical batch"
                )
            for envelope_id in source_ids:
                envelope = journal.get_by_id(envelope_id)
                if envelope is None:
                    raise ReconciliationProofError(
                        f"proof for {settlement_id} cites unretained evidence {envelope_id}"
                    )
                if envelope.received_at > knowledge_cutoff:
                    raise ReconciliationProofError(
                        f"proof for {settlement_id} cites evidence after knowledge cutoff"
                    )

            scoped_hash = _scoped_input_sha256(composition, bank)
            previous = self.latest(settlement_id)
            if previous is not None:
                if knowledge_cutoff < previous.knowledge_cutoff:
                    raise ReconciliationProofError(
                        f"knowledge cutoff moved backwards for {settlement_id}"
                    )
                if generated_at < previous.generated_at:
                    raise ReconciliationProofError(
                        f"generation time moved backwards for {settlement_id}"
                    )
                if not set(previous.source_envelope_ids).issubset(source_ids):
                    raise ReconciliationProofError(
                        f"authoritative evidence disappeared for {settlement_id}"
                    )
                if previous.scoped_input_sha256 == scoped_hash:
                    unchanged.append(settlement_id)
                    continue

            status = _derive_status(composition.status, bank.status)
            reopened = (
                previous is not None
                and previous.status is ReconciliationStatus.PROVEN_RECONCILED
                and status is not ReconciliationStatus.PROVEN_RECONCILED
            )
            version = 1 if previous is None else previous.version + 1
            proof = ReconciliationProofVersion(
                id=_proof_version_id(settlement_id, version, scoped_hash),
                settlement_id=settlement_id,
                version=version,
                status=status,
                composition=composition,
                bank=bank,
                source_envelope_ids=source_ids,
                scoped_input_sha256=scoped_hash,
                batch_compilation_sha256=batch_compilation_sha256,
                composition_ruleset_version=COMPOSITION_RULESET_VERSION,
                bank_ruleset_version=BANK_RULESET_VERSION,
                combiner_ruleset_version=GATE9_RULESET_VERSION,
                knowledge_cutoff=knowledge_cutoff,
                generated_at=generated_at,
                prior_version_id=None if previous is None else previous.id,
                reopened=reopened,
                reason_codes=_combined_reason_codes(
                    composition,
                    bank,
                    reopened=reopened,
                ),
            )
            created.append(proof)

        # Commit only after every settlement in the batch has passed validation.
        for proof in created:
            self._history.setdefault(proof.settlement_id, []).append(proof)

        return ProofUpdate(
            created_versions=tuple(created),
            unchanged_settlement_ids=tuple(unchanged),
        )


def diff_proof_versions(
    before: ReconciliationProofVersion,
    after: ReconciliationProofVersion,
) -> ProofVersionDiff:
    if before.settlement_id != after.settlement_id:
        raise ReconciliationProofError("cannot diff proofs for different settlements")
    if after.version <= before.version:
        raise ReconciliationProofError("proof diff requires a later version")

    changed: list[str] = []
    if before.composition != after.composition:
        changed.append("composition")
    if _authoritative_bank_payload(before.bank) != _authoritative_bank_payload(after.bank):
        changed.append("bank")

    before_reasons = set(before.reason_codes)
    after_reasons = set(after.reason_codes)
    added_sources = set(after.source_envelope_ids) - set(before.source_envelope_ids)
    return ProofVersionDiff(
        settlement_id=before.settlement_id,
        from_version_id=before.id,
        to_version_id=after.id,
        status_before=before.status,
        status_after=after.status,
        reopened=after.reopened,
        changed_fragments=tuple(changed),
        added_reason_codes=tuple(sorted(after_reasons - before_reasons)),
        removed_reason_codes=tuple(sorted(before_reasons - after_reasons)),
        added_source_envelope_ids=tuple(sorted(added_sources, key=str)),
        composition_residual_before=before.composition.residual,
        composition_residual_after=after.composition.residual,
        bank_residual_before=before.bank.residual,
        bank_residual_after=after.bank.residual,
    )
