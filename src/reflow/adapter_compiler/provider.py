from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from reflow.domain import SourceKind
from reflow.ingestion import RawRecord

from .compiler import (
    CompiledAdapter,
    SampleValidationReport,
    compile_adapter,
    target_fields,
    validate_sample,
)
from .contracts import (
    ActivationState,
    AdapterSpec,
    CanonicalRecordKind,
    FinancialControlTotal,
    TransformKind,
)
from .profile import StructuralProfile, profile_rows


@dataclass(frozen=True, slots=True)
class ProposalContext:
    adapter_id: str
    version: int
    source_kind: SourceKind
    record_kind: CanonicalRecordKind
    profile: StructuralProfile
    target_fields: tuple[str, ...]
    allowed_transforms: tuple[TransformKind, ...]


class AdapterProposalProvider(Protocol):
    def propose(self, context: ProposalContext) -> AdapterSpec: ...


@dataclass(frozen=True, slots=True)
class ProposalEvaluation:
    context: ProposalContext
    proposed_spec: AdapterSpec
    compiled: CompiledAdapter | None
    sample_report: SampleValidationReport | None
    rejection_reason: str | None

    @property
    def approved(self) -> bool:
        return self.sample_report is not None and self.sample_report.state.value == "approved"


def _apply_financial_control(
    compiled: CompiledAdapter,
    rows: tuple[RawRecord, ...],
    report: SampleValidationReport,
    control: FinancialControlTotal | None,
) -> SampleValidationReport:
    if control is None:
        return replace(report, state=ActivationState.NEEDS_REVIEW)
    if control.expected_row_count != len(rows):
        return replace(
            report,
            state=ActivationState.REJECTED,
            error_messages=(*report.error_messages, "financial control row count mismatch"),
        )
    total = 0
    for row in rows:
        normalized = compiled.normalize(row)
        value = normalized.get(control.target_field)
        if isinstance(value, bool) or not isinstance(value, int):
            return replace(
                report,
                state=ActivationState.REJECTED,
                error_messages=(
                    *report.error_messages,
                    "financial control target is not exact integer paise",
                ),
            )
        total += value
    if total != control.expected_total_paise:
        return replace(
            report,
            state=ActivationState.REJECTED,
            error_messages=(*report.error_messages, "financial control total mismatch"),
        )
    return replace(
        report,
        state=ActivationState.NEEDS_REVIEW,
        financial_control_verified=True,
    )


def propose_and_validate(
    provider: AdapterProposalProvider,
    rows: tuple[RawRecord, ...],
    *,
    adapter_id: str,
    version: int,
    source_kind: SourceKind,
    record_kind: CanonicalRecordKind,
    sample_limit: int = 5,
    financial_control: FinancialControlTotal | None = None,
) -> ProposalEvaluation:
    profile = profile_rows(rows, sample_limit=sample_limit)
    if not adapter_id or adapter_id != adapter_id.strip():
        raise ValueError("adapter id must be non-empty and trimmed")
    if version < 1:
        raise ValueError("adapter version must be positive")
    context = ProposalContext(
        adapter_id=adapter_id,
        version=version,
        source_kind=source_kind,
        record_kind=record_kind,
        profile=profile,
        target_fields=target_fields(record_kind),
        allowed_transforms=tuple(TransformKind),
    )
    spec = provider.propose(context)
    if (
        spec.adapter_id != adapter_id
        or spec.version != version
        or spec.source_kind is not source_kind
        or spec.record_kind is not record_kind
    ):
        return ProposalEvaluation(
            context=context,
            proposed_spec=spec,
            compiled=None,
            sample_report=None,
            rejection_reason="provider proposed the wrong adapter identity/source contract",
        )
    try:
        compiled = compile_adapter(spec, profile)
        report = validate_sample(compiled, rows)
        if report.state is ActivationState.APPROVED:
            report = _apply_financial_control(compiled, rows, report, financial_control)
    except (TypeError, ValueError) as exc:
        return ProposalEvaluation(
            context=context,
            proposed_spec=spec,
            compiled=None,
            sample_report=None,
            rejection_reason=f"{type(exc).__name__}: {exc}",
        )
    return ProposalEvaluation(
        context=context,
        proposed_spec=spec,
        compiled=compiled,
        sample_report=report,
        rejection_reason=(
            None
            if report.state is ActivationState.APPROVED
            else (
                "explicit operator review or verified migration required before activation"
                if report.state is ActivationState.NEEDS_REVIEW
                else "sample or financial-control validation rejected spec"
            )
        ),
    )
