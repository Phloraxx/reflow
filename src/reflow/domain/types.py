from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class EntityId:
    value: str
    prefix: ClassVar[str] = ""

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value:
            raise TypeError(f"{type(self).__name__} requires a non-empty string")
        if self.prefix:
            if not self.value.startswith(self.prefix):
                raise ValueError(
                    f"{type(self).__name__} must start with {self.prefix!r}: {self.value!r}"
                )
            if len(self.value) == len(self.prefix):
                raise ValueError(
                    f"{type(self).__name__} requires content after {self.prefix!r}"
                )

    def __str__(self) -> str:
        return self.value


class OrderId(EntityId):
    prefix = "order_"


class PaymentId(EntityId):
    prefix = "pay_"


class RefundId(EntityId):
    prefix = "rfnd_"


class TransferId(EntityId):
    prefix = "trf_"


class AdjustmentId(EntityId):
    prefix = "adj_"


class SettlementId(EntityId):
    prefix = "setl_"


class ReconEntryId(EntityId):
    prefix = "recon_"


class BankEntryId(EntityId):
    prefix = "bank_"


class SourceEnvelopeId(EntityId):
    prefix = "src_"


class EvidenceEdgeId(EntityId):
    prefix = "edge_"


class ExceptionCaseId(EntityId):
    prefix = "exc_"


class ProofId(EntityId):
    prefix = "proof_"


class Currency(StrEnum):
    INR = "INR"


class SourceKind(StrEnum):
    MERCHANT = "merchant"
    RAZORPAY_EVENT = "razorpay_event"
    RAZORPAY_RECON = "razorpay_recon"
    RAZORPAY_SETTLEMENT = "razorpay_settlement"
    BANK = "bank"
    SYNTHETIC = "synthetic"


class PaymentEventKind(StrEnum):
    CREATED = "created"
    AUTHORIZED = "authorized"
    FAILED = "failed"
    CAPTURED = "captured"
    REFUNDED = "refunded"


class PaymentStatus(StrEnum):
    CREATED = "created"
    AUTHORIZED = "authorized"
    FAILED = "failed"
    CAPTURED = "captured"
    PARTIALLY_REFUNDED = "partially_refunded"
    REFUNDED = "refunded"


class ReconEntityKind(StrEnum):
    PAYMENT = "payment"
    REFUND = "refund"
    TRANSFER = "transfer"
    ADJUSTMENT = "adjustment"


class EvidenceStrength(StrEnum):
    WEAK = "weak"
    CANDIDATE = "candidate"
    STRONG = "strong"
    AUTHORITATIVE = "authoritative"


class EdgeState(StrEnum):
    CANDIDATE = "candidate"
    PROVEN = "proven"
    REJECTED = "rejected"


class ProofStatus(StrEnum):
    PROVEN_RECONCILED = "proven_reconciled"
    WAITING_FOR_BANK = "waiting_for_bank"
    RESIDUAL = "residual"
    CONTRADICTED = "contradicted"
    AMBIGUOUS = "ambiguous"


class ExceptionKind(StrEnum):
    MISSING_EVIDENCE = "missing_evidence"
    AMOUNT_MISMATCH = "amount_mismatch"
    IDENTITY_CONFLICT = "identity_conflict"
    AMBIGUOUS_MATCH = "ambiguous_match"
    MALFORMED_SOURCE = "malformed_source"
    SCHEMA_DRIFT = "schema_drift"
    OUT_OF_RANGE = "out_of_range"
    DUPLICATE_ECONOMIC_ROW = "duplicate_economic_row"
