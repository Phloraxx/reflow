from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from reflow import domain
from reflow.ingestion import RawRecord

from .compiler import CanonicalRecord, compile_adapter, validate_sample
from .contracts import ActivationState, AdapterSpec, CanonicalRecordKind
from .profile import profile_rows
from .provider import AdapterProposalProvider, ProposalContext, propose_and_validate
from .spec_io import parse_adapter_spec_payload

ADAPTER_BENCHMARK_SCHEMA_VERSION = "gate12-adapter-benchmark-v1"


class AdapterCaseExpectation(StrEnum):
    ACTIVATABLE = "activatable"
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

    def __post_init__(self) -> None:
        if not self.case_id or self.case_id != self.case_id.strip():
            raise ValueError("benchmark case id must be non-empty and trimmed")
        if self.expectation is AdapterCaseExpectation.ACTIVATABLE and not self.expected_records:
            raise ValueError("activatable benchmark case requires canonical truth")
        if self.expectation is AdapterCaseExpectation.MUST_REJECT and self.expected_records:
            raise ValueError("must-reject benchmark case cannot carry canonical truth")


@dataclass(frozen=True, slots=True)
class AdapterCaseResult:
    case_id: str
    proposed_spec: AdapterSpec | None
    activated: bool
    canonical_records: tuple[CanonicalRecord, ...]
    rejection_reason: str | None


@dataclass(frozen=True, slots=True)
class AdapterBenchmarkReport:
    case_count: int
    proposals_returned: int
    activations: int
    safe_activations: int
    unsafe_activations: int
    expected_activations: int
    expected_rejections: int
    false_rejections: int
    correct_rejections: int

    def __post_init__(self) -> None:
        values = tuple(asdict(self).values())
        if any(not isinstance(value, int) or value < 0 for value in values):
            raise ValueError("adapter benchmark report counts must be non-negative integers")
        if self.safe_activations + self.unsafe_activations != self.activations:
            raise ValueError("activation counts do not partition")
        if self.expected_activations + self.expected_rejections != self.case_count:
            raise ValueError("benchmark expectations do not partition")
        if self.false_rejections > self.expected_activations:
            raise ValueError("false rejection count exceeds activatable cases")
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
        )
    except (TypeError, ValueError) as exc:
        return AdapterCaseResult(
            case_id=case.case_id,
            proposed_spec=None,
            activated=False,
            canonical_records=(),
            rejection_reason=f"{type(exc).__name__}: {exc}",
        )
    if not evaluated.approved or evaluated.compiled is None:
        return AdapterCaseResult(
            case_id=case.case_id,
            proposed_spec=evaluated.proposed_spec,
            activated=False,
            canonical_records=(),
            rejection_reason=evaluated.rejection_reason,
        )
    records = tuple(evaluated.compiled.canonicalize(row) for row in case.rows)
    return AdapterCaseResult(
        case_id=case.case_id,
        proposed_spec=evaluated.proposed_spec,
        activated=True,
        canonical_records=_sorted_records(records),
        rejection_reason=None,
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
    false_rejections = 0
    correct_rejections = 0
    for case_id, case in case_index.items():
        result = result_index[case_id]
        if result.activated:
            if (
                case.expectation is AdapterCaseExpectation.ACTIVATABLE
                and result.canonical_records == _sorted_records(case.expected_records)
            ):
                safe_activations += 1
            else:
                unsafe_activations += 1
        elif case.expectation is AdapterCaseExpectation.ACTIVATABLE:
            false_rejections += 1
        else:
            correct_rejections += 1

    return AdapterBenchmarkReport(
        case_count=len(cases),
        proposals_returned=sum(result.proposed_spec is not None for result in results),
        activations=sum(result.activated for result in results),
        safe_activations=safe_activations,
        unsafe_activations=unsafe_activations,
        expected_activations=sum(
            case.expectation is AdapterCaseExpectation.ACTIVATABLE for case in cases
        ),
        expected_rejections=sum(
            case.expectation is AdapterCaseExpectation.MUST_REJECT for case in cases
        ),
        false_rejections=false_rejections,
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


def benchmark_payload(
    cases: tuple[AdapterBenchmarkCase, ...],
    results: tuple[AdapterCaseResult, ...],
    report: AdapterBenchmarkReport,
    *,
    provider_name: str,
    model_name: str | None = None,
) -> dict[str, Any]:
    case_index = {case.case_id: case for case in cases}
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
                "activated": result.activated,
                "canonical_records": [canonical_payload(row) for row in result.canonical_records],
                "rejection_reason": result.rejection_reason,
                "expectation": case_index[result.case_id].expectation.value,
            }
            for result in results
        ],
        "report": asdict(report),
    }
