from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from . import domain
from .control_plane import (
    MaterialityBand,
    ReconciliationPolicyVersion,
    ReconciliationRun,
    SourceCompleteness,
    SourceDeliveryManifest,
)
from .reconciliation_proof import ReconciliationProofVersion, ReconciliationStatus

GATE14_CASE_RULESET_VERSION = "gate14-exception-cases-v1"

__all__ = [
    "GATE14_CASE_RULESET_VERSION",
    "CaseResolution",
    "CaseRunUpdate",
    "CaseWorkflowStatus",
    "DispositionKind",
    "ExceptionCaseDisposition",
    "ExceptionCaseError",
    "ExceptionCaseObservation",
    "ExceptionCaseState",
    "InMemoryExceptionCaseLedger",
    "IncidentCluster",
    "SourceStateSnapshot",
    "build_incident_clusters",
]


class ExceptionCaseError(ValueError):
    """Gate 14 case inputs violate deterministic lifecycle or lineage invariants."""


class CaseWorkflowStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    AWAITING_SOURCE = "awaiting_source"
    DEFERRED = "deferred"
    CLOSED = "closed"


class CaseResolution(StrEnum):
    PROOF_RECONCILED = "proof_reconciled"
    ECONOMIC_IDENTITY_CHANGED = "economic_identity_changed"
    OPERATOR_CLOSED = "operator_closed"
    OPERATIONAL_VARIANCE_ACCEPTED = "operational_variance_accepted"


class DispositionKind(StrEnum):
    ASSIGN_OWNER = "assign_owner"
    ACKNOWLEDGE = "acknowledge"
    REQUEST_SOURCE_CORRECTION = "request_source_correction"
    DEFER = "defer"
    ACCEPT_OPERATIONAL_VARIANCE = "accept_operational_variance"
    CLOSE = "close"
    REOPEN = "reopen"


def _aware(value: datetime, label: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{label} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ExceptionCaseError(f"{label} must be timezone-aware")


def _text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExceptionCaseError(f"{label} must be a non-empty string")
    if value != value.strip():
        raise ExceptionCaseError(f"{label} must not contain surrounding whitespace")
    return value


def _optional_text(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    return _text(value, label)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _content_id(prefix: str, value: object) -> str:
    return f"{prefix}{_sha256(value)[:24]}"


def _tracking_key_id(
    *,
    scope_id: domain.ReconciliationScopeId,
    settlement_id: domain.SettlementId,
    affected_amount: domain.Money,
    settlement_utr: str | None,
) -> domain.ExceptionTrackingKeyId:
    material = {
        "contract": GATE14_CASE_RULESET_VERSION,
        "scope_id": str(scope_id),
        "settlement_id": str(settlement_id),
        "amount_paise": affected_amount.amount_paise,
        "currency": affected_amount.currency.value,
        "settlement_utr": settlement_utr,
    }
    return domain.ExceptionTrackingKeyId(_content_id("track_", material))


def _case_id(tracking_key: domain.ExceptionTrackingKeyId) -> domain.ExceptionCaseId:
    return domain.ExceptionCaseId(
        _content_id(
            "case_",
            {
                "contract": GATE14_CASE_RULESET_VERSION,
                "tracking_key": str(tracking_key),
            },
        )
    )


@dataclass(frozen=True, slots=True)
class SourceStateSnapshot:
    source_kind: domain.SourceKind
    completeness: SourceCompleteness
    received_late: bool
    manifest_id: domain.SourceDeliveryManifestId

    def __post_init__(self) -> None:
        if not isinstance(self.source_kind, domain.SourceKind):
            raise TypeError("source state kind must be SourceKind")
        if not isinstance(self.completeness, SourceCompleteness):
            raise TypeError("source state completeness must be SourceCompleteness")
        if not isinstance(self.received_late, bool):
            raise TypeError("source state received_late must be bool")
        if not isinstance(self.manifest_id, domain.SourceDeliveryManifestId):
            raise TypeError("source state manifest id must be SourceDeliveryManifestId")


def _source_fingerprint_material(
    source_states: tuple[SourceStateSnapshot, ...],
) -> list[dict[str, object]]:
    return [
        {
            "source_kind": state.source_kind.value,
            "completeness": state.completeness.value,
            "received_late": state.received_late,
        }
        for state in source_states
    ]


def _incident_fingerprint_id(
    *,
    scope_id: domain.ReconciliationScopeId,
    financial_status: ReconciliationStatus,
    reason_codes: tuple[str, ...],
    source_states: tuple[SourceStateSnapshot, ...],
) -> domain.IncidentFingerprintId:
    material = {
        "contract": GATE14_CASE_RULESET_VERSION,
        "scope_id": str(scope_id),
        "financial_status": financial_status.value,
        "reason_codes": list(reason_codes),
        "source_signature": _source_fingerprint_material(source_states),
    }
    return domain.IncidentFingerprintId(_content_id("incident_", material))


def _observation_id(
    *,
    case_id: domain.ExceptionCaseId,
    tracking_key: domain.ExceptionTrackingKeyId,
    scope_id: domain.ReconciliationScopeId,
    run_id: domain.ReconciliationRunId,
    proof_version_id: domain.ProofVersionId,
    policy_version_id: domain.ReconciliationPolicyVersionId,
    settlement_id: domain.SettlementId,
    financial_status: ReconciliationStatus,
    reason_codes: tuple[str, ...],
    affected_amount: domain.Money,
    materiality_band: MaterialityBand,
    settlement_utr: str | None,
    source_states: tuple[SourceStateSnapshot, ...],
    incident_fingerprint_id: domain.IncidentFingerprintId,
    observed_at: datetime,
) -> domain.ExceptionCaseObservationId:
    material = {
        "contract": GATE14_CASE_RULESET_VERSION,
        "case_id": str(case_id),
        "tracking_key": str(tracking_key),
        "scope_id": str(scope_id),
        "run_id": str(run_id),
        "proof_version_id": str(proof_version_id),
        "policy_version_id": str(policy_version_id),
        "settlement_id": str(settlement_id),
        "financial_status": financial_status.value,
        "reason_codes": list(reason_codes),
        "affected_amount_paise": affected_amount.amount_paise,
        "currency": affected_amount.currency.value,
        "materiality_band": materiality_band.value,
        "settlement_utr": settlement_utr,
        "source_states": [
            {
                "source_kind": state.source_kind.value,
                "completeness": state.completeness.value,
                "received_late": state.received_late,
                "manifest_id": str(state.manifest_id),
            }
            for state in source_states
        ],
        "incident_fingerprint_id": str(incident_fingerprint_id),
        "observed_at": observed_at.isoformat(),
    }
    return domain.ExceptionCaseObservationId(_content_id("caseobs_", material))


@dataclass(frozen=True, slots=True)
class ExceptionCaseObservation:
    id: domain.ExceptionCaseObservationId
    case_id: domain.ExceptionCaseId
    tracking_key: domain.ExceptionTrackingKeyId
    scope_id: domain.ReconciliationScopeId
    run_id: domain.ReconciliationRunId
    proof_version_id: domain.ProofVersionId
    policy_version_id: domain.ReconciliationPolicyVersionId
    settlement_id: domain.SettlementId
    financial_status: ReconciliationStatus
    reason_codes: tuple[str, ...]
    affected_amount: domain.Money
    materiality_band: MaterialityBand
    settlement_utr: str | None
    source_states: tuple[SourceStateSnapshot, ...]
    incident_fingerprint_id: domain.IncidentFingerprintId
    observed_at: datetime
    ruleset_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, domain.ExceptionCaseObservationId):
            raise TypeError("case observation id must be ExceptionCaseObservationId")
        if not isinstance(self.case_id, domain.ExceptionCaseId):
            raise TypeError("case id must be ExceptionCaseId")
        if not isinstance(self.tracking_key, domain.ExceptionTrackingKeyId):
            raise TypeError("tracking key must be ExceptionTrackingKeyId")
        if not isinstance(self.scope_id, domain.ReconciliationScopeId):
            raise TypeError("observation scope id must be ReconciliationScopeId")
        if not isinstance(self.run_id, domain.ReconciliationRunId):
            raise TypeError("observation run id must be ReconciliationRunId")
        if not isinstance(self.proof_version_id, domain.ProofVersionId):
            raise TypeError("observation proof id must be ProofVersionId")
        if not isinstance(self.policy_version_id, domain.ReconciliationPolicyVersionId):
            raise TypeError("observation policy id must be ReconciliationPolicyVersionId")
        if not isinstance(self.settlement_id, domain.SettlementId):
            raise TypeError("observation settlement id must be SettlementId")
        if not isinstance(self.financial_status, ReconciliationStatus):
            raise TypeError("observation financial status must be ReconciliationStatus")
        if tuple(sorted(set(self.reason_codes))) != self.reason_codes:
            raise ValueError("observation reason codes must be unique and canonical-sorted")
        if not isinstance(self.affected_amount, domain.Money):
            raise TypeError("observation affected amount must be Money")
        if self.affected_amount.amount_paise <= 0:
            raise ValueError("observation affected amount must be positive")
        if not isinstance(self.materiality_band, MaterialityBand):
            raise TypeError("observation materiality must be MaterialityBand")
        _optional_text(self.settlement_utr, "settlement UTR")
        if any(not isinstance(value, SourceStateSnapshot) for value in self.source_states):
            raise TypeError("observation source states must be SourceStateSnapshot")
        source_kinds = tuple(state.source_kind for state in self.source_states)
        if tuple(sorted(set(source_kinds), key=lambda kind: kind.value)) != source_kinds:
            raise ValueError("observation source states must be unique and canonical-sorted")
        if not isinstance(self.incident_fingerprint_id, domain.IncidentFingerprintId):
            raise TypeError("observation incident fingerprint must be IncidentFingerprintId")
        _aware(self.observed_at, "observation time")
        if self.ruleset_version != GATE14_CASE_RULESET_VERSION:
            raise ValueError("observation ruleset version does not match Gate 14")
        expected_tracking = _tracking_key_id(
            scope_id=self.scope_id,
            settlement_id=self.settlement_id,
            affected_amount=self.affected_amount,
            settlement_utr=self.settlement_utr,
        )
        if self.tracking_key != expected_tracking:
            raise ValueError("observation tracking key does not match economic identity")
        if self.case_id != _case_id(self.tracking_key):
            raise ValueError("case id does not match tracking key")
        expected_fingerprint = _incident_fingerprint_id(
            scope_id=self.scope_id,
            financial_status=self.financial_status,
            reason_codes=self.reason_codes,
            source_states=self.source_states,
        )
        if self.incident_fingerprint_id != expected_fingerprint:
            raise ValueError("incident fingerprint does not match current failure pattern")
        expected_id = _observation_id(
            case_id=self.case_id,
            tracking_key=self.tracking_key,
            scope_id=self.scope_id,
            run_id=self.run_id,
            proof_version_id=self.proof_version_id,
            policy_version_id=self.policy_version_id,
            settlement_id=self.settlement_id,
            financial_status=self.financial_status,
            reason_codes=self.reason_codes,
            affected_amount=self.affected_amount,
            materiality_band=self.materiality_band,
            settlement_utr=self.settlement_utr,
            source_states=self.source_states,
            incident_fingerprint_id=self.incident_fingerprint_id,
            observed_at=self.observed_at,
        )
        if self.id != expected_id:
            raise ValueError("case observation id does not match immutable content")


def _make_observation(
    *,
    run: ReconciliationRun,
    policy: ReconciliationPolicyVersion,
    proof: ReconciliationProofVersion,
    source_states: tuple[SourceStateSnapshot, ...],
) -> ExceptionCaseObservation:
    amount = proof.composition.settlement_amount
    settlement_utr = proof.bank.settlement_utr
    tracking_key = _tracking_key_id(
        scope_id=run.scope_id,
        settlement_id=proof.settlement_id,
        affected_amount=amount,
        settlement_utr=settlement_utr,
    )
    case_id = _case_id(tracking_key)
    reasons = tuple(sorted(set(proof.reason_codes)))
    fingerprint = _incident_fingerprint_id(
        scope_id=run.scope_id,
        financial_status=proof.status,
        reason_codes=reasons,
        source_states=source_states,
    )
    materiality = policy.materiality_band(amount)
    observation_id = _observation_id(
        case_id=case_id,
        tracking_key=tracking_key,
        scope_id=run.scope_id,
        run_id=run.id,
        proof_version_id=proof.id,
        policy_version_id=policy.id,
        settlement_id=proof.settlement_id,
        financial_status=proof.status,
        reason_codes=reasons,
        affected_amount=amount,
        materiality_band=materiality,
        settlement_utr=settlement_utr,
        source_states=source_states,
        incident_fingerprint_id=fingerprint,
        observed_at=run.completed_at,
    )
    return ExceptionCaseObservation(
        id=observation_id,
        case_id=case_id,
        tracking_key=tracking_key,
        scope_id=run.scope_id,
        run_id=run.id,
        proof_version_id=proof.id,
        policy_version_id=policy.id,
        settlement_id=proof.settlement_id,
        financial_status=proof.status,
        reason_codes=reasons,
        affected_amount=amount,
        materiality_band=materiality,
        settlement_utr=settlement_utr,
        source_states=source_states,
        incident_fingerprint_id=fingerprint,
        observed_at=run.completed_at,
        ruleset_version=GATE14_CASE_RULESET_VERSION,
    )


def _disposition_id(
    *,
    case_id: domain.ExceptionCaseId,
    sequence: int,
    actor_id: str,
    occurred_at: datetime,
    kind: DispositionKind,
    owner: str | None,
    note: str | None,
) -> domain.ExceptionDispositionId:
    material = {
        "contract": GATE14_CASE_RULESET_VERSION,
        "case_id": str(case_id),
        "sequence": sequence,
        "actor_id": actor_id,
        "occurred_at": occurred_at.isoformat(),
        "kind": kind.value,
        "owner": owner,
        "note": note,
    }
    return domain.ExceptionDispositionId(_content_id("disp_", material))


@dataclass(frozen=True, slots=True)
class ExceptionCaseDisposition:
    id: domain.ExceptionDispositionId
    case_id: domain.ExceptionCaseId
    sequence: int
    actor_id: str
    occurred_at: datetime
    kind: DispositionKind
    owner: str | None
    note: str | None
    ruleset_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, domain.ExceptionDispositionId):
            raise TypeError("disposition id must be ExceptionDispositionId")
        if not isinstance(self.case_id, domain.ExceptionCaseId):
            raise TypeError("disposition case id must be ExceptionCaseId")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise TypeError("disposition sequence must be int")
        if self.sequence < 1:
            raise ValueError("disposition sequence must be positive")
        _text(self.actor_id, "disposition actor")
        _aware(self.occurred_at, "disposition time")
        if not isinstance(self.kind, DispositionKind):
            raise TypeError("disposition kind must be DispositionKind")
        _optional_text(self.owner, "disposition owner")
        _optional_text(self.note, "disposition note")
        if self.kind is DispositionKind.ASSIGN_OWNER:
            if self.owner is None:
                raise ValueError("ASSIGN_OWNER requires an owner")
        elif self.owner is not None:
            raise ValueError("only ASSIGN_OWNER may change owner")
        if self.ruleset_version != GATE14_CASE_RULESET_VERSION:
            raise ValueError("disposition ruleset version does not match Gate 14")
        expected_id = _disposition_id(
            case_id=self.case_id,
            sequence=self.sequence,
            actor_id=self.actor_id,
            occurred_at=self.occurred_at,
            kind=self.kind,
            owner=self.owner,
            note=self.note,
        )
        if self.id != expected_id:
            raise ValueError("disposition id does not match immutable content")


@dataclass(frozen=True, slots=True)
class CaseRunUpdate:
    created_observation_ids: tuple[domain.ExceptionCaseObservationId, ...]
    created_case_ids: tuple[domain.ExceptionCaseId, ...]
    superseded_case_ids: tuple[domain.ExceptionCaseId, ...]
    auto_closed_case_ids: tuple[domain.ExceptionCaseId, ...]


@dataclass(frozen=True, slots=True)
class ExceptionCaseState:
    case_id: domain.ExceptionCaseId
    tracking_key: domain.ExceptionTrackingKeyId
    scope_id: domain.ReconciliationScopeId
    settlement_id: domain.SettlementId
    settlement_utr: str | None
    affected_amount: domain.Money
    first_seen_at: datetime
    last_seen_at: datetime
    first_seen_run_id: domain.ReconciliationRunId
    last_seen_run_id: domain.ReconciliationRunId
    latest_observation_id: domain.ExceptionCaseObservationId
    latest_proof_version_id: domain.ProofVersionId
    financial_status: ReconciliationStatus
    materiality_band: MaterialityBand
    incident_fingerprint_id: domain.IncidentFingerprintId
    workflow_status: CaseWorkflowStatus
    resolution: CaseResolution | None
    owner: str | None
    superseded_by_case_id: domain.ExceptionCaseId | None
    observation_count: int
    disposition_count: int

    def age_seconds(self, as_of: datetime) -> int:
        _aware(as_of, "case age as_of")
        if as_of < self.first_seen_at:
            raise ExceptionCaseError("case age as_of cannot predate first seen")
        return int((as_of - self.first_seen_at).total_seconds())


def _incident_cluster_id(
    *,
    run_id: domain.ReconciliationRunId,
    scope_id: domain.ReconciliationScopeId,
    incident_fingerprint_id: domain.IncidentFingerprintId,
    case_ids: tuple[domain.ExceptionCaseId, ...],
    affected_value: domain.Money,
) -> domain.IncidentClusterId:
    material = {
        "contract": GATE14_CASE_RULESET_VERSION,
        "run_id": str(run_id),
        "scope_id": str(scope_id),
        "incident_fingerprint_id": str(incident_fingerprint_id),
        "case_ids": [str(value) for value in case_ids],
        "affected_value_paise": affected_value.amount_paise,
        "currency": affected_value.currency.value,
    }
    return domain.IncidentClusterId(_content_id("cluster_", material))


@dataclass(frozen=True, slots=True)
class IncidentCluster:
    id: domain.IncidentClusterId
    run_id: domain.ReconciliationRunId
    scope_id: domain.ReconciliationScopeId
    incident_fingerprint_id: domain.IncidentFingerprintId
    case_ids: tuple[domain.ExceptionCaseId, ...]
    affected_case_count: int
    affected_value: domain.Money
    financial_status: ReconciliationStatus
    reason_codes: tuple[str, ...]
    source_states: tuple[SourceStateSnapshot, ...]
    ruleset_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, domain.IncidentClusterId):
            raise TypeError("cluster id must be IncidentClusterId")
        if not isinstance(self.run_id, domain.ReconciliationRunId):
            raise TypeError("cluster run id must be ReconciliationRunId")
        if not isinstance(self.scope_id, domain.ReconciliationScopeId):
            raise TypeError("cluster scope id must be ReconciliationScopeId")
        if not isinstance(self.incident_fingerprint_id, domain.IncidentFingerprintId):
            raise TypeError("cluster fingerprint must be IncidentFingerprintId")
        if any(not isinstance(value, domain.ExceptionCaseId) for value in self.case_ids):
            raise TypeError("cluster case ids must be ExceptionCaseId")
        if tuple(sorted(set(self.case_ids), key=str)) != self.case_ids:
            raise ValueError("cluster case ids must be unique and canonical-sorted")
        if self.affected_case_count != len(self.case_ids):
            raise ValueError("cluster affected case count does not match case IDs")
        if not isinstance(self.affected_value, domain.Money):
            raise TypeError("cluster affected value must be Money")
        if self.affected_value.amount_paise <= 0:
            raise ValueError("cluster affected value must be positive")
        if not isinstance(self.financial_status, ReconciliationStatus):
            raise TypeError("cluster financial status must be ReconciliationStatus")
        if self.financial_status is ReconciliationStatus.PROVEN_RECONCILED:
            raise ValueError("green proof observations cannot form an incident cluster")
        if tuple(sorted(set(self.reason_codes))) != self.reason_codes:
            raise ValueError("cluster reason codes must be unique and canonical-sorted")
        if any(not isinstance(value, SourceStateSnapshot) for value in self.source_states):
            raise TypeError("cluster source states must be SourceStateSnapshot")
        if self.ruleset_version != GATE14_CASE_RULESET_VERSION:
            raise ValueError("cluster ruleset version does not match Gate 14")
        expected_fingerprint = _incident_fingerprint_id(
            scope_id=self.scope_id,
            financial_status=self.financial_status,
            reason_codes=self.reason_codes,
            source_states=self.source_states,
        )
        if self.incident_fingerprint_id != expected_fingerprint:
            raise ValueError("cluster fingerprint does not match incident signature")
        expected_id = _incident_cluster_id(
            run_id=self.run_id,
            scope_id=self.scope_id,
            incident_fingerprint_id=self.incident_fingerprint_id,
            case_ids=self.case_ids,
            affected_value=self.affected_value,
        )
        if self.id != expected_id:
            raise ValueError("cluster id does not match immutable content")


def build_incident_clusters(
    *,
    run: ReconciliationRun,
    observations: tuple[ExceptionCaseObservation, ...],
) -> tuple[IncidentCluster, ...]:
    if not isinstance(run, ReconciliationRun):
        raise TypeError("run must be ReconciliationRun")
    run_proof_ids = set(run.proof_version_ids)
    run_manifest_ids = set(run.source_manifest_ids)
    seen_cases: set[domain.ExceptionCaseId] = set()
    groups: dict[domain.IncidentFingerprintId, list[ExceptionCaseObservation]] = {}
    for observation in observations:
        if not isinstance(observation, ExceptionCaseObservation):
            raise TypeError("observations must be ExceptionCaseObservation")
        if observation.run_id != run.id or observation.scope_id != run.scope_id:
            raise ExceptionCaseError("incident observation belongs to another run or scope")
        if observation.proof_version_id not in run_proof_ids:
            raise ExceptionCaseError("incident observation proof is outside run proof IDs")
        if {state.manifest_id for state in observation.source_states} != run_manifest_ids:
            raise ExceptionCaseError("incident observation source states do not bind run manifests")
        if observation.case_id in seen_cases:
            raise ExceptionCaseError("one run cannot count the same case twice")
        seen_cases.add(observation.case_id)
        if observation.financial_status is ReconciliationStatus.PROVEN_RECONCILED:
            continue
        groups.setdefault(observation.incident_fingerprint_id, []).append(observation)

    clusters: list[IncidentCluster] = []
    for fingerprint, group in groups.items():
        ordered = tuple(sorted(group, key=lambda row: str(row.case_id)))
        first = ordered[0]
        if any(row.financial_status is not first.financial_status for row in ordered):
            raise ExceptionCaseError("one incident fingerprint has multiple financial statuses")
        if any(row.reason_codes != first.reason_codes for row in ordered):
            raise ExceptionCaseError("one incident fingerprint has multiple reason signatures")
        if any(row.source_states != first.source_states for row in ordered):
            raise ExceptionCaseError("one run fingerprint has multiple source-state packets")
        affected_value = domain.sum_money(
            [row.affected_amount for row in ordered],
            first.affected_amount.currency,
        )
        case_ids = tuple(row.case_id for row in ordered)
        cluster_id = _incident_cluster_id(
            run_id=run.id,
            scope_id=run.scope_id,
            incident_fingerprint_id=fingerprint,
            case_ids=case_ids,
            affected_value=affected_value,
        )
        clusters.append(
            IncidentCluster(
                id=cluster_id,
                run_id=run.id,
                scope_id=run.scope_id,
                incident_fingerprint_id=fingerprint,
                case_ids=case_ids,
                affected_case_count=len(case_ids),
                affected_value=affected_value,
                financial_status=first.financial_status,
                reason_codes=first.reason_codes,
                source_states=first.source_states,
                ruleset_version=GATE14_CASE_RULESET_VERSION,
            )
        )
    return tuple(sorted(clusters, key=lambda row: str(row.incident_fingerprint_id)))


def _source_states(
    manifests: tuple[SourceDeliveryManifest, ...],
) -> tuple[SourceStateSnapshot, ...]:
    ordered = tuple(sorted(manifests, key=lambda row: row.source_kind.value))
    return tuple(
        SourceStateSnapshot(
            source_kind=manifest.source_kind,
            completeness=manifest.completeness,
            received_late=manifest.received_late,
            manifest_id=manifest.id,
        )
        for manifest in ordered
    )


def _validate_run_inputs(
    *,
    run: ReconciliationRun,
    policy: ReconciliationPolicyVersion,
    manifests: tuple[SourceDeliveryManifest, ...],
    proof_versions: tuple[ReconciliationProofVersion, ...],
) -> tuple[tuple[SourceDeliveryManifest, ...], tuple[ReconciliationProofVersion, ...]]:
    if not isinstance(run, ReconciliationRun):
        raise TypeError("run must be ReconciliationRun")
    if not isinstance(policy, ReconciliationPolicyVersion):
        raise TypeError("policy must be ReconciliationPolicyVersion")
    if run.policy_version_id != policy.id:
        raise ExceptionCaseError("policy ID does not match reconciliation run")

    manifest_by_kind: dict[domain.SourceKind, SourceDeliveryManifest] = {}
    for manifest in manifests:
        if not isinstance(manifest, SourceDeliveryManifest):
            raise TypeError("manifests must be SourceDeliveryManifest")
        if manifest.source_kind in manifest_by_kind:
            raise ExceptionCaseError("duplicate source manifest kind in case run")
        if manifest.scope_id != run.scope_id:
            raise ExceptionCaseError("source manifest scope does not match reconciliation run")
        if manifest.period_start != run.period_start or manifest.period_end != run.period_end:
            raise ExceptionCaseError("source manifest period does not match reconciliation run")
        if manifest.reporting_timezone != run.reporting_timezone:
            raise ExceptionCaseError("source manifest timezone does not match reconciliation run")
        if manifest.received_at is not None and manifest.received_at > run.knowledge_cutoff:
            raise ExceptionCaseError("source manifest delivery exceeds reconciliation run cutoff")
        if manifest.evaluated_at > run.completed_at:
            raise ExceptionCaseError("source manifest was evaluated after reconciliation run")
        manifest_by_kind[manifest.source_kind] = manifest
    missing_required = set(policy.required_source_kinds) - set(manifest_by_kind)
    if missing_required:
        raise ExceptionCaseError("required policy source manifests are missing from case run")
    ordered_manifests = tuple(
        sorted(manifest_by_kind.values(), key=lambda row: row.source_kind.value)
    )
    if tuple(manifest.id for manifest in ordered_manifests) != run.source_manifest_ids:
        raise ExceptionCaseError("source manifest IDs do not match reconciliation run")

    proof_by_settlement: dict[domain.SettlementId, ReconciliationProofVersion] = {}
    for proof in proof_versions:
        if not isinstance(proof, ReconciliationProofVersion):
            raise TypeError("proof versions must be ReconciliationProofVersion")
        if proof.settlement_id in proof_by_settlement:
            raise ExceptionCaseError("duplicate settlement proof in case run")
        if proof.batch_compilation_sha256 != run.canonical_compilation_sha256:
            raise ExceptionCaseError("proof compilation does not match reconciliation run")
        if proof.knowledge_cutoff > run.knowledge_cutoff:
            raise ExceptionCaseError("proof knowledge exceeds reconciliation run cutoff")
        if proof.generated_at > run.completed_at:
            raise ExceptionCaseError("proof was generated after reconciliation run completion")
        proof_by_settlement[proof.settlement_id] = proof
    ordered_proofs = tuple(sorted(proof_by_settlement.values(), key=lambda row: str(row.id)))
    if tuple(proof.id for proof in ordered_proofs) != run.proof_version_ids:
        raise ExceptionCaseError("proof IDs do not match reconciliation run proof IDs")
    return ordered_manifests, tuple(
        sorted(proof_by_settlement.values(), key=lambda row: str(row.settlement_id))
    )


class InMemoryExceptionCaseLedger:
    """Append-only reference ledger for deterministic Gate 14 case semantics."""

    def __init__(self) -> None:
        self._observations: dict[domain.ExceptionCaseId, list[ExceptionCaseObservation]] = {}
        self._observation_by_id: dict[
            domain.ExceptionCaseObservationId, ExceptionCaseObservation
        ] = {}
        self._run_settlement: dict[
            tuple[domain.ReconciliationRunId, domain.SettlementId],
            ExceptionCaseObservation,
        ] = {}
        self._dispositions: dict[domain.ExceptionCaseId, list[ExceptionCaseDisposition]] = {}
        self._latest_case_by_settlement: dict[
            tuple[domain.ReconciliationScopeId, domain.SettlementId],
            domain.ExceptionCaseId,
        ] = {}
        self._superseded_by: dict[domain.ExceptionCaseId, domain.ExceptionCaseId] = {}
        self._latest_observed_at_by_settlement: dict[
            tuple[domain.ReconciliationScopeId, domain.SettlementId], datetime
        ] = {}

    def observations(
        self, case_id: domain.ExceptionCaseId
    ) -> tuple[ExceptionCaseObservation, ...]:
        return tuple(self._observations.get(case_id, ()))

    def observation_by_id(
        self, observation_id: domain.ExceptionCaseObservationId
    ) -> ExceptionCaseObservation:
        observation = self._observation_by_id.get(observation_id)
        if observation is None:
            raise ExceptionCaseError(f"unknown case observation {observation_id}")
        return observation

    def dispositions(
        self, case_id: domain.ExceptionCaseId
    ) -> tuple[ExceptionCaseDisposition, ...]:
        return tuple(self._dispositions.get(case_id, ()))

    def apply_run(
        self,
        *,
        run: ReconciliationRun,
        policy: ReconciliationPolicyVersion,
        manifests: tuple[SourceDeliveryManifest, ...],
        proof_versions: tuple[ReconciliationProofVersion, ...],
    ) -> CaseRunUpdate:
        ordered_manifests, ordered_proofs = _validate_run_inputs(
            run=run,
            policy=policy,
            manifests=manifests,
            proof_versions=proof_versions,
        )
        source_states = _source_states(ordered_manifests)

        staged_observations: list[ExceptionCaseObservation] = []
        staged_new_cases: set[domain.ExceptionCaseId] = set()
        staged_supersessions: dict[domain.ExceptionCaseId, domain.ExceptionCaseId] = {}
        staged_latest = dict(self._latest_case_by_settlement)
        staged_settlement_times = dict(self._latest_observed_at_by_settlement)
        auto_closed: set[domain.ExceptionCaseId] = set()

        for proof in ordered_proofs:
            expected = _make_observation(
                run=run,
                policy=policy,
                proof=proof,
                source_states=source_states,
            )
            run_key = (run.id, proof.settlement_id)
            existing_run_observation = self._run_settlement.get(run_key)
            if existing_run_observation is not None:
                if existing_run_observation != expected:
                    raise ExceptionCaseError(
                        "same run/settlement has conflicting immutable case observation"
                    )
                continue

            history = self._observations.get(expected.case_id, [])
            settlement_key = (run.scope_id, proof.settlement_id)
            prior_case_id = staged_latest.get(settlement_key)
            case_exists = bool(history) or expected.case_id in staged_new_cases
            settlement_last_seen = staged_settlement_times.get(settlement_key)
            if settlement_last_seen is not None and expected.observed_at < settlement_last_seen:
                raise ExceptionCaseError(
                    "settlement case chronology moved backwards/out-of-order"
                )
            if expected.case_id in self._superseded_by:
                raise ExceptionCaseError(
                    "stale/superseded economic identity cannot be reactivated"
                )

            if proof.status is ReconciliationStatus.PROVEN_RECONCILED and not case_exists:
                # Gate 14 creates a case only after a non-green proof has existed.
                continue

            if history and expected.observed_at < history[-1].observed_at:
                raise ExceptionCaseError("case observation time moved backwards/out-of-order")
            for staged in staged_observations:
                if staged.case_id == expected.case_id and expected.observed_at < staged.observed_at:
                    raise ExceptionCaseError("case observation time moved backwards/out-of-order")

            if prior_case_id is not None and prior_case_id != expected.case_id:
                existing_target = self._superseded_by.get(prior_case_id)
                staged_target = staged_supersessions.get(prior_case_id)
                target = staged_target or existing_target
                if target is not None and target != expected.case_id:
                    raise ExceptionCaseError("case economic identity has conflicting supersession")
                staged_supersessions[prior_case_id] = expected.case_id

            if not case_exists:
                staged_new_cases.add(expected.case_id)
            staged_observations.append(expected)
            staged_latest[settlement_key] = expected.case_id
            staged_settlement_times[settlement_key] = expected.observed_at
            if proof.status is ReconciliationStatus.PROVEN_RECONCILED:
                auto_closed.add(expected.case_id)

        # Commit only after every proof/run invariant has passed.
        for old_case_id, new_case_id in staged_supersessions.items():
            self._superseded_by[old_case_id] = new_case_id
        for observation in staged_observations:
            self._observations.setdefault(observation.case_id, []).append(observation)
            self._observation_by_id[observation.id] = observation
            self._run_settlement[(observation.run_id, observation.settlement_id)] = observation
            settlement_key = (observation.scope_id, observation.settlement_id)
            self._latest_case_by_settlement[settlement_key] = observation.case_id
            self._latest_observed_at_by_settlement[settlement_key] = observation.observed_at

        return CaseRunUpdate(
            created_observation_ids=tuple(
                sorted((value.id for value in staged_observations), key=str)
            ),
            created_case_ids=tuple(sorted(staged_new_cases, key=str)),
            superseded_case_ids=tuple(sorted(staged_supersessions, key=str)),
            auto_closed_case_ids=tuple(sorted(auto_closed, key=str)),
        )

    def append_disposition(
        self,
        *,
        case_id: domain.ExceptionCaseId,
        sequence: int,
        actor_id: str,
        occurred_at: datetime,
        kind: DispositionKind,
        owner: str | None = None,
        note: str | None = None,
    ) -> ExceptionCaseDisposition:
        if not isinstance(case_id, domain.ExceptionCaseId):
            raise TypeError("case_id must be ExceptionCaseId")
        history = self._observations.get(case_id)
        if not history:
            raise ExceptionCaseError(f"unknown exception case {case_id}")
        actor_id = _text(actor_id, "disposition actor")
        owner = _optional_text(owner, "disposition owner")
        note = _optional_text(note, "disposition note")
        _aware(occurred_at, "disposition time")
        if not isinstance(kind, DispositionKind):
            raise TypeError("kind must be DispositionKind")
        if isinstance(sequence, bool) or not isinstance(sequence, int):
            raise TypeError("disposition sequence must be int")
        if sequence < 1:
            raise ExceptionCaseError("disposition sequence must be positive")
        if occurred_at < history[0].observed_at:
            raise ExceptionCaseError("disposition cannot predate the exception case")

        disposition_id = _disposition_id(
            case_id=case_id,
            sequence=sequence,
            actor_id=actor_id,
            occurred_at=occurred_at,
            kind=kind,
            owner=owner,
            note=note,
        )
        candidate = ExceptionCaseDisposition(
            id=disposition_id,
            case_id=case_id,
            sequence=sequence,
            actor_id=actor_id,
            occurred_at=occurred_at,
            kind=kind,
            owner=owner,
            note=note,
            ruleset_version=GATE14_CASE_RULESET_VERSION,
        )
        dispositions = self._dispositions.setdefault(case_id, [])
        if sequence <= len(dispositions):
            existing = dispositions[sequence - 1]
            if existing == candidate:
                return existing
            raise ExceptionCaseError("disposition sequence already contains conflicting record")
        if sequence != len(dispositions) + 1:
            raise ExceptionCaseError("disposition sequence must be contiguous and monotonic")
        if dispositions and occurred_at < dispositions[-1].occurred_at:
            raise ExceptionCaseError("disposition time cannot move backwards")
        current = self.state(case_id)
        if current.resolution in {
            CaseResolution.PROOF_RECONCILED,
            CaseResolution.ECONOMIC_IDENTITY_CHANGED,
        }:
            raise ExceptionCaseError(
                "financially resolved/superseded case cannot accept new workflow"
            )
        if (
            current.workflow_status is CaseWorkflowStatus.CLOSED
            and kind is not DispositionKind.REOPEN
        ):
            raise ExceptionCaseError(
                "closed workflow requires explicit REOPEN before another status change"
            )
        dispositions.append(candidate)
        return candidate

    def state(self, case_id: domain.ExceptionCaseId) -> ExceptionCaseState:
        history = self._observations.get(case_id)
        if not history:
            raise ExceptionCaseError(f"unknown exception case {case_id}")
        first = history[0]
        latest = history[-1]
        dispositions = self._dispositions.get(case_id, [])
        owner: str | None = None
        workflow = CaseWorkflowStatus.OPEN
        resolution: CaseResolution | None = None
        for disposition in dispositions:
            if disposition.kind is DispositionKind.ASSIGN_OWNER:
                owner = disposition.owner
            elif disposition.kind is DispositionKind.ACKNOWLEDGE:
                workflow = CaseWorkflowStatus.ACKNOWLEDGED
                resolution = None
            elif disposition.kind is DispositionKind.REQUEST_SOURCE_CORRECTION:
                workflow = CaseWorkflowStatus.AWAITING_SOURCE
                resolution = None
            elif disposition.kind is DispositionKind.DEFER:
                workflow = CaseWorkflowStatus.DEFERRED
                resolution = None
            elif disposition.kind is DispositionKind.ACCEPT_OPERATIONAL_VARIANCE:
                workflow = CaseWorkflowStatus.CLOSED
                resolution = CaseResolution.OPERATIONAL_VARIANCE_ACCEPTED
            elif disposition.kind is DispositionKind.CLOSE:
                workflow = CaseWorkflowStatus.CLOSED
                resolution = CaseResolution.OPERATOR_CLOSED
            elif disposition.kind is DispositionKind.REOPEN:
                workflow = CaseWorkflowStatus.OPEN
                resolution = None

        superseded_by = self._superseded_by.get(case_id)
        if superseded_by is not None:
            workflow = CaseWorkflowStatus.CLOSED
            resolution = CaseResolution.ECONOMIC_IDENTITY_CHANGED
        elif latest.financial_status is ReconciliationStatus.PROVEN_RECONCILED:
            workflow = CaseWorkflowStatus.CLOSED
            resolution = CaseResolution.PROOF_RECONCILED

        return ExceptionCaseState(
            case_id=case_id,
            tracking_key=latest.tracking_key,
            scope_id=latest.scope_id,
            settlement_id=latest.settlement_id,
            settlement_utr=latest.settlement_utr,
            affected_amount=latest.affected_amount,
            first_seen_at=first.observed_at,
            last_seen_at=latest.observed_at,
            first_seen_run_id=first.run_id,
            last_seen_run_id=latest.run_id,
            latest_observation_id=latest.id,
            latest_proof_version_id=latest.proof_version_id,
            financial_status=latest.financial_status,
            materiality_band=latest.materiality_band,
            incident_fingerprint_id=latest.incident_fingerprint_id,
            workflow_status=workflow,
            resolution=resolution,
            owner=owner,
            superseded_by_case_id=superseded_by,
            observation_count=len(history),
            disposition_count=len(dispositions),
        )
