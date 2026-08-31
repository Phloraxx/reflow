from __future__ import annotations

from dataclasses import replace

from reflow.adapter_compiler import (
    ActivationState,
    AdapterApprovalEvidence,
    ApprovalEvidenceKind,
    AdapterSpec,
    ApprovedAdapterVersion,
    CanonicalRecordKind,
    DriftState,
    FieldMapping,
    FinancialControlTotal,
    InMemoryAdapterStore,
    TransformKind,
    compile_adapter,
    detect_drift,
    profile_rows,
    propose_and_validate,
    validate_sample,
)
from reflow.domain import SourceKind


def _rows() -> tuple[dict[str, object], ...]:
    return (
        {"Order": "order_001", "Amount": "100.00", "Created": "2026-08-31T10:00:00+05:30"},
        {"Order": "order_002", "Amount": "50.50", "Created": "2026-08-31T10:01:00+05:30"},
    )


def _spec(version: int = 1) -> AdapterSpec:
    return AdapterSpec(
        adapter_id="merchant_unknown",
        version=version,
        source_kind=SourceKind.MERCHANT,
        record_kind=CanonicalRecordKind.MERCHANT_ORDER,
        mappings=tuple(
            sorted(
                (
                    FieldMapping("amount_paise", TransformKind.RUPEES_TO_PAISE, "Amount"),
                    FieldMapping("created_at", TransformKind.ISO_DATETIME, "Created"),
                    FieldMapping("currency", TransformKind.CONSTANT, constant="INR"),
                    FieldMapping("order_id", TransformKind.TEXT, "Order"),
                ),
                key=lambda item: item.target_field,
            )
        ),
    )


class FixedProvider:
    def __init__(self, spec: AdapterSpec) -> None:
        self.spec = spec
        self.seen_target_fields: tuple[str, ...] = ()

    def propose(self, context):
        self.seen_target_fields = context.target_fields
        return self.spec


def test_provider_proposal_cannot_bypass_deterministic_validation() -> None:
    provider = FixedProvider(_spec())
    result = propose_and_validate(
        provider,
        _rows(),
        adapter_id="merchant_unknown",
        version=1,
        source_kind=SourceKind.MERCHANT,
        record_kind=CanonicalRecordKind.MERCHANT_ORDER,
    )
    assert not result.approved
    assert result.sample_report is not None
    assert result.sample_report.state is ActivationState.NEEDS_REVIEW
    assert "amount_paise" in provider.seen_target_fields

    controlled = propose_and_validate(
        provider,
        _rows(),
        adapter_id="merchant_unknown",
        version=1,
        source_kind=SourceKind.MERCHANT,
        record_kind=CanonicalRecordKind.MERCHANT_ORDER,
        financial_control=FinancialControlTotal(
            target_field="amount_paise",
            expected_total_paise=15050,
            expected_row_count=2,
            evidence_label="synthetic merchant control total",
        ),
    )
    assert not controlled.approved
    assert controlled.sample_report is not None
    assert controlled.sample_report.state is ActivationState.NEEDS_REVIEW
    assert controlled.sample_report.financial_control_verified

    wrong_unit = FixedProvider(
        replace(
            _spec(),
            mappings=tuple(
                replace(mapping, transform=TransformKind.INTEGER_PAISE)
                if mapping.target_field == "amount_paise"
                else mapping
                for mapping in _spec().mappings
            ),
        )
    )
    rejected = propose_and_validate(
        wrong_unit,
        _rows(),
        adapter_id="merchant_unknown",
        version=1,
        source_kind=SourceKind.MERCHANT,
        record_kind=CanonicalRecordKind.MERCHANT_ORDER,
    )
    assert not rejected.approved
    assert rejected.sample_report is not None
    assert rejected.sample_report.state is ActivationState.REJECTED


def test_provider_wrong_source_contract_is_rejected_before_activation() -> None:
    wrong = FixedProvider(replace(_spec(), source_kind=SourceKind.BANK))
    result = propose_and_validate(
        wrong,
        _rows(),
        adapter_id="merchant_unknown",
        version=1,
        source_kind=SourceKind.MERCHANT,
        record_kind=CanonicalRecordKind.MERCHANT_ORDER,
    )
    assert not result.approved
    assert result.compiled is None
    assert "wrong adapter identity/source contract" in (result.rejection_reason or "")


def test_approved_adapter_store_and_drift_states() -> None:
    rows = _rows()
    profile = profile_rows(rows)
    compiled = compile_adapter(_spec(), profile)
    report = validate_sample(compiled, rows)
    approved = ApprovedAdapterVersion.from_compiled(
        compiled,
        profile,
        report,
        AdapterApprovalEvidence(
            kind=ApprovalEvidenceKind.OPERATOR_REVIEW,
            reference="test-review-1",
        ),
    )
    store = InMemoryAdapterStore()
    store.activate(approved)
    assert store.latest("merchant_unknown") == approved
    assert detect_drift(approved, profile) is DriftState.KNOWN_SCHEMA

    added_unused = tuple({**row, "Unused": "x"} for row in rows)
    assert detect_drift(approved, profile_rows(added_unused)) is DriftState.BENIGN_DRIFT

    missing_required_source = tuple(
        {key: value for key, value in row.items() if key != "Amount"} for row in rows
    )
    assert (
        detect_drift(approved, profile_rows(missing_required_source))
        is DriftState.BREAKING_DRIFT
    )

    type_changed = tuple({**row, "Amount": 100} for row in rows)
    assert detect_drift(approved, profile_rows(type_changed)) is DriftState.BREAKING_DRIFT

    assert detect_drift(None, profile) is DriftState.UNRECOGNIZED_SOURCE


def test_adapter_store_requires_monotonic_versions() -> None:
    rows = _rows()
    profile = profile_rows(rows)
    store = InMemoryAdapterStore()
    for version in (1, 2):
        compiled = compile_adapter(_spec(version), profile)
        approved = ApprovedAdapterVersion.from_compiled(
            compiled,
            profile,
            validate_sample(compiled, rows),
            AdapterApprovalEvidence(
                kind=ApprovalEvidenceKind.OPERATOR_REVIEW,
                reference=f"test-review-{version}",
            ),
        )
        store.activate(approved)
    assert [item.spec.version for item in store.versions("merchant_unknown")] == [1, 2]
