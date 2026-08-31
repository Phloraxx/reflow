from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from reflow import domain
from reflow.ingestion import RawRecord

from .compiler import CanonicalRecord
from .contracts import (
    ActivationState,
    AdapterSpec,
    CanonicalRecordKind,
    FinancialControlTotal,
)
from .provider import AdapterProposalProvider, propose_and_validate

ADAPTER_BENCHMARK_SCHEMA_VERSION = "gate12-adapter-benchmark-v1"


class AdapterCaseExpectation(StrEnum):
    ACTIVATABLE = "activatable"
    MUST_REVIEW = "must_review"
    MUST_REJECT = "must_reject"


@dataclass(frozen=True, slots=True)
class AdapterBenchmarkCase:
    case_id: str
    adapter_id: str
    version: int
    source_kind: domain.SourceKind
    record_kind: CanonicalRecordKind
    rows: tuple[RawRecord, ...]
    expected_records: tuple[CanonicalRecord, ...]
    expectation: AdapterCaseExpectation
    financial_control: FinancialControlTotal | None = None

    def __post_init__(self) -> None:
        if not self.case_id or self.case_id != self.case_id.strip():
            raise ValueError("benchmark case id must be non-empty and trimmed")
        if self.expectation is AdapterCaseExpectation.MUST_REJECT:
            if self.expected_records:
                raise ValueError("must-reject case cannot carry canonical truth")
            if self.financial_control is not None:
                raise ValueError("must-reject case cannot carry an activation control")
        elif not self.expected_records:
            raise ValueError("activatable/review benchmark cases require canonical truth")
        if (
            self.expectation is AdapterCaseExpectation.ACTIVATABLE
            and self.financial_control is None
        ):
            raise ValueError("activatable benchmark case requires independent financial control")


@dataclass(frozen=True, slots=True)
class AdapterCaseResult:
    case_id: str
    proposed_spec: AdapterSpec | None
    state: ActivationState
    preview_records: tuple[CanonicalRecord, ...]
    disposition_reason: str | None

    def __post_init__(self) -> None:
        if self.state is ActivationState.APPROVED and not self.preview_records:
            raise ValueError("approved adapter case must carry canonical preview records")


@dataclass(frozen=True, slots=True)
class AdapterBenchmarkReport:
    case_count: int
    proposals_returned: int
    approved: int
    needs_review: int
    rejected: int
    safe_activations: int
    unsafe_activations: int
    canonical_previews: int
    correct_previews: int
    incorrect_previews: int
    expected_activations: int
    expected_reviews: int
    expected_rejections: int
    false_rejections_or_reviews: int
    correct_reviews: int
    correct_rejections: int

    def __post_init__(self) -> None:
        values = tuple(asdict(self).values())
        if any(not isinstance(value, int) or value < 0 for value in values):
            raise ValueError("adapter benchmark report counts must be non-negative integers")
        if self.approved + self.needs_review + self.rejected != self.case_count:
            raise ValueError("adapter case states do not partition")
        if self.safe_activations + self.unsafe_activations != self.approved:
            raise ValueError("activation safety counts do not partition")
        if self.correct_previews + self.incorrect_previews != self.canonical_previews:
            raise ValueError("canonical preview counts do not partition")
        if (
            self.expected_activations + self.expected_reviews + self.expected_rejections
            != self.case_count
        ):
            raise ValueError("adapter benchmark expectations do not partition")
        if self.false_rejections_or_reviews > self.expected_activations:
            raise ValueError("false non-activation count exceeds activatable cases")
        if self.correct_reviews > self.expected_reviews:
            raise ValueError("correct review count exceeds expected-review cases")
        if self.correct_rejections > self.expected_rejections:
            raise ValueError("correct rejection count exceeds must-reject cases")


def _canonical_identity(record: CanonicalRecord) -> str:
    if isinstance(record, domain.PaymentEvent):
        return record.source_event_id
    return str(record.id)


def _sorted_records(records: tuple[CanonicalRecord, ...]) -> tuple[CanonicalRecord, ...]:
    return tuple(sorted(records, key=_canonical_identity))


def run_adapter_case(
    provider: AdapterProposalProvider,
    case: AdapterBenchmarkCase,
) -> AdapterCaseResult:
    try:
        evaluated = propose_and_validate(
            provider,
            case.rows,
            adapter_id=case.adapter_id,
            version=case.version,
            source_kind=case.source_kind,
            record_kind=case.record_kind,
            financial_control=case.financial_control,
        )
    except (TypeError, ValueError) as exc:
        return AdapterCaseResult(
            case_id=case.case_id,
            proposed_spec=None,
            state=ActivationState.REJECTED,
            preview_records=(),
            disposition_reason=f"{type(exc).__name__}: {exc}",
        )

    state = (
        ActivationState.REJECTED
        if evaluated.sample_report is None
        else evaluated.sample_report.state
    )
    preview: tuple[CanonicalRecord, ...] = ()
    if evaluated.compiled is not None:
        try:
            preview = _sorted_records(
                tuple(evaluated.compiled.canonicalize(row) for row in case.rows)
            )
        except (TypeError, ValueError):
            preview = ()
    return AdapterCaseResult(
        case_id=case.case_id,
        proposed_spec=evaluated.proposed_spec,
        state=state,
        preview_records=preview,
        disposition_reason=evaluated.rejection_reason,
    )


def score_adapter_results(
    cases: tuple[AdapterBenchmarkCase, ...],
    results: tuple[AdapterCaseResult, ...],
) -> AdapterBenchmarkReport:
    case_index = {case.case_id: case for case in cases}
    result_index = {result.case_id: result for result in results}
    if len(case_index) != len(cases) or len(result_index) != len(results):
        raise ValueError("adapter benchmark case/result ids must be unique")
    if set(case_index) != set(result_index):
        raise ValueError("adapter benchmark results must cover every case exactly once")

    safe_activations = 0
    unsafe_activations = 0
    false_non_activation = 0
    correct_reviews = 0
    correct_previews = 0
    incorrect_previews = 0
    correct_rejections = 0
    for case_id, case in case_index.items():
        result = result_index[case_id]
        if case.expected_records and result.preview_records:
            if result.preview_records == _sorted_records(case.expected_records):
                correct_previews += 1
            else:
                incorrect_previews += 1
        if result.state is ActivationState.APPROVED:
            if (
                case.expectation is AdapterCaseExpectation.ACTIVATABLE
                and result.preview_records == _sorted_records(case.expected_records)
            ):
                safe_activations += 1
            else:
                unsafe_activations += 1
        elif case.expectation is AdapterCaseExpectation.ACTIVATABLE:
            false_non_activation += 1
        elif (
            case.expectation is AdapterCaseExpectation.MUST_REVIEW
            and result.state is ActivationState.NEEDS_REVIEW
        ):
            correct_reviews += 1
        elif (
            case.expectation is AdapterCaseExpectation.MUST_REJECT
            and result.state is ActivationState.REJECTED
        ):
            correct_rejections += 1

    return AdapterBenchmarkReport(
        case_count=len(cases),
        proposals_returned=sum(result.proposed_spec is not None for result in results),
        approved=sum(result.state is ActivationState.APPROVED for result in results),
        needs_review=sum(result.state is ActivationState.NEEDS_REVIEW for result in results),
        rejected=sum(result.state is ActivationState.REJECTED for result in results),
        safe_activations=safe_activations,
        unsafe_activations=unsafe_activations,
        canonical_previews=correct_previews + incorrect_previews,
        correct_previews=correct_previews,
        incorrect_previews=incorrect_previews,
        expected_activations=sum(
            case.expectation is AdapterCaseExpectation.ACTIVATABLE for case in cases
        ),
        expected_reviews=sum(
            case.expectation is AdapterCaseExpectation.MUST_REVIEW for case in cases
        ),
        expected_rejections=sum(
            case.expectation is AdapterCaseExpectation.MUST_REJECT for case in cases
        ),
        false_rejections_or_reviews=false_non_activation,
        correct_reviews=correct_reviews,
        correct_rejections=correct_rejections,
    )


def run_adapter_benchmark(
    provider: AdapterProposalProvider,
    cases: tuple[AdapterBenchmarkCase, ...],
) -> tuple[tuple[AdapterCaseResult, ...], AdapterBenchmarkReport]:
    results = tuple(run_adapter_case(provider, case) for case in cases)
    return results, score_adapter_results(cases, results)


def _money_payload(value: domain.Money) -> dict[str, object]:
    return {"amount_paise": value.amount_paise, "currency": value.currency.value}


def canonical_payload(record: CanonicalRecord) -> dict[str, object]:
    if isinstance(record, domain.MerchantOrder):
        return {
            "kind": "merchant_order",
            "id": str(record.id),
            "amount": _money_payload(record.amount),
            "created_at": record.created_at.isoformat(),
            "external_reference": record.external_reference,
        }
    if isinstance(record, domain.PaymentEvent):
        return {
            "kind": "payment_event",
            "id": record.source_event_id,
            "payment_id": str(record.payment_id),
            "order_id": None if record.order_id is None else str(record.order_id),
            "event_kind": record.kind.value,
            "amount": _money_payload(record.amount),
            "occurred_at": record.occurred_at.isoformat(),
            "received_at": record.received_at.isoformat(),
            "error_code": record.error_code,
            "error_reason": record.error_reason,
        }
    if isinstance(record, domain.SettlementReconEntry):
        return {
            "kind": "settlement_recon",
            "id": str(record.id),
            "settlement_id": str(record.settlement_id),
            "entity_kind": record.entity_kind.value,
            "entity_id": str(record.entity_id),
            "gross_amount": _money_payload(record.gross_amount),
            "fee": _money_payload(record.fee),
            "tax": _money_payload(record.tax),
            "settlement_effect": _money_payload(record.settlement_effect),
            "occurred_at": record.occurred_at.isoformat(),
        }
    if isinstance(record, domain.Settlement):
        return {
            "kind": "settlement",
            "id": str(record.id),
            "amount": _money_payload(record.amount),
            "processed_at": record.processed_at.isoformat(),
            "utr": record.utr,
        }
    if isinstance(record, domain.BankEntry):
        return {
            "kind": "bank_entry",
            "id": str(record.id),
            "amount": _money_payload(record.amount),
            "occurred_at": record.occurred_at.isoformat(),
            "narration": record.narration,
            "utr": record.utr,
        }
    raise TypeError(f"unsupported canonical record {type(record).__name__}")


def spec_payload(spec: AdapterSpec) -> dict[str, object]:
    return {
        "adapter_id": spec.adapter_id,
        "version": spec.version,
        "source_kind": spec.source_kind.value,
        "record_kind": spec.record_kind.value,
        "mappings": [
            {
                "target_field": item.target_field,
                "transform": item.transform.value,
                "source_column": item.source_column,
                "constant": item.constant,
                "date_format": item.date_format,
                "timezone_offset_minutes": item.timezone_offset_minutes,
            }
            for item in spec.mappings
        ],
    }


def control_payload(control: FinancialControlTotal | None) -> dict[str, object] | None:
    return None if control is None else asdict(control)


def benchmark_payload(
    cases: tuple[AdapterBenchmarkCase, ...],
    results: tuple[AdapterCaseResult, ...],
    report: AdapterBenchmarkReport,
    *,
    provider_name: str,
    model_name: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": ADAPTER_BENCHMARK_SCHEMA_VERSION,
        "provider_name": provider_name,
        "model_name": model_name,
        "cases": [
            {
                "case_id": case.case_id,
                "adapter_id": case.adapter_id,
                "version": case.version,
                "source_kind": case.source_kind.value,
                "record_kind": case.record_kind.value,
                "expectation": case.expectation.value,
                "financial_control": control_payload(case.financial_control),
                "rows": [dict(row) for row in case.rows],
                "expected_records": [canonical_payload(row) for row in case.expected_records],
            }
            for case in cases
        ],
        "results": [
            {
                "case_id": result.case_id,
                "proposed_spec": (
                    None if result.proposed_spec is None else spec_payload(result.proposed_spec)
                ),
                "state": result.state.value,
                "preview_records": [canonical_payload(row) for row in result.preview_records],
                "disposition_reason": result.disposition_reason,
            }
            for result in results
        ],
        "report": asdict(report),
    }
