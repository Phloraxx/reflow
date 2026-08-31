from __future__ import annotations

from dataclasses import replace

import pytest

from reflow.adapter_compiler import (
    ActivationState,
    AdapterSpec,
    ApprovalEvidenceKind,
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
    validate_sample,
)
from reflow.adapter_compiler.lifecycle import approval_evidence_for_adapter
from reflow.adapter_compiler.provider import _propose_and_validate_rows
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
    result = _propose_and_validate_rows(
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

    controlled = _propose_and_validate_rows(
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
    rejected = _propose_and_validate_rows(
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
    result = _propose_and_validate_rows(
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
        approval_evidence_for_adapter(
            compiled,
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

    renamed_by_whitespace = tuple(
        {(" Amount " if key == "Amount" else key): value for key, value in row.items()}
        for row in rows
    )
    renamed_profile = profile_rows(renamed_by_whitespace)
    assert renamed_profile.schema_fingerprint != profile.schema_fingerprint
    assert detect_drift(approved, renamed_profile) is DriftState.BREAKING_DRIFT

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
            approval_evidence_for_adapter(
                compiled,
                kind=ApprovalEvidenceKind.OPERATOR_REVIEW,
                reference=f"test-review-{version}",
            ),
        )
        store.activate(approved)
    assert [item.spec.version for item in store.versions("merchant_unknown")] == [1, 2]


def test_approved_adapter_version_self_verifies_and_store_preserves_contract() -> None:
    rows = _rows()
    profile = profile_rows(rows)
    compiled = compile_adapter(_spec(), profile)
    report = validate_sample(compiled, rows)
    approved = ApprovedAdapterVersion.from_compiled(
        compiled,
        profile,
        report,
        approval_evidence_for_adapter(
            compiled,
            kind=ApprovalEvidenceKind.OPERATOR_REVIEW,
            reference="self-verification-test",
        ),
    )
    with pytest.raises(ValueError, match="source columns"):
        replace(approved, source_columns=("Wrong",))
    with pytest.raises(ValueError, match="schema fingerprint"):
        replace(approved, schema_fingerprint="0" * 63)

    store = InMemoryAdapterStore()
    store.activate(approved)
    assert store.get_version("merchant_unknown", 1) == approved
    changed = replace(
        approved,
        spec=replace(approved.spec, version=2, source_kind=SourceKind.BANK),
        approval_evidence=replace(
            approved.approval_evidence,
            reference="wrong-contract-test",
            adapter_version=2,
        ),
    )
    with pytest.raises(ValueError, match="source kind"):
        store.activate(changed)


def test_same_schema_newer_version_routes_latest_without_losing_history() -> None:
    rows = _rows()
    profile = profile_rows(rows)
    store = InMemoryAdapterStore()
    approved_versions = []
    for version in (1, 2):
        compiled = compile_adapter(_spec(version), profile)
        approved = ApprovedAdapterVersion.from_compiled(
            compiled,
            profile,
            validate_sample(compiled, rows),
            approval_evidence_for_adapter(
                compiled,
                kind=ApprovalEvidenceKind.OPERATOR_REVIEW,
                reference=f"same-schema-review-{version}",
            ),
        )
        store.activate(approved)
        approved_versions.append(approved)
    assert (
        store.resolve_schema("merchant_unknown", profile.schema_fingerprint)
        == approved_versions[-1]
    )
    assert store.get_version("merchant_unknown", 1) == approved_versions[0]
    assert store.get_version("merchant_unknown", 2) == approved_versions[1]


def test_validation_report_cannot_authorize_a_different_adapter_version() -> None:
    rows = _rows()
    profile = profile_rows(rows)
    v1 = compile_adapter(_spec(1), profile)
    v2 = compile_adapter(_spec(2), profile)
    report_v1 = validate_sample(v1, rows)
    evidence_v2 = approval_evidence_for_adapter(
        v2,
        kind=ApprovalEvidenceKind.OPERATOR_REVIEW,
        reference="reviewed-v2",
    )
    with pytest.raises(ValueError, match="sample validation report"):
        ApprovedAdapterVersion.from_compiled(v2, profile, report_v1, evidence_v2)


def test_approval_evidence_cannot_authorize_a_different_schema() -> None:
    rows = _rows()
    profile = profile_rows(rows)
    compiled = compile_adapter(_spec(), profile)
    report = validate_sample(compiled, rows)
    foreign = replace(
        approval_evidence_for_adapter(
            compiled,
            kind=ApprovalEvidenceKind.OPERATOR_REVIEW,
            reference="reviewed-original-schema",
        ),
        schema_fingerprint="0" * 64,
    )
    with pytest.raises(ValueError, match="approval evidence"):
        ApprovedAdapterVersion.from_compiled(compiled, profile, report, foreign)
