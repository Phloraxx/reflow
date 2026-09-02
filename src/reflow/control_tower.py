from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from . import domain
from .evaluation.benchmark_artifacts import load_verified_benchmark
from .persistence import ArtifactKind, CurrentPointer, PointerKind, StoredArtifact

__all__ = [
    "BankProofView",
    "CaseFileView",
    "CaseObservationView",
    "CompositionProofView",
    "ControlTowerIntegrityError",
    "ControlTowerNotFound",
    "ControlTowerReader",
    "DispositionView",
    "EvaluationArtifactView",
    "EvaluationLabView",
    "ExceptionQueueItem",
    "MoneyView",
    "OverviewView",
    "ProofDetailView",
    "ProofListItem",
    "ProofStatusSummary",
    "ReadArtifactStore",
    "RunOverviewView",
    "SourceLabItem",
    "SourceStateView",
]


class ControlTowerIntegrityError(ValueError):
    """Persisted Gate 13-17 state cannot support a trustworthy read projection."""


class ControlTowerNotFound(LookupError):
    """A requested scoped immutable artifact is unavailable."""


class ReadArtifactStore(Protocol):
    def artifact(self, artifact_id: str) -> StoredArtifact | None: ...

    def current(self, *, kind: PointerKind, stream_key: str) -> CurrentPointer | None: ...

    def artifacts(
        self,
        *,
        kind: ArtifactKind,
        scope_id: domain.ReconciliationScopeId | None,
        limit: int = 100,
    ) -> tuple[StoredArtifact, ...]: ...


@dataclass(frozen=True, slots=True)
class MoneyView:
    amount_paise: int
    currency: str
    display: str


@dataclass(frozen=True, slots=True)
class ProofStatusSummary:
    status: str
    count: int
    amount: MoneyView


@dataclass(frozen=True, slots=True)
class SourceLabItem:
    manifest_id: str
    source_kind: str
    completeness: str
    received_late: bool
    delivery_mode: str
    expected_by: str
    received_at: str | None
    watermark_at: str | None
    adapter_version: str
    schema_fingerprint: str
    delivered_envelope_count: int
    effective_envelope_count: int


@dataclass(frozen=True, slots=True)
class RunOverviewView:
    run_id: str
    outcome: str
    period_start: str
    period_end: str
    reporting_timezone: str
    knowledge_cutoff: str
    completed_at: str
    code_build_sha: str | None
    close_readiness_id: str
    close_status: str
    close_reason_codes: tuple[str, ...]
    coverage_certificate_id: str
    coverage_status: str
    orphan_count: int
    orphan_known_value: MoneyView
    balance_control_id: str
    balance_status: str
    balance_residual: MoneyView


@dataclass(frozen=True, slots=True)
class OverviewView:
    scope_id: str
    has_current_run: bool
    run: RunOverviewView | None
    proof_status: tuple[ProofStatusSummary, ...]
    sources: tuple[SourceLabItem, ...]
    active_exception_count: int
    active_exception_value: MoneyView | None


@dataclass(frozen=True, slots=True)
class ProofListItem:
    proof_id: str
    settlement_id: str
    version: int
    status: str
    settlement_amount: MoneyView
    reason_codes: tuple[str, ...]
    knowledge_cutoff: str
    generated_at: str
    reopened: bool


@dataclass(frozen=True, slots=True)
class CompositionProofView:
    status: str
    settlement_amount: MoneyView
    observed_composition: MoneyView
    residual: MoneyView
    component_ids: tuple[str, ...]
    source_envelope_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BankProofView:
    status: str
    settlement_utr: str | None
    expected_amount: MoneyView
    observed_bank_credit: MoneyView
    residual: MoneyView
    bank_entry_ids: tuple[str, ...]
    source_envelope_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProofDetailView:
    proof_id: str
    settlement_id: str
    version: int
    status: str
    reason_codes: tuple[str, ...]
    reopened: bool
    prior_version_id: str | None
    knowledge_cutoff: str
    generated_at: str
    source_envelope_ids: tuple[str, ...]
    composition: CompositionProofView
    bank: BankProofView
    version_timeline: tuple[ProofListItem, ...]


@dataclass(frozen=True, slots=True)
class SourceStateView:
    source_kind: str
    completeness: str
    received_late: bool
    manifest_id: str


@dataclass(frozen=True, slots=True)
class ExceptionQueueItem:
    case_id: str
    settlement_id: str
    latest_observation_id: str
    latest_proof_version_id: str
    financial_status: str
    materiality_band: str
    affected_amount: MoneyView
    workflow_status: str
    resolution: str | None
    owner: str | None
    incident_fingerprint_id: str
    incident_cluster_id: str | None
    source_blockers: tuple[str, ...]
    first_seen_at: str
    last_seen_at: str
    age_seconds: int
    observation_count: int
    disposition_count: int
    superseded_by_case_id: str | None
    is_active: bool


@dataclass(frozen=True, slots=True)
class CaseObservationView:
    observation_id: str
    run_id: str
    proof_version_id: str
    financial_status: str
    reason_codes: tuple[str, ...]
    affected_amount: MoneyView
    materiality_band: str
    incident_fingerprint_id: str
    source_states: tuple[SourceStateView, ...]
    observed_at: str


@dataclass(frozen=True, slots=True)
class DispositionView:
    disposition_id: str
    sequence: int
    actor_id: str
    occurred_at: str
    kind: str
    owner: str | None
    note: str | None


@dataclass(frozen=True, slots=True)
class InvestigationView:
    investigation_id: str
    status: str
    next_action: str
    hypothesis: str | None
    citations: tuple[str, ...]
    request_source_kind: str | None
    rejection_reason: str | None
    as_of: str
    trace_count: int


@dataclass(frozen=True, slots=True)
class CaseFileView:
    case: ExceptionQueueItem
    observations: tuple[CaseObservationView, ...]
    dispositions: tuple[DispositionView, ...]
    proof: ProofDetailView
    investigation: InvestigationView | None


@dataclass(frozen=True, slots=True)
class EvaluationArtifactView:
    filename: str
    schema_version: str
    artifact_sha256: str
    config: Mapping[str, object]
    hardware: Mapping[str, object]
    metrics: Mapping[str, object]
    status_counts: Mapping[str, object] | None


@dataclass(frozen=True, slots=True)
class EvaluationLabView:
    artifacts: tuple[EvaluationArtifactView, ...]


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ControlTowerIntegrityError(f"{label} must be an object")
    return value


def _sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, (list, tuple)):
        raise ControlTowerIntegrityError(f"{label} must be a sequence")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ControlTowerIntegrityError(f"{label} must be non-empty trimmed text")
    return value


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _text(value, label)


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ControlTowerIntegrityError(f"{label} must be an integer")
    return value


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ControlTowerIntegrityError(f"{label} must be boolean")
    return value


def _strings(value: object, label: str) -> tuple[str, ...]:
    return tuple(_text(item, label) for item in _sequence(value, label))


def _timestamp(value: object, label: str) -> datetime:
    raw = _text(value, label)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ControlTowerIntegrityError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ControlTowerIntegrityError(f"{label} must be timezone-aware")
    return parsed


def _timestamp_text(value: object, label: str) -> str:
    return _timestamp(value, label).isoformat()


def _money(value: object, label: str) -> MoneyView:
    payload = _mapping(value, label)
    amount = _integer(payload.get("amount_paise"), f"{label}.amount_paise")
    currency = _text(payload.get("currency"), f"{label}.currency")
    sign = "-" if amount < 0 else ""
    whole, paise = divmod(abs(amount), 100)
    prefix = "₹" if currency == "INR" else f"{currency} "
    return MoneyView(
        amount_paise=amount,
        currency=currency,
        display=f"{sign}{prefix}{whole:,}.{paise:02d}",
    )


def _sum_money(values: Sequence[MoneyView], label: str) -> MoneyView:
    if not values:
        raise ControlTowerIntegrityError(f"{label} cannot aggregate an empty money set")
    currencies = {value.currency for value in values}
    if len(currencies) != 1:
        raise ControlTowerIntegrityError(f"{label} cannot aggregate mixed currencies")
    currency = next(iter(currencies))
    return _money(
        {"amount_paise": sum(value.amount_paise for value in values), "currency": currency},
        label,
    )


def _scope_payload_matches(
    artifact: StoredArtifact, scope_id: domain.ReconciliationScopeId
) -> None:
    if artifact.scope_id != scope_id:
        raise ControlTowerIntegrityError(
            f"artifact {artifact.artifact_id} belongs to another reconciliation scope"
        )
    payload_scope = artifact.payload.get("scope_id")
    if payload_scope is not None and payload_scope != str(scope_id):
        raise ControlTowerIntegrityError(
            f"artifact {artifact.artifact_id} payload scope disagrees with storage scope"
        )
    payload_id = artifact.payload.get("id")
    if payload_id is not None and payload_id != artifact.artifact_id:
        raise ControlTowerIntegrityError(
            f"artifact {artifact.artifact_id} payload identity disagrees with storage identity"
        )


def _artifact_time(artifact: StoredArtifact, payload_key: str) -> datetime:
    if artifact.observed_at is not None:
        return artifact.observed_at
    value = artifact.payload.get(payload_key)
    if value is None:
        return datetime.min.replace(tzinfo=UTC)
    return _timestamp(value, f"{artifact.artifact_id}.{payload_key}")


_MATERIALITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_PROOF_STATUS_ORDER = (
    "proven_reconciled",
    "pending_bank_credit",
    "residual",
    "incomplete",
    "contradicted",
)


class ControlTowerReader:
    def __init__(
        self,
        store: ReadArtifactStore,
        *,
        evaluation_root: Path,
        final_evaluation_summary: Path | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._evaluation_root = evaluation_root
        self._final_evaluation_summary = final_evaluation_summary
        self._now = now or (lambda: datetime.now(UTC))

    def _list(
        self,
        kind: ArtifactKind,
        scope_id: domain.ReconciliationScopeId,
    ) -> tuple[StoredArtifact, ...]:
        artifacts = self._store.artifacts(kind=kind, scope_id=scope_id, limit=10_000)
        for artifact in artifacts:
            if artifact.kind is not kind:
                raise ControlTowerIntegrityError("artifact query returned the wrong artifact kind")
            _scope_payload_matches(artifact, scope_id)
        return artifacts

    def _artifact(
        self,
        artifact_id: str,
        kind: ArtifactKind,
        scope_id: domain.ReconciliationScopeId,
    ) -> StoredArtifact:
        artifact = self._store.artifact(artifact_id)
        if artifact is None:
            raise ControlTowerNotFound(f"unknown {kind.value} artifact {artifact_id}")
        if artifact.kind is not kind:
            raise ControlTowerIntegrityError(
                f"artifact {artifact_id} is {artifact.kind.value}, expected {kind.value}"
            )
        _scope_payload_matches(artifact, scope_id)
        return artifact

    def _latest_run_artifact(self, scope_id: domain.ReconciliationScopeId) -> StoredArtifact | None:
        pointer = self._store.current(kind=PointerKind.LATEST_RUN, stream_key=str(scope_id))
        if pointer is None:
            return None
        if pointer.kind is not PointerKind.LATEST_RUN or pointer.stream_key != str(scope_id):
            raise ControlTowerIntegrityError("latest run pointer does not match requested scope")
        return self._artifact(pointer.artifact_id, ArtifactKind.RECONCILIATION_RUN, scope_id)

    @staticmethod
    def _source_item(artifact: StoredArtifact) -> SourceLabItem:
        p = artifact.payload
        delivered = _strings(p.get("delivered_envelope_ids"), "delivered envelope IDs")
        effective = _strings(p.get("effective_envelope_ids"), "effective envelope IDs")
        return SourceLabItem(
            manifest_id=artifact.artifact_id,
            source_kind=_text(p.get("source_kind"), "source kind"),
            completeness=_text(p.get("completeness"), "source completeness"),
            received_late=_boolean(p.get("received_late"), "source received_late"),
            delivery_mode=_text(p.get("delivery_mode"), "source delivery_mode"),
            expected_by=_timestamp_text(p.get("expected_by"), "source expected_by"),
            received_at=(
                None
                if p.get("received_at") is None
                else _timestamp_text(p.get("received_at"), "source received_at")
            ),
            watermark_at=(
                None
                if p.get("watermark_at") is None
                else _timestamp_text(p.get("watermark_at"), "source watermark_at")
            ),
            adapter_version=_text(p.get("adapter_version"), "source adapter version"),
            schema_fingerprint=_text(p.get("schema_fingerprint"), "source schema fingerprint"),
            delivered_envelope_count=len(delivered),
            effective_envelope_count=len(effective),
        )

    def sources(self, scope_id: domain.ReconciliationScopeId) -> tuple[SourceLabItem, ...]:
        items = tuple(
            self._source_item(artifact)
            for artifact in self._list(ArtifactKind.SOURCE_DELIVERY_MANIFEST, scope_id)
        )
        return tuple(sorted(items, key=lambda item: (item.source_kind, item.manifest_id)))

    def _scoped_run_proof_ids(
        self, scope_id: domain.ReconciliationScopeId
    ) -> frozenset[str]:
        proof_ids: set[str] = set()
        for run in self._list(ArtifactKind.RECONCILIATION_RUN, scope_id):
            proof_ids.update(_strings(run.payload.get("proof_version_ids"), "run proof IDs"))
        return frozenset(proof_ids)

    def _proof_list_item(self, artifact: StoredArtifact) -> ProofListItem:
        p = artifact.payload
        composition = _mapping(p.get("composition"), "proof composition")
        return ProofListItem(
            proof_id=artifact.artifact_id,
            settlement_id=_text(p.get("settlement_id"), "proof settlement id"),
            version=_integer(p.get("version"), "proof version"),
            status=_text(p.get("status"), "proof status"),
            settlement_amount=_money(
                composition.get("settlement_amount"), "proof settlement amount"
            ),
            reason_codes=_strings(p.get("reason_codes"), "proof reason codes"),
            knowledge_cutoff=_timestamp_text(p.get("knowledge_cutoff"), "proof knowledge cutoff"),
            generated_at=_timestamp_text(p.get("generated_at"), "proof generated_at"),
            reopened=_boolean(p.get("reopened"), "proof reopened"),
        )

    def proofs(self, scope_id: domain.ReconciliationScopeId) -> tuple[ProofListItem, ...]:
        proof_ids = self._scoped_run_proof_ids(scope_id)
        items = tuple(
            self._proof_list_item(
                self._artifact(proof_id, ArtifactKind.PROOF_VERSION, scope_id)
            )
            for proof_id in proof_ids
        )
        return tuple(
            sorted(
                items,
                key=lambda item: (
                    _timestamp(item.generated_at, "proof generated_at"),
                    item.proof_id,
                ),
                reverse=True,
            )
        )

    def proof_detail(
        self, scope_id: domain.ReconciliationScopeId, proof_id: str
    ) -> ProofDetailView:
        artifact = self._artifact(proof_id, ArtifactKind.PROOF_VERSION, scope_id)
        if proof_id not in self._scoped_run_proof_ids(scope_id):
            raise ControlTowerIntegrityError(
                "proof is not referenced by any reconciliation run in requested scope"
            )
        p = artifact.payload
        composition = _mapping(p.get("composition"), "proof composition")
        bank = _mapping(p.get("bank"), "proof bank")
        settlement_id = _text(p.get("settlement_id"), "proof settlement id")
        timeline = tuple(
            sorted(
                (item for item in self.proofs(scope_id) if item.settlement_id == settlement_id),
                key=lambda item: item.version,
            )
        )
        return ProofDetailView(
            proof_id=artifact.artifact_id,
            settlement_id=settlement_id,
            version=_integer(p.get("version"), "proof version"),
            status=_text(p.get("status"), "proof status"),
            reason_codes=_strings(p.get("reason_codes"), "proof reason codes"),
            reopened=_boolean(p.get("reopened"), "proof reopened"),
            prior_version_id=_optional_text(p.get("prior_version_id"), "proof prior version id"),
            knowledge_cutoff=_timestamp_text(p.get("knowledge_cutoff"), "proof knowledge cutoff"),
            generated_at=_timestamp_text(p.get("generated_at"), "proof generated_at"),
            source_envelope_ids=_strings(p.get("source_envelope_ids"), "proof source envelope ids"),
            composition=CompositionProofView(
                status=_text(composition.get("status"), "composition status"),
                settlement_amount=_money(
                    composition.get("settlement_amount"), "composition settlement amount"
                ),
                observed_composition=_money(
                    composition.get("observed_composition"), "composition observed amount"
                ),
                residual=_money(composition.get("residual"), "composition residual"),
                component_ids=_strings(composition.get("component_ids"), "composition IDs"),
                source_envelope_ids=_strings(
                    composition.get("source_envelope_ids"), "composition source envelope IDs"
                ),
                reason_codes=_strings(composition.get("reason_codes"), "composition reason codes"),
            ),
            bank=BankProofView(
                status=_text(bank.get("status"), "bank status"),
                settlement_utr=_optional_text(bank.get("settlement_utr"), "settlement UTR"),
                expected_amount=_money(bank.get("expected_amount"), "bank expected amount"),
                observed_bank_credit=_money(
                    bank.get("observed_bank_credit"), "bank observed credit"
                ),
                residual=_money(bank.get("residual"), "bank residual"),
                bank_entry_ids=_strings(bank.get("bank_entry_ids"), "bank entry IDs"),
                source_envelope_ids=_strings(
                    bank.get("source_envelope_ids"), "bank source envelope IDs"
                ),
                reason_codes=_strings(bank.get("reason_codes"), "bank reason codes"),
            ),
            version_timeline=timeline,
        )

    @staticmethod
    def _observation_view(artifact: StoredArtifact) -> CaseObservationView:
        p = artifact.payload
        states = tuple(
            SourceStateView(
                source_kind=_text(_mapping(item, "source state").get("source_kind"), "source kind"),
                completeness=_text(
                    _mapping(item, "source state").get("completeness"),
                    "source completeness",
                ),
                received_late=_boolean(
                    _mapping(item, "source state").get("received_late"),
                    "source received late",
                ),
                manifest_id=_text(
                    _mapping(item, "source state").get("manifest_id"), "source manifest id"
                ),
            )
            for item in _sequence(p.get("source_states"), "observation source states")
        )
        return CaseObservationView(
            observation_id=artifact.artifact_id,
            run_id=_text(p.get("run_id"), "observation run id"),
            proof_version_id=_text(p.get("proof_version_id"), "observation proof id"),
            financial_status=_text(p.get("financial_status"), "observation financial status"),
            reason_codes=_strings(p.get("reason_codes"), "observation reason codes"),
            affected_amount=_money(p.get("affected_amount"), "observation affected amount"),
            materiality_band=_text(p.get("materiality_band"), "observation materiality"),
            incident_fingerprint_id=_text(
                p.get("incident_fingerprint_id"), "observation incident fingerprint"
            ),
            source_states=states,
            observed_at=_timestamp_text(p.get("observed_at"), "observation observed_at"),
        )

    @staticmethod
    def _disposition_view(artifact: StoredArtifact) -> DispositionView:
        p = artifact.payload
        return DispositionView(
            disposition_id=artifact.artifact_id,
            sequence=_integer(p.get("sequence"), "disposition sequence"),
            actor_id=_text(p.get("actor_id"), "disposition actor"),
            occurred_at=_timestamp_text(p.get("occurred_at"), "disposition occurred_at"),
            kind=_text(p.get("kind"), "disposition kind"),
            owner=_optional_text(p.get("owner"), "disposition owner"),
            note=_optional_text(p.get("note"), "disposition note"),
        )

    def _case_queue(self, scope_id: domain.ReconciliationScopeId) -> tuple[ExceptionQueueItem, ...]:
        observation_artifacts = self._list(ArtifactKind.CASE_OBSERVATION, scope_id)
        disposition_artifacts = self._list(ArtifactKind.CASE_DISPOSITION, scope_id)
        cluster_artifacts = self._list(ArtifactKind.INCIDENT_CLUSTER, scope_id)

        observations: dict[str, list[tuple[StoredArtifact, CaseObservationView]]] = {}
        settlement_for_case: dict[str, str] = {}
        tracking_for_case: dict[str, str] = {}
        utr_for_case: dict[str, str | None] = {}
        for artifact in observation_artifacts:
            p = artifact.payload
            case_id = _text(p.get("case_id"), "observation case id")
            view = self._observation_view(artifact)
            observations.setdefault(case_id, []).append((artifact, view))
            settlement_for_case[case_id] = _text(
                p.get("settlement_id"), "observation settlement id"
            )
            tracking_for_case[case_id] = _text(p.get("tracking_key"), "observation tracking key")
            utr_for_case[case_id] = _optional_text(p.get("settlement_utr"), "settlement UTR")

        dispositions: dict[str, list[DispositionView]] = {}
        for artifact in disposition_artifacts:
            case_id = _text(artifact.payload.get("case_id"), "disposition case id")
            dispositions.setdefault(case_id, []).append(self._disposition_view(artifact))

        cluster_for_case: dict[str, str] = {}
        for artifact in cluster_artifacts:
            for case_id in _strings(artifact.payload.get("case_ids"), "incident case IDs"):
                prior = cluster_for_case.get(case_id)
                if prior is not None and prior != artifact.artifact_id:
                    # Clusters are run-specific; keep the newest artifact by observed time/ID below.
                    existing = self._store.artifact(prior)
                    if existing is not None and _artifact_time(
                        existing, "observed_at"
                    ) > _artifact_time(artifact, "observed_at"):
                        continue
                cluster_for_case[case_id] = artifact.artifact_id

        latest_case_by_settlement: dict[str, tuple[str, datetime]] = {}
        for case_id, rows in observations.items():
            latest = max(rows, key=lambda row: _timestamp(row[1].observed_at, "observed_at"))[1]
            settlement_id = settlement_for_case[case_id]
            seen = latest_case_by_settlement.get(settlement_id)
            latest_time = _timestamp(latest.observed_at, "observed_at")
            if (
                seen is None
                or latest_time > seen[1]
                or (latest_time == seen[1] and case_id > seen[0])
            ):
                latest_case_by_settlement[settlement_id] = (case_id, latest_time)

        now = self._now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ControlTowerIntegrityError("control tower clock must be timezone-aware")
        result: list[ExceptionQueueItem] = []
        for case_id, rows in observations.items():
            ordered = sorted(rows, key=lambda row: _timestamp(row[1].observed_at, "observed_at"))
            first_payload = ordered[0][0].payload
            latest_payload = ordered[-1][0].payload
            latest_view = ordered[-1][1]
            case_dispositions = sorted(
                dispositions.get(case_id, []), key=lambda item: item.sequence
            )
            if tuple(item.sequence for item in case_dispositions) != tuple(
                range(1, len(case_dispositions) + 1)
            ):
                raise ControlTowerIntegrityError("case disposition sequence is non-contiguous")
            owner: str | None = None
            workflow = "open"
            resolution: str | None = None
            for item in case_dispositions:
                if item.kind == "assign_owner":
                    owner = item.owner
                elif item.kind == "acknowledge":
                    workflow, resolution = "acknowledged", None
                elif item.kind == "request_source_correction":
                    workflow, resolution = "awaiting_source", None
                elif item.kind == "defer":
                    workflow, resolution = "deferred", None
                elif item.kind == "accept_operational_variance":
                    workflow, resolution = "closed", "operational_variance_accepted"
                elif item.kind == "close":
                    workflow, resolution = "closed", "operator_closed"
                elif item.kind == "reopen":
                    workflow, resolution = "open", None
                else:
                    raise ControlTowerIntegrityError(f"unsupported disposition kind {item.kind}")

            settlement_id = settlement_for_case[case_id]
            latest_case = latest_case_by_settlement[settlement_id][0]
            superseded_by = None if latest_case == case_id else latest_case
            if superseded_by is not None:
                workflow, resolution = "closed", "economic_identity_changed"
            elif latest_view.financial_status == "proven_reconciled":
                workflow, resolution = "closed", "proof_reconciled"

            first_seen = _timestamp(first_payload.get("observed_at"), "first observation time")
            last_seen = _timestamp(latest_payload.get("observed_at"), "latest observation time")
            if last_seen < first_seen:
                raise ControlTowerIntegrityError("case observation chronology moved backwards")
            age = max(0, int((now - first_seen).total_seconds()))
            blockers = tuple(
                sorted(
                    f"{state.source_kind}:{state.completeness}"
                    + (":late" if state.received_late else "")
                    for state in latest_view.source_states
                    if state.completeness != "complete" or state.received_late
                )
            )
            active = (
                latest_view.financial_status != "proven_reconciled"
                and superseded_by is None
                and workflow != "closed"
            )
            result.append(
                ExceptionQueueItem(
                    case_id=case_id,
                    settlement_id=settlement_id,
                    latest_observation_id=latest_view.observation_id,
                    latest_proof_version_id=latest_view.proof_version_id,
                    financial_status=latest_view.financial_status,
                    materiality_band=latest_view.materiality_band,
                    affected_amount=latest_view.affected_amount,
                    workflow_status=workflow,
                    resolution=resolution,
                    owner=owner,
                    incident_fingerprint_id=latest_view.incident_fingerprint_id,
                    incident_cluster_id=cluster_for_case.get(case_id),
                    source_blockers=blockers,
                    first_seen_at=first_seen.isoformat(),
                    last_seen_at=last_seen.isoformat(),
                    age_seconds=age,
                    observation_count=len(ordered),
                    disposition_count=len(case_dispositions),
                    superseded_by_case_id=superseded_by,
                    is_active=active,
                )
            )
            # Retain these checks so corrupted identity helper fields cannot be silently ignored.
            _text(tracking_for_case[case_id], "case tracking key")
            _optional_text(utr_for_case[case_id], "case settlement UTR")

        return tuple(
            sorted(
                result,
                key=lambda item: (
                    not item.is_active,
                    _MATERIALITY_ORDER.get(item.materiality_band, 99),
                    -item.age_seconds,
                    item.case_id,
                ),
            )
        )

    def exceptions(self, scope_id: domain.ReconciliationScopeId) -> tuple[ExceptionQueueItem, ...]:
        return self._case_queue(scope_id)

    def _investigation(
        self,
        scope_id: domain.ReconciliationScopeId,
        *,
        case_id: str,
        observation_id: str,
        proof_id: str,
    ) -> InvestigationView | None:
        candidates: list[tuple[StoredArtifact, InvestigationView]] = []
        for artifact in self._list(ArtifactKind.INVESTIGATION_RESULT, scope_id):
            p = artifact.payload
            if (
                p.get("case_id") != case_id
                or p.get("observation_id") != observation_id
                or p.get("proof_version_id") != proof_id
            ):
                continue
            trace = _sequence(p.get("trace"), "investigation trace")
            candidates.append(
                (
                    artifact,
                    InvestigationView(
                        investigation_id=artifact.artifact_id,
                        status=_text(p.get("status"), "investigation status"),
                        next_action=_text(p.get("next_action"), "investigation next action"),
                        hypothesis=_optional_text(p.get("hypothesis"), "investigation hypothesis"),
                        citations=_strings(p.get("citations"), "investigation citations"),
                        request_source_kind=_optional_text(
                            p.get("request_source_kind"), "investigation request source kind"
                        ),
                        rejection_reason=_optional_text(
                            p.get("rejection_reason"), "investigation rejection reason"
                        ),
                        as_of=_timestamp_text(p.get("as_of"), "investigation as_of"),
                        trace_count=len(trace),
                    ),
                )
            )
        if not candidates:
            return None
        return max(
            candidates, key=lambda pair: (_artifact_time(pair[0], "as_of"), pair[0].artifact_id)
        )[1]

    def case_file(self, scope_id: domain.ReconciliationScopeId, case_id: str) -> CaseFileView:
        queue = {item.case_id: item for item in self._case_queue(scope_id)}
        case = queue.get(case_id)
        if case is None:
            raise ControlTowerNotFound(f"unknown exception case {case_id}")
        observations = tuple(
            sorted(
                (
                    self._observation_view(artifact)
                    for artifact in self._list(ArtifactKind.CASE_OBSERVATION, scope_id)
                    if artifact.payload.get("case_id") == case_id
                ),
                key=lambda item: (
                    _timestamp(item.observed_at, "observation time"),
                    item.observation_id,
                ),
            )
        )
        dispositions = tuple(
            sorted(
                (
                    self._disposition_view(artifact)
                    for artifact in self._list(ArtifactKind.CASE_DISPOSITION, scope_id)
                    if artifact.payload.get("case_id") == case_id
                ),
                key=lambda item: item.sequence,
            )
        )
        proof = self.proof_detail(scope_id, case.latest_proof_version_id)
        investigation = self._investigation(
            scope_id,
            case_id=case.case_id,
            observation_id=case.latest_observation_id,
            proof_id=case.latest_proof_version_id,
        )
        return CaseFileView(
            case=case,
            observations=observations,
            dispositions=dispositions,
            proof=proof,
            investigation=investigation,
        )

    def overview(self, scope_id: domain.ReconciliationScopeId) -> OverviewView:
        run_artifact = self._latest_run_artifact(scope_id)
        if run_artifact is None:
            return OverviewView(
                scope_id=str(scope_id),
                has_current_run=False,
                run=None,
                proof_status=(),
                sources=self.sources(scope_id),
                active_exception_count=0,
                active_exception_value=None,
            )

        run = run_artifact.payload
        proof_ids = _strings(run.get("proof_version_ids"), "run proof IDs")
        proof_artifacts = tuple(
            self._artifact(proof_id, ArtifactKind.PROOF_VERSION, scope_id) for proof_id in proof_ids
        )
        proof_items = tuple(self._proof_list_item(artifact) for artifact in proof_artifacts)
        amounts = [item.settlement_amount for item in proof_items]
        if amounts and len({item.currency for item in amounts}) != 1:
            raise ControlTowerIntegrityError("run proof summary contains mixed currencies")
        currency = amounts[0].currency if amounts else None
        status_summary: list[ProofStatusSummary] = []
        for status in _PROOF_STATUS_ORDER:
            values = [item.settlement_amount for item in proof_items if item.status == status]
            if values:
                amount = _sum_money(values, f"{status} proof total")
            elif currency is not None:
                amount = _money({"amount_paise": 0, "currency": currency}, f"{status} zero total")
            else:
                continue
            status_summary.append(
                ProofStatusSummary(status=status, count=len(values), amount=amount)
            )

        manifest_ids = _strings(run.get("source_manifest_ids"), "run source manifest IDs")
        source_items = tuple(
            self._source_item(
                self._artifact(manifest_id, ArtifactKind.SOURCE_DELIVERY_MANIFEST, scope_id)
            )
            for manifest_id in manifest_ids
        )
        close_id = _text(run.get("close_readiness_id"), "run close readiness id")
        coverage_id = _text(run.get("coverage_certificate_id"), "run coverage id")
        balance_id = _text(run.get("balance_control_id"), "run balance id")
        close = self._artifact(close_id, ArtifactKind.CLOSE_READINESS, scope_id).payload
        coverage = self._artifact(coverage_id, ArtifactKind.EVIDENCE_COVERAGE, scope_id).payload
        balance = self._artifact(balance_id, ArtifactKind.BALANCE_CONTROL, scope_id).payload

        queue = self._case_queue(scope_id)
        active = tuple(item for item in queue if item.is_active)
        active_value = (
            None
            if not active
            else _sum_money([item.affected_amount for item in active], "active exception value")
        )
        run_view = RunOverviewView(
            run_id=run_artifact.artifact_id,
            outcome=_text(run.get("outcome"), "run outcome"),
            period_start=_timestamp_text(run.get("period_start"), "run period start"),
            period_end=_timestamp_text(run.get("period_end"), "run period end"),
            reporting_timezone=_text(run.get("reporting_timezone"), "run timezone"),
            knowledge_cutoff=_timestamp_text(run.get("knowledge_cutoff"), "run knowledge cutoff"),
            completed_at=_timestamp_text(run.get("completed_at"), "run completed_at"),
            code_build_sha=_optional_text(run.get("code_build_sha"), "run code build sha"),
            close_readiness_id=close_id,
            close_status=_text(close.get("status"), "close readiness status"),
            close_reason_codes=_strings(close.get("reason_codes"), "close readiness reasons"),
            coverage_certificate_id=coverage_id,
            coverage_status=_text(coverage.get("status"), "coverage status"),
            orphan_count=_integer(coverage.get("orphan_count"), "coverage orphan count"),
            orphan_known_value=_money(
                coverage.get("orphan_known_value"), "coverage orphan known value"
            ),
            balance_control_id=balance_id,
            balance_status=_text(balance.get("status"), "balance status"),
            balance_residual=_money(balance.get("residual"), "balance residual"),
        )
        if run_view.outcome != run_view.close_status:
            raise ControlTowerIntegrityError("run outcome disagrees with close readiness status")
        return OverviewView(
            scope_id=str(scope_id),
            has_current_run=True,
            run=run_view,
            proof_status=tuple(status_summary),
            sources=tuple(sorted(source_items, key=lambda item: item.source_kind)),
            active_exception_count=len(active),
            active_exception_value=active_value,
        )

    def evaluation(self) -> EvaluationLabView:
        paths = (
            []
            if not self._evaluation_root.exists()
            else list(sorted(self._evaluation_root.glob("*.json")))
        )
        if (
            self._final_evaluation_summary is not None
            and self._final_evaluation_summary.is_file()
            and self._final_evaluation_summary not in paths
        ):
            paths.append(self._final_evaluation_summary)
        artifacts: list[EvaluationArtifactView] = []
        for path in paths:
            try:
                payload = load_verified_benchmark(path)
            except (OSError, ValueError) as exc:
                raise ControlTowerIntegrityError(
                    f"evaluation artifact {path.name} failed verification"
                ) from exc
            config = _mapping(payload.get("config"), "evaluation config")
            hardware = _mapping(payload.get("hardware"), "evaluation hardware")
            metrics = _mapping(payload.get("metrics"), "evaluation metrics")
            status_counts_value = payload.get("status_counts")
            status_counts = (
                None
                if status_counts_value is None
                else _mapping(status_counts_value, "evaluation status counts")
            )
            artifacts.append(
                EvaluationArtifactView(
                    filename=path.name,
                    schema_version=_text(payload.get("schema_version"), "evaluation schema"),
                    artifact_sha256=_text(
                        payload.get("artifact_sha256"), "evaluation artifact digest"
                    ),
                    config=dict(config),
                    hardware=dict(hardware),
                    metrics=dict(metrics),
                    status_counts=None if status_counts is None else dict(status_counts),
                )
            )
        return EvaluationLabView(artifacts=tuple(artifacts))
