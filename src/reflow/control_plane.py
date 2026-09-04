from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import domain
from .bank_proof import BANK_RULESET_VERSION, BankReceiptStatus
from .ingestion import CanonicalBatch
from .reconciliation_proof import (
    GATE9_RULESET_VERSION,
    ReconciliationProofVersion,
    ReconciliationStatus,
)
from .settlement_proof import COMPOSITION_RULESET_VERSION, CompositionStatus

GATE13_CONTROL_RULESET_VERSION = "gate13-control-plane-v1"
_SUPPORTED_CONTROLS = ("balance_control", "evidence_coverage")
_RUN_RULESET_VERSIONS = (
    COMPOSITION_RULESET_VERSION,
    BANK_RULESET_VERSION,
    GATE9_RULESET_VERSION,
    GATE13_CONTROL_RULESET_VERSION,
)

__all__ = [
    "GATE13_CONTROL_RULESET_VERSION",
    "BalanceControlProof",
    "BalanceControlStatus",
    "CloseReadinessCertificate",
    "CloseReadinessStatus",
    "ControlPlaneError",
    "CoverageBucket",
    "CoverageBucketSummary",
    "CoverageItem",
    "CoverageStatus",
    "DeliveryMode",
    "EvidenceCoverageAssignment",
    "EvidenceCoverageCertificate",
    "MaterialityBand",
    "ReconciliationPolicyVersion",
    "ReconciliationRun",
    "ReconciliationScope",
    "SourceCompleteness",
    "SourceDeliveryManifest",
    "build_balance_control",
    "build_close_readiness",
    "build_evidence_coverage",
    "build_reconciliation_run",
    "make_reconciliation_policy_version",
    "make_reconciliation_scope",
    "make_source_delivery_manifest",
]


class ControlPlaneError(ValueError):
    """Gate 13 control-plane inputs violate a deterministic finance invariant."""


class DeliveryMode(StrEnum):
    SNAPSHOT = "snapshot"
    DELTA = "delta"


class SourceCompleteness(StrEnum):
    WAITING = "waiting"
    LATE = "late"
    PARTIAL = "partial"
    COMPLETE = "complete"


class CoverageBucket(StrEnum):
    PROVEN = "proven"
    OPEN_UNSETTLED = "open_unsettled"
    WAITING_FOR_SOURCE = "waiting_for_source"
    CONTRADICTED_RESIDUAL = "contradicted_residual"
    QUARANTINED = "quarantined"
    ORPHAN = "orphan"


class CoverageStatus(StrEnum):
    COMPLETE = "complete"
    FAILED = "failed"


class BalanceControlStatus(StrEnum):
    PROVEN = "proven"
    RESIDUAL = "residual"


class CloseReadinessStatus(StrEnum):
    READY = "ready"
    NOT_READY = "not_ready"


class MaterialityBand(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


def _aware(value: datetime, label: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{label} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ControlPlaneError(f"{label} must be timezone-aware")


def _text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ControlPlaneError(f"{label} must be a non-empty string")
    if value != value.strip():
        raise ControlPlaneError(f"{label} must not contain surrounding whitespace")
    return value


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


def _require_sha256(value: str, label: str) -> None:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{label} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{label} must be a SHA-256 hex digest") from exc


def _content_id(prefix: str, value: object) -> str:
    return f"{prefix}{_sha256(value)[:24]}"


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _sorted_ids(
    values: tuple[domain.SourceEnvelopeId, ...],
) -> tuple[domain.SourceEnvelopeId, ...]:
    unique = set(values)
    if len(unique) != len(values):
        raise ControlPlaneError("source envelope ids must be unique")
    return tuple(sorted(values, key=str))


def _timezone_exists(name: str) -> None:
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ControlPlaneError(f"unknown reporting timezone {name!r}") from exc


def _matches_timezone(value: datetime, timezone_name: str) -> bool:
    zone = ZoneInfo(timezone_name)
    return value.utcoffset() == value.astimezone(zone).utcoffset()


@dataclass(frozen=True, slots=True)
class ReconciliationScope:
    id: domain.ReconciliationScopeId
    merchant_account_id: str
    provider: str
    provider_account_id: str
    bank_account_id: str
    currency: domain.Currency
    channel: str | None

    def __post_init__(self) -> None:
        _text(self.merchant_account_id, "merchant account id")
        _text(self.provider, "provider")
        _text(self.provider_account_id, "provider account id")
        _text(self.bank_account_id, "bank account id")
        if not isinstance(self.currency, domain.Currency):
            raise TypeError("currency must be Currency")
        if self.channel is not None:
            _text(self.channel, "channel")
        expected = _scope_id(
            merchant_account_id=self.merchant_account_id,
            provider=self.provider,
            provider_account_id=self.provider_account_id,
            bank_account_id=self.bank_account_id,
            currency=self.currency,
            channel=self.channel,
        )
        if self.id != expected:
            raise ValueError("reconciliation scope id does not match its immutable content")

    def account_for(self, source_kind: domain.SourceKind) -> str:
        if not isinstance(source_kind, domain.SourceKind):
            raise TypeError("source_kind must be SourceKind")
        if source_kind is domain.SourceKind.MERCHANT:
            return self.merchant_account_id
        if source_kind in {
            domain.SourceKind.RAZORPAY_EVENT,
            domain.SourceKind.RAZORPAY_RECON,
            domain.SourceKind.RAZORPAY_SETTLEMENT,
            domain.SourceKind.RAZORPAY_INSTANT_SETTLEMENT,
        }:
            return self.provider_account_id
        if source_kind is domain.SourceKind.BANK:
            return self.bank_account_id
        raise AssertionError(f"unmapped source kind {source_kind}")


def _scope_id(
    *,
    merchant_account_id: str,
    provider: str,
    provider_account_id: str,
    bank_account_id: str,
    currency: domain.Currency,
    channel: str | None,
) -> domain.ReconciliationScopeId:
    material = {
        "contract": GATE13_CONTROL_RULESET_VERSION,
        "merchant_account_id": merchant_account_id,
        "provider": provider,
        "provider_account_id": provider_account_id,
        "bank_account_id": bank_account_id,
        "currency": currency.value,
        "channel": channel,
    }
    return domain.ReconciliationScopeId(_content_id("scope_", material))


def make_reconciliation_scope(
    *,
    merchant_account_id: str,
    provider: str,
    provider_account_id: str,
    bank_account_id: str,
    currency: domain.Currency,
    channel: str | None = None,
) -> ReconciliationScope:
    merchant_account_id = _text(merchant_account_id, "merchant account id")
    provider = _text(provider, "provider")
    provider_account_id = _text(provider_account_id, "provider account id")
    bank_account_id = _text(bank_account_id, "bank account id")
    if not isinstance(currency, domain.Currency):
        raise TypeError("currency must be Currency")
    if channel is not None:
        channel = _text(channel, "channel")
    return ReconciliationScope(
        id=_scope_id(
            merchant_account_id=merchant_account_id,
            provider=provider,
            provider_account_id=provider_account_id,
            bank_account_id=bank_account_id,
            currency=currency,
            channel=channel,
        ),
        merchant_account_id=merchant_account_id,
        provider=provider,
        provider_account_id=provider_account_id,
        bank_account_id=bank_account_id,
        currency=currency,
        channel=channel,
    )


@dataclass(frozen=True, slots=True)
class ReconciliationPolicyVersion:
    id: domain.ReconciliationPolicyVersionId
    version_label: str
    required_source_kinds: tuple[domain.SourceKind, ...]
    reporting_timezone: str
    bank_wait_sla_seconds: int
    materiality_thresholds_paise: tuple[int, int, int]
    enabled_controls: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.version_label, "policy version label")
        _text(self.reporting_timezone, "reporting timezone")
        _timezone_exists(self.reporting_timezone)
        if not self.required_source_kinds:
            raise ValueError("policy must require at least one source kind")
        if any(not isinstance(kind, domain.SourceKind) for kind in self.required_source_kinds):
            raise TypeError("required source kinds must be SourceKind values")
        if tuple(sorted(set(self.required_source_kinds), key=lambda kind: kind.value)) != (
            self.required_source_kinds
        ):
            raise ValueError("required source kinds must be unique and canonical-sorted")
        if isinstance(self.bank_wait_sla_seconds, bool) or not isinstance(
            self.bank_wait_sla_seconds, int
        ):
            raise TypeError("bank wait SLA must be integer seconds")
        if self.bank_wait_sla_seconds < 0:
            raise ValueError("bank wait SLA cannot be negative")
        low, medium, high = self.materiality_thresholds_paise
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (low, medium, high)
        ):
            raise TypeError("materiality thresholds must be integer paise")
        if not 0 <= low < medium < high:
            raise ValueError("materiality thresholds must be strictly increasing and non-negative")
        if tuple(sorted(set(self.enabled_controls))) != self.enabled_controls:
            raise ValueError("enabled controls must be unique and canonical-sorted")
        if self.enabled_controls != _SUPPORTED_CONTROLS:
            raise ValueError(
                "Gate 13 v1 requires the evidence-coverage and balance controls"
            )
        expected = _policy_id(
            version_label=self.version_label,
            required_source_kinds=self.required_source_kinds,
            reporting_timezone=self.reporting_timezone,
            bank_wait_sla_seconds=self.bank_wait_sla_seconds,
            materiality_thresholds_paise=self.materiality_thresholds_paise,
            enabled_controls=self.enabled_controls,
        )
        if self.id != expected:
            raise ValueError("policy version id does not match its immutable content")

    def materiality_band(self, amount: domain.Money) -> MaterialityBand:
        if not isinstance(amount, domain.Money):
            raise TypeError("materiality requires Money")
        value = abs(amount.amount_paise)
        low, medium, high = self.materiality_thresholds_paise
        if value <= low:
            return MaterialityBand.LOW
        if value <= medium:
            return MaterialityBand.MEDIUM
        if value <= high:
            return MaterialityBand.HIGH
        return MaterialityBand.CRITICAL


def _policy_id(
    *,
    version_label: str,
    required_source_kinds: tuple[domain.SourceKind, ...],
    reporting_timezone: str,
    bank_wait_sla_seconds: int,
    materiality_thresholds_paise: tuple[int, int, int],
    enabled_controls: tuple[str, ...],
) -> domain.ReconciliationPolicyVersionId:
    material = {
        "contract": GATE13_CONTROL_RULESET_VERSION,
        "version_label": version_label,
        "required_source_kinds": [kind.value for kind in required_source_kinds],
        "reporting_timezone": reporting_timezone,
        "bank_wait_sla_seconds": bank_wait_sla_seconds,
        "materiality_thresholds_paise": list(materiality_thresholds_paise),
        "enabled_controls": list(enabled_controls),
    }
    return domain.ReconciliationPolicyVersionId(_content_id("policy_", material))


def make_reconciliation_policy_version(
    *,
    version_label: str,
    required_source_kinds: tuple[domain.SourceKind, ...],
    reporting_timezone: str,
    bank_wait_sla_seconds: int,
    materiality_thresholds_paise: tuple[int, int, int],
    enabled_controls: tuple[str, ...] = _SUPPORTED_CONTROLS,
) -> ReconciliationPolicyVersion:
    canonical_sources = tuple(sorted(set(required_source_kinds), key=lambda kind: kind.value))
    canonical_controls = tuple(sorted(set(enabled_controls)))
    return ReconciliationPolicyVersion(
        id=_policy_id(
            version_label=version_label,
            required_source_kinds=canonical_sources,
            reporting_timezone=reporting_timezone,
            bank_wait_sla_seconds=bank_wait_sla_seconds,
            materiality_thresholds_paise=materiality_thresholds_paise,
            enabled_controls=canonical_controls,
        ),
        version_label=version_label,
        required_source_kinds=canonical_sources,
        reporting_timezone=reporting_timezone,
        bank_wait_sla_seconds=bank_wait_sla_seconds,
        materiality_thresholds_paise=materiality_thresholds_paise,
        enabled_controls=canonical_controls,
    )


@dataclass(frozen=True, slots=True)
class SourceDeliveryManifest:
    id: domain.SourceDeliveryManifestId
    scope_id: domain.ReconciliationScopeId
    source_kind: domain.SourceKind
    source_account_id: str
    delivery_mode: DeliveryMode
    period_start: datetime
    period_end: datetime
    reporting_timezone: str
    expected_by: datetime
    evaluated_at: datetime
    received_at: datetime | None
    watermark_at: datetime | None
    completeness: SourceCompleteness
    received_late: bool
    delivered_envelope_ids: tuple[domain.SourceEnvelopeId, ...]
    effective_envelope_ids: tuple[domain.SourceEnvelopeId, ...]
    content_sha256: str
    prior_manifest_id: domain.SourceDeliveryManifestId | None
    adapter_version: str
    schema_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.scope_id, domain.ReconciliationScopeId):
            raise TypeError("scope_id must be ReconciliationScopeId")
        if not isinstance(self.source_kind, domain.SourceKind):
            raise TypeError("source_kind must be SourceKind")
        _text(self.source_account_id, "source account id")
        if not isinstance(self.delivery_mode, DeliveryMode):
            raise TypeError("delivery_mode must be DeliveryMode")
        for value, label in (
            (self.period_start, "period start"),
            (self.period_end, "period end"),
            (self.expected_by, "expected by"),
            (self.evaluated_at, "evaluated at"),
        ):
            _aware(value, label)
        if self.period_end <= self.period_start:
            raise ValueError("source period end must be after period start")
        if self.received_at is not None:
            _aware(self.received_at, "received at")
            if self.received_at > self.evaluated_at:
                raise ValueError("source cannot be received after manifest evaluation")
        if self.watermark_at is not None:
            _aware(self.watermark_at, "watermark at")
        _text(self.reporting_timezone, "reporting timezone")
        _timezone_exists(self.reporting_timezone)
        _text(self.adapter_version, "adapter version")
        _text(self.schema_fingerprint, "schema fingerprint")
        if not isinstance(self.completeness, SourceCompleteness):
            raise TypeError("completeness must be SourceCompleteness")
        if self.delivered_envelope_ids != _sorted_ids(self.delivered_envelope_ids):
            raise ValueError("delivered envelope ids must be canonical-sorted")
        if self.effective_envelope_ids != _sorted_ids(self.effective_envelope_ids):
            raise ValueError("effective envelope ids must be canonical-sorted")
        if self.delivery_mode is DeliveryMode.SNAPSHOT:
            if self.effective_envelope_ids != self.delivered_envelope_ids:
                raise ValueError("snapshot delivery must replace prior effective evidence")
        elif not set(self.delivered_envelope_ids).issubset(self.effective_envelope_ids):
            raise ValueError("delta effective evidence must include delivered evidence")
        if self.received_at is None:
            if self.delivered_envelope_ids:
                raise ValueError("undelivered source cannot contain delivered evidence")
            if self.watermark_at is not None:
                raise ValueError("undelivered source cannot carry a source watermark")
            if self.completeness not in {
                SourceCompleteness.WAITING,
                SourceCompleteness.LATE,
            }:
                raise ValueError("undelivered source must be waiting or late")
        else:
            if self.completeness in {
                SourceCompleteness.WAITING,
                SourceCompleteness.LATE,
            }:
                raise ValueError("received source cannot remain waiting or late")
        if (
            self.completeness is SourceCompleteness.COMPLETE
            and (self.watermark_at is None or self.watermark_at < self.period_end)
        ):
            raise ValueError("complete source requires watermark through period end")
        expected_late = self.received_at is not None and self.received_at > self.expected_by
        if self.received_late != expected_late:
            raise ValueError("received_late does not match expected delivery window")
        expected_content = _sha256([str(value) for value in self.effective_envelope_ids])
        if self.content_sha256 != expected_content:
            raise ValueError("manifest content hash does not match effective evidence")
        expected_id = _manifest_id(
            scope_id=self.scope_id,
            source_kind=self.source_kind,
            source_account_id=self.source_account_id,
            delivery_mode=self.delivery_mode,
            period_start=self.period_start,
            period_end=self.period_end,
            reporting_timezone=self.reporting_timezone,
            expected_by=self.expected_by,
            received_at=self.received_at,
            watermark_at=self.watermark_at,
            completeness=self.completeness,
            received_late=self.received_late,
            delivered_envelope_ids=self.delivered_envelope_ids,
            effective_envelope_ids=self.effective_envelope_ids,
            prior_manifest_id=self.prior_manifest_id,
            adapter_version=self.adapter_version,
            schema_fingerprint=self.schema_fingerprint,
        )
        if self.id != expected_id:
            raise ValueError("source manifest id does not match its immutable content")


def _manifest_id(
    *,
    scope_id: domain.ReconciliationScopeId,
    source_kind: domain.SourceKind,
    source_account_id: str,
    delivery_mode: DeliveryMode,
    period_start: datetime,
    period_end: datetime,
    reporting_timezone: str,
    expected_by: datetime,
    received_at: datetime | None,
    watermark_at: datetime | None,
    completeness: SourceCompleteness,
    received_late: bool,
    delivered_envelope_ids: tuple[domain.SourceEnvelopeId, ...],
    effective_envelope_ids: tuple[domain.SourceEnvelopeId, ...],
    prior_manifest_id: domain.SourceDeliveryManifestId | None,
    adapter_version: str,
    schema_fingerprint: str,
) -> domain.SourceDeliveryManifestId:
    material = {
        "contract": GATE13_CONTROL_RULESET_VERSION,
        "scope_id": str(scope_id),
        "source_kind": source_kind.value,
        "source_account_id": source_account_id,
        "delivery_mode": delivery_mode.value,
        "period_start": _iso(period_start),
        "period_end": _iso(period_end),
        "reporting_timezone": reporting_timezone,
        "expected_by": _iso(expected_by),
        "received_at": _iso(received_at),
        "watermark_at": _iso(watermark_at),
        "completeness": completeness.value,
        "received_late": received_late,
        "delivered_envelope_ids": [str(value) for value in delivered_envelope_ids],
        "effective_envelope_ids": [str(value) for value in effective_envelope_ids],
        "prior_manifest_id": None if prior_manifest_id is None else str(prior_manifest_id),
        "adapter_version": adapter_version,
        "schema_fingerprint": schema_fingerprint,
    }
    return domain.SourceDeliveryManifestId(_content_id("delivery_", material))


def make_source_delivery_manifest(
    *,
    scope: ReconciliationScope,
    source_kind: domain.SourceKind,
    source_account_id: str,
    delivery_mode: DeliveryMode,
    period_start: datetime,
    period_end: datetime,
    reporting_timezone: str,
    expected_by: datetime,
    evaluated_at: datetime,
    received_at: datetime | None,
    watermark_at: datetime | None,
    is_complete: bool,
    delivered_envelope_ids: tuple[domain.SourceEnvelopeId, ...],
    adapter_version: str,
    schema_fingerprint: str,
    prior: SourceDeliveryManifest | None = None,
) -> SourceDeliveryManifest:
    if not isinstance(scope, ReconciliationScope):
        raise TypeError("scope must be ReconciliationScope")
    if not isinstance(source_kind, domain.SourceKind):
        raise TypeError("source_kind must be SourceKind")
    if not isinstance(delivery_mode, DeliveryMode):
        raise TypeError("delivery_mode must be DeliveryMode")
    source_account_id = _text(source_account_id, "source account id")
    if source_account_id != scope.account_for(source_kind):
        raise ControlPlaneError(
            f"source account does not belong to reconciliation scope {scope.id}"
        )
    if not isinstance(is_complete, bool):
        raise TypeError("is_complete must be bool")
    for value, label in (
        (period_start, "period start"),
        (period_end, "period end"),
        (expected_by, "expected by"),
        (evaluated_at, "evaluated at"),
    ):
        _aware(value, label)
    if received_at is not None:
        _aware(received_at, "received at")
    if watermark_at is not None:
        _aware(watermark_at, "watermark at")
    _text(reporting_timezone, "reporting timezone")
    _timezone_exists(reporting_timezone)
    adapter_version = _text(adapter_version, "adapter version")
    schema_fingerprint = _text(schema_fingerprint, "schema fingerprint")
    delivered = _sorted_ids(delivered_envelope_ids)

    if prior is not None:
        if prior.scope_id != scope.id:
            raise ControlPlaneError("prior source manifest belongs to another scope")
        if prior.source_kind is not source_kind:
            raise ControlPlaneError("prior source manifest belongs to another source kind")
        if prior.source_account_id != source_account_id:
            raise ControlPlaneError("prior source manifest belongs to another source account")
        if prior.period_start != period_start or prior.period_end != period_end:
            raise ControlPlaneError("source delivery lineage cannot cross reporting periods")
        if prior.reporting_timezone != reporting_timezone:
            raise ControlPlaneError("source delivery lineage cannot cross reporting timezones")

    if received_at is None:
        if delivered:
            raise ControlPlaneError("undelivered source cannot contain delivered evidence")
        if watermark_at is not None:
            raise ControlPlaneError("undelivered source cannot carry a watermark")
        if is_complete:
            raise ControlPlaneError("undelivered source cannot be complete")
        completeness = (
            SourceCompleteness.WAITING
            if evaluated_at <= expected_by
            else SourceCompleteness.LATE
        )
    else:
        if received_at > evaluated_at:
            raise ControlPlaneError("source cannot be received after manifest evaluation")
        if is_complete:
            if watermark_at is None or watermark_at < period_end:
                raise ControlPlaneError("complete delivery requires watermark through period end")
            completeness = SourceCompleteness.COMPLETE
        else:
            completeness = SourceCompleteness.PARTIAL

    if delivery_mode is DeliveryMode.SNAPSHOT or prior is None:
        effective = delivered
    else:
        effective = tuple(
            sorted(set(prior.effective_envelope_ids) | set(delivered), key=str)
        )
    received_late = received_at is not None and received_at > expected_by
    content_sha256 = _sha256([str(value) for value in effective])
    prior_id = None if prior is None else prior.id
    manifest_id = _manifest_id(
        scope_id=scope.id,
        source_kind=source_kind,
        source_account_id=source_account_id,
        delivery_mode=delivery_mode,
        period_start=period_start,
        period_end=period_end,
        reporting_timezone=reporting_timezone,
        expected_by=expected_by,
        received_at=received_at,
        watermark_at=watermark_at,
        completeness=completeness,
        received_late=received_late,
        delivered_envelope_ids=delivered,
        effective_envelope_ids=effective,
        prior_manifest_id=prior_id,
        adapter_version=adapter_version,
        schema_fingerprint=schema_fingerprint,
    )
    return SourceDeliveryManifest(
        id=manifest_id,
        scope_id=scope.id,
        source_kind=source_kind,
        source_account_id=source_account_id,
        delivery_mode=delivery_mode,
        period_start=period_start,
        period_end=period_end,
        reporting_timezone=reporting_timezone,
        expected_by=expected_by,
        evaluated_at=evaluated_at,
        received_at=received_at,
        watermark_at=watermark_at,
        completeness=completeness,
        received_late=received_late,
        delivered_envelope_ids=delivered,
        effective_envelope_ids=effective,
        content_sha256=content_sha256,
        prior_manifest_id=prior_id,
        adapter_version=adapter_version,
        schema_fingerprint=schema_fingerprint,
    )


@dataclass(frozen=True, slots=True)
class EvidenceCoverageAssignment:
    envelope_id: domain.SourceEnvelopeId
    bucket: CoverageBucket

    def __post_init__(self) -> None:
        if not isinstance(self.envelope_id, domain.SourceEnvelopeId):
            raise TypeError("coverage envelope_id must be SourceEnvelopeId")
        if not isinstance(self.bucket, CoverageBucket):
            raise TypeError("coverage bucket must be CoverageBucket")


@dataclass(frozen=True, slots=True)
class CoverageItem:
    envelope_id: domain.SourceEnvelopeId
    source_kind: domain.SourceKind
    bucket: CoverageBucket
    amount: domain.Money | None


@dataclass(frozen=True, slots=True)
class CoverageBucketSummary:
    bucket: CoverageBucket
    record_count: int
    known_value: domain.Money
    unknown_value_count: int


@dataclass(frozen=True, slots=True)
class EvidenceCoverageCertificate:
    id: domain.EvidenceCoverageCertificateId
    scope_id: domain.ReconciliationScopeId
    manifest_ids: tuple[domain.SourceDeliveryManifestId, ...]
    batch_compilation_sha256: str
    proof_version_ids: tuple[domain.ProofVersionId, ...]
    items: tuple[CoverageItem, ...]
    summaries: tuple[CoverageBucketSummary, ...]
    status: CoverageStatus
    orphan_count: int
    orphan_known_value: domain.Money
    ruleset_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, domain.EvidenceCoverageCertificateId):
            raise TypeError("coverage id must be EvidenceCoverageCertificateId")
        if not isinstance(self.scope_id, domain.ReconciliationScopeId):
            raise TypeError("coverage scope_id must be ReconciliationScopeId")
        if any(
            not isinstance(value, domain.SourceDeliveryManifestId)
            for value in self.manifest_ids
        ):
            raise TypeError("coverage manifest ids must be SourceDeliveryManifestId")
        if len(set(self.manifest_ids)) != len(self.manifest_ids):
            raise ValueError("coverage manifest ids must be unique")
        _require_sha256(self.batch_compilation_sha256, "batch compilation hash")
        if any(not isinstance(value, domain.ProofVersionId) for value in self.proof_version_ids):
            raise TypeError("coverage proof ids must be ProofVersionId")
        if tuple(sorted(set(self.proof_version_ids), key=str)) != self.proof_version_ids:
            raise ValueError("coverage proof ids must be unique and canonical-sorted")
        if any(not isinstance(item, CoverageItem) for item in self.items):
            raise TypeError("coverage items must be CoverageItem")
        envelope_ids = tuple(item.envelope_id for item in self.items)
        if tuple(sorted(set(envelope_ids), key=str)) != envelope_ids:
            raise ValueError("coverage items must have unique canonical-sorted envelope ids")
        currencies = {
            item.amount.currency for item in self.items if item.amount is not None
        } | {summary.known_value.currency for summary in self.summaries}
        currencies.add(self.orphan_known_value.currency)
        if len(currencies) != 1:
            raise ValueError("coverage certificate money must use one currency")
        if any(not isinstance(summary, CoverageBucketSummary) for summary in self.summaries):
            raise TypeError("coverage summaries must be CoverageBucketSummary")
        if tuple(summary.bucket for summary in self.summaries) != tuple(CoverageBucket):
            raise ValueError("coverage summaries must contain every bucket in canonical order")
        for summary in self.summaries:
            bucket_items = tuple(item for item in self.items if item.bucket is summary.bucket)
            expected_value = domain.sum_money(
                [item.amount for item in bucket_items if item.amount is not None],
                summary.known_value.currency,
            )
            if summary.record_count != len(bucket_items):
                raise ValueError("coverage summary count does not match coverage items")
            if summary.known_value != expected_value:
                raise ValueError("coverage summary value does not match coverage items")
            if summary.unknown_value_count != sum(
                item.amount is None for item in bucket_items
            ):
                raise ValueError("coverage unknown-value count does not match coverage items")
        orphan = self.summary(CoverageBucket.ORPHAN)
        if self.orphan_count != orphan.record_count:
            raise ValueError("coverage orphan count does not match orphan summary")
        if self.orphan_known_value != orphan.known_value:
            raise ValueError("coverage orphan value does not match orphan summary")
        expected_status = (
            CoverageStatus.COMPLETE if self.orphan_count == 0 else CoverageStatus.FAILED
        )
        if self.status is not expected_status:
            raise ValueError("coverage status does not match orphan evidence")
        if self.ruleset_version != GATE13_CONTROL_RULESET_VERSION:
            raise ValueError("coverage ruleset version does not match Gate 13")
        expected_id = _coverage_id(
            scope_id=self.scope_id,
            manifest_ids=self.manifest_ids,
            batch_compilation_sha256=self.batch_compilation_sha256,
            proof_version_ids=self.proof_version_ids,
            items=self.items,
        )
        if self.id != expected_id:
            raise ValueError("coverage id does not match its immutable content")

    def summary(self, bucket: CoverageBucket) -> CoverageBucketSummary:
        return next(summary for summary in self.summaries if summary.bucket is bucket)


def _index_manifests(
    manifests: tuple[SourceDeliveryManifest, ...],
) -> dict[domain.SourceKind, SourceDeliveryManifest]:
    indexed: dict[domain.SourceKind, SourceDeliveryManifest] = {}
    for manifest in manifests:
        if manifest.source_kind in indexed:
            raise ControlPlaneError(
                f"multiple source manifests supplied for {manifest.source_kind.value}"
            )
        indexed[manifest.source_kind] = manifest
    return indexed


def _validate_manifest_scope(
    scope: ReconciliationScope,
    manifest: SourceDeliveryManifest,
) -> None:
    if manifest.scope_id != scope.id:
        raise ControlPlaneError("source manifest belongs to another reconciliation scope")
    if manifest.source_account_id != scope.account_for(manifest.source_kind):
        raise ControlPlaneError("source manifest account does not match reconciliation scope")


def _canonical_amounts(
    batch: CanonicalBatch,
    scope: ReconciliationScope,
) -> dict[domain.SourceEnvelopeId, domain.Money]:
    by_identity: dict[tuple[domain.SourceKind, str], domain.Money] = {}
    by_identity.update(
        ((domain.SourceKind.MERCHANT, str(row.id)), row.amount) for row in batch.orders
    )
    by_identity.update(
        ((domain.SourceKind.RAZORPAY_EVENT, row.source_event_id), row.amount)
        for row in batch.payment_events
    )
    by_identity.update(
        ((domain.SourceKind.RAZORPAY_RECON, str(row.id)), row.settlement_effect)
        for row in batch.recon_entries
    )
    by_identity.update(
        ((domain.SourceKind.RAZORPAY_SETTLEMENT, str(row.id)), row.amount)
        for row in batch.settlements
    )
    by_identity.update(
        ((domain.SourceKind.BANK, str(row.id)), row.amount) for row in batch.bank_entries
    )
    amounts: dict[domain.SourceEnvelopeId, domain.Money] = {}
    for link in batch.source_links:
        amount = by_identity.get(link.canonical_identity)
        if amount is None:
            raise ControlPlaneError(
                "canonical source link has no financially relevant canonical record"
            )
        if amount.currency != scope.currency:
            raise ControlPlaneError("canonical evidence currency crosses reconciliation scope")
        if link.envelope_id in amounts:
            raise ControlPlaneError("one source envelope maps to multiple canonical records")
        amounts[link.envelope_id] = amount
    return amounts


def _index_proof_versions(
    batch: CanonicalBatch,
    proof_versions: tuple[ReconciliationProofVersion, ...],
) -> dict[domain.SettlementId, ReconciliationProofVersion]:
    indexed: dict[domain.SettlementId, ReconciliationProofVersion] = {}
    for proof in proof_versions:
        if proof.settlement_id in indexed:
            raise ControlPlaneError(
                f"multiple Gate 9 proofs supplied for {proof.settlement_id}"
            )
        if proof.batch_compilation_sha256 != batch.compilation_sha256:
            raise ControlPlaneError("Gate 9 proof belongs to another canonical compilation")
        indexed[proof.settlement_id] = proof
    expected = {settlement.id for settlement in batch.settlements}
    if set(indexed) != expected:
        raise ControlPlaneError(
            "run/coverage requires exactly one Gate 9 proof per canonical settlement"
        )
    return indexed


def _merge_coverage_bucket(
    existing: CoverageBucket | None,
    incoming: CoverageBucket,
) -> CoverageBucket:
    if existing is None:
        return incoming
    if CoverageBucket.CONTRADICTED_RESIDUAL in {existing, incoming}:
        return CoverageBucket.CONTRADICTED_RESIDUAL
    if CoverageBucket.PROVEN in {existing, incoming}:
        return CoverageBucket.PROVEN
    return existing


def _derived_canonical_buckets(
    batch: CanonicalBatch,
    proof_versions: tuple[ReconciliationProofVersion, ...],
) -> dict[domain.SourceEnvelopeId, CoverageBucket]:
    proofs = _index_proof_versions(batch, proof_versions)
    source_index = batch.source_index()
    derived: dict[domain.SourceEnvelopeId, CoverageBucket] = {}

    def assign(envelope_id: domain.SourceEnvelopeId, bucket: CoverageBucket) -> None:
        derived[envelope_id] = _merge_coverage_bucket(derived.get(envelope_id), bucket)

    upstream_payments: dict[domain.PaymentId, CoverageBucket] = {}
    upstream_orders: dict[domain.OrderId, CoverageBucket] = {}
    recon_by_envelope = {
        source_index[(domain.SourceKind.RAZORPAY_RECON, str(entry.id))]: entry
        for entry in batch.recon_entries
    }

    for proof in proofs.values():
        composition_bucket = (
            CoverageBucket.PROVEN
            if proof.composition.status is CompositionStatus.PROVEN
            else CoverageBucket.CONTRADICTED_RESIDUAL
        )
        for envelope_id in proof.composition.source_envelope_ids:
            assign(envelope_id, composition_bucket)
            entry = recon_by_envelope.get(envelope_id)
            if entry is not None and entry.entity_kind is domain.ReconEntityKind.PAYMENT:
                assert isinstance(entry.entity_id, domain.PaymentId)
                current = upstream_payments.get(entry.entity_id)
                upstream_payments[entry.entity_id] = _merge_coverage_bucket(
                    current, composition_bucket
                )

        if proof.bank.status is BankReceiptStatus.PROVEN:
            bank_bucket = CoverageBucket.PROVEN
        elif proof.bank.status is BankReceiptStatus.WAITING:
            bank_bucket = CoverageBucket.OPEN_UNSETTLED
        else:
            bank_bucket = CoverageBucket.CONTRADICTED_RESIDUAL
        for envelope_id in proof.bank.source_envelope_ids:
            assign(envelope_id, bank_bucket)

    for event in batch.payment_events:
        bucket = upstream_payments.get(event.payment_id)
        if bucket is None:
            continue
        envelope_id = source_index[(domain.SourceKind.RAZORPAY_EVENT, event.source_event_id)]
        assign(envelope_id, bucket)
        if event.order_id is not None:
            upstream_orders[event.order_id] = _merge_coverage_bucket(
                upstream_orders.get(event.order_id), bucket
            )

    for order in batch.orders:
        bucket = upstream_orders.get(order.id)
        if bucket is None:
            continue
        envelope_id = source_index[(domain.SourceKind.MERCHANT, str(order.id))]
        assign(envelope_id, bucket)

    for link in batch.source_links:
        if link.envelope_id in derived:
            continue
        if link.source_kind in {
            domain.SourceKind.MERCHANT,
            domain.SourceKind.RAZORPAY_EVENT,
        }:
            derived[link.envelope_id] = CoverageBucket.OPEN_UNSETTLED
        else:
            derived[link.envelope_id] = CoverageBucket.ORPHAN
    return derived


def _coverage_id(
    *,
    scope_id: domain.ReconciliationScopeId,
    manifest_ids: tuple[domain.SourceDeliveryManifestId, ...],
    batch_compilation_sha256: str,
    proof_version_ids: tuple[domain.ProofVersionId, ...],
    items: tuple[CoverageItem, ...],
) -> domain.EvidenceCoverageCertificateId:
    material = {
        "contract": GATE13_CONTROL_RULESET_VERSION,
        "scope_id": str(scope_id),
        "manifest_ids": [str(value) for value in manifest_ids],
        "batch_compilation_sha256": batch_compilation_sha256,
        "proof_version_ids": [str(value) for value in proof_version_ids],
        "items": [
            {
                "envelope_id": str(item.envelope_id),
                "source_kind": item.source_kind.value,
                "bucket": item.bucket.value,
                "amount_paise": None if item.amount is None else item.amount.amount_paise,
                "currency": None if item.amount is None else item.amount.currency.value,
            }
            for item in items
        ],
    }
    return domain.EvidenceCoverageCertificateId(_content_id("coverage_", material))


def build_evidence_coverage(
    *,
    scope: ReconciliationScope,
    batch: CanonicalBatch,
    manifests: tuple[SourceDeliveryManifest, ...],
    proof_versions: tuple[ReconciliationProofVersion, ...],
    assignments: tuple[EvidenceCoverageAssignment, ...],
) -> EvidenceCoverageCertificate:
    if not batch.source_links or batch.compilation_sha256 is None:
        raise ControlPlaneError("coverage requires a journal-backed canonical compilation")
    manifest_index = _index_manifests(manifests)
    expected: dict[domain.SourceEnvelopeId, domain.SourceKind] = {}
    for manifest in manifest_index.values():
        _validate_manifest_scope(scope, manifest)
        for envelope_id in manifest.effective_envelope_ids:
            if envelope_id in expected:
                raise ControlPlaneError("source evidence appears in multiple delivery manifests")
            expected[envelope_id] = manifest.source_kind

    for link in batch.source_links:
        link_manifest = manifest_index.get(link.source_kind)
        if link_manifest is None:
            raise ControlPlaneError(
                f"canonical evidence has no source manifest for {link.source_kind.value}"
            )
        if expected.get(link.envelope_id) != link.source_kind:
            raise ControlPlaneError("canonical evidence is outside its source delivery manifest")

    amounts = _canonical_amounts(batch, scope)
    proof_index = _index_proof_versions(batch, proof_versions)
    proof_version_ids = tuple(sorted((proof.id for proof in proof_index.values()), key=str))
    derived = _derived_canonical_buckets(batch, proof_versions)
    assigned: dict[domain.SourceEnvelopeId, CoverageBucket] = {}
    for assignment in assignments:
        if assignment.envelope_id in assigned:
            raise ControlPlaneError("one evidence record was assigned to multiple coverage buckets")
        if assignment.envelope_id not in expected:
            raise ControlPlaneError("coverage assignment references evidence outside manifests")
        if assignment.envelope_id in amounts:
            raise ControlPlaneError("canonical evidence coverage is proof-derived")
        if assignment.bucket is not CoverageBucket.QUARANTINED:
            raise ControlPlaneError(
                "non-canonical retained evidence can only be explicitly quarantined"
            )
        assigned[assignment.envelope_id] = assignment.bucket

    items = tuple(
        CoverageItem(
            envelope_id=envelope_id,
            source_kind=expected[envelope_id],
            bucket=(
                derived[envelope_id]
                if envelope_id in amounts
                else assigned.get(envelope_id, CoverageBucket.ORPHAN)
            ),
            amount=amounts.get(envelope_id),
        )
        for envelope_id in sorted(expected, key=str)
    )
    summaries: list[CoverageBucketSummary] = []
    for bucket in CoverageBucket:
        bucket_items = tuple(item for item in items if item.bucket is bucket)
        known = domain.sum_money(
            [item.amount for item in bucket_items if item.amount is not None],
            scope.currency,
        )
        summaries.append(
            CoverageBucketSummary(
                bucket=bucket,
                record_count=len(bucket_items),
                known_value=known,
                unknown_value_count=sum(item.amount is None for item in bucket_items),
            )
        )
    orphan_summary = next(
        summary for summary in summaries if summary.bucket is CoverageBucket.ORPHAN
    )
    status = (
        CoverageStatus.COMPLETE
        if orphan_summary.record_count == 0
        else CoverageStatus.FAILED
    )
    manifest_ids = tuple(
        manifest.id
        for manifest in sorted(manifest_index.values(), key=lambda row: row.source_kind.value)
    )
    certificate_id = _coverage_id(
        scope_id=scope.id,
        manifest_ids=manifest_ids,
        batch_compilation_sha256=batch.compilation_sha256,
        proof_version_ids=proof_version_ids,
        items=items,
    )
    return EvidenceCoverageCertificate(
        id=certificate_id,
        scope_id=scope.id,
        manifest_ids=manifest_ids,
        batch_compilation_sha256=batch.compilation_sha256,
        proof_version_ids=proof_version_ids,
        items=items,
        summaries=tuple(summaries),
        status=status,
        orphan_count=orphan_summary.record_count,
        orphan_known_value=orphan_summary.known_value,
        ruleset_version=GATE13_CONTROL_RULESET_VERSION,
    )


@dataclass(frozen=True, slots=True)
class BalanceControlProof:
    id: domain.BalanceControlProofId
    scope_id: domain.ReconciliationScopeId
    policy_version_id: domain.ReconciliationPolicyVersionId
    period_start: datetime
    period_end: datetime
    reporting_timezone: str
    opening_as_of: datetime
    closing_as_of: datetime
    opening_position: domain.Money
    provider_activity: domain.Money
    bank_proven_payouts: domain.Money
    authoritative_adjustments: domain.Money
    derived_closing_position: domain.Money
    observed_closing_position: domain.Money
    residual: domain.Money
    status: BalanceControlStatus
    ruleset_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, domain.BalanceControlProofId):
            raise TypeError("balance control id must be BalanceControlProofId")
        if not isinstance(self.scope_id, domain.ReconciliationScopeId):
            raise TypeError("balance scope_id must be ReconciliationScopeId")
        if not isinstance(self.policy_version_id, domain.ReconciliationPolicyVersionId):
            raise TypeError("balance policy id must be ReconciliationPolicyVersionId")
        for value, label in (
            (self.period_start, "period start"),
            (self.period_end, "period end"),
            (self.opening_as_of, "opening point-in-time"),
            (self.closing_as_of, "closing point-in-time"),
        ):
            _aware(value, label)
        if self.period_end <= self.period_start:
            raise ValueError("balance period end must be after period start")
        _text(self.reporting_timezone, "reporting timezone")
        _timezone_exists(self.reporting_timezone)
        for value, label in (
            (self.period_start, "period start"),
            (self.period_end, "period end"),
            (self.opening_as_of, "opening point-in-time"),
            (self.closing_as_of, "closing point-in-time"),
        ):
            if not _matches_timezone(value, self.reporting_timezone):
                raise ValueError(f"{label} does not align to reporting timezone")
        if self.opening_as_of != self.period_start:
            raise ValueError("opening point-in-time must equal period start")
        if self.closing_as_of != self.period_end:
            raise ValueError("closing point-in-time must equal period end")
        money_fields = (
            self.opening_position,
            self.provider_activity,
            self.bank_proven_payouts,
            self.authoritative_adjustments,
            self.derived_closing_position,
            self.observed_closing_position,
            self.residual,
        )
        if any(not isinstance(value, domain.Money) for value in money_fields):
            raise TypeError("balance control values must be Money")
        if len({value.currency for value in money_fields}) != 1:
            raise ValueError("balance control values must use one currency")
        expected_derived = (
            self.opening_position
            + self.provider_activity
            - self.bank_proven_payouts
            + self.authoritative_adjustments
        )
        if self.derived_closing_position != expected_derived:
            raise ValueError("derived closing position does not match exact balance equation")
        expected_residual = expected_derived - self.observed_closing_position
        if self.residual != expected_residual:
            raise ValueError("balance residual does not match derived minus observed closing")
        expected_status = (
            BalanceControlStatus.PROVEN
            if expected_residual.is_zero
            else BalanceControlStatus.RESIDUAL
        )
        if self.status is not expected_status:
            raise ValueError("balance status does not match exact residual")
        if self.ruleset_version != GATE13_CONTROL_RULESET_VERSION:
            raise ValueError("balance ruleset version does not match Gate 13")
        expected_id = _balance_id(
            scope_id=self.scope_id,
            policy_version_id=self.policy_version_id,
            period_start=self.period_start,
            period_end=self.period_end,
            reporting_timezone=self.reporting_timezone,
            opening_position=self.opening_position,
            provider_activity=self.provider_activity,
            bank_proven_payouts=self.bank_proven_payouts,
            authoritative_adjustments=self.authoritative_adjustments,
            observed_closing_position=self.observed_closing_position,
        )
        if self.id != expected_id:
            raise ValueError("balance control id does not match its immutable content")


def _balance_id(
    *,
    scope_id: domain.ReconciliationScopeId,
    policy_version_id: domain.ReconciliationPolicyVersionId,
    period_start: datetime,
    period_end: datetime,
    reporting_timezone: str,
    opening_position: domain.Money,
    provider_activity: domain.Money,
    bank_proven_payouts: domain.Money,
    authoritative_adjustments: domain.Money,
    observed_closing_position: domain.Money,
) -> domain.BalanceControlProofId:
    material = {
        "contract": GATE13_CONTROL_RULESET_VERSION,
        "scope_id": str(scope_id),
        "policy_version_id": str(policy_version_id),
        "period_start": _iso(period_start),
        "period_end": _iso(period_end),
        "reporting_timezone": reporting_timezone,
        "opening_position": opening_position.amount_paise,
        "provider_activity": provider_activity.amount_paise,
        "bank_proven_payouts": bank_proven_payouts.amount_paise,
        "authoritative_adjustments": authoritative_adjustments.amount_paise,
        "observed_closing_position": observed_closing_position.amount_paise,
        "currency": opening_position.currency.value,
    }
    return domain.BalanceControlProofId(_content_id("balctrl_", material))


def build_balance_control(
    *,
    scope: ReconciliationScope,
    policy: ReconciliationPolicyVersion,
    period_start: datetime,
    period_end: datetime,
    reporting_timezone: str,
    opening_as_of: datetime,
    closing_as_of: datetime,
    opening_position: domain.Money,
    provider_activity: domain.Money,
    bank_proven_payouts: domain.Money,
    authoritative_adjustments: domain.Money,
    observed_closing_position: domain.Money,
) -> BalanceControlProof:
    for value, label in (
        (period_start, "period start"),
        (period_end, "period end"),
        (opening_as_of, "opening point-in-time"),
        (closing_as_of, "closing point-in-time"),
    ):
        _aware(value, label)
    if period_end <= period_start:
        raise ControlPlaneError("balance period end must be after period start")
    if reporting_timezone != policy.reporting_timezone:
        raise ControlPlaneError("balance reporting timezone does not match policy")
    _timezone_exists(reporting_timezone)
    for value, label in (
        (period_start, "period start"),
        (period_end, "period end"),
        (opening_as_of, "opening point-in-time"),
        (closing_as_of, "closing point-in-time"),
    ):
        if not _matches_timezone(value, reporting_timezone):
            raise ControlPlaneError(f"{label} does not align to reporting timezone")
    if opening_as_of != period_start:
        raise ControlPlaneError("opening point-in-time must equal period start")
    if closing_as_of != period_end:
        raise ControlPlaneError("closing point-in-time must equal period end")
    money_fields = (
        opening_position,
        provider_activity,
        bank_proven_payouts,
        authoritative_adjustments,
        observed_closing_position,
    )
    if any(not isinstance(value, domain.Money) for value in money_fields):
        raise TypeError("balance control values must be Money")
    if any(value.currency != scope.currency for value in money_fields):
        raise ControlPlaneError("balance control currency crosses reconciliation scope")
    derived = (
        opening_position
        + provider_activity
        - bank_proven_payouts
        + authoritative_adjustments
    )
    residual = derived - observed_closing_position
    status = BalanceControlStatus.PROVEN if residual.is_zero else BalanceControlStatus.RESIDUAL
    proof_id = _balance_id(
        scope_id=scope.id,
        policy_version_id=policy.id,
        period_start=period_start,
        period_end=period_end,
        reporting_timezone=reporting_timezone,
        opening_position=opening_position,
        provider_activity=provider_activity,
        bank_proven_payouts=bank_proven_payouts,
        authoritative_adjustments=authoritative_adjustments,
        observed_closing_position=observed_closing_position,
    )
    return BalanceControlProof(
        id=proof_id,
        scope_id=scope.id,
        policy_version_id=policy.id,
        period_start=period_start,
        period_end=period_end,
        reporting_timezone=reporting_timezone,
        opening_as_of=opening_as_of,
        closing_as_of=closing_as_of,
        opening_position=opening_position,
        provider_activity=provider_activity,
        bank_proven_payouts=bank_proven_payouts,
        authoritative_adjustments=authoritative_adjustments,
        derived_closing_position=derived,
        observed_closing_position=observed_closing_position,
        residual=residual,
        status=status,
        ruleset_version=GATE13_CONTROL_RULESET_VERSION,
    )


@dataclass(frozen=True, slots=True)
class CloseReadinessCertificate:
    id: domain.CloseReadinessCertificateId
    policy_version_id: domain.ReconciliationPolicyVersionId
    manifest_ids: tuple[domain.SourceDeliveryManifestId, ...]
    proof_version_ids: tuple[domain.ProofVersionId, ...]
    coverage_certificate_id: domain.EvidenceCoverageCertificateId
    balance_control_id: domain.BalanceControlProofId
    status: CloseReadinessStatus
    reason_codes: tuple[str, ...]
    ruleset_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, domain.CloseReadinessCertificateId):
            raise TypeError("close readiness id must be CloseReadinessCertificateId")
        if not isinstance(self.policy_version_id, domain.ReconciliationPolicyVersionId):
            raise TypeError("close readiness policy id must be ReconciliationPolicyVersionId")
        if any(
            not isinstance(value, domain.SourceDeliveryManifestId)
            for value in self.manifest_ids
        ):
            raise TypeError("close readiness manifest ids must be SourceDeliveryManifestId")
        if len(set(self.manifest_ids)) != len(self.manifest_ids):
            raise ValueError("close readiness manifest ids must be unique")
        if any(not isinstance(value, domain.ProofVersionId) for value in self.proof_version_ids):
            raise TypeError("close readiness proof ids must be ProofVersionId")
        if tuple(sorted(set(self.proof_version_ids), key=str)) != self.proof_version_ids:
            raise ValueError("close readiness proof ids must be unique and canonical-sorted")
        if not isinstance(self.coverage_certificate_id, domain.EvidenceCoverageCertificateId):
            raise TypeError("close readiness coverage id must be EvidenceCoverageCertificateId")
        if not isinstance(self.balance_control_id, domain.BalanceControlProofId):
            raise TypeError("close readiness balance id must be BalanceControlProofId")
        if not isinstance(self.status, CloseReadinessStatus):
            raise TypeError("close readiness status must be CloseReadinessStatus")
        if tuple(sorted(set(self.reason_codes))) != self.reason_codes:
            raise ValueError("close readiness reasons must be unique and canonical-sorted")
        expected_status = (
            CloseReadinessStatus.READY
            if not self.reason_codes
            else CloseReadinessStatus.NOT_READY
        )
        if self.status is not expected_status:
            raise ValueError("close readiness status does not match reason codes")
        if self.ruleset_version != GATE13_CONTROL_RULESET_VERSION:
            raise ValueError("close readiness ruleset version does not match Gate 13")
        expected_id = _close_id(
            policy_version_id=self.policy_version_id,
            manifest_ids=self.manifest_ids,
            proof_version_ids=self.proof_version_ids,
            coverage_certificate_id=self.coverage_certificate_id,
            balance_control_id=self.balance_control_id,
            status=self.status,
            reason_codes=self.reason_codes,
        )
        if self.id != expected_id:
            raise ValueError("close readiness id does not match its immutable content")


def _close_id(
    *,
    policy_version_id: domain.ReconciliationPolicyVersionId,
    manifest_ids: tuple[domain.SourceDeliveryManifestId, ...],
    proof_version_ids: tuple[domain.ProofVersionId, ...],
    coverage_certificate_id: domain.EvidenceCoverageCertificateId,
    balance_control_id: domain.BalanceControlProofId,
    status: CloseReadinessStatus,
    reason_codes: tuple[str, ...],
) -> domain.CloseReadinessCertificateId:
    material = {
        "contract": GATE13_CONTROL_RULESET_VERSION,
        "policy_version_id": str(policy_version_id),
        "manifest_ids": [str(value) for value in manifest_ids],
        "proof_version_ids": [str(value) for value in proof_version_ids],
        "coverage_certificate_id": str(coverage_certificate_id),
        "balance_control_id": str(balance_control_id),
        "status": status.value,
        "reason_codes": list(reason_codes),
    }
    return domain.CloseReadinessCertificateId(_content_id("close_", material))


def build_close_readiness(
    *,
    policy: ReconciliationPolicyVersion,
    manifests: tuple[SourceDeliveryManifest, ...],
    proof_versions: tuple[ReconciliationProofVersion, ...],
    coverage: EvidenceCoverageCertificate,
    balance: BalanceControlProof,
) -> CloseReadinessCertificate:
    if not manifests:
        raise ControlPlaneError("close readiness requires source delivery manifests")
    manifest_index = _index_manifests(manifests)
    manifest_ids = tuple(
        manifest.id
        for manifest in sorted(manifest_index.values(), key=lambda row: row.source_kind.value)
    )
    proof_version_ids = tuple(sorted((proof.id for proof in proof_versions), key=str))
    if len(set(proof_version_ids)) != len(proof_version_ids):
        raise ControlPlaneError("close readiness received duplicate proof versions")
    if coverage.manifest_ids != manifest_ids:
        raise ControlPlaneError("coverage certificate does not bind close source manifests")
    if coverage.proof_version_ids != proof_version_ids:
        raise ControlPlaneError("coverage certificate does not bind close proof versions")
    if coverage.scope_id != balance.scope_id:
        raise ControlPlaneError("coverage and balance controls belong to different scopes")
    if balance.policy_version_id != policy.id:
        raise ControlPlaneError("balance control belongs to another policy")
    for manifest in manifest_index.values():
        if (
            manifest.period_start != balance.period_start
            or manifest.period_end != balance.period_end
        ):
            raise ControlPlaneError("close source period does not align with balance control")
        if manifest.reporting_timezone != balance.reporting_timezone:
            raise ControlPlaneError("close source timezone does not align with balance control")
    reasons: set[str] = set()
    for source_kind in policy.required_source_kinds:
        required_manifest = manifest_index.get(source_kind)
        if required_manifest is None:
            reasons.add(f"SOURCE_MANIFEST_MISSING:{source_kind.value}")
            continue
        if required_manifest.reporting_timezone != policy.reporting_timezone:
            raise ControlPlaneError("source manifest reporting timezone does not match policy")
        if required_manifest.completeness is not SourceCompleteness.COMPLETE:
            reasons.add(
                f"SOURCE_{required_manifest.completeness.value.upper()}:{source_kind.value}"
            )

    if coverage.status is CoverageStatus.FAILED:
        reasons.add("ORPHAN_EVIDENCE")
    if coverage.summary(CoverageBucket.QUARANTINED).record_count:
        reasons.add("QUARANTINED_EVIDENCE")
    if balance.status is BalanceControlStatus.RESIDUAL:
        reasons.add("BALANCE_RESIDUAL")
    if any(
        proof.status is not ReconciliationStatus.PROVEN_RECONCILED
        for proof in proof_versions
    ):
        reasons.add("SETTLEMENT_PROOF_NOT_GREEN")

    bank_manifest = manifest_index.get(domain.SourceKind.BANK)
    if (
        any(proof.bank.status is BankReceiptStatus.WAITING for proof in proof_versions)
        and bank_manifest is not None
        and bank_manifest.completeness is SourceCompleteness.COMPLETE
    ):
        reasons.add("BANK_CREDIT_MISSING")

    reason_codes = tuple(sorted(reasons))
    status = CloseReadinessStatus.READY if not reason_codes else CloseReadinessStatus.NOT_READY
    certificate_id = _close_id(
        policy_version_id=policy.id,
        manifest_ids=manifest_ids,
        proof_version_ids=proof_version_ids,
        coverage_certificate_id=coverage.id,
        balance_control_id=balance.id,
        status=status,
        reason_codes=reason_codes,
    )
    return CloseReadinessCertificate(
        id=certificate_id,
        policy_version_id=policy.id,
        manifest_ids=manifest_ids,
        proof_version_ids=proof_version_ids,
        coverage_certificate_id=coverage.id,
        balance_control_id=balance.id,
        status=status,
        reason_codes=reason_codes,
        ruleset_version=GATE13_CONTROL_RULESET_VERSION,
    )


@dataclass(frozen=True, slots=True)
class ReconciliationRun:
    id: domain.ReconciliationRunId
    scope_id: domain.ReconciliationScopeId
    policy_version_id: domain.ReconciliationPolicyVersionId
    source_manifest_ids: tuple[domain.SourceDeliveryManifestId, ...]
    period_start: datetime
    period_end: datetime
    reporting_timezone: str
    canonical_compilation_sha256: str
    proof_ruleset_versions: tuple[str, ...]
    knowledge_cutoff: datetime
    code_build_sha: str | None
    input_sha256: str
    output_sha256: str
    proof_version_ids: tuple[domain.ProofVersionId, ...]
    coverage_certificate_id: domain.EvidenceCoverageCertificateId
    balance_control_id: domain.BalanceControlProofId
    close_readiness_id: domain.CloseReadinessCertificateId
    outcome: CloseReadinessStatus
    started_at: datetime
    completed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.id, domain.ReconciliationRunId):
            raise TypeError("run id must be ReconciliationRunId")
        if not isinstance(self.scope_id, domain.ReconciliationScopeId):
            raise TypeError("run scope_id must be ReconciliationScopeId")
        if not isinstance(self.policy_version_id, domain.ReconciliationPolicyVersionId):
            raise TypeError("run policy id must be ReconciliationPolicyVersionId")
        if any(
            not isinstance(value, domain.SourceDeliveryManifestId)
            for value in self.source_manifest_ids
        ):
            raise TypeError("run source manifest ids must be SourceDeliveryManifestId")
        if len(set(self.source_manifest_ids)) != len(self.source_manifest_ids):
            raise ValueError("run source manifest ids must be unique")
        _aware(self.period_start, "run period start")
        _aware(self.period_end, "run period end")
        if self.period_end <= self.period_start:
            raise ValueError("run period end must be after period start")
        _text(self.reporting_timezone, "run reporting timezone")
        _timezone_exists(self.reporting_timezone)
        if not _matches_timezone(self.period_start, self.reporting_timezone):
            raise ValueError("run period start does not align to reporting timezone")
        if not _matches_timezone(self.period_end, self.reporting_timezone):
            raise ValueError("run period end does not align to reporting timezone")
        _require_sha256(self.canonical_compilation_sha256, "canonical compilation hash")
        if self.proof_ruleset_versions != _RUN_RULESET_VERSIONS:
            raise ValueError("run proof ruleset versions do not match audited rulesets")
        _aware(self.knowledge_cutoff, "run knowledge cutoff")
        _aware(self.started_at, "run started at")
        _aware(self.completed_at, "run completed at")
        if self.started_at < self.knowledge_cutoff:
            raise ValueError("run cannot start before its knowledge cutoff")
        if self.completed_at < self.started_at:
            raise ValueError("run cannot complete before it starts")
        if self.code_build_sha is not None:
            _text(self.code_build_sha, "code build sha")
        _require_sha256(self.input_sha256, "run input hash")
        _require_sha256(self.output_sha256, "run output hash")
        if any(not isinstance(value, domain.ProofVersionId) for value in self.proof_version_ids):
            raise TypeError("run proof ids must be ProofVersionId")
        if tuple(sorted(set(self.proof_version_ids), key=str)) != self.proof_version_ids:
            raise ValueError("run proof ids must be unique and canonical-sorted")
        if not isinstance(self.coverage_certificate_id, domain.EvidenceCoverageCertificateId):
            raise TypeError("run coverage id must be EvidenceCoverageCertificateId")
        if not isinstance(self.balance_control_id, domain.BalanceControlProofId):
            raise TypeError("run balance id must be BalanceControlProofId")
        if not isinstance(self.close_readiness_id, domain.CloseReadinessCertificateId):
            raise TypeError("run close readiness id must be CloseReadinessCertificateId")
        if not isinstance(self.outcome, CloseReadinessStatus):
            raise TypeError("run outcome must be CloseReadinessStatus")
        expected_input = _sha256(
            _run_input_material_from_values(
                scope_id=self.scope_id,
                policy_version_id=self.policy_version_id,
                source_manifest_ids=self.source_manifest_ids,
                period_start=self.period_start,
                period_end=self.period_end,
                reporting_timezone=self.reporting_timezone,
                canonical_compilation_sha256=self.canonical_compilation_sha256,
                proof_ruleset_versions=self.proof_ruleset_versions,
                knowledge_cutoff=self.knowledge_cutoff,
                code_build_sha=self.code_build_sha,
            )
        )
        if self.input_sha256 != expected_input:
            raise ValueError("run input hash does not match immutable run inputs")
        expected_id = domain.ReconciliationRunId(f"run_{expected_input[:24]}")
        if self.id != expected_id:
            raise ValueError("run id does not match immutable run inputs")
        expected_output = _run_output_sha256(
            proof_version_ids=self.proof_version_ids,
            coverage_certificate_id=self.coverage_certificate_id,
            balance_control_id=self.balance_control_id,
            close_readiness_id=self.close_readiness_id,
            outcome=self.outcome,
        )
        if self.output_sha256 != expected_output:
            raise ValueError("run output hash does not match immutable run outputs")


def _run_input_material_from_values(
    *,
    scope_id: domain.ReconciliationScopeId,
    policy_version_id: domain.ReconciliationPolicyVersionId,
    source_manifest_ids: tuple[domain.SourceDeliveryManifestId, ...],
    period_start: datetime,
    period_end: datetime,
    reporting_timezone: str,
    canonical_compilation_sha256: str,
    proof_ruleset_versions: tuple[str, ...],
    knowledge_cutoff: datetime,
    code_build_sha: str | None,
) -> dict[str, object]:
    return {
        "scope_id": str(scope_id),
        "policy_version_id": str(policy_version_id),
        "source_manifest_ids": [str(value) for value in source_manifest_ids],
        "period_start": _iso(period_start),
        "period_end": _iso(period_end),
        "reporting_timezone": reporting_timezone,
        "canonical_compilation_sha256": canonical_compilation_sha256,
        "proof_ruleset_versions": list(proof_ruleset_versions),
        "knowledge_cutoff": _iso(knowledge_cutoff),
        "code_build_sha": code_build_sha,
    }


def _run_input_material(
    *,
    scope: ReconciliationScope,
    policy: ReconciliationPolicyVersion,
    manifests: tuple[SourceDeliveryManifest, ...],
    batch: CanonicalBatch,
    knowledge_cutoff: datetime,
    code_build_sha: str | None,
) -> dict[str, object]:
    assert batch.compilation_sha256 is not None
    return _run_input_material_from_values(
        scope_id=scope.id,
        policy_version_id=policy.id,
        source_manifest_ids=tuple(manifest.id for manifest in manifests),
        period_start=manifests[0].period_start,
        period_end=manifests[0].period_end,
        reporting_timezone=policy.reporting_timezone,
        canonical_compilation_sha256=batch.compilation_sha256,
        proof_ruleset_versions=_RUN_RULESET_VERSIONS,
        knowledge_cutoff=knowledge_cutoff,
        code_build_sha=code_build_sha,
    )


def _run_output_sha256(
    *,
    proof_version_ids: tuple[domain.ProofVersionId, ...],
    coverage_certificate_id: domain.EvidenceCoverageCertificateId,
    balance_control_id: domain.BalanceControlProofId,
    close_readiness_id: domain.CloseReadinessCertificateId,
    outcome: CloseReadinessStatus,
) -> str:
    return _sha256(
        {
            "proof_version_ids": [str(value) for value in proof_version_ids],
            "coverage_certificate_id": str(coverage_certificate_id),
            "balance_control_id": str(balance_control_id),
            "close_readiness_id": str(close_readiness_id),
            "outcome": outcome.value,
        }
    )


def build_reconciliation_run(
    *,
    scope: ReconciliationScope,
    policy: ReconciliationPolicyVersion,
    manifests: tuple[SourceDeliveryManifest, ...],
    batch: CanonicalBatch,
    proof_versions: tuple[ReconciliationProofVersion, ...],
    coverage: EvidenceCoverageCertificate,
    balance: BalanceControlProof,
    close_readiness: CloseReadinessCertificate,
    knowledge_cutoff: datetime,
    started_at: datetime,
    completed_at: datetime,
    code_build_sha: str | None = None,
) -> ReconciliationRun:
    _aware(knowledge_cutoff, "knowledge cutoff")
    _aware(started_at, "started at")
    _aware(completed_at, "completed at")
    if started_at < knowledge_cutoff:
        raise ControlPlaneError("run cannot start before its knowledge cutoff")
    if completed_at < started_at:
        raise ControlPlaneError("run cannot complete before it starts")
    if code_build_sha is not None:
        code_build_sha = _text(code_build_sha, "code build sha")
    if not batch.source_links or batch.compilation_sha256 is None:
        raise ControlPlaneError("run requires a journal-backed canonical compilation")
    if not manifests:
        raise ControlPlaneError("run requires explicit source delivery manifests")

    manifest_index = _index_manifests(manifests)
    missing_required = set(policy.required_source_kinds) - set(manifest_index)
    if missing_required:
        missing = ",".join(sorted(kind.value for kind in missing_required))
        raise ControlPlaneError(f"run is missing required source manifests: {missing}")
    ordered_manifests = tuple(
        sorted(manifest_index.values(), key=lambda row: row.source_kind.value)
    )
    period_start = ordered_manifests[0].period_start
    period_end = ordered_manifests[0].period_end
    for manifest in ordered_manifests:
        _validate_manifest_scope(scope, manifest)
        if manifest.reporting_timezone != policy.reporting_timezone:
            raise ControlPlaneError("source manifest reporting timezone does not match policy")
        if manifest.period_start != period_start or manifest.period_end != period_end:
            raise ControlPlaneError("run source manifests do not share one reporting period")
        if manifest.received_at is not None and manifest.received_at > knowledge_cutoff:
            raise ControlPlaneError("run includes source delivery after knowledge cutoff")
        if manifest.evaluated_at > completed_at:
            raise ControlPlaneError("run source manifest was evaluated after run completion")

    proof_index = _index_proof_versions(batch, proof_versions)
    proof_ids = tuple(sorted((proof.id for proof in proof_index.values()), key=str))

    effective_envelopes = {
        source_kind: frozenset(manifest.effective_envelope_ids)
        for source_kind, manifest in manifest_index.items()
    }
    for link in batch.source_links:
        link_manifest = manifest_index.get(link.source_kind)
        if (
            link_manifest is None
            or link.envelope_id not in effective_envelopes[link.source_kind]
        ):
            raise ControlPlaneError("run canonical evidence is outside source delivery manifests")

    if coverage.scope_id != scope.id:
        raise ControlPlaneError("coverage certificate belongs to another scope")
    expected_manifest_ids = tuple(manifest.id for manifest in ordered_manifests)
    if coverage.manifest_ids != expected_manifest_ids:
        raise ControlPlaneError("coverage certificate does not bind the run source manifests")
    if coverage.batch_compilation_sha256 != batch.compilation_sha256:
        raise ControlPlaneError("coverage certificate does not bind the canonical compilation")
    if coverage.proof_version_ids != proof_ids:
        raise ControlPlaneError("coverage certificate does not bind the run proof versions")
    if balance.scope_id != scope.id or balance.policy_version_id != policy.id:
        raise ControlPlaneError("balance control belongs to another scope or policy")
    if balance.period_start != period_start or balance.period_end != period_end:
        raise ControlPlaneError("balance control period does not align with run period")
    if balance.reporting_timezone != policy.reporting_timezone:
        raise ControlPlaneError("balance control timezone does not align with policy")
    if close_readiness.policy_version_id != policy.id:
        raise ControlPlaneError("close readiness belongs to another policy")
    if close_readiness.manifest_ids != expected_manifest_ids:
        raise ControlPlaneError("close readiness does not bind the run source manifests")
    if close_readiness.proof_version_ids != proof_ids:
        raise ControlPlaneError("close readiness does not bind the run proof versions")
    if close_readiness.coverage_certificate_id != coverage.id:
        raise ControlPlaneError("close readiness does not bind the coverage certificate")
    if close_readiness.balance_control_id != balance.id:
        raise ControlPlaneError("close readiness does not bind the balance control")

    batch_envelope_ids = {link.envelope_id for link in batch.source_links}
    for proof in proof_index.values():
        if proof.knowledge_cutoff > knowledge_cutoff:
            raise ControlPlaneError("settlement proof knows evidence after run cutoff")
        if proof.generated_at > completed_at:
            raise ControlPlaneError("settlement proof was generated after run completion")
        if not set(proof.source_envelope_ids).issubset(batch_envelope_ids):
            raise ControlPlaneError("settlement proof cites evidence outside run compilation")

    input_material = _run_input_material(
        scope=scope,
        policy=policy,
        manifests=ordered_manifests,
        batch=batch,
        knowledge_cutoff=knowledge_cutoff,
        code_build_sha=code_build_sha,
    )
    input_sha256 = _sha256(input_material)
    output_sha256 = _run_output_sha256(
        proof_version_ids=proof_ids,
        coverage_certificate_id=coverage.id,
        balance_control_id=balance.id,
        close_readiness_id=close_readiness.id,
        outcome=close_readiness.status,
    )
    run_id = domain.ReconciliationRunId(f"run_{input_sha256[:24]}")
    return ReconciliationRun(
        id=run_id,
        scope_id=scope.id,
        policy_version_id=policy.id,
        source_manifest_ids=expected_manifest_ids,
        period_start=period_start,
        period_end=period_end,
        reporting_timezone=policy.reporting_timezone,
        canonical_compilation_sha256=batch.compilation_sha256,
        proof_ruleset_versions=_RUN_RULESET_VERSIONS,
        knowledge_cutoff=knowledge_cutoff,
        code_build_sha=code_build_sha,
        input_sha256=input_sha256,
        output_sha256=output_sha256,
        proof_version_ids=proof_ids,
        coverage_certificate_id=coverage.id,
        balance_control_id=balance.id,
        close_readiness_id=close_readiness.id,
        outcome=close_readiness.status,
        started_at=started_at,
        completed_at=completed_at,
    )
