from __future__ import annotations

import argparse
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

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
    IncidentCluster,
    InMemoryExceptionCaseLedger,
    build_incident_clusters,
)
from reflow.ingestion import ObservedBatch, ingest_observed_batch
from reflow.investigation import (
    InvestigationContext,
    InvestigationRunResult,
    ReadOnlyInvestigationTools,
    run_investigation,
)
from reflow.journal import InMemoryJournal
from reflow.money_graph import build_money_graph
from reflow.persistence import (
    ArtifactKind,
    PointerKind,
    PostgresApplicationStore,
    ReflowApplicationService,
)
from reflow.reconciliation_proof import InMemoryProofLedger, ReconciliationProofVersion
from reflow.settlement_proof import prove_all_settlement_compositions

PERIOD_START = datetime(2026, 8, 31, 0, 0, tzinfo=UTC)
PERIOD_END = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
RECEIVED_AT = datetime(2026, 9, 1, 15, 50, tzinfo=UTC)
EVALUATED_AT = datetime(2026, 9, 1, 15, 52, tzinfo=UTC)
RUN_COMPLETED_AT = datetime(2026, 9, 1, 15, 54, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class DemoBundle:
    scope: ReconciliationScope
    policy: ReconciliationPolicyVersion
    proof: ReconciliationProofVersion
    manifests: tuple[SourceDeliveryManifest, ...]
    coverage: EvidenceCoverageCertificate
    balance: BalanceControlProof
    close: CloseReadinessCertificate
    run: ReconciliationRun
    observations: tuple[ExceptionCaseObservation, ...]
    dispositions: tuple[ExceptionCaseDisposition, ...]
    clusters: tuple[IncidentCluster, ...]
    investigation: InvestigationRunResult
    journal: InMemoryJournal


class _DemoInvestigator:
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
            "hypothesis": "Bank evidence is unavailable and should be requested",
            "citations": [str(source_id)],
            "financial_claims": [],
            "next_action": "REQUEST_SOURCE",
            "request_source_kind": "bank",
        }


def _observed() -> ObservedBatch:
    return ObservedBatch(
        merchant_rows=(
            {
                "order_id": "order_gate18_demo",
                "amount_paise": 10_000,
                "currency": "INR",
                "created_at": (PERIOD_START + timedelta(hours=1)).isoformat(),
                "external_reference": "gate18-demo",
            },
        ),
        razorpay_events=(
            {
                "event_id": "evt_gate18_demo",
                "payment_id": "pay_gate18_demo",
                "order_id": "order_gate18_demo",
                "event_kind": "captured",
                "amount_paise": 10_000,
                "currency": "INR",
                "occurred_at": (PERIOD_START + timedelta(hours=1, minutes=1)).isoformat(),
                "received_at": (PERIOD_START + timedelta(hours=1, minutes=2)).isoformat(),
                "error_code": None,
                "error_reason": None,
            },
        ),
        recon_rows=(
            {
                "recon_id": "recon_gate18_demo",
                "settlement_id": "setl_gate18_demo",
                "entity_kind": "payment",
                "entity_id": "pay_gate18_demo",
                "gross_amount_paise": 10_000,
                "fee_paise": 100,
                "tax_paise": 18,
                "settlement_effect_paise": 9_882,
                "currency": "INR",
                "occurred_at": (PERIOD_START + timedelta(hours=3)).isoformat(),
            },
        ),
        settlement_rows=(
            {
                "settlement_id": "setl_gate18_demo",
                "amount_paise": 9_882,
                "currency": "INR",
                "processed_at": (PERIOD_START + timedelta(hours=5)).isoformat(),
                "utr": "UTR-GATE18-DEMO",
            },
        ),
        bank_rows=(),
    )


def build_demo_bundle() -> DemoBundle:
    journal = InMemoryJournal()
    batch = ingest_observed_batch(_observed(), journal, received_at=RECEIVED_AT)
    graph = build_money_graph(batch)
    compositions = prove_all_settlement_compositions(batch, graph)
    banks = prove_all_bank_receipts(batch)
    proof_update = InMemoryProofLedger().apply_batch(
        batch,
        journal,
        compositions,
        banks,
        knowledge_cutoff=RECEIVED_AT,
        generated_at=RECEIVED_AT + timedelta(minutes=1),
    )
    if len(proof_update.created_versions) != 1:
        raise RuntimeError("Gate 18 demo expects exactly one proof")
    proof = proof_update.created_versions[0]
    if proof.bank.status is not BankReceiptStatus.WAITING:
        raise RuntimeError("Gate 18 demo must remain a bank-waiting exception")

    scope = make_reconciliation_scope(
        merchant_account_id="merchant_gate18_demo",
        provider="razorpay",
        provider_account_id="rzp_gate18_demo",
        bank_account_id="bank_gate18_demo",
        currency=domain.Currency.INR,
        channel="payments",
    )
    policy = make_reconciliation_policy_version(
        version_label="gate18-demo-v1",
        required_source_kinds=tuple(domain.SourceKind),
        reporting_timezone="UTC",
        bank_wait_sla_seconds=3_600,
        materiality_thresholds_paise=(1_000, 5_000, 9_000),
    )
    manifests: list[SourceDeliveryManifest] = []
    for source_kind in domain.SourceKind:
        envelope_ids = tuple(
            link.envelope_id for link in batch.source_links if link.source_kind is source_kind
        )
        bank_missing = source_kind is domain.SourceKind.BANK
        manifests.append(
            make_source_delivery_manifest(
                scope=scope,
                source_kind=source_kind,
                source_account_id=scope.account_for(source_kind),
                delivery_mode=DeliveryMode.SNAPSHOT,
                period_start=PERIOD_START,
                period_end=PERIOD_END,
                reporting_timezone="UTC",
                expected_by=(
                    EVALUATED_AT - timedelta(hours=2)
                    if bank_missing
                    else EVALUATED_AT + timedelta(hours=1)
                ),
                evaluated_at=EVALUATED_AT,
                received_at=None if bank_missing else RECEIVED_AT,
                watermark_at=None if bank_missing else PERIOD_END,
                is_complete=not bank_missing,
                delivered_envelope_ids=() if bank_missing else envelope_ids,
                adapter_version="normalized-demo-v1",
                schema_fingerprint=f"gate18-demo-{source_kind.value}-v1",
            )
        )
    manifest_tuple = tuple(manifests)
    coverage = build_evidence_coverage(
        scope=scope,
        batch=batch,
        manifests=manifest_tuple,
        proof_versions=(proof,),
        assignments=(),
    )
    balance = build_balance_control(
        scope=scope,
        policy=policy,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        reporting_timezone="UTC",
        opening_as_of=PERIOD_START,
        closing_as_of=PERIOD_END,
        opening_position=domain.Money.zero(),
        provider_activity=proof.composition.settlement_amount,
        bank_proven_payouts=domain.Money.zero(),
        authoritative_adjustments=domain.Money.zero(),
        observed_closing_position=proof.composition.settlement_amount,
    )
    close = build_close_readiness(
        policy=policy,
        manifests=manifest_tuple,
        proof_versions=(proof,),
        coverage=coverage,
        balance=balance,
    )
    run = build_reconciliation_run(
        scope=scope,
        policy=policy,
        manifests=manifest_tuple,
        batch=batch,
        proof_versions=(proof,),
        coverage=coverage,
        balance=balance,
        close_readiness=close,
        knowledge_cutoff=EVALUATED_AT,
        started_at=EVALUATED_AT + timedelta(minutes=1),
        completed_at=RUN_COMPLETED_AT,
        code_build_sha="gate18-demo",
    )

    case_ledger = InMemoryExceptionCaseLedger()
    update = case_ledger.apply_run(
        run=run,
        policy=policy,
        manifests=manifest_tuple,
        proof_versions=(proof,),
    )
    observations = tuple(
        case_ledger.observation_by_id(observation_id)
        for observation_id in update.created_observation_ids
    )
    if len(observations) != 1:
        raise RuntimeError("Gate 18 demo expects exactly one exception observation")
    case_id = observations[0].case_id
    first_disposition = case_ledger.append_disposition(
        case_id=case_id,
        sequence=1,
        actor_id="demo-finance-operator",
        occurred_at=RUN_COMPLETED_AT + timedelta(minutes=1),
        kind=DispositionKind.ASSIGN_OWNER,
        owner="finance-ops",
        note=None,
    )
    second_disposition = case_ledger.append_disposition(
        case_id=case_id,
        sequence=2,
        actor_id="demo-finance-operator",
        occurred_at=RUN_COMPLETED_AT + timedelta(minutes=2),
        kind=DispositionKind.REQUEST_SOURCE_CORRECTION,
        note="Awaiting authoritative bank delivery",
    )
    clusters = build_incident_clusters(run=run, observations=observations)
    investigation = run_investigation(
        _DemoInvestigator(),
        case_state=case_ledger.state(case_id),
        observation=observations[0],
        proof=proof,
        journal=journal,
        as_of=RUN_COMPLETED_AT + timedelta(minutes=3),
    )
    return DemoBundle(
        scope=scope,
        policy=policy,
        proof=proof,
        manifests=manifest_tuple,
        coverage=coverage,
        balance=balance,
        close=close,
        run=run,
        observations=observations,
        dispositions=(first_disposition, second_disposition),
        clusters=clusters,
        investigation=investigation,
        journal=journal,
    )


def seed_demo(dsn: str) -> DemoBundle:
    bundle = build_demo_bundle()
    service = ReflowApplicationService(PostgresApplicationStore(dsn))
    for envelope in bundle.journal.entries():
        service.append_source(envelope)

    service.persist_artifact(
        kind=ArtifactKind.RECONCILIATION_SCOPE,
        artifact_id=str(bundle.scope.id),
        payload=bundle.scope,
        scope_id=bundle.scope.id,
        observed_at=PERIOD_START,
    )
    service.persist_artifact(
        kind=ArtifactKind.POLICY_VERSION,
        artifact_id=str(bundle.policy.id),
        payload=bundle.policy,
        scope_id=bundle.scope.id,
        observed_at=PERIOD_START,
    )
    for manifest in bundle.manifests:
        service.persist_artifact(
            kind=ArtifactKind.SOURCE_DELIVERY_MANIFEST,
            artifact_id=str(manifest.id),
            payload=manifest,
            scope_id=bundle.scope.id,
            observed_at=manifest.evaluated_at,
        )
    service.persist_artifact(
        kind=ArtifactKind.PROOF_VERSION,
        artifact_id=str(bundle.proof.id),
        payload=bundle.proof,
        scope_id=bundle.scope.id,
        observed_at=bundle.proof.generated_at,
    )

    coverage = bundle.coverage
    balance = bundle.balance
    close = bundle.close
    service.persist_artifact(
        kind=ArtifactKind.EVIDENCE_COVERAGE,
        artifact_id=str(coverage.id),
        payload=coverage,
        scope_id=bundle.scope.id,
        observed_at=RUN_COMPLETED_AT,
    )
    service.persist_artifact(
        kind=ArtifactKind.BALANCE_CONTROL,
        artifact_id=str(balance.id),
        payload=balance,
        scope_id=bundle.scope.id,
        observed_at=RUN_COMPLETED_AT,
    )
    service.persist_artifact(
        kind=ArtifactKind.CLOSE_READINESS,
        artifact_id=str(close.id),
        payload=close,
        scope_id=bundle.scope.id,
        observed_at=RUN_COMPLETED_AT,
    )
    service.publish_current(
        artifact_kind=ArtifactKind.RECONCILIATION_RUN,
        artifact_id=str(bundle.run.id),
        payload=bundle.run,
        scope_id=bundle.scope.id,
        observed_at=bundle.run.completed_at,
        pointer_kind=PointerKind.LATEST_RUN,
        stream_key=str(bundle.scope.id),
        expected_generation=0,
    )
    for observation in bundle.observations:
        service.persist_artifact(
            kind=ArtifactKind.CASE_OBSERVATION,
            artifact_id=str(observation.id),
            payload=observation,
            scope_id=bundle.scope.id,
            observed_at=observation.observed_at,
        )
    for disposition in bundle.dispositions:
        service.persist_artifact(
            kind=ArtifactKind.CASE_DISPOSITION,
            artifact_id=str(disposition.id),
            payload=disposition,
            scope_id=bundle.scope.id,
            observed_at=disposition.occurred_at,
        )
    for cluster in bundle.clusters:
        service.persist_artifact(
            kind=ArtifactKind.INCIDENT_CLUSTER,
            artifact_id=str(cluster.id),
            payload=cluster,
            scope_id=bundle.scope.id,
            observed_at=bundle.run.completed_at,
        )
    service.persist_artifact(
        kind=ArtifactKind.INVESTIGATION_RESULT,
        artifact_id=str(bundle.investigation.id),
        payload=bundle.investigation,
        scope_id=bundle.scope.id,
        observed_at=bundle.investigation.as_of,
    )
    for trace in bundle.investigation.trace:
        service.persist_artifact(
            kind=ArtifactKind.INVESTIGATION_TRACE,
            artifact_id=str(trace.id),
            payload=trace,
            scope_id=bundle.scope.id,
            observed_at=bundle.investigation.as_of,
        )
    return bundle


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed deterministic synthetic Gate 18 demo state")
    parser.add_argument("--dsn", default=os.getenv("REFLOW_POSTGRES_DSN"))
    args = parser.parse_args()
    if not args.dsn:
        parser.error("--dsn or REFLOW_POSTGRES_DSN is required")
    bundle = seed_demo(args.dsn)
    print(str(bundle.scope.id))


if __name__ == "__main__":
    main()
