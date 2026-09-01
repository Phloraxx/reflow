from __future__ import annotations

import inspect
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import pytest

import reflow.exception_cases as exception_cases_module
from reflow.bank_proof import BankReceiptStatus, prove_all_bank_receipts
from reflow.control_plane import (
    DeliveryMode,
    ReconciliationPolicyVersion,
    ReconciliationRun,
    ReconciliationScope,
    SourceCompleteness,
    SourceDeliveryManifest,
    build_balance_control,
    build_close_readiness,
    build_evidence_coverage,
    build_reconciliation_run,
    make_reconciliation_policy_version,
    make_reconciliation_scope,
    make_source_delivery_manifest,
)
from reflow.domain import Currency, Money, SourceKind
from reflow.exception_cases import (
    CaseResolution,
    CaseWorkflowStatus,
    DispositionKind,
    ExceptionCaseError,
    InMemoryExceptionCaseLedger,
    build_incident_clusters,
)
from reflow.ingestion import ObservedBatch, ingest_observed_batch
from reflow.journal import InMemoryJournal
from reflow.money_graph import build_money_graph
from reflow.reconciliation_proof import (
    InMemoryProofLedger,
    ReconciliationProofVersion,
    ReconciliationStatus,
)
from reflow.settlement_proof import prove_all_settlement_compositions

PERIOD_START = datetime(2026, 8, 31, 0, 0, tzinfo=UTC)
PERIOD_END = PERIOD_START + timedelta(days=1)
RUN1_AT = PERIOD_END + timedelta(hours=1)
RUN2_AT = RUN1_AT + timedelta(days=1)
ALL_SOURCES = tuple(SourceKind)


@dataclass(frozen=True, slots=True)
class SettlementSpec:
    suffix: str
    settlement_amount: int
    utr: str
    bank_amount: int | None = None

    @property
    def gross(self) -> int:
        return self.settlement_amount + 118


@dataclass(frozen=True, slots=True)
class RunBundle:
    scope: ReconciliationScope
    policy: ReconciliationPolicyVersion
    batch: object
    proofs: tuple[ReconciliationProofVersion, ...]
    manifests: tuple[SourceDeliveryManifest, ...]
    run: ReconciliationRun


def _scope(
    *, merchant: str = "merchant_demo", provider_account: str = "rzp_demo"
) -> ReconciliationScope:
    return make_reconciliation_scope(
        merchant_account_id=merchant,
        provider="razorpay",
        provider_account_id=provider_account,
        bank_account_id="bank_demo",
        currency=Currency.INR,
        channel="payments",
    )


def _policy(
    *,
    label: str = "gate14-test-v1",
    thresholds: tuple[int, int, int] = (10_000, 100_000, 1_000_000),
) -> ReconciliationPolicyVersion:
    return make_reconciliation_policy_version(
        version_label=label,
        required_source_kinds=ALL_SOURCES,
        reporting_timezone="UTC",
        bank_wait_sla_seconds=3600,
        materiality_thresholds_paise=thresholds,
    )


def _observed(*specs: SettlementSpec) -> ObservedBatch:
    merchant_rows = []
    payment_rows = []
    recon_rows = []
    settlement_rows = []
    bank_rows = []
    for index, spec in enumerate(specs, start=1):
        offset = timedelta(minutes=index)
        merchant_rows.append(
            {
                "order_id": f"order_{spec.suffix}",
                "amount_paise": spec.gross,
                "currency": "INR",
                "created_at": (PERIOD_START + offset).isoformat(),
                "external_reference": f"ref-{spec.suffix}",
            }
        )
        payment_rows.append(
            {
                "event_id": f"evt_{spec.suffix}",
                "payment_id": f"pay_{spec.suffix}",
                "order_id": f"order_{spec.suffix}",
                "event_kind": "captured",
                "amount_paise": spec.gross,
                "currency": "INR",
                "occurred_at": (PERIOD_START + timedelta(minutes=10) + offset).isoformat(),
                "received_at": (PERIOD_START + timedelta(minutes=11) + offset).isoformat(),
                "error_code": None,
                "error_reason": None,
            }
        )
        recon_rows.append(
            {
                "recon_id": f"recon_{spec.suffix}",
                "settlement_id": f"setl_{spec.suffix}",
                "entity_kind": "payment",
                "entity_id": f"pay_{spec.suffix}",
                "gross_amount_paise": spec.gross,
                "fee_paise": 100,
                "tax_paise": 18,
                "settlement_effect_paise": spec.settlement_amount,
                "currency": "INR",
                "occurred_at": (PERIOD_START + timedelta(hours=2) + offset).isoformat(),
            }
        )
        settlement_rows.append(
            {
                "settlement_id": f"setl_{spec.suffix}",
                "amount_paise": spec.settlement_amount,
                "currency": "INR",
                "processed_at": (PERIOD_START + timedelta(hours=4) + offset).isoformat(),
                "utr": spec.utr,
            }
        )
        if spec.bank_amount is not None:
            bank_rows.append(
                {
                    "bank_entry_id": f"bank_{spec.suffix}",
                    "amount_paise": spec.bank_amount,
                    "currency": "INR",
                    "occurred_at": (PERIOD_START + timedelta(hours=5) + offset).isoformat(),
                    "narration": f"Razorpay settlement {spec.utr}",
                    "utr": spec.utr,
                }
            )
    return ObservedBatch(
        merchant_rows=tuple(merchant_rows),
        razorpay_events=tuple(payment_rows),
        recon_rows=tuple(recon_rows),
        settlement_rows=tuple(settlement_rows),
        bank_rows=tuple(bank_rows),
    )


def _manifests(
    *,
    batch,
    scope: ReconciliationScope,
    received_at: datetime,
    bank_complete: bool = True,
) -> tuple[SourceDeliveryManifest, ...]:
    manifests = []
    for source_kind in ALL_SOURCES:
        envelope_ids = tuple(
            link.envelope_id for link in batch.source_links if link.source_kind is source_kind
        )
        complete = bank_complete if source_kind is SourceKind.BANK else True
        manifests.append(
            make_source_delivery_manifest(
                scope=scope,
                source_kind=source_kind,
                source_account_id=scope.account_for(source_kind),
                delivery_mode=DeliveryMode.SNAPSHOT,
                period_start=PERIOD_START,
                period_end=PERIOD_END,
                reporting_timezone="UTC",
                expected_by=received_at + timedelta(hours=1),
                evaluated_at=received_at,
                received_at=received_at,
                watermark_at=PERIOD_END if complete else None,
                is_complete=complete,
                delivered_envelope_ids=envelope_ids,
                adapter_version="normalized-v1",
                schema_fingerprint=f"schema-{source_kind.value}-v1",
            )
        )
    return tuple(manifests)


def _run_from_parts(
    *,
    scope: ReconciliationScope,
    policy: ReconciliationPolicyVersion,
    batch,
    proofs: tuple[ReconciliationProofVersion, ...],
    manifests: tuple[SourceDeliveryManifest, ...],
    completed_at: datetime,
) -> ReconciliationRun:
    coverage = build_evidence_coverage(
        scope=scope,
        batch=batch,
        manifests=manifests,
        proof_versions=proofs,
        assignments=(),
    )
    provider_activity = Money(
        sum(proof.composition.settlement_amount.amount_paise for proof in proofs)
    )
    proven_bank = Money(
        sum(
            proof.bank.observed_bank_credit.amount_paise
            for proof in proofs
            if proof.bank.status is BankReceiptStatus.PROVEN
        )
    )
    balance = build_balance_control(
        scope=scope,
        policy=policy,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        reporting_timezone="UTC",
        opening_as_of=PERIOD_START,
        closing_as_of=PERIOD_END,
        opening_position=Money.zero(),
        provider_activity=provider_activity,
        bank_proven_payouts=proven_bank,
        authoritative_adjustments=Money.zero(),
        observed_closing_position=provider_activity - proven_bank,
    )
    close = build_close_readiness(
        policy=policy,
        manifests=manifests,
        proof_versions=proofs,
        coverage=coverage,
        balance=balance,
    )
    latest_source_time = max(manifest.evaluated_at for manifest in manifests)
    latest_proof_time = max(proof.generated_at for proof in proofs)
    knowledge_cutoff = max(latest_source_time, max(proof.knowledge_cutoff for proof in proofs))
    started_at = max(knowledge_cutoff, latest_proof_time) + timedelta(seconds=1)
    assert completed_at >= started_at
    return build_reconciliation_run(
        scope=scope,
        policy=policy,
        manifests=manifests,
        batch=batch,
        proof_versions=proofs,
        coverage=coverage,
        balance=balance,
        close_readiness=close,
        knowledge_cutoff=knowledge_cutoff,
        started_at=started_at,
        completed_at=completed_at,
        code_build_sha="gate14-test",
    )


def _bundle(
    *specs: SettlementSpec,
    scope: ReconciliationScope | None = None,
    policy: ReconciliationPolicyVersion | None = None,
    at: datetime = RUN1_AT,
    bank_complete: bool = True,
    journal: InMemoryJournal | None = None,
    proof_ledger: InMemoryProofLedger | None = None,
) -> tuple[RunBundle, InMemoryJournal, InMemoryProofLedger]:
    scope = scope or _scope()
    policy = policy or _policy()
    journal = journal or InMemoryJournal()
    proof_ledger = proof_ledger or InMemoryProofLedger()
    batch = ingest_observed_batch(_observed(*specs), journal, received_at=at)
    graph = build_money_graph(batch)
    compositions = prove_all_settlement_compositions(batch, graph)
    banks = prove_all_bank_receipts(batch)
    proof_ledger.apply_batch(
        batch,
        journal,
        compositions,
        banks,
        knowledge_cutoff=at,
        generated_at=at + timedelta(seconds=1),
    )
    proofs = tuple(
        proof
        for settlement in sorted(batch.settlements, key=lambda row: str(row.id))
        if (proof := proof_ledger.latest(settlement.id)) is not None
    )
    manifests = _manifests(
        batch=batch,
        scope=scope,
        received_at=at,
        bank_complete=bank_complete,
    )
    run = _run_from_parts(
        scope=scope,
        policy=policy,
        batch=batch,
        proofs=proofs,
        manifests=manifests,
        completed_at=at + timedelta(seconds=3),
    )
    return RunBundle(scope, policy, batch, proofs, manifests, run), journal, proof_ledger


def _rerun(
    bundle: RunBundle,
    *,
    completed_at: datetime,
    policy: ReconciliationPolicyVersion | None = None,
    bank_complete: bool | None = None,
) -> RunBundle:
    policy = policy or bundle.policy
    if bank_complete is None:
        bank_manifest = next(
            manifest
            for manifest in bundle.manifests
            if manifest.source_kind is SourceKind.BANK
        )
        bank_complete = bank_manifest.completeness is SourceCompleteness.COMPLETE
    manifests = _manifests(
        batch=bundle.batch,
        scope=bundle.scope,
        received_at=completed_at - timedelta(seconds=4),
        bank_complete=bank_complete,
    )
    run = _run_from_parts(
        scope=bundle.scope,
        policy=policy,
        batch=bundle.batch,
        proofs=bundle.proofs,
        manifests=manifests,
        completed_at=completed_at,
    )
    return RunBundle(bundle.scope, policy, bundle.batch, bundle.proofs, manifests, run)


def _apply(ledger: InMemoryExceptionCaseLedger, bundle: RunBundle, proofs=None):
    return ledger.apply_run(
        run=bundle.run,
        policy=bundle.policy,
        manifests=bundle.manifests,
        proof_versions=bundle.proofs if proofs is None else proofs,
    )


def _pending_bundle(**kwargs):
    return _bundle(SettlementSpec("1", 9882, "UTR-DEMO-1"), **kwargs)


def test_unchanged_non_green_economics_retains_case_identity_across_runs() -> None:
    first, _, _ = _pending_bundle()
    second = _rerun(first, completed_at=RUN2_AT + timedelta(seconds=3))
    ledger = InMemoryExceptionCaseLedger()

    first_update = _apply(ledger, first)
    second_update = _apply(ledger, second)

    assert len(first_update.created_case_ids) == 1
    case_id = first_update.created_case_ids[0]
    assert second_update.created_case_ids == ()
    assert ledger.state(case_id).observation_count == 2
    assert (
        ledger.observations(case_id)[0].tracking_key
        == ledger.observations(case_id)[1].tracking_key
    )


def test_first_last_seen_and_age_derive_from_immutable_run_times() -> None:
    first, _, _ = _pending_bundle()
    second = _rerun(first, completed_at=RUN2_AT + timedelta(seconds=3))
    ledger = InMemoryExceptionCaseLedger()
    case_id = _apply(ledger, first).created_case_ids[0]
    _apply(ledger, second)

    state = ledger.state(case_id)
    assert state.first_seen_at == first.run.completed_at
    assert state.last_seen_at == second.run.completed_at
    assert state.first_seen_run_id == first.run.id
    assert state.last_seen_run_id == second.run.id
    assert state.age_seconds(second.run.completed_at + timedelta(hours=2)) == int(
        (second.run.completed_at + timedelta(hours=2) - first.run.completed_at).total_seconds()
    )


def test_same_run_replay_is_idempotent() -> None:
    bundle, _, _ = _pending_bundle()
    ledger = InMemoryExceptionCaseLedger()
    first = _apply(ledger, bundle)
    second = _apply(ledger, bundle)
    case_id = first.created_case_ids[0]

    assert second.created_observation_ids == ()
    assert second.created_case_ids == ()
    assert ledger.state(case_id).observation_count == 1


def test_later_green_proof_auto_closes_without_rewriting_history() -> None:
    first, journal, proof_ledger = _pending_bundle()
    second, _, _ = _bundle(
        SettlementSpec("1", 9882, "UTR-DEMO-1", bank_amount=9882),
        scope=first.scope,
        policy=first.policy,
        at=RUN2_AT,
        journal=journal,
        proof_ledger=proof_ledger,
    )
    ledger = InMemoryExceptionCaseLedger()
    case_id = _apply(ledger, first).created_case_ids[0]
    before = ledger.observations(case_id)[0]
    _apply(ledger, second)

    state = ledger.state(case_id)
    assert state.financial_status is ReconciliationStatus.PROVEN_RECONCILED
    assert state.workflow_status is CaseWorkflowStatus.CLOSED
    assert state.resolution is CaseResolution.PROOF_RECONCILED
    assert state.observation_count == 2
    assert ledger.observations(case_id)[0] == before


def test_changed_settlement_amount_creates_new_case_and_supersedes_old() -> None:
    scope = _scope()
    first, _, _ = _pending_bundle(scope=scope)
    second, _, _ = _bundle(
        SettlementSpec("1", 19882, "UTR-DEMO-1"),
        scope=scope,
        at=RUN2_AT,
    )
    ledger = InMemoryExceptionCaseLedger()
    old_id = _apply(ledger, first).created_case_ids[0]
    update = _apply(ledger, second)
    new_id = update.created_case_ids[0]

    assert new_id != old_id
    assert ledger.state(old_id).resolution is CaseResolution.ECONOMIC_IDENTITY_CHANGED
    assert ledger.state(old_id).superseded_by_case_id == new_id
    assert ledger.state(new_id).owner is None
    assert ledger.state(new_id).disposition_count == 0


def test_changed_utr_creates_new_case_and_supersedes_old() -> None:
    scope = _scope()
    first, _, _ = _pending_bundle(scope=scope)
    second, _, _ = _bundle(
        SettlementSpec("1", 9882, "UTR-DEMO-CHANGED"),
        scope=scope,
        at=RUN2_AT,
    )
    ledger = InMemoryExceptionCaseLedger()
    old_id = _apply(ledger, first).created_case_ids[0]
    new_id = _apply(ledger, second).created_case_ids[0]

    assert new_id != old_id
    assert ledger.state(old_id).superseded_by_case_id == new_id


def test_reason_change_keeps_case_identity_but_changes_fingerprint() -> None:
    first, journal, proof_ledger = _pending_bundle()
    second, _, _ = _bundle(
        SettlementSpec("1", 9882, "UTR-DEMO-1", bank_amount=9881),
        scope=first.scope,
        policy=first.policy,
        at=RUN2_AT,
        journal=journal,
        proof_ledger=proof_ledger,
    )
    ledger = InMemoryExceptionCaseLedger()
    case_id = _apply(ledger, first).created_case_ids[0]
    _apply(ledger, second)
    observations = ledger.observations(case_id)

    assert observations[0].financial_status is ReconciliationStatus.PENDING_BANK_CREDIT
    assert observations[1].financial_status is ReconciliationStatus.RESIDUAL
    assert observations[0].incident_fingerprint_id != observations[1].incident_fingerprint_id
    assert observations[0].case_id == observations[1].case_id


def test_policy_materiality_change_is_visible_without_changing_case_or_truth() -> None:
    first_policy = _policy(label="strict", thresholds=(1000, 5000, 9000))
    second_policy = _policy(label="relaxed", thresholds=(10_000, 100_000, 1_000_000))
    first, _, _ = _pending_bundle(policy=first_policy)
    second = _rerun(
        first,
        completed_at=RUN2_AT + timedelta(seconds=3),
        policy=second_policy,
    )
    ledger = InMemoryExceptionCaseLedger()
    case_id = _apply(ledger, first).created_case_ids[0]
    _apply(ledger, second)
    before, after = ledger.observations(case_id)

    assert before.policy_version_id != after.policy_version_id
    assert before.materiality_band != after.materiality_band
    assert before.financial_status is after.financial_status
    assert before.tracking_key == after.tracking_key


def test_different_scope_never_inherits_another_scope_case() -> None:
    first, _, _ = _pending_bundle(scope=_scope(merchant="merchant_a", provider_account="rzp_a"))
    second, _, _ = _pending_bundle(
        scope=_scope(merchant="merchant_b", provider_account="rzp_b"),
        at=RUN2_AT,
    )
    ledger = InMemoryExceptionCaseLedger()
    first_id = _apply(ledger, first).created_case_ids[0]
    second_id = _apply(ledger, second).created_case_ids[0]

    assert first_id != second_id
    assert ledger.state(first_id).superseded_by_case_id is None


def test_run_proof_id_set_mismatch_fails_closed() -> None:
    bundle, _, _ = _pending_bundle()
    with pytest.raises(ExceptionCaseError, match=r"proof.*run|run.*proof"):
        _apply(InMemoryExceptionCaseLedger(), bundle, proofs=())


def test_observation_order_is_deterministic_under_proof_permutation() -> None:
    bundle, _, _ = _bundle(
        SettlementSpec("1", 9882, "UTR-1"),
        SettlementSpec("2", 19882, "UTR-2"),
    )
    left = InMemoryExceptionCaseLedger()
    right = InMemoryExceptionCaseLedger()

    update_left = _apply(left, bundle)
    update_right = _apply(right, bundle, proofs=tuple(reversed(bundle.proofs)))

    assert update_left.created_observation_ids == update_right.created_observation_ids
    assert update_left.created_case_ids == update_right.created_case_ids


def test_dispositions_are_append_only_sequence_safe_content_addressed_and_replayable() -> None:
    bundle, _, _ = _pending_bundle()
    ledger = InMemoryExceptionCaseLedger()
    case_id = _apply(ledger, bundle).created_case_ids[0]
    when = bundle.run.completed_at + timedelta(minutes=1)

    first = ledger.append_disposition(
        case_id=case_id,
        sequence=1,
        actor_id="ops@example.test",
        occurred_at=when,
        kind=DispositionKind.ASSIGN_OWNER,
        owner="finance-team",
        note="triage",
    )
    replay = ledger.append_disposition(
        case_id=case_id,
        sequence=1,
        actor_id="ops@example.test",
        occurred_at=when,
        kind=DispositionKind.ASSIGN_OWNER,
        owner="finance-team",
        note="triage",
    )
    assert replay == first
    assert ledger.dispositions(case_id) == (first,)

    with pytest.raises(ExceptionCaseError, match="sequence"):
        ledger.append_disposition(
            case_id=case_id,
            sequence=1,
            actor_id="other@example.test",
            occurred_at=when,
            kind=DispositionKind.ASSIGN_OWNER,
            owner="other-team",
        )
    with pytest.raises(ExceptionCaseError, match="sequence"):
        ledger.append_disposition(
            case_id=case_id,
            sequence=3,
            actor_id="ops@example.test",
            occurred_at=when + timedelta(minutes=1),
            kind=DispositionKind.ACKNOWLEDGE,
        )


def test_owner_and_workflow_state_derive_from_dispositions() -> None:
    bundle, _, _ = _pending_bundle()
    ledger = InMemoryExceptionCaseLedger()
    case_id = _apply(ledger, bundle).created_case_ids[0]
    when = bundle.run.completed_at + timedelta(minutes=1)

    ledger.append_disposition(
        case_id=case_id,
        sequence=1,
        actor_id="ops",
        occurred_at=when,
        kind=DispositionKind.ASSIGN_OWNER,
        owner="alice",
    )
    assert ledger.state(case_id).owner == "alice"
    assert ledger.state(case_id).workflow_status is CaseWorkflowStatus.OPEN
    ledger.append_disposition(
        case_id=case_id,
        sequence=2,
        actor_id="alice",
        occurred_at=when + timedelta(minutes=1),
        kind=DispositionKind.ACKNOWLEDGE,
    )
    assert ledger.state(case_id).workflow_status is CaseWorkflowStatus.ACKNOWLEDGED
    ledger.append_disposition(
        case_id=case_id,
        sequence=3,
        actor_id="alice",
        occurred_at=when + timedelta(minutes=2),
        kind=DispositionKind.REQUEST_SOURCE_CORRECTION,
    )
    assert ledger.state(case_id).workflow_status is CaseWorkflowStatus.AWAITING_SOURCE
    assert ledger.state(case_id).owner == "alice"


@pytest.mark.parametrize(
    ("kind", "resolution"),
    [
        (DispositionKind.CLOSE, CaseResolution.OPERATOR_CLOSED),
        (
            DispositionKind.ACCEPT_OPERATIONAL_VARIANCE,
            CaseResolution.OPERATIONAL_VARIANCE_ACCEPTED,
        ),
    ],
)
def test_operator_closure_never_changes_financial_truth(kind, resolution) -> None:
    bundle, _, _ = _pending_bundle()
    ledger = InMemoryExceptionCaseLedger()
    case_id = _apply(ledger, bundle).created_case_ids[0]
    ledger.append_disposition(
        case_id=case_id,
        sequence=1,
        actor_id="ops",
        occurred_at=bundle.run.completed_at + timedelta(minutes=1),
        kind=kind,
    )

    state = ledger.state(case_id)
    assert state.workflow_status is CaseWorkflowStatus.CLOSED
    assert state.resolution is resolution
    assert state.financial_status is ReconciliationStatus.PENDING_BANK_CREDIT


def test_reopen_changes_workflow_only() -> None:
    bundle, _, _ = _pending_bundle()
    ledger = InMemoryExceptionCaseLedger()
    case_id = _apply(ledger, bundle).created_case_ids[0]
    when = bundle.run.completed_at + timedelta(minutes=1)
    ledger.append_disposition(
        case_id=case_id,
        sequence=1,
        actor_id="ops",
        occurred_at=when,
        kind=DispositionKind.CLOSE,
    )
    ledger.append_disposition(
        case_id=case_id,
        sequence=2,
        actor_id="ops",
        occurred_at=when + timedelta(minutes=1),
        kind=DispositionKind.REOPEN,
    )

    state = ledger.state(case_id)
    assert state.workflow_status is CaseWorkflowStatus.OPEN
    assert state.resolution is None
    assert state.financial_status is ReconciliationStatus.PENDING_BANK_CREDIT


def test_incident_grouping_is_deterministic_under_input_permutation() -> None:
    bundle, _, _ = _bundle(
        SettlementSpec("1", 9882, "UTR-1"),
        SettlementSpec("2", 19882, "UTR-2"),
    )
    ledger = InMemoryExceptionCaseLedger()
    update = _apply(ledger, bundle)
    observations = tuple(
        ledger.observation_by_id(value) for value in update.created_observation_ids
    )

    first = build_incident_clusters(run=bundle.run, observations=observations)
    second = build_incident_clusters(run=bundle.run, observations=tuple(reversed(observations)))
    assert first == second


def test_incident_cluster_preserves_exact_case_count_and_affected_value() -> None:
    bundle, _, _ = _bundle(
        SettlementSpec("1", 9882, "UTR-1"),
        SettlementSpec("2", 19882, "UTR-2"),
    )
    ledger = InMemoryExceptionCaseLedger()
    update = _apply(ledger, bundle)
    observations = tuple(
        ledger.observation_by_id(value) for value in update.created_observation_ids
    )
    clusters = build_incident_clusters(run=bundle.run, observations=observations)

    assert len(clusters) == 1
    assert clusters[0].affected_case_count == 2
    assert clusters[0].affected_value == Money(9882 + 19882)


def test_source_incident_pattern_can_change_without_changing_case_identity() -> None:
    first, _, _ = _pending_bundle(bank_complete=False)
    second = _rerun(
        first,
        completed_at=RUN2_AT + timedelta(seconds=3),
        bank_complete=True,
    )
    ledger = InMemoryExceptionCaseLedger()
    case_id = _apply(ledger, first).created_case_ids[0]
    _apply(ledger, second)
    before, after = ledger.observations(case_id)

    assert before.case_id == after.case_id
    assert before.incident_fingerprint_id != after.incident_fingerprint_id
    assert before.source_states != after.source_states
    assert before.financial_status is after.financial_status


def test_out_of_order_case_observation_time_fails_closed() -> None:
    base, _, _ = _pending_bundle()
    later = _rerun(base, completed_at=RUN2_AT + timedelta(days=1, seconds=3))
    earlier = _rerun(base, completed_at=RUN2_AT + timedelta(seconds=3))
    ledger = InMemoryExceptionCaseLedger()
    _apply(ledger, later)

    with pytest.raises(ExceptionCaseError, match=r"backwards|out-of-order"):
        _apply(ledger, earlier)


def test_gate14_production_module_does_not_import_simulator_truth() -> None:
    source = inspect.getsource(exception_cases_module)
    assert "reflow.simulator" not in source
    assert "simulator.truth" not in source


def test_closed_workflow_requires_explicit_reopen_before_other_status_changes() -> None:
    bundle, _, _ = _pending_bundle()
    ledger = InMemoryExceptionCaseLedger()
    case_id = _apply(ledger, bundle).created_case_ids[0]
    when = bundle.run.completed_at + timedelta(minutes=1)
    ledger.append_disposition(
        case_id=case_id,
        sequence=1,
        actor_id="ops",
        occurred_at=when,
        kind=DispositionKind.CLOSE,
    )

    with pytest.raises(ExceptionCaseError, match=r"closed.*REOPEN|REOPEN.*closed"):
        ledger.append_disposition(
            case_id=case_id,
            sequence=2,
            actor_id="ops",
            occurred_at=when + timedelta(minutes=1),
            kind=DispositionKind.ACKNOWLEDGE,
        )


def test_stale_prior_economic_identity_cannot_reverse_supersession() -> None:
    scope = _scope()
    original, _, _ = _pending_bundle(scope=scope)
    superseding, _, _ = _bundle(
        SettlementSpec("1", 19882, "UTR-DEMO-1"),
        scope=scope,
        at=RUN2_AT,
    )
    stale_original = _rerun(
        original,
        completed_at=RUN1_AT + timedelta(hours=12),
    )
    ledger = InMemoryExceptionCaseLedger()
    old_id = _apply(ledger, original).created_case_ids[0]
    new_id = _apply(ledger, superseding).created_case_ids[0]
    assert ledger.state(old_id).superseded_by_case_id == new_id

    with pytest.raises(ExceptionCaseError, match=r"backwards|out-of-order|stale"):
        _apply(ledger, stale_original)
    assert ledger.state(old_id).superseded_by_case_id == new_id



def test_case_observation_rejects_direct_tampering() -> None:
    bundle, _, _ = _pending_bundle()
    ledger = InMemoryExceptionCaseLedger()
    observation_id = _apply(ledger, bundle).created_observation_ids[0]
    observation = ledger.observation_by_id(observation_id)

    with pytest.raises(ValueError, match=r"tracking key|immutable content"):
        replace(observation, affected_amount=Money(observation.affected_amount.amount_paise + 1))


def test_disposition_rejects_direct_tampering() -> None:
    bundle, _, _ = _pending_bundle()
    ledger = InMemoryExceptionCaseLedger()
    case_id = _apply(ledger, bundle).created_case_ids[0]
    disposition = ledger.append_disposition(
        case_id=case_id,
        sequence=1,
        actor_id="ops",
        occurred_at=bundle.run.completed_at + timedelta(minutes=1),
        kind=DispositionKind.ACKNOWLEDGE,
    )

    with pytest.raises(ValueError, match="immutable content"):
        replace(disposition, actor_id="tampered")


def test_incident_cluster_rejects_direct_tampering() -> None:
    bundle, _, _ = _bundle(
        SettlementSpec("1", 9882, "UTR-1"),
        SettlementSpec("2", 19882, "UTR-2"),
    )
    ledger = InMemoryExceptionCaseLedger()
    update = _apply(ledger, bundle)
    observations = tuple(
        ledger.observation_by_id(value) for value in update.created_observation_ids
    )
    cluster = build_incident_clusters(run=bundle.run, observations=observations)[0]

    with pytest.raises(ValueError, match="count"):
        replace(cluster, affected_case_count=cluster.affected_case_count + 1)


def test_failed_multi_case_run_is_atomic() -> None:
    scope = _scope()
    later_two, _, _ = _bundle(
        SettlementSpec("2", 19882, "UTR-2"),
        scope=scope,
        at=RUN2_AT,
    )
    middle_both, _, _ = _bundle(
        SettlementSpec("1", 9882, "UTR-1"),
        SettlementSpec("2", 19882, "UTR-2"),
        scope=scope,
        at=RUN1_AT + timedelta(hours=12),
    )
    isolated_one, _, _ = _bundle(
        SettlementSpec("1", 9882, "UTR-1"),
        scope=scope,
        at=RUN1_AT + timedelta(hours=12),
    )
    case1_id = _apply(InMemoryExceptionCaseLedger(), isolated_one).created_case_ids[0]

    ledger = InMemoryExceptionCaseLedger()
    _apply(ledger, later_two)
    with pytest.raises(ExceptionCaseError, match=r"backwards|out-of-order"):
        _apply(ledger, middle_both)
    with pytest.raises(ExceptionCaseError, match="unknown exception case"):
        ledger.state(case1_id)



def test_run_manifest_id_set_mismatch_fails_closed() -> None:
    bundle, _, _ = _pending_bundle()
    with pytest.raises(ExceptionCaseError, match=r"manifest.*run|run.*manifest"):
        InMemoryExceptionCaseLedger().apply_run(
            run=bundle.run,
            policy=bundle.policy,
            manifests=bundle.manifests[:-1],
            proof_versions=bundle.proofs,
        )


def test_run_policy_id_mismatch_fails_closed() -> None:
    bundle, _, _ = _pending_bundle()
    other_policy = _policy(label="different-policy")
    with pytest.raises(ExceptionCaseError, match=r"policy.*run|run.*policy"):
        InMemoryExceptionCaseLedger().apply_run(
            run=bundle.run,
            policy=other_policy,
            manifests=bundle.manifests,
            proof_versions=bundle.proofs,
        )
