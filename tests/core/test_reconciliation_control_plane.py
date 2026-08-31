from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from reflow.bank_proof import BankReceiptStatus, prove_all_bank_receipts
from reflow.control_plane import (
    BalanceControlStatus,
    CloseReadinessStatus,
    ControlPlaneError,
    CoverageBucket,
    CoverageStatus,
    DeliveryMode,
    EvidenceCoverageAssignment,
    MaterialityBand,
    SourceCompleteness,
    build_balance_control,
    build_close_readiness,
    build_evidence_coverage,
    build_reconciliation_run,
    make_reconciliation_policy_version,
    make_reconciliation_scope,
    make_source_delivery_manifest,
)
from reflow.domain import Currency, Money, SourceEnvelopeId, SourceKind
from reflow.ingestion import ObservedBatch, ingest_observed_batch
from reflow.journal import InMemoryJournal
from reflow.money_graph import build_money_graph
from reflow.reconciliation_proof import InMemoryProofLedger
from reflow.settlement_proof import prove_all_settlement_compositions

T0 = datetime(2026, 8, 31, 0, 0, tzinfo=UTC)
T1 = T0 + timedelta(days=1)
ALL_SOURCES = tuple(SourceKind)


def _observed(*, include_bank: bool = True, bank_amount: int = 9882) -> ObservedBatch:
    bank_rows = (
        ({
            "bank_entry_id": "bank_1",
            "amount_paise": bank_amount,
            "currency": "INR",
            "occurred_at": (T0 + timedelta(hours=5)).isoformat(),
            "narration": "Razorpay settlement UTR-DEMO-1",
            "utr": "UTR-DEMO-1",
        },)
        if include_bank
        else ()
    )
    return ObservedBatch(
        merchant_rows=(
            {
                "order_id": "order_1",
                "amount_paise": 10000,
                "currency": "INR",
                "created_at": (T0 + timedelta(minutes=1)).isoformat(),
                "external_reference": "demo-1",
            },
            {
                "order_id": "order_2",
                "amount_paise": 2500,
                "currency": "INR",
                "created_at": (T0 + timedelta(minutes=1, seconds=30)).isoformat(),
                "external_reference": "open-unsettled-demo",
            },
        ),
        razorpay_events=(
            {
                "event_id": "evt_1",
                "payment_id": "pay_1",
                "order_id": "order_1",
                "event_kind": "captured",
                "amount_paise": 10000,
                "currency": "INR",
                "occurred_at": (T0 + timedelta(minutes=2)).isoformat(),
                "received_at": (T0 + timedelta(minutes=3)).isoformat(),
                "error_code": None,
                "error_reason": None,
            },
        ),
        recon_rows=(
            {
                "recon_id": "recon_1",
                "settlement_id": "setl_1",
                "entity_kind": "payment",
                "entity_id": "pay_1",
                "gross_amount_paise": 10000,
                "fee_paise": 100,
                "tax_paise": 18,
                "settlement_effect_paise": 9882,
                "currency": "INR",
                "occurred_at": (T0 + timedelta(hours=2)).isoformat(),
            },
        ),
        settlement_rows=(
            {
                "settlement_id": "setl_1",
                "amount_paise": 9882,
                "currency": "INR",
                "processed_at": (T0 + timedelta(hours=4)).isoformat(),
                "utr": "UTR-DEMO-1",
            },
        ),
        bank_rows=bank_rows,
    )


def _scope(*, merchant: str = "merchant_demo", provider: str = "rzp_demo"):
    return make_reconciliation_scope(
        merchant_account_id=merchant,
        provider="razorpay",
        provider_account_id=provider,
        bank_account_id="bank_demo",
        currency=Currency.INR,
        channel="payments",
    )


def _policy(*, thresholds: tuple[int, int, int] = (10_000, 100_000, 1_000_000)):
    return make_reconciliation_policy_version(
        version_label="gate13-test-v1",
        required_source_kinds=ALL_SOURCES,
        reporting_timezone="UTC",
        bank_wait_sla_seconds=3600,
        materiality_thresholds_paise=thresholds,
    )


def _compile(
    *,
    include_bank: bool = True,
    reverse_rows: bool = False,
    bank_amount: int = 9882,
):
    observed = _observed(include_bank=include_bank, bank_amount=bank_amount)
    if reverse_rows:
        observed = replace(
            observed,
            merchant_rows=tuple(reversed(observed.merchant_rows)),
            razorpay_events=tuple(reversed(observed.razorpay_events)),
            recon_rows=tuple(reversed(observed.recon_rows)),
            settlement_rows=tuple(reversed(observed.settlement_rows)),
            bank_rows=tuple(reversed(observed.bank_rows)),
        )
    journal = InMemoryJournal()
    batch = ingest_observed_batch(observed, journal, received_at=T1)
    graph = build_money_graph(batch)
    compositions = prove_all_settlement_compositions(batch, graph)
    banks = prove_all_bank_receipts(batch)
    update = InMemoryProofLedger().apply_batch(
        batch,
        journal,
        compositions,
        banks,
        knowledge_cutoff=T1,
        generated_at=T1 + timedelta(seconds=1),
    )
    return batch, banks, update.created_versions


def _manifest(
    batch,
    scope,
    source_kind: SourceKind,
    *,
    complete: bool = True,
    received: bool = True,
    expected_by: datetime = T1 + timedelta(hours=1),
    evaluated_at: datetime = T1,
):
    envelope_ids = tuple(
        link.envelope_id for link in batch.source_links if link.source_kind is source_kind
    )
    return make_source_delivery_manifest(
        scope=scope,
        source_kind=source_kind,
        source_account_id=scope.account_for(source_kind),
        delivery_mode=DeliveryMode.SNAPSHOT,
        period_start=T0,
        period_end=T1,
        reporting_timezone="UTC",
        expected_by=expected_by,
        evaluated_at=evaluated_at,
        received_at=T1 if received else None,
        watermark_at=T1 if complete and received else None,
        is_complete=complete and received,
        delivered_envelope_ids=envelope_ids,
        adapter_version="normalized-v1",
        schema_fingerprint=f"schema-{source_kind.value}-v1",
    )


def _manifests(batch, scope, *, bank_complete: bool = True, bank_received: bool = True):
    manifests = []
    for source_kind in ALL_SOURCES:
        if source_kind is SourceKind.BANK:
            manifests.append(
                _manifest(
                    batch,
                    scope,
                    source_kind,
                    complete=bank_complete,
                    received=bank_received,
                )
            )
        else:
            manifests.append(_manifest(batch, scope, source_kind))
    return tuple(manifests)


def _coverage(batch, scope, manifests, proofs):
    return build_evidence_coverage(
        scope=scope,
        batch=batch,
        manifests=manifests,
        proof_versions=proofs,
        assignments=(),
    )


def _balance(scope, policy, *, bank_paid: int = 9882, closing: int = 0):
    return build_balance_control(
        scope=scope,
        policy=policy,
        period_start=T0,
        period_end=T1,
        reporting_timezone="UTC",
        opening_as_of=T0,
        closing_as_of=T1,
        opening_position=Money(0),
        provider_activity=Money(9882),
        bank_proven_payouts=Money(bank_paid),
        authoritative_adjustments=Money(0),
        observed_closing_position=Money(closing),
    )


def _run_bundle(*, include_bank: bool = True, reverse_rows: bool = False):
    scope = _scope()
    policy = _policy()
    batch, banks, proofs = _compile(include_bank=include_bank, reverse_rows=reverse_rows)
    manifests = _manifests(batch, scope)
    coverage = _coverage(batch, scope, manifests, proofs)
    balance = _balance(scope, policy)
    close = build_close_readiness(
        policy=policy,
        manifests=manifests,
        proof_versions=proofs,
        coverage=coverage,
        balance=balance,
    )
    return scope, policy, batch, banks, proofs, manifests, coverage, balance, close


def test_same_inputs_policy_and_cutoff_produce_same_run_identity() -> None:
    scope, policy, batch, _, proofs, manifests, coverage, balance, close = _run_bundle()
    first = build_reconciliation_run(
        scope=scope,
        policy=policy,
        manifests=manifests,
        batch=batch,
        proof_versions=proofs,
        coverage=coverage,
        balance=balance,
        close_readiness=close,
        knowledge_cutoff=T1,
        started_at=T1 + timedelta(minutes=1),
        completed_at=T1 + timedelta(minutes=2),
        code_build_sha="8c28a53",
    )
    second = build_reconciliation_run(
        scope=scope,
        policy=policy,
        manifests=manifests,
        batch=batch,
        proof_versions=proofs,
        coverage=coverage,
        balance=balance,
        close_readiness=close,
        knowledge_cutoff=T1,
        started_at=T1 + timedelta(hours=2),
        completed_at=T1 + timedelta(hours=3),
        code_build_sha="8c28a53",
    )
    assert first.id == second.id
    assert first.input_sha256 == second.input_sha256


def test_source_row_delivery_permutation_does_not_change_run_identity() -> None:
    first_bundle = _run_bundle(reverse_rows=False)
    second_bundle = _run_bundle(reverse_rows=True)

    def create(bundle, offset: int):
        scope, policy, batch, _, proofs, manifests, coverage, balance, close = bundle
        return build_reconciliation_run(
            scope=scope,
            policy=policy,
            manifests=manifests,
            batch=batch,
            proof_versions=proofs,
            coverage=coverage,
            balance=balance,
            close_readiness=close,
            knowledge_cutoff=T1,
            started_at=T1 + timedelta(minutes=offset),
            completed_at=T1 + timedelta(minutes=offset + 1),
            code_build_sha="8c28a53",
        )

    first = create(first_bundle, 1)
    second = create(second_bundle, 10)
    assert first_bundle[2].compilation_sha256 == second_bundle[2].compilation_sha256
    assert first.id == second.id


def test_waiting_late_and_complete_delivery_are_distinct_immutable_states() -> None:
    scope = _scope()
    expected_by = T1
    waiting = make_source_delivery_manifest(
        scope=scope,
        source_kind=SourceKind.BANK,
        source_account_id=scope.bank_account_id,
        delivery_mode=DeliveryMode.SNAPSHOT,
        period_start=T0,
        period_end=T1,
        reporting_timezone="UTC",
        expected_by=expected_by,
        evaluated_at=T1 - timedelta(minutes=1),
        received_at=None,
        watermark_at=None,
        is_complete=False,
        delivered_envelope_ids=(),
        adapter_version="bank-v1",
        schema_fingerprint="bank-schema-v1",
    )
    late = make_source_delivery_manifest(
        scope=scope,
        source_kind=SourceKind.BANK,
        source_account_id=scope.bank_account_id,
        delivery_mode=DeliveryMode.SNAPSHOT,
        period_start=T0,
        period_end=T1,
        reporting_timezone="UTC",
        expected_by=expected_by,
        evaluated_at=T1 + timedelta(minutes=1),
        received_at=None,
        watermark_at=None,
        is_complete=False,
        delivered_envelope_ids=(),
        adapter_version="bank-v1",
        schema_fingerprint="bank-schema-v1",
        prior=waiting,
    )
    complete = make_source_delivery_manifest(
        scope=scope,
        source_kind=SourceKind.BANK,
        source_account_id=scope.bank_account_id,
        delivery_mode=DeliveryMode.SNAPSHOT,
        period_start=T0,
        period_end=T1,
        reporting_timezone="UTC",
        expected_by=expected_by,
        evaluated_at=T1 + timedelta(minutes=10),
        received_at=T1 + timedelta(minutes=5),
        watermark_at=T1,
        is_complete=True,
        delivered_envelope_ids=(),
        adapter_version="bank-v1",
        schema_fingerprint="bank-schema-v1",
        prior=late,
    )
    assert waiting.completeness is SourceCompleteness.WAITING
    assert late.completeness is SourceCompleteness.LATE
    assert complete.completeness is SourceCompleteness.COMPLETE
    assert complete.received_late
    assert waiting.completeness is SourceCompleteness.WAITING
    assert len({waiting.id, late.id, complete.id}) == 3


def test_snapshot_replaces_while_delta_carries_forward_prior_evidence() -> None:
    scope = _scope()
    first_id = SourceEnvelopeId("src_first")
    second_id = SourceEnvelopeId("src_second")
    base = make_source_delivery_manifest(
        scope=scope,
        source_kind=SourceKind.BANK,
        source_account_id=scope.bank_account_id,
        delivery_mode=DeliveryMode.SNAPSHOT,
        period_start=T0,
        period_end=T1,
        reporting_timezone="UTC",
        expected_by=T1,
        evaluated_at=T1,
        received_at=T1,
        watermark_at=T1,
        is_complete=True,
        delivered_envelope_ids=(first_id,),
        adapter_version="bank-v1",
        schema_fingerprint="bank-v1",
    )
    snapshot = make_source_delivery_manifest(
        scope=scope,
        source_kind=SourceKind.BANK,
        source_account_id=scope.bank_account_id,
        delivery_mode=DeliveryMode.SNAPSHOT,
        period_start=T0,
        period_end=T1,
        reporting_timezone="UTC",
        expected_by=T1,
        evaluated_at=T1,
        received_at=T1,
        watermark_at=T1,
        is_complete=True,
        delivered_envelope_ids=(second_id,),
        adapter_version="bank-v1",
        schema_fingerprint="bank-v1",
        prior=base,
    )
    delta = make_source_delivery_manifest(
        scope=scope,
        source_kind=SourceKind.BANK,
        source_account_id=scope.bank_account_id,
        delivery_mode=DeliveryMode.DELTA,
        period_start=T0,
        period_end=T1,
        reporting_timezone="UTC",
        expected_by=T1,
        evaluated_at=T1,
        received_at=T1,
        watermark_at=T1,
        is_complete=True,
        delivered_envelope_ids=(second_id,),
        adapter_version="bank-v1",
        schema_fingerprint="bank-v1",
        prior=base,
    )
    assert snapshot.effective_envelope_ids == (second_id,)
    assert delta.effective_envelope_ids == (first_id, second_id)


def test_scope_account_boundary_rejects_another_provider_account() -> None:
    scope_a = _scope(provider="rzp_a")
    scope_b = _scope(merchant="merchant_b", provider="rzp_b")
    batch, _, proofs = _compile()
    manifests_a = list(_manifests(batch, scope_a))
    wrong = _manifest(batch, scope_b, SourceKind.RAZORPAY_RECON)
    manifests_a[ALL_SOURCES.index(SourceKind.RAZORPAY_RECON)] = wrong

    with pytest.raises(ControlPlaneError, match="scope"):
        _coverage(batch, scope_a, tuple(manifests_a), proofs)


def test_missing_bank_delivery_differs_from_complete_delivery_missing_credit() -> None:
    scope = _scope()
    policy = _policy()
    batch, banks, proofs = _compile(include_bank=False)
    assert banks[0].status is BankReceiptStatus.WAITING

    waiting_manifests = _manifests(batch, scope, bank_complete=False, bank_received=False)
    waiting_coverage = _coverage(batch, scope, waiting_manifests, proofs)
    waiting_close = build_close_readiness(
        policy=policy,
        manifests=waiting_manifests,
        proof_versions=proofs,
        coverage=waiting_coverage,
        balance=_balance(scope, policy, bank_paid=0, closing=9882),
    )

    complete_manifests = _manifests(batch, scope, bank_complete=True, bank_received=True)
    complete_coverage = _coverage(batch, scope, complete_manifests, proofs)
    complete_close = build_close_readiness(
        policy=policy,
        manifests=complete_manifests,
        proof_versions=proofs,
        coverage=complete_coverage,
        balance=_balance(scope, policy, bank_paid=0, closing=9882),
    )

    assert "SOURCE_WAITING:bank" in waiting_close.reason_codes
    assert "BANK_CREDIT_MISSING" not in waiting_close.reason_codes
    assert "BANK_CREDIT_MISSING" in complete_close.reason_codes
    assert "SOURCE_WAITING:bank" not in complete_close.reason_codes


def test_every_manifest_evidence_record_has_exactly_one_coverage_bucket() -> None:
    scope, _, batch, _, proofs, manifests, coverage, _, _ = _run_bundle()
    assert coverage.status is CoverageStatus.COMPLETE
    assert len(coverage.items) == len(batch.source_links)
    assert coverage.orphan_count == 0

    canonical_id = batch.source_links[0].envelope_id
    with pytest.raises(ControlPlaneError, match="proof-derived"):
        build_evidence_coverage(
            scope=scope,
            batch=batch,
            manifests=manifests,
            proof_versions=proofs,
            assignments=(
                EvidenceCoverageAssignment(canonical_id, CoverageBucket.PROVEN),
            ),
        )


def test_unclassified_relevant_evidence_becomes_orphan_and_blocks_close() -> None:
    scope, policy, batch, _banks, proofs, manifests, _, balance, _ = _run_bundle()
    unsupported = SourceEnvelopeId("src_unclassified_relevant")
    bank_manifest = next(
        manifest for manifest in manifests if manifest.source_kind is SourceKind.BANK
    )
    replacement = make_source_delivery_manifest(
        scope=scope,
        source_kind=SourceKind.BANK,
        source_account_id=scope.bank_account_id,
        delivery_mode=DeliveryMode.DELTA,
        period_start=T0,
        period_end=T1,
        reporting_timezone="UTC",
        expected_by=bank_manifest.expected_by,
        evaluated_at=T1,
        received_at=T1,
        watermark_at=T1,
        is_complete=True,
        delivered_envelope_ids=(unsupported,),
        adapter_version="bank-v1",
        schema_fingerprint="bank-schema-v1",
        prior=bank_manifest,
    )
    expanded_manifests = tuple(
        replacement if manifest.source_kind is SourceKind.BANK else manifest
        for manifest in manifests
    )
    coverage = build_evidence_coverage(
        scope=scope,
        batch=batch,
        manifests=expanded_manifests,
        proof_versions=proofs,
        assignments=(),
    )
    close = build_close_readiness(
        policy=policy,
        manifests=expanded_manifests,
        proof_versions=proofs,
        coverage=coverage,
        balance=balance,
    )
    assert coverage.status is CoverageStatus.FAILED
    assert coverage.orphan_count == 1
    assert close.status is CloseReadinessStatus.NOT_READY
    assert "ORPHAN_EVIDENCE" in close.reason_codes


def test_noncanonical_retained_evidence_requires_explicit_quarantine() -> None:
    scope, _, batch, _, proofs, manifests, _, _, _ = _run_bundle()
    raw_only = SourceEnvelopeId("src_raw_only_invalid")
    bank_manifest = next(
        manifest for manifest in manifests if manifest.source_kind is SourceKind.BANK
    )
    expanded_bank = make_source_delivery_manifest(
        scope=scope,
        source_kind=SourceKind.BANK,
        source_account_id=scope.bank_account_id,
        delivery_mode=DeliveryMode.DELTA,
        period_start=T0,
        period_end=T1,
        reporting_timezone="UTC",
        expected_by=bank_manifest.expected_by,
        evaluated_at=T1,
        received_at=T1,
        watermark_at=T1,
        is_complete=True,
        delivered_envelope_ids=(raw_only,),
        adapter_version="bank-v1",
        schema_fingerprint="bank-schema-v1",
        prior=bank_manifest,
    )
    expanded = tuple(
        expanded_bank if manifest.source_kind is SourceKind.BANK else manifest
        for manifest in manifests
    )
    failed = build_evidence_coverage(
        scope=scope,
        batch=batch,
        manifests=expanded,
        proof_versions=proofs,
        assignments=(),
    )
    quarantined = build_evidence_coverage(
        scope=scope,
        batch=batch,
        manifests=expanded,
        proof_versions=proofs,
        assignments=(EvidenceCoverageAssignment(raw_only, CoverageBucket.QUARANTINED),),
    )
    assert failed.status is CoverageStatus.FAILED
    assert quarantined.status is CoverageStatus.COMPLETE
    assert quarantined.summary(CoverageBucket.QUARANTINED).record_count == 1


def test_run_requires_exactly_one_gate9_proof_per_canonical_settlement() -> None:
    scope, policy, batch, _, proofs, manifests, coverage, balance, close = _run_bundle()
    with pytest.raises(ControlPlaneError, match="exactly one Gate 9 proof"):
        build_reconciliation_run(
            scope=scope,
            policy=policy,
            manifests=manifests,
            batch=batch,
            proof_versions=(),
            coverage=coverage,
            balance=balance,
            close_readiness=close,
            knowledge_cutoff=T1,
            started_at=T1 + timedelta(minutes=1),
            completed_at=T1 + timedelta(minutes=2),
            code_build_sha="8c28a53",
        )
    assert len(proofs) == len(batch.settlements) == 1


def test_materiality_changes_priority_not_exact_balance_truth() -> None:
    scope = _scope()
    low_threshold_policy = _policy(thresholds=(100, 200, 300))
    high_threshold_policy = _policy(thresholds=(100_000, 200_000, 300_000))
    money = Money(50_000)
    assert low_threshold_policy.materiality_band(money) is MaterialityBand.CRITICAL
    assert high_threshold_policy.materiality_band(money) is MaterialityBand.LOW

    first = build_balance_control(
        scope=scope,
        policy=low_threshold_policy,
        period_start=T0,
        period_end=T1,
        reporting_timezone="UTC",
        opening_as_of=T0,
        closing_as_of=T1,
        opening_position=Money(0),
        provider_activity=Money(1000),
        bank_proven_payouts=Money(900),
        authoritative_adjustments=Money(0),
        observed_closing_position=Money(0),
    )
    second = build_balance_control(
        scope=scope,
        policy=high_threshold_policy,
        period_start=T0,
        period_end=T1,
        reporting_timezone="UTC",
        opening_as_of=T0,
        closing_as_of=T1,
        opening_position=Money(0),
        provider_activity=Money(1000),
        bank_proven_payouts=Money(900),
        authoritative_adjustments=Money(0),
        observed_closing_position=Money(0),
    )
    assert first.status is BalanceControlStatus.RESIDUAL
    assert second.status is BalanceControlStatus.RESIDUAL
    assert first.residual == second.residual == Money(100)


def test_balance_control_rejects_misaligned_point_in_time_and_timezone() -> None:
    scope = _scope()
    policy = _policy()
    with pytest.raises(ControlPlaneError, match="opening point-in-time"):
        build_balance_control(
            scope=scope,
            policy=policy,
            period_start=T0,
            period_end=T1,
            reporting_timezone="UTC",
            opening_as_of=T0 + timedelta(seconds=1),
            closing_as_of=T1,
            opening_position=Money(0),
            provider_activity=Money(0),
            bank_proven_payouts=Money(0),
            authoritative_adjustments=Money(0),
            observed_closing_position=Money(0),
        )

    with pytest.raises(ControlPlaneError, match="reporting timezone"):
        build_balance_control(
            scope=scope,
            policy=policy,
            period_start=T0,
            period_end=T1,
            reporting_timezone="Asia/Kolkata",
            opening_as_of=T0,
            closing_as_of=T1,
            opening_position=Money(0),
            provider_activity=Money(0),
            bank_proven_payouts=Money(0),
            authoritative_adjustments=Money(0),
            observed_closing_position=Money(0),
        )


def test_contradicted_fragment_cannot_be_masked_by_proven_fragment_coverage() -> None:
    scope = _scope()
    batch, banks, proofs = _compile(bank_amount=9800)
    assert banks[0].status is BankReceiptStatus.RESIDUAL
    manifests = _manifests(batch, scope)
    coverage = _coverage(batch, scope, manifests, proofs)
    settlement_envelope_id = batch.source_index()[
        (SourceKind.RAZORPAY_SETTLEMENT, "setl_1")
    ]
    settlement_item = next(
        item for item in coverage.items if item.envelope_id == settlement_envelope_id
    )
    assert settlement_item.bucket is CoverageBucket.CONTRADICTED_RESIDUAL


def test_coverage_certificate_rejects_tampered_derived_status() -> None:
    *_, coverage, _, _ = _run_bundle()
    assert coverage.status is CoverageStatus.COMPLETE
    with pytest.raises(ValueError, match="coverage status"):
        replace(coverage, status=CoverageStatus.FAILED)


def test_balance_control_rejects_tampered_residual() -> None:
    *_, balance, _ = _run_bundle()
    assert balance.status is BalanceControlStatus.PROVEN
    with pytest.raises(ValueError, match="balance residual"):
        replace(balance, residual=Money(1))


def test_close_readiness_rejects_tampered_status_reasons() -> None:
    *_, close = _run_bundle()
    assert close.status is CloseReadinessStatus.READY
    with pytest.raises(ValueError, match="status does not match reason codes"):
        replace(close, reason_codes=("FORGED_NOT_READY",))


def test_run_capsule_rejects_tampered_output_binding() -> None:
    scope, policy, batch, _, proofs, manifests, coverage, balance, close = _run_bundle()
    run = build_reconciliation_run(
        scope=scope,
        policy=policy,
        manifests=manifests,
        batch=batch,
        proof_versions=proofs,
        coverage=coverage,
        balance=balance,
        close_readiness=close,
        knowledge_cutoff=T1,
        started_at=T1 + timedelta(minutes=1),
        completed_at=T1 + timedelta(minutes=2),
        code_build_sha="8c28a53",
    )
    with pytest.raises(ValueError, match="run output hash"):
        replace(run, outcome=CloseReadinessStatus.NOT_READY)


def test_gate13_v1_rejects_policy_that_disables_a_required_core_control() -> None:
    with pytest.raises(ValueError, match="requires the evidence-coverage and balance controls"):
        make_reconciliation_policy_version(
            version_label="missing-coverage",
            required_source_kinds=ALL_SOURCES,
            reporting_timezone="UTC",
            bank_wait_sla_seconds=3600,
            materiality_thresholds_paise=(10_000, 100_000, 1_000_000),
            enabled_controls=("balance_control",),
        )


def test_source_manifest_rejects_declared_account_outside_scope() -> None:
    scope = _scope(provider="rzp_a")
    batch, _, _ = _compile()
    envelope_ids = tuple(
        link.envelope_id
        for link in batch.source_links
        if link.source_kind is SourceKind.RAZORPAY_RECON
    )
    with pytest.raises(ControlPlaneError, match="source account does not belong"):
        make_source_delivery_manifest(
            scope=scope,
            source_kind=SourceKind.RAZORPAY_RECON,
            source_account_id="rzp_b",
            delivery_mode=DeliveryMode.SNAPSHOT,
            period_start=T0,
            period_end=T1,
            reporting_timezone="UTC",
            expected_by=T1 + timedelta(hours=1),
            evaluated_at=T1,
            received_at=T1,
            watermark_at=T1,
            is_complete=True,
            delivered_envelope_ids=envelope_ids,
            adapter_version="normalized-v1",
            schema_fingerprint="schema-razorpay-recon-v1",
        )
