from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from reflow import domain
from reflow.adapter_compiler.contracts import CanonicalRecordKind, FinancialControlTotal
from reflow.adapter_compiler.model_provider import (
    adapter_provider_from_environment,
    adapter_provider_status,
)
from reflow.adapter_compiler.proposal_pipeline import propose_and_validate_journaled
from reflow.bank_proof import BankReceiptProof, BankReceiptStatus, iter_bank_receipts
from reflow.control_plane import (
    DeliveryMode,
    build_balance_control,
    build_close_readiness,
    build_evidence_coverage,
    build_reconciliation_run,
    make_reconciliation_policy_version,
    make_reconciliation_scope,
    make_source_delivery_manifest,
)
from reflow.exception_cases import InMemoryExceptionCaseLedger
from reflow.ingestion import AdapterError, CanonicalBatch, ObservedBatch, ingest_observed_batch
from reflow.investigation import run_investigation
from reflow.investigation_model_provider import (
    investigation_provider_from_environment,
    investigation_provider_status,
)
from reflow.journal import InMemoryJournal, JournalConflictError
from reflow.money_graph import MoneyGraph, build_money_graph
from reflow.razorpay_acceptance import RazorpayAcceptanceClient, RazorpayAcceptanceError
from reflow.razorpay_integration import RazorpayEvidenceOrigin
from reflow.reconciliation_proof import (
    InMemoryProofLedger,
    ReconciliationProofVersion,
    ReconciliationStatus,
)
from reflow.settlement_proof import SettlementCompositionProof, iter_settlement_compositions
from reflow.simulator import WorldConfig, generate_world, observe_world
from reflow.simulator.truth import HiddenWorld

from .candidates import CandidateDecision, CandidateRun, CandidateStatus, run_fuzzy_threshold
from .profiles import EvaluationProfile, corruption_plan
from .scoring import EvaluationReport, project_hidden_truth, score_candidate_run


class PitchDemoPhase(StrEnum):
    READY = "ready"
    DATASET_READY = "dataset_ready"
    RUNNING = "running"
    COMPLETE = "complete"
    SOURCE_REJECTED = "source_rejected"
    TRUTH_UNLOCKED = "truth_unlocked"


@dataclass(frozen=True, slots=True)
class PitchDatasetConfig:
    settlement_count: int = 500
    profile: EvaluationProfile = EvaluationProfile.RECONCILIATION_ADVERSARIAL
    world_seed: int = 402
    observation_seed: int = 1402

    def __post_init__(self) -> None:
        if self.settlement_count not in {100, 250, 500, 1000}:
            raise ValueError("demo settlement_count must be one of 100, 250, 500, 1000")
        if not isinstance(self.profile, EvaluationProfile):
            raise TypeError("demo profile must be EvaluationProfile")


@dataclass(frozen=True, slots=True)
class PitchDatasetMetadata:
    settlement_count: int
    profile: str
    world_seed: int
    observation_seed: int
    observed_record_count: int
    source_counts: dict[str, int]
    dataset_sha256: str
    truth_commitment_sha256: str
    corruption_count: int


@dataclass(frozen=True, slots=True)
class PitchRunSummary:
    elapsed_seconds: float
    proof_pipeline_seconds: float
    settlements_per_second: float
    graph_edges: int
    proof_count: int
    status_counts: dict[str, int]
    exception_count: int
    source_rejection: dict[str, object] | None


@dataclass(frozen=True, slots=True)
class PitchEvaluationSummary:
    truth_settlement_count: int
    truth_reconciled: int
    reflow: dict[str, object]
    fuzzy: dict[str, object]


def _money(value: domain.Money) -> dict[str, object]:
    return {
        "amount_paise": value.amount_paise,
        "currency": value.currency.value,
        "display": f"₹{value.amount_paise / 100:,.2f}",
    }


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _observed_payload(observed: ObservedBatch) -> dict[str, object]:
    return {
        "merchant_rows": observed.merchant_rows,
        "razorpay_events": observed.razorpay_events,
        "recon_rows": observed.recon_rows,
        "settlement_rows": observed.settlement_rows,
        "bank_rows": observed.bank_rows,
    }


def _source_counts(observed: ObservedBatch) -> dict[str, int]:
    return {
        "merchant": len(observed.merchant_rows),
        "razorpay_payments": len(observed.razorpay_events),
        "razorpay_recon": len(observed.recon_rows),
        "razorpay_settlements": len(observed.settlement_rows),
        "bank": len(observed.bank_rows),
    }


def _candidate_run(
    batch: CanonicalBatch,
    proofs: tuple[ReconciliationProofVersion, ...],
) -> CandidateRun:
    status_map = {
        ReconciliationStatus.PROVEN_RECONCILED: CandidateStatus.RECONCILED,
        ReconciliationStatus.PENDING_BANK_CREDIT: CandidateStatus.UNRESOLVED,
        ReconciliationStatus.RESIDUAL: CandidateStatus.RESIDUAL,
        ReconciliationStatus.INCOMPLETE: CandidateStatus.INCOMPLETE,
        ReconciliationStatus.CONTRADICTED: CandidateStatus.CONTRADICTED,
    }
    recon_by_id = {row.id: row for row in batch.recon_entries}
    bank_by_id = {row.id: row for row in batch.bank_entries}
    decisions = tuple(
        CandidateDecision(
            settlement_id=proof.settlement_id,
            status=status_map[proof.status],
            settlement_amount=proof.composition.settlement_amount,
            composition_components=tuple(
                recon_by_id[row_id] for row_id in proof.composition.component_ids
            ),
            bank_entries=tuple(bank_by_id[row_id] for row_id in proof.bank.bank_entry_ids),
            reason_codes=proof.reason_codes,
        )
        for proof in sorted(proofs, key=lambda item: str(item.settlement_id))
    )
    return CandidateRun("ReFlow_Core", decisions)


def _report_payload(report: EvaluationReport) -> dict[str, object]:
    precision = (
        None
        if report.auto_reconciled == 0
        else report.true_auto_reconciled / report.auto_reconciled
    )
    recall = (
        None
        if report.truth_reconciled == 0
        else report.true_auto_reconciled / report.truth_reconciled
    )
    false_rate = (
        None
        if report.auto_reconciled == 0
        else report.false_auto_reconciled / report.auto_reconciled
    )
    return {
        "system_name": report.system_name,
        "auto_reconciled": report.auto_reconciled,
        "true_auto_reconciled": report.true_auto_reconciled,
        "false_auto_reconciled": report.false_auto_reconciled,
        "unresolved": report.unresolved,
        "precision": precision,
        "recall": recall,
        "silent_false_match_rate": false_rate,
        "status_counts": asdict(report.decision_status_counts),
    }


class PitchDemoService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with getattr(self, "_lock", threading.Lock()):
            self._phase = PitchDemoPhase.READY
            self._config: PitchDatasetConfig | None = None
            self._world: HiddenWorld | None = None
            self._observed: ObservedBatch | None = None
            self._metadata: PitchDatasetMetadata | None = None
            self._manifest: tuple[object, ...] = ()
            self._journal: InMemoryJournal | None = None
            self._batch: CanonicalBatch | None = None
            self._graph: MoneyGraph | None = None
            self._compositions: tuple[SettlementCompositionProof, ...] = ()
            self._banks: tuple[BankReceiptProof, ...] = ()
            self._proofs: tuple[ReconciliationProofVersion, ...] = ()
            self._run: CandidateRun | None = None
            self._fuzzy: CandidateRun | None = None
            self._run_summary: PitchRunSummary | None = None
            self._evaluation: PitchEvaluationSummary | None = None

    def status(self) -> dict[str, object]:
        return {
            "phase": self._phase.value,
            "dataset": None if self._metadata is None else asdict(self._metadata),
            "run": None if self._run_summary is None else asdict(self._run_summary),
            "truth_unlocked": self._evaluation is not None,
            "evaluation": None if self._evaluation is None else asdict(self._evaluation),
            "can_generate": self._phase not in {PitchDemoPhase.RUNNING},
            "can_run": self._phase is PitchDemoPhase.DATASET_READY,
            "can_unlock": self._phase is PitchDemoPhase.COMPLETE,
        }

    def generate(self, config: PitchDatasetConfig) -> dict[str, object]:
        with self._lock:
            if self._phase is PitchDemoPhase.RUNNING:
                raise RuntimeError("cannot replace dataset while reconciliation is running")
            world = generate_world(
                config.world_seed,
                WorldConfig(settlement_count=config.settlement_count),
            )
            bundle = observe_world(
                world,
                seed=config.observation_seed,
                plan=corruption_plan(config.profile),
            )
            observed = bundle.observed
            counts = _source_counts(observed)
            truth_projection = project_hidden_truth(world)
            metadata = PitchDatasetMetadata(
                settlement_count=config.settlement_count,
                profile=config.profile.value,
                world_seed=config.world_seed,
                observation_seed=config.observation_seed,
                observed_record_count=sum(counts.values()),
                source_counts=counts,
                dataset_sha256=_canonical_hash(_observed_payload(observed)),
                truth_commitment_sha256=_canonical_hash(asdict(truth_projection)),
                corruption_count=len(bundle.manifest),
            )
            self._config = config
            self._world = world
            self._observed = observed
            self._metadata = metadata
            self._manifest = tuple(bundle.manifest)
            self._journal = None
            self._batch = None
            self._graph = None
            self._compositions = ()
            self._banks = ()
            self._proofs = ()
            self._run = None
            self._fuzzy = None
            self._run_summary = None
            self._evaluation = None
            self._phase = PitchDemoPhase.DATASET_READY
            return self.status()

    def run_stream(self) -> Iterator[dict[str, object]]:
        with self._lock:
            if self._phase is not PitchDemoPhase.DATASET_READY:
                raise RuntimeError("generate a dataset before running reconciliation")
            assert self._observed is not None
            observed = self._observed
            settlement_count = len(observed.settlement_rows)
            self._phase = PitchDemoPhase.RUNNING

        started = time.perf_counter()
        received_at = datetime(2027, 1, 1, tzinfo=UTC)
        journal = InMemoryJournal()
        yield {
            "event": "stage_started",
            "stage": "ingestion",
            "label": "Journal and normalize source evidence",
            "total": self._metadata.observed_record_count if self._metadata else 0,
        }
        stage = time.perf_counter()
        try:
            batch = ingest_observed_batch(observed, journal, received_at=received_at)
        except (AdapterError, JournalConflictError) as exc:
            elapsed = time.perf_counter() - started
            summary = PitchRunSummary(
                elapsed_seconds=round(elapsed, 6),
                proof_pipeline_seconds=0.0,
                settlements_per_second=0.0,
                graph_edges=0,
                proof_count=0,
                status_counts={status.value: 0 for status in ReconciliationStatus},
                exception_count=0,
                source_rejection={
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "retained_raw_envelopes": len(journal),
                },
            )
            with self._lock:
                self._journal = journal
                self._run_summary = summary
                self._phase = PitchDemoPhase.SOURCE_REJECTED
            yield {"event": "source_rejected", "run": asdict(summary)}
            return
        yield {
            "event": "stage_completed",
            "stage": "ingestion",
            "duration_seconds": round(time.perf_counter() - stage, 6),
            "processed": len(journal),
            "source_counts": _source_counts(observed),
        }

        stage = time.perf_counter()
        yield {
            "event": "stage_started",
            "stage": "graph",
            "label": "Build authoritative Money Graph",
            "total": settlement_count,
        }
        graph = build_money_graph(batch)
        yield {
            "event": "stage_completed",
            "stage": "graph",
            "duration_seconds": round(time.perf_counter() - stage, 6),
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
        }

        proof_pipeline_started = time.perf_counter()
        stage = time.perf_counter()
        yield {
            "event": "stage_started",
            "stage": "composition",
            "label": "Prove settlement composition",
            "total": settlement_count,
        }
        compositions: list[SettlementCompositionProof] = []
        for index, composition_proof in enumerate(
            iter_settlement_compositions(batch, graph), start=1
        ):
            compositions.append(composition_proof)
            if index == settlement_count or index % 25 == 0:
                yield {
                    "event": "progress",
                    "stage": "composition",
                    "processed": index,
                    "total": settlement_count,
                    "latest_settlement_id": str(composition_proof.settlement_id),
                    "latest_status": composition_proof.status.value,
                }
        yield {
            "event": "stage_completed",
            "stage": "composition",
            "duration_seconds": round(time.perf_counter() - stage, 6),
            "processed": len(compositions),
        }

        stage = time.perf_counter()
        yield {
            "event": "stage_started",
            "stage": "bank",
            "label": "Verify bank receipt by UTR identity",
            "total": settlement_count,
        }
        banks: list[BankReceiptProof] = []
        for index, bank_proof in enumerate(iter_bank_receipts(batch), start=1):
            banks.append(bank_proof)
            if index == settlement_count or index % 25 == 0:
                yield {
                    "event": "progress",
                    "stage": "bank",
                    "processed": index,
                    "total": settlement_count,
                    "latest_settlement_id": str(bank_proof.settlement_id),
                    "latest_status": bank_proof.status.value,
                }
        yield {
            "event": "stage_completed",
            "stage": "bank",
            "duration_seconds": round(time.perf_counter() - stage, 6),
            "processed": len(banks),
        }

        stage = time.perf_counter()
        yield {
            "event": "stage_started",
            "stage": "proof",
            "label": "Generate immutable reconciliation proofs",
            "total": settlement_count,
        }
        ledger = InMemoryProofLedger()
        update = ledger.apply_batch(
            batch,
            journal,
            tuple(compositions),
            tuple(banks),
            knowledge_cutoff=received_at,
            generated_at=received_at + timedelta(microseconds=1),
        )
        proofs = update.created_versions
        proof_pipeline_seconds = time.perf_counter() - proof_pipeline_started
        status_counts = {status.value: 0 for status in ReconciliationStatus}
        for proof_version in proofs:
            status_counts[proof_version.status.value] += 1
        exception_count = len(proofs) - status_counts[ReconciliationStatus.PROVEN_RECONCILED.value]
        yield {
            "event": "stage_completed",
            "stage": "proof",
            "duration_seconds": round(time.perf_counter() - stage, 6),
            "processed": len(proofs),
            "status_counts": status_counts,
        }

        run = _candidate_run(batch, proofs)
        fuzzy = run_fuzzy_threshold(batch)
        elapsed = time.perf_counter() - started
        summary = PitchRunSummary(
            elapsed_seconds=round(elapsed, 6),
            proof_pipeline_seconds=round(proof_pipeline_seconds, 6),
            settlements_per_second=(
                0.0
                if proof_pipeline_seconds <= 0
                else round(len(proofs) / proof_pipeline_seconds, 2)
            ),
            graph_edges=len(graph.edges),
            proof_count=len(proofs),
            status_counts=status_counts,
            exception_count=exception_count,
            source_rejection=None,
        )
        with self._lock:
            self._journal = journal
            self._batch = batch
            self._graph = graph
            self._compositions = tuple(compositions)
            self._banks = tuple(banks)
            self._proofs = proofs
            self._run = run
            self._fuzzy = fuzzy
            self._run_summary = summary
            self._phase = PitchDemoPhase.COMPLETE
        yield {"event": "run_completed", "run": asdict(summary)}

    def settlements(self, *, status: str | None = None) -> list[dict[str, object]]:
        if self._phase not in {PitchDemoPhase.COMPLETE, PitchDemoPhase.TRUTH_UNLOCKED}:
            return []
        rows: list[dict[str, object]] = []
        for proof in self._proofs:
            if status is not None and proof.status.value != status:
                continue
            rows.append(
                {
                    "settlement_id": str(proof.settlement_id),
                    "status": proof.status.value,
                    "amount": _money(proof.composition.settlement_amount),
                    "composition_status": proof.composition.status.value,
                    "bank_status": proof.bank.status.value,
                    "composition_components": len(proof.composition.component_ids),
                    "reason_codes": list(proof.reason_codes),
                }
            )
        return rows

    def settlement_detail(self, settlement_id: str) -> dict[str, object]:
        if self._batch is None:
            raise RuntimeError("run reconciliation before requesting proof detail")
        proof = next(
            (item for item in self._proofs if str(item.settlement_id) == settlement_id),
            None,
        )
        if proof is None:
            raise KeyError(settlement_id)
        recon = {
            str(row.id): row
            for row in self._batch.recon_entries
            if row.settlement_id == proof.settlement_id
        }
        banks = {str(row.id): row for row in self._batch.bank_entries}
        components = [
            {
                "recon_id": str(row.id),
                "entity_kind": row.entity_kind.value,
                "entity_id": str(row.entity_id),
                "gross": _money(row.gross_amount),
                "fee": _money(row.fee),
                "tax": _money(row.tax),
                "settlement_effect": _money(row.settlement_effect),
            }
            for row in (recon[str(row_id)] for row_id in proof.composition.component_ids)
        ]
        bank_rows = [
            {
                "bank_entry_id": str(row.id),
                "amount": _money(row.amount),
                "utr": row.utr,
                "narration": row.narration,
            }
            for row in (banks[str(row_id)] for row_id in proof.bank.bank_entry_ids)
        ]
        return {
            "settlement_id": settlement_id,
            "status": proof.status.value,
            "settlement_amount": _money(proof.composition.settlement_amount),
            "observed_composition": _money(proof.composition.observed_composition),
            "composition_residual": _money(proof.composition.residual),
            "bank_observed": _money(proof.bank.observed_bank_credit),
            "bank_residual": _money(proof.bank.residual),
            "settlement_utr": proof.bank.settlement_utr,
            "reason_codes": list(proof.reason_codes),
            "components": components,
            "bank_entries": bank_rows,
            "source_envelope_count": len(proof.source_envelope_ids),
            "ai_investigatable": (
                proof.status is not ReconciliationStatus.PROVEN_RECONCILED
                and len(proof.source_envelope_ids) <= 64
            ),
        }

    def razorpay_status(self) -> dict[str, object]:
        mode = os.environ.get("REFLOW_RAZORPAY_MODE", "test").strip().lower()
        configured = all(
            bool(os.environ.get(name))
            for name in ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "REFLOW_RAZORPAY_ACCOUNT_ID")
        )
        return {
            "configured": configured,
            "mode": mode,
            "api": "https://api.razorpay.com/v1",
        }

    def probe_razorpay(self) -> dict[str, object]:
        status = self.razorpay_status()
        if not status["configured"]:
            raise RuntimeError("Razorpay API credentials are not configured")
        mode = status["mode"]
        if mode not in {"test", "live"}:
            raise RuntimeError("REFLOW_RAZORPAY_MODE must be 'test' or 'live'")
        origin = (
            RazorpayEvidenceOrigin.REAL_TEST_MODE
            if mode == "test"
            else RazorpayEvidenceOrigin.REAL_LIVE
        )
        key_id = os.environ["RAZORPAY_KEY_ID"]
        key_secret = os.environ["RAZORPAY_KEY_SECRET"]
        account_id = os.environ["REFLOW_RAZORPAY_ACCOUNT_ID"]
        client = RazorpayAcceptanceClient(
            key_id=key_id,
            key_secret=key_secret,
            account_id=account_id,
            evidence_origin=origin,
            max_pages=5,
            max_records=5_000,
        )
        try:
            payments = client.fetch_payments()
            settlements = client.fetch_settlements()
            recon = client.fetch_recon(year=2026, month=9)
        except RazorpayAcceptanceError as exc:
            raise RuntimeError(str(exc)) from exc
        payment_statuses: dict[str, int] = {}
        payment_methods: dict[str, int] = {}
        for payment in payments:
            payment_status = payment.get("status")
            if isinstance(payment_status, str):
                payment_statuses[payment_status] = payment_statuses.get(payment_status, 0) + 1
            method = payment.get("method")
            if isinstance(method, str):
                payment_methods[method] = payment_methods.get(method, 0) + 1
        return {
            "configured": True,
            "mode": mode,
            "account_fingerprint": hashlib.sha256(account_id.encode()).hexdigest()[:16],
            "payments": len(payments),
            "payment_statuses": payment_statuses,
            "payment_methods": payment_methods,
            "settlements": len(settlements),
            "recon_rows": len(recon),
            "endpoints": [
                "/v1/payments",
                "/v1/settlements",
                "/v1/settlements/recon/combined",
            ],
            "privacy": "aggregate counts only; payer fields are not returned to the demo UI",
        }

    def ai_status(self) -> dict[str, object]:
        return adapter_provider_status()

    def investigate_settlement(self, settlement_id: str) -> dict[str, object]:
        if self._batch is None or self._journal is None:
            raise RuntimeError("run reconciliation before investigating an exception")
        proof = next(
            (item for item in self._proofs if str(item.settlement_id) == settlement_id),
            None,
        )
        if proof is None:
            raise KeyError(settlement_id)
        if proof.status is ReconciliationStatus.PROVEN_RECONCILED:
            raise RuntimeError("proven settlements do not require exception investigation")
        if len(proof.source_envelope_ids) > 64:
            raise RuntimeError("selected proof exceeds the bounded AI evidence budget")

        scope = make_reconciliation_scope(
            merchant_account_id="merchant_pitch_demo",
            provider="razorpay",
            provider_account_id="rzp_pitch_demo",
            bank_account_id="bank_pitch_demo",
            currency=domain.Currency.INR,
            channel="payments",
        )
        policy = make_reconciliation_policy_version(
            version_label="pitch-demo-v1",
            required_source_kinds=tuple(domain.SourceKind),
            reporting_timezone="UTC",
            bank_wait_sla_seconds=3600,
            materiality_thresholds_paise=(50_000, 500_000, 1_000_000),
        )
        period_start = min(item.processed_at for item in self._batch.settlements) - timedelta(
            days=2
        )
        period_end = max(item.processed_at for item in self._batch.settlements) + timedelta(days=2)
        evaluated_at = max(
            period_end,
            max(item.knowledge_cutoff for item in self._proofs),
        ) + timedelta(days=1)
        bank_complete = proof.status is not ReconciliationStatus.PENDING_BANK_CREDIT
        manifests = []
        for source_kind in domain.SourceKind:
            envelope_ids = tuple(
                link.envelope_id
                for link in self._batch.source_links
                if link.source_kind is source_kind
            )
            complete = bank_complete if source_kind is domain.SourceKind.BANK else True
            manifests.append(
                make_source_delivery_manifest(
                    scope=scope,
                    source_kind=source_kind,
                    source_account_id=scope.account_for(source_kind),
                    delivery_mode=DeliveryMode.SNAPSHOT,
                    period_start=period_start,
                    period_end=period_end,
                    reporting_timezone="UTC",
                    expected_by=period_end,
                    evaluated_at=evaluated_at,
                    received_at=evaluated_at,
                    watermark_at=period_end if complete else None,
                    is_complete=complete,
                    delivered_envelope_ids=envelope_ids,
                    adapter_version="pitch-normalized-v1",
                    schema_fingerprint=f"pitch-{source_kind.value}-v1",
                )
            )
        manifest_tuple = tuple(manifests)
        coverage = build_evidence_coverage(
            scope=scope,
            batch=self._batch,
            manifests=manifest_tuple,
            proof_versions=self._proofs,
            assignments=(),
        )
        provider_activity = domain.Money(
            sum(item.composition.settlement_amount.amount_paise for item in self._proofs)
        )
        bank_proven = domain.Money(
            sum(
                item.bank.observed_bank_credit.amount_paise
                for item in self._proofs
                if item.bank.status is BankReceiptStatus.PROVEN
            )
        )
        balance = build_balance_control(
            scope=scope,
            policy=policy,
            period_start=period_start,
            period_end=period_end,
            reporting_timezone="UTC",
            opening_as_of=period_start,
            closing_as_of=period_end,
            opening_position=domain.Money.zero(),
            provider_activity=provider_activity,
            bank_proven_payouts=bank_proven,
            authoritative_adjustments=domain.Money.zero(),
            observed_closing_position=provider_activity - bank_proven,
        )
        close = build_close_readiness(
            policy=policy,
            manifests=manifest_tuple,
            proof_versions=self._proofs,
            coverage=coverage,
            balance=balance,
        )
        run = build_reconciliation_run(
            scope=scope,
            policy=policy,
            manifests=manifest_tuple,
            batch=self._batch,
            proof_versions=self._proofs,
            coverage=coverage,
            balance=balance,
            close_readiness=close,
            knowledge_cutoff=evaluated_at,
            started_at=evaluated_at + timedelta(seconds=1),
            completed_at=evaluated_at + timedelta(seconds=2),
            code_build_sha="pitch-demo",
        )
        case_ledger = InMemoryExceptionCaseLedger()
        case_update = case_ledger.apply_run(
            run=run,
            policy=policy,
            manifests=manifest_tuple,
            proof_versions=self._proofs,
        )
        observation = next(
            (
                case_ledger.observation_by_id(observation_id)
                for observation_id in case_update.created_observation_ids
                if case_ledger.observation_by_id(observation_id).settlement_id
                == proof.settlement_id
            ),
            None,
        )
        if observation is None:
            raise RuntimeError("selected non-green proof did not produce an exception case")
        result = run_investigation(
            investigation_provider_from_environment(),
            case_state=case_ledger.state(observation.case_id),
            observation=observation,
            proof=proof,
            journal=self._journal,
            as_of=run.completed_at + timedelta(seconds=3),
        )
        return {
            "provider": investigation_provider_status(),
            "settlement_id": settlement_id,
            "case_id": str(result.case_id),
            "result_id": str(result.id),
            "status": result.status.value,
            "next_action": result.next_action.value,
            "hypothesis": result.hypothesis,
            "request_source_kind": (
                None if result.request_source_kind is None else result.request_source_kind.value
            ),
            "citations": [str(value) for value in result.citations],
            "financial_claims": [
                {
                    "fact": claim.fact.value,
                    "amount": _money(claim.amount),
                }
                for claim in result.financial_claims
            ],
            "trace": [
                {
                    "sequence": item.sequence,
                    "tool": item.tool.value,
                    "outcome": item.outcome.value,
                    "returned_refs": list(item.returned_refs),
                }
                for item in result.trace
            ],
            "rejection_reason": result.rejection_reason,
            "authority": "read_only_evidence; no financial-truth mutation",
        }

    def propose_bank_schema_adapter(self) -> dict[str, object]:
        provider = adapter_provider_from_environment()
        rows = (
            {
                "Txn": "bank_export_001",
                "Credit": "2417.82",
                "Date": "31/08/2026",
                "Memo": "RAZORPAY SETTLEMENT",
                "Reference": "UTR-DEMO-001",
                "Timezone": "Asia/Kolkata",
            },
            {
                "Txn": "bank_export_002",
                "Credit": "998.82",
                "Date": "02/09/2026",
                "Memo": "RAZORPAY SETTLEMENT",
                "Reference": "UTR-DEMO-002",
                "Timezone": "Asia/Kolkata",
            },
            {
                "Txn": "bank_export_003",
                "Credit": "1250.00",
                "Date": "04/09/2026",
                "Memo": "RAZORPAY SETTLEMENT",
                "Reference": "UTR-DEMO-003",
                "Timezone": "Asia/Kolkata",
            },
        )
        control_total = 241_782 + 99_882 + 125_000
        evaluation = propose_and_validate_journaled(
            provider,
            rows,
            InMemoryJournal(),
            batch_id="pitch-bank-schema-drift",
            received_at=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
            adapter_id="pitch_bank_schema_adapter",
            version=1,
            source_kind=domain.SourceKind.BANK,
            record_kind=CanonicalRecordKind.BANK_ENTRY,
            sample_limit=3,
            financial_control=FinancialControlTotal(
                target_field="amount_paise",
                expected_total_paise=control_total,
                expected_row_count=len(rows),
                evidence_label="synthetic bank export control total",
            ),
        )
        proposal = evaluation.proposal
        report = proposal.sample_report
        return {
            "provider": adapter_provider_status(),
            "source_columns": list(rows[0]),
            "sample_rows": list(rows),
            "target_fields": list(proposal.context.target_fields),
            "mappings": [
                {
                    "target_field": mapping.target_field,
                    "source_column": mapping.source_column,
                    "transform": mapping.transform.value,
                    "constant": mapping.constant,
                    "date_format": mapping.date_format,
                    "timezone_offset_minutes": mapping.timezone_offset_minutes,
                }
                for mapping in proposal.proposed_spec.mappings
            ],
            "validation_state": None if report is None else report.state.value,
            "financial_control_verified": (
                False if report is None else report.financial_control_verified
            ),
            "error_messages": [] if report is None else list(report.error_messages),
            "rejection_reason": proposal.rejection_reason,
            "retained_raw_envelopes": len(evaluation.source_envelope_ids),
            "expected_total": _money(domain.Money(control_total)),
        }

    def unlock_truth(self) -> dict[str, object]:
        with self._lock:
            if self._phase is not PitchDemoPhase.COMPLETE:
                raise RuntimeError("truth can only be unlocked after a completed run")
            assert self._world is not None
            assert self._run is not None
            assert self._fuzzy is not None
            truth = project_hidden_truth(self._world)
            reflow_report = score_candidate_run(truth, self._run)
            fuzzy_report = score_candidate_run(truth, self._fuzzy)
            evaluation = PitchEvaluationSummary(
                truth_settlement_count=len(truth.settlements),
                truth_reconciled=sum(item.reconciled for item in truth.settlements),
                reflow=_report_payload(reflow_report),
                fuzzy=_report_payload(fuzzy_report),
            )
            self._evaluation = evaluation
            self._phase = PitchDemoPhase.TRUTH_UNLOCKED
            return asdict(evaluation)


__all__ = [
    "PitchDatasetConfig",
    "PitchDemoPhase",
    "PitchDemoService",
]
