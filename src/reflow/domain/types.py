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
        if self.value != self.value.strip():
            raise ValueError(f"{type(self).__name__} cannot contain surrounding whitespace")
        if self.prefix:
            if not self.value.startswith(self.prefix):
                raise ValueError(
                    f"{type(self).__name__} must start with {self.prefix!r}: {self.value!r}"
                )
            if not self.value[len(self.prefix) :].strip():
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


class ProofVersionId(EntityId):
    prefix = "proofv_"


class ReconciliationScopeId(EntityId):
    prefix = "scope_"


class SourceDeliveryManifestId(EntityId):
    prefix = "delivery_"


class ReconciliationPolicyVersionId(EntityId):
    prefix = "policy_"


class ReconciliationRunId(EntityId):
    prefix = "run_"


class EvidenceCoverageCertificateId(EntityId):
    prefix = "coverage_"


class BalanceControlProofId(EntityId):
    prefix = "balctrl_"


class CloseReadinessCertificateId(EntityId):
    prefix = "close_"


class ExceptionTrackingKeyId(EntityId):
    prefix = "track_"


class ExceptionCaseId(EntityId):
    prefix = "case_"


class ExceptionCaseObservationId(EntityId):
    prefix = "caseobs_"


class ExceptionDispositionId(EntityId):
    prefix = "disp_"


class IncidentFingerprintId(EntityId):
    prefix = "incident_"


class IncidentClusterId(EntityId):
    prefix = "cluster_"


class ResidualCandidateId(EntityId):
    prefix = "rcand_"


class ResidualExplanationId(EntityId):
    prefix = "rexp_"


class InvestigationTraceEntryId(EntityId):
    prefix = "trace_"


class InvestigationResultId(EntityId):
    prefix = "invest_"


class Currency(StrEnum):
    INR = "INR"


class SourceKind(StrEnum):
    MERCHANT = "merchant"
    RAZORPAY_EVENT = "razorpay_event"
    RAZORPAY_RECON = "razorpay_recon"
    RAZORPAY_SETTLEMENT = "razorpay_settlement"
    BANK = "bank"


class PaymentEventKind(StrEnum):
    CREATED = "created"
    AUTHORIZED = "authorized"
    FAILED = "failed"
    CAPTURED = "captured"


class PaymentStatus(StrEnum):
    CREATED = "created"
    AUTHORIZED = "authorized"
    FAILED = "failed"
    CAPTURED = "captured"


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
