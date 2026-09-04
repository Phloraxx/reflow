from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from time import perf_counter

from reflow import domain
from reflow.bank_proof import BankReceiptStatus, prove_all_bank_receipts
from reflow.control_plane import (
    BalanceControlProof,
    CloseReadinessCertificate,
    DeliveryMode,
    EvidenceCoverageCertificate,
    ReconciliationPolicyVersion,
    ReconciliationRun,
    ReconciliationScope,
    SourceDeliveryManifest,
    build_balance_control,
    build_close_readiness,
    build_evidence_coverage,
    build_reconciliation_run,
    make_reconciliation_policy_version,
    make_reconciliation_scope,
    make_source_delivery_manifest,
)
from reflow.exception_cases import (
    DispositionKind,
    ExceptionCaseDisposition,
    ExceptionCaseObservation,
    InMemoryExceptionCaseLedger,
    build_incident_clusters,
)
from reflow.ingestion import CanonicalBatch, ObservedBatch, ingest_observed_batch
from reflow.investigation import (
    InvestigationContext,
    InvestigationRunResult,
    ReadOnlyInvestigationTools,
    run_investigation,
)
from reflow.journal import InMemoryJournal
from reflow.money_graph import build_money_graph
from reflow.persistence import ArtifactKind, PointerKind, ReflowApplicationService
from reflow.reconciliation_proof import (
    InMemoryProofLedger,
    ReconciliationProofVersion,
)
from reflow.settlement_proof import prove_all_settlement_compositions

__all__ = ["JudgeDemoError", "JudgeDemoService"]

PERIOD_START = datetime(2026, 9, 4, 0, 0, tzinfo=UTC)
PERIOD_END = datetime(2026, 9, 5, 0, 0, tzinfo=UTC)
RUN1_AT = datetime(2026, 9, 4, 9, 0, tzinfo=UTC)
RUN2_AT = datetime(2026, 9, 4, 10, 0, tzinfo=UTC)


class JudgeDemoError(ValueError):
    """The local judge demo action is invalid for the current phase."""


class JudgeDemoPhase(StrEnum):
    READY = "ready"
    INITIAL_RUN = "initial_run"
    BANK_ARRIVED = "bank_arrived"
    RECONCILED = "reconciled"


@dataclass(frozen=True, slots=True)
class DemoStage:
    key: str
    label: str
    duration_ms: float
    facts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DemoOutcome:
    settlement_id: str
    label: str
    amount_paise: int
    amount_display: str
    status: str
    composition_status: str
    bank_status: str
    residual_paise: int
    residual_display: str
    proof_id: str
    version: int


@dataclass(frozen=True, slots=True)
class DemoActionResult:
    phase: str
    scope_id: str
    stages: tuple[DemoStage, ...]
    outcomes: tuple[DemoOutcome, ...]
    focus_case_id: str | None
    focus_proof_id: str | None
    message: str


@dataclass(frozen=True, slots=True)
class _RunParts:
    batch: CanonicalBatch
    proofs: tuple[ReconciliationProofVersion, ...]
    new_proofs: tuple[ReconciliationProofVersion, ...]
    manifests: tuple[SourceDeliveryManifest, ...]
    run: ReconciliationRun
    coverage: EvidenceCoverageCertificate
    balance: BalanceControlProof
    close: CloseReadinessCertificate
    observations: tuple[ExceptionCaseObservation, ...]
    dispositions: tuple[ExceptionCaseDisposition, ...]
    investigation: InvestigationRunResult | None


class _JudgeInvestigator:
    def propose(
        self,
        context: InvestigationContext,
        tools: ReadOnlyInvestigationTools,
    ) -> Mapping[str, object]:
        tools.case_snapshot()
        tools.proof_snapshot()
        source_id = context.available_source_envelope_ids[0]
        tools.source_evidence(source_id)
        return {
            "case_id": str(context.case_id),
            "observation_id": str(context.observation_id),
            "proof_version_id": str(context.proof_version_id),
            "hypothesis": (
                "Authoritative bank evidence is incomplete; request the missing bank delivery."
            ),
            "citations": [str(source_id)],
            "financial_claims": [],
            "next_action": "REQUEST_SOURCE",
            "request_source_kind": "bank",
        }


def _money_display(paise: int) -> str:
    sign = "-" if paise < 0 else ""
    value = abs(paise)
    return f"{sign}₹{value // 100:,}.{value % 100:02d}"


def _scope() -> ReconciliationScope:
    return make_reconciliation_scope(
        merchant_account_id="merchant_judge_demo",
        provider="razorpay",
        provider_account_id="rzp_judge_demo",
        bank_account_id="bank_judge_demo",
        currency=domain.Currency.INR,
        channel="payments",
    )


def _policy() -> ReconciliationPolicyVersion:
    return make_reconciliation_policy_version(
        version_label="judge-demo-v1",
        required_source_kinds=tuple(domain.SourceKind),
        reporting_timezone="UTC",
        bank_wait_sla_seconds=3600,
        materiality_thresholds_paise=(50_000, 500_000, 1_000_000),
    )


def _observed(*, pending_only: bool, bank_arrived: bool) -> ObservedBatch:
    specs: tuple[tuple[str, int, int], ...] = (
        ("green", 1_000_000, 1_000_000),
        ("pending", 2_000_000, 2_000_000),
        ("residual", 3_000_000, 2_950_000),
        ("contradicted", 1_250_000, 1_250_000),
    )
    if pending_only:
        specs = (specs[1],)
    merchant_rows: list[dict[str, object]] = []
    razorpay_events: list[dict[str, object]] = []
    recon_rows: list[dict[str, object]] = []
    settlement_rows: list[dict[str, object]] = []
    stable_index = {
        "green": 1,
        "pending": 2,
        "residual": 3,
        "contradicted": 4,
    }
    for label, settlement_amount, composition_amount in specs:
        at = PERIOD_START + timedelta(hours=1, minutes=stable_index[label])
        merchant_rows.append(
            {
                "order_id": f"order_demo_{label}",
                "amount_paise": composition_amount,
                "currency": "INR",
                "created_at": at.isoformat(),
                "external_reference": f"judge-demo-{label}",
            }
        )
        razorpay_events.append(
            {
                "event_id": f"evt_demo_{label}",
                "payment_id": f"pay_demo_{label}",
                "order_id": f"order_demo_{label}",
                "event_kind": "captured",
                "amount_paise": composition_amount,
                "currency": "INR",
                "occurred_at": (at + timedelta(minutes=1)).isoformat(),
                "received_at": (at + timedelta(minutes=2)).isoformat(),
                "error_code": None,
                "error_reason": None,
            }
        )
        recon_rows.append(
            {
                "recon_id": f"recon_demo_{label}",
                "settlement_id": f"setl_demo_{label}",
                "entity_kind": "payment",
                "entity_id": f"pay_demo_{label}",
                "gross_amount_paise": composition_amount,
                "fee_paise": 0,
                "tax_paise": 0,
                "settlement_effect_paise": composition_amount,
                "currency": "INR",
                "occurred_at": (at + timedelta(hours=1)).isoformat(),
            }
        )
        settlement_rows.append(
            {
                "settlement_id": f"setl_demo_{label}",
                "amount_paise": settlement_amount,
                "currency": "INR",
                "processed_at": (at + timedelta(hours=2)).isoformat(),
                "utr": f"UTR-DEMO-{label.upper()}",
            }
        )

    bank_rows: list[dict[str, object]] = []
    if not pending_only:
        bank_rows.extend(
            [
                {
                    "bank_entry_id": "bank_demo_green",
                    "amount_paise": 1_000_000,
                    "currency": "INR",
                    "occurred_at": (PERIOD_START + timedelta(hours=5)).isoformat(),
                    "narration": "Razorpay settlement UTR-DEMO-GREEN",
                    "utr": "UTR-DEMO-GREEN",
                },
                {
                    "bank_entry_id": "bank_demo_residual",
                    "amount_paise": 3_000_000,
                    "currency": "INR",
                    "occurred_at": (PERIOD_START + timedelta(hours=5, minutes=2)).isoformat(),
                    "narration": "Razorpay settlement UTR-DEMO-RESIDUAL",
                    "utr": "UTR-DEMO-RESIDUAL",
                },
                {
                    "bank_entry_id": "bank_demo_contradicted_a",
                    "amount_paise": 1_250_000,
                    "currency": "INR",
                    "occurred_at": (PERIOD_START + timedelta(hours=5, minutes=3)).isoformat(),
                    "narration": "Razorpay settlement UTR-DEMO-CONTRADICTED",
                    "utr": "UTR-DEMO-CONTRADICTED",
                },
                {
                    "bank_entry_id": "bank_demo_contradicted_b",
                    "amount_paise": 100,
                    "currency": "INR",
                    "occurred_at": (PERIOD_START + timedelta(hours=5, minutes=4)).isoformat(),
                    "narration": "Duplicate UTR evidence",
                    "utr": "UTR-DEMO-CONTRADICTED",
                },
            ]
        )
    if bank_arrived:
        bank_rows.append(
            {
                "bank_entry_id": "bank_demo_pending",
                "amount_paise": 2_000_000,
                "currency": "INR",
                "occurred_at": (PERIOD_START + timedelta(hours=9, minutes=30)).isoformat(),
                "narration": "Razorpay settlement UTR-DEMO-PENDING",
                "utr": "UTR-DEMO-PENDING",
            }
        )
    return ObservedBatch(
        merchant_rows=tuple(merchant_rows),
        razorpay_events=tuple(razorpay_events),
        recon_rows=tuple(recon_rows),
        settlement_rows=tuple(settlement_rows),
        bank_rows=tuple(bank_rows),
    )


def _manifests(
    *,
    batch: CanonicalBatch,
    scope: ReconciliationScope,
    evaluated_at: datetime,
    bank_complete: bool,
) -> tuple[SourceDeliveryManifest, ...]:
    manifests: list[SourceDeliveryManifest] = []
    for source_kind in domain.SourceKind:
        envelope_ids = tuple(
            link.envelope_id for link in batch.source_links if link.source_kind is source_kind
        )
        complete = bank_complete if source_kind is domain.SourceKind.BANK else True
        manifests.append(
            make_source_delivery_manifest(
                scope=scope,
                source_kind=source_kind,
                source_account_id=scope.account_for(source_kind),
                delivery_mode=DeliveryMode.SNAPSHOT,
                period_start=PERIOD_START,
                period_end=PERIOD_END,
                reporting_timezone="UTC",
                expected_by=evaluated_at + timedelta(hours=1),
                evaluated_at=evaluated_at,
                received_at=evaluated_at,
                watermark_at=PERIOD_END if complete else None,
                is_complete=complete,
                delivered_envelope_ids=envelope_ids,
                adapter_version="judge-demo-normalized-v1",
                schema_fingerprint=f"judge-demo-{source_kind.value}-v1",
            )
        )
    return tuple(manifests)


def _outcomes(proofs: tuple[ReconciliationProofVersion, ...]) -> tuple[DemoOutcome, ...]:
    labels = {
        "setl_demo_green": "Exact match",
        "setl_demo_pending": "Bank evidence missing",
        "setl_demo_residual": "₹500 unexplained",
        "setl_demo_contradicted": "Reused UTR contradiction",
    }
    result = []
    order = {
        "setl_demo_green": 0,
        "setl_demo_pending": 1,
        "setl_demo_residual": 2,
        "setl_demo_contradicted": 3,
    }
    for proof in sorted(proofs, key=lambda item: order.get(str(item.settlement_id), 99)):
        residual = max(
            abs(proof.composition.residual.amount_paise),
            abs(proof.bank.residual.amount_paise),
        )
        amount = proof.composition.settlement_amount.amount_paise
        result.append(
            DemoOutcome(
                settlement_id=str(proof.settlement_id),
                label=labels.get(str(proof.settlement_id), str(proof.settlement_id)),
                amount_paise=amount,
                amount_display=_money_display(amount),
                status=proof.status.value,
                composition_status=proof.composition.status.value,
                bank_status=proof.bank.status.value,
                residual_paise=residual,
                residual_display=_money_display(residual),
                proof_id=str(proof.id),
                version=proof.version,
            )
        )
    return tuple(result)


class JudgeDemoService:
    def __init__(self, service: ReflowApplicationService) -> None:
        self._service = service
        self._scope = _scope()
        self._policy = _policy()
        self._journal = InMemoryJournal()
        self._proof_ledger = InMemoryProofLedger()
        self._case_ledger = InMemoryExceptionCaseLedger()
        self._phase = JudgeDemoPhase.READY
        self._persisted_envelopes: set[domain.SourceEnvelopeId] = set()
        self._run_generation = 0
        self._focus_case_id: str | None = None
        self._focus_proof_id: str | None = None
        self._latest_outcomes: tuple[DemoOutcome, ...] = ()

    @property
    def scope_id(self) -> domain.ReconciliationScopeId:
        return self._scope.id

    def status(self) -> dict[str, object]:
        return {
            "enabled": True,
            "phase": self._phase.value,
            "scope_id": str(self._scope.id),
            "focus_case_id": self._focus_case_id,
            "focus_proof_id": self._focus_proof_id,
            "raw_record_count": 21
            if self._phase in {JudgeDemoPhase.BANK_ARRIVED, JudgeDemoPhase.RECONCILED}
            else 20,
            "settlement_count": 4,
            "outcomes": [asdict(item) for item in self._latest_outcomes],
            "can_run": self._phase is JudgeDemoPhase.READY,
            "can_add_bank": self._phase is JudgeDemoPhase.INITIAL_RUN,
            "can_rerun": self._phase is JudgeDemoPhase.BANK_ARRIVED,
        }

    def run_initial(self) -> DemoActionResult:
        if self._phase is not JudgeDemoPhase.READY:
            raise JudgeDemoError("initial reconciliation has already run")
        stages: list[DemoStage] = []
        parts = self._execute(
            observed=_observed(pending_only=False, bank_arrived=False),
            at=RUN1_AT,
            bank_complete=False,
            publish_current=True,
            stages=stages,
        )
        pending = next(
            proof for proof in parts.proofs if str(proof.settlement_id) == "setl_demo_pending"
        )
        pending_observation = next(
            obs for obs in parts.observations if obs.settlement_id == pending.settlement_id
        )
        self._focus_case_id = str(pending_observation.case_id)
        self._focus_proof_id = str(pending.id)
        self._latest_outcomes = _outcomes(parts.proofs)
        self._phase = JudgeDemoPhase.INITIAL_RUN
        return DemoActionResult(
            phase=self._phase.value,
            scope_id=str(self._scope.id),
            stages=tuple(stages),
            outcomes=self._latest_outcomes,
            focus_case_id=self._focus_case_id,
            focus_proof_id=self._focus_proof_id,
            message=(
                "Full four-settlement reconciliation completed with one proof and three "
                "explicit exceptions."
            ),
        )

    def add_bank_evidence(self) -> DemoActionResult:
        if self._phase is not JudgeDemoPhase.INITIAL_RUN:
            raise JudgeDemoError("bank evidence can only arrive after the initial run")
        started = perf_counter()
        self._phase = JudgeDemoPhase.BANK_ARRIVED
        stage = DemoStage(
            key="bank-arrival",
            label="Receive missing bank evidence",
            duration_ms=round((perf_counter() - started) * 1000, 3),
            facts=("bank_demo_pending", "UTR-DEMO-PENDING", "₹20,000.00 authoritative credit"),
        )
        return DemoActionResult(
            phase=self._phase.value,
            scope_id=str(self._scope.id),
            stages=(stage,),
            outcomes=self._latest_outcomes,
            focus_case_id=self._focus_case_id,
            focus_proof_id=self._focus_proof_id,
            message="The missing bank row is now available for focused proof re-evaluation.",
        )

    def rerun_affected(self) -> DemoActionResult:
        if self._phase is not JudgeDemoPhase.BANK_ARRIVED:
            raise JudgeDemoError("focused re-evaluation requires the missing bank evidence first")
        stages: list[DemoStage] = []
        parts = self._execute(
            observed=_observed(pending_only=True, bank_arrived=True),
            at=RUN2_AT,
            bank_complete=True,
            publish_current=False,
            stages=stages,
        )
        proof = parts.proofs[0]
        self._focus_proof_id = str(proof.id)
        self._latest_outcomes = tuple(
            proof_outcome
            if proof_outcome.settlement_id != "setl_demo_pending"
            else _outcomes((proof,))[0]
            for proof_outcome in self._latest_outcomes
        )
        self._phase = JudgeDemoPhase.RECONCILED
        return DemoActionResult(
            phase=self._phase.value,
            scope_id=str(self._scope.id),
            stages=tuple(stages),
            outcomes=self._latest_outcomes,
            focus_case_id=self._focus_case_id,
            focus_proof_id=self._focus_proof_id,
            message=(
                "Late authoritative evidence produced proof v2 and auto-closed the pending "
                "case without rewriting v1."
            ),
        )

    def _execute(
        self,
        *,
        observed: ObservedBatch,
        at: datetime,
        bank_complete: bool,
        publish_current: bool,
        stages: list[DemoStage],
    ) -> _RunParts:
        started = perf_counter()
        batch = ingest_observed_batch(observed, self._journal, received_at=at)
        stages.append(
            DemoStage(
                "ingest",
                "Ingest immutable evidence",
                round((perf_counter() - started) * 1000, 3),
                (
                    f"{len(batch.source_links)} journal-backed source records",
                    (
                        f"{len(batch.settlements)} "
                        f"settlement{'s' if len(batch.settlements) != 1 else ''}"
                    ),
                ),
            )
        )

        started = perf_counter()
        graph = build_money_graph(batch)
        stages.append(
            DemoStage(
                "graph",
                "Build Money Graph",
                round((perf_counter() - started) * 1000, 3),
                (f"{len(graph.nodes)} nodes", f"{len(graph.edges)} authoritative edges"),
            )
        )

        started = perf_counter()
        compositions = prove_all_settlement_compositions(batch, graph)
        composition_green = sum(proof.residual.is_zero for proof in compositions)
        stages.append(
            DemoStage(
                "composition",
                "Prove settlement composition",
                round((perf_counter() - started) * 1000, 3),
                (
                    f"{composition_green}/{len(compositions)} exact compositions",
                    "No tolerance or fuzzy amount match",
                ),
            )
        )

        started = perf_counter()
        banks = prove_all_bank_receipts(batch)
        bank_green = sum(proof.status is BankReceiptStatus.PROVEN for proof in banks)
        stages.append(
            DemoStage(
                "bank",
                "Verify bank receipt independently",
                round((perf_counter() - started) * 1000, 3),
                (
                    f"{bank_green}/{len(banks)} bank proofs proven",
                    "UTR identity checked before amount",
                ),
            )
        )

        started = perf_counter()
        update = self._proof_ledger.apply_batch(
            batch,
            self._journal,
            compositions,
            banks,
            knowledge_cutoff=at,
            generated_at=at + timedelta(seconds=1),
        )
        proofs = tuple(
            proof
            for settlement in sorted(batch.settlements, key=lambda item: str(item.id))
            if (proof := self._proof_ledger.latest(settlement.id)) is not None
        )
        stages.append(
            DemoStage(
                "proofs",
                "Generate immutable reconciliation proofs",
                round((perf_counter() - started) * 1000, 3),
                (
                    f"{len(update.created_versions)} new proof version(s)",
                    f"{sum(p.status.value == 'proven_reconciled' for p in proofs)} green",
                ),
            )
        )

        started = perf_counter()
        manifests = _manifests(
            batch=batch,
            scope=self._scope,
            evaluated_at=at + timedelta(seconds=2),
            bank_complete=bank_complete,
        )
        coverage = build_evidence_coverage(
            scope=self._scope,
            batch=batch,
            manifests=manifests,
            proof_versions=proofs,
            assignments=(),
        )
        provider_activity = domain.Money(
            sum(proof.composition.settlement_amount.amount_paise for proof in proofs)
        )
        bank_proven = domain.Money(
            sum(
                proof.bank.observed_bank_credit.amount_paise
                for proof in proofs
                if proof.bank.status is BankReceiptStatus.PROVEN
            )
        )
        balance = build_balance_control(
            scope=self._scope,
            policy=self._policy,
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            reporting_timezone="UTC",
            opening_as_of=PERIOD_START,
            closing_as_of=PERIOD_END,
            opening_position=domain.Money.zero(),
            provider_activity=provider_activity,
            bank_proven_payouts=bank_proven,
            authoritative_adjustments=domain.Money.zero(),
            observed_closing_position=provider_activity - bank_proven,
        )
        close = build_close_readiness(
            policy=self._policy,
            manifests=manifests,
            proof_versions=proofs,
            coverage=coverage,
            balance=balance,
        )
        run = build_reconciliation_run(
            scope=self._scope,
            policy=self._policy,
            manifests=manifests,
            batch=batch,
            proof_versions=proofs,
            coverage=coverage,
            balance=balance,
            close_readiness=close,
            knowledge_cutoff=at + timedelta(seconds=2),
            started_at=at + timedelta(seconds=3),
            completed_at=at + timedelta(seconds=4),
            code_build_sha="judge-demo",
        )
        case_update = self._case_ledger.apply_run(
            run=run,
            policy=self._policy,
            manifests=manifests,
            proof_versions=proofs,
        )
        observations = tuple(
            self._case_ledger.observation_by_id(observation_id)
            for observation_id in case_update.created_observation_ids
        )
        stages.append(
            DemoStage(
                "controls",
                "Run close controls and create exceptions",
                round((perf_counter() - started) * 1000, 3),
                (
                    f"close: {close.status.value}",
                    f"{len(case_update.created_case_ids)} new case(s)",
                    f"{len(case_update.auto_closed_case_ids)} auto-closed",
                ),
            )
        )

        dispositions: tuple[ExceptionCaseDisposition, ...] = ()
        investigation: InvestigationRunResult | None = None
        if publish_current:
            pending_observation = next(
                obs for obs in observations if str(obs.settlement_id) == "setl_demo_pending"
            )
            first = self._case_ledger.append_disposition(
                case_id=pending_observation.case_id,
                sequence=1,
                actor_id="judge-demo-operator",
                occurred_at=run.completed_at + timedelta(seconds=1),
                kind=DispositionKind.ASSIGN_OWNER,
                owner="finance-ops",
            )
            second = self._case_ledger.append_disposition(
                case_id=pending_observation.case_id,
                sequence=2,
                actor_id="judge-demo-operator",
                occurred_at=run.completed_at + timedelta(seconds=2),
                kind=DispositionKind.REQUEST_SOURCE_CORRECTION,
                note="Awaiting authoritative bank delivery",
            )
            dispositions = (first, second)
            pending_proof = next(
                proof
                for proof in proofs
                if proof.settlement_id == pending_observation.settlement_id
            )
            investigation = run_investigation(
                _JudgeInvestigator(),
                case_state=self._case_ledger.state(pending_observation.case_id),
                observation=pending_observation,
                proof=pending_proof,
                journal=self._journal,
                as_of=run.completed_at + timedelta(seconds=3),
            )

        self._persist(
            batch=batch,
            new_proofs=update.created_versions,
            manifests=manifests,
            coverage=coverage,
            balance=balance,
            close=close,
            run=run,
            observations=observations,
            dispositions=dispositions,
            investigation=investigation,
            publish_current=publish_current,
        )
        return _RunParts(
            batch=batch,
            proofs=proofs,
            new_proofs=update.created_versions,
            manifests=manifests,
            run=run,
            coverage=coverage,
            balance=balance,
            close=close,
            observations=observations,
            dispositions=dispositions,
            investigation=investigation,
        )

    def _persist(
        self,
        *,
        batch: CanonicalBatch,
        new_proofs: tuple[ReconciliationProofVersion, ...],
        manifests: tuple[SourceDeliveryManifest, ...],
        coverage: EvidenceCoverageCertificate,
        balance: BalanceControlProof,
        close: CloseReadinessCertificate,
        run: ReconciliationRun,
        observations: tuple[ExceptionCaseObservation, ...],
        dispositions: tuple[ExceptionCaseDisposition, ...],
        investigation: InvestigationRunResult | None,
        publish_current: bool,
    ) -> None:
        for envelope in self._journal.entries():
            if envelope.id in self._persisted_envelopes:
                continue
            self._service.append_source(envelope)
            self._persisted_envelopes.add(envelope.id)
        self._service.persist_artifact(
            kind=ArtifactKind.RECONCILIATION_SCOPE,
            artifact_id=str(self._scope.id),
            payload=self._scope,
            scope_id=self._scope.id,
        )
        self._service.persist_artifact(
            kind=ArtifactKind.POLICY_VERSION,
            artifact_id=str(self._policy.id),
            payload=self._policy,
            scope_id=self._scope.id,
        )
        for manifest in manifests:
            self._service.persist_artifact(
                kind=ArtifactKind.SOURCE_DELIVERY_MANIFEST,
                artifact_id=str(manifest.id),
                payload=manifest,
                scope_id=self._scope.id,
                observed_at=manifest.evaluated_at,
            )
        for proof in new_proofs:
            self._service.persist_artifact(
                kind=ArtifactKind.PROOF_VERSION,
                artifact_id=str(proof.id),
                payload=proof,
                scope_id=self._scope.id,
                observed_at=proof.generated_at,
            )
        for kind, payload in (
            (ArtifactKind.EVIDENCE_COVERAGE, coverage),
            (ArtifactKind.BALANCE_CONTROL, balance),
            (ArtifactKind.CLOSE_READINESS, close),
        ):
            self._service.persist_artifact(
                kind=kind,
                artifact_id=str(payload.id),
                payload=payload,
                scope_id=self._scope.id,
            )
        if publish_current:
            self._service.publish_current(
                artifact_kind=ArtifactKind.RECONCILIATION_RUN,
                artifact_id=str(run.id),
                payload=run,
                scope_id=self._scope.id,
                observed_at=run.completed_at,
                pointer_kind=PointerKind.LATEST_RUN,
                stream_key=str(self._scope.id),
                expected_generation=self._run_generation,
            )
            self._run_generation += 1
        else:
            self._service.persist_artifact(
                kind=ArtifactKind.RECONCILIATION_RUN,
                artifact_id=str(run.id),
                payload=run,
                scope_id=self._scope.id,
                observed_at=run.completed_at,
            )
        for observation in observations:
            self._service.persist_artifact(
                kind=ArtifactKind.CASE_OBSERVATION,
                artifact_id=str(observation.id),
                payload=observation,
                scope_id=self._scope.id,
                observed_at=observation.observed_at,
            )
        for disposition in dispositions:
            self._service.persist_artifact(
                kind=ArtifactKind.CASE_DISPOSITION,
                artifact_id=str(disposition.id),
                payload=disposition,
                scope_id=self._scope.id,
                observed_at=disposition.occurred_at,
            )
            self._service.publish_current(
                artifact_kind=ArtifactKind.CASE_DISPOSITION,
                artifact_id=str(disposition.id),
                payload=disposition,
                scope_id=self._scope.id,
                observed_at=disposition.occurred_at,
                pointer_kind=PointerKind.LATEST_CASE_DISPOSITION,
                stream_key=str(disposition.case_id),
                expected_generation=disposition.sequence - 1,
            )
        for cluster in build_incident_clusters(run=run, observations=observations):
            self._service.persist_artifact(
                kind=ArtifactKind.INCIDENT_CLUSTER,
                artifact_id=str(cluster.id),
                payload=cluster,
                scope_id=self._scope.id,
                observed_at=run.completed_at,
            )
        if investigation is not None:
            self._service.persist_artifact(
                kind=ArtifactKind.INVESTIGATION_RESULT,
                artifact_id=str(investigation.id),
                payload=investigation,
                scope_id=self._scope.id,
                observed_at=investigation.as_of,
            )
            for trace in investigation.trace:
                self._service.persist_artifact(
                    kind=ArtifactKind.INVESTIGATION_TRACE,
                    artifact_id=str(trace.id),
                    payload=trace,
                    scope_id=self._scope.id,
                    observed_at=investigation.as_of,
                )
