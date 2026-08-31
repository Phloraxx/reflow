from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict

from reflow import domain
from reflow.ingestion import RawRecord

from .benchmark import (
    ADAPTER_BENCHMARK_SCHEMA_VERSION,
    AdapterBenchmarkReport,
    AdapterCaseExpectation,
    canonical_payload,
)
from .contracts import (
    ActivationState,
    AdapterSpec,
    CanonicalRecordKind,
    FinancialControlTotal,
)
from .provider import AdapterProposalProvider, ProposalContext, propose_and_validate
from .spec_io import parse_adapter_spec_payload


class AdapterArtifactVerificationError(ValueError):
    pass


class _StoredSpecProvider(AdapterProposalProvider):
    def __init__(self, spec_payload: object) -> None:
        self.spec = parse_adapter_spec_payload(spec_payload)

    def propose(self, context: ProposalContext) -> AdapterSpec:
        return self.spec


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise AdapterArtifactVerificationError(f"{label} must be an object")
    return value


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise AdapterArtifactVerificationError(f"{label} must be an array")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise AdapterArtifactVerificationError(f"{label} must be a string")
    return value


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AdapterArtifactVerificationError(f"{label} must be an integer")
    return value


def _rows(value: object) -> tuple[RawRecord, ...]:
    rows: list[RawRecord] = []
    for raw in _list(value, "case rows"):
        item = _mapping(raw, "case row")
        rows.append(dict(item))
    return tuple(rows)


def _control(value: object) -> FinancialControlTotal | None:
    if value is None:
        return None
    item = _mapping(value, "financial control")
    return FinancialControlTotal(
        target_field=_string(item.get("target_field"), "control target field"),
        expected_total_paise=_integer(
            item.get("expected_total_paise"), "control total paise"
        ),
        expected_row_count=_integer(item.get("expected_row_count"), "control row count"),
        evidence_label=_string(item.get("evidence_label"), "control evidence label"),
    )


def _recompute_case_result(
    case: Mapping[str, object],
    result: Mapping[str, object],
) -> tuple[ActivationState, list[dict[str, object]], bool]:
    proposed = result.get("proposed_spec")
    if proposed is None:
        return ActivationState.REJECTED, [], False
    provider = _StoredSpecProvider(proposed)
    rows = _rows(case.get("rows"))
    try:
        evaluated = propose_and_validate(
            provider,
            rows,
            adapter_id=_string(case.get("adapter_id"), "adapter id"),
            version=_integer(case.get("version"), "adapter version"),
            source_kind=domain.SourceKind(
                _string(case.get("source_kind"), "source kind")
            ),
            record_kind=CanonicalRecordKind(
                _string(case.get("record_kind"), "record kind")
            ),
            financial_control=_control(case.get("financial_control")),
        )
    except (TypeError, ValueError) as exc:
        raise AdapterArtifactVerificationError(
            f"stored proposal cannot be deterministically replayed: {exc}"
        ) from exc
    state = (
        ActivationState.REJECTED
        if evaluated.sample_report is None
        else evaluated.sample_report.state
    )
    records: list[dict[str, object]] = []
    if evaluated.compiled is not None:
        try:
            records = [
                canonical_payload(evaluated.compiled.canonicalize(row))
                for row in rows
            ]
        except (TypeError, ValueError):
            records = []
        records.sort(key=lambda item: str(item["id"]))
    if state is ActivationState.APPROVED and not records:
        raise AdapterArtifactVerificationError("approved proposal lost canonical preview")
    return state, records, True


def _recompute_report(
    cases: list[Mapping[str, object]],
    results: list[Mapping[str, object]],
) -> AdapterBenchmarkReport:
    cases_by_id = {
        _string(case.get("case_id"), "case id"): case
        for case in cases
    }
    results_by_id = {
        _string(result.get("case_id"), "result case id"): result
        for result in results
    }
    if len(cases_by_id) != len(cases) or len(results_by_id) != len(results):
        raise AdapterArtifactVerificationError("case/result ids must be unique")
    if set(cases_by_id) != set(results_by_id):
        raise AdapterArtifactVerificationError("artifact results do not cover all cases")

    states: dict[str, ActivationState] = {}
    proposal_present: dict[str, bool] = {}
    unsafe = 0
    safe = 0
    correct_previews = 0
    incorrect_previews = 0
    false_non_activation = 0
    correct_reviews = 0
    correct_rejections = 0
    for case_id, case in cases_by_id.items():
        result = results_by_id[case_id]
        state, records, has_proposal = _recompute_case_result(case, result)
        states[case_id] = state
        proposal_present[case_id] = has_proposal
        stored_state = ActivationState(_string(result.get("state"), "result state"))
        if stored_state is not state:
            raise AdapterArtifactVerificationError(
                f"case {case_id} state differs from deterministic replay"
            )
        stored_records = _list(result.get("preview_records"), "preview records")
        if stored_records != records:
            raise AdapterArtifactVerificationError(
                f"case {case_id} canonical records differ from deterministic replay"
            )

        expectation = AdapterCaseExpectation(
            _string(case.get("expectation"), "case expectation")
        )
        expected = _list(case.get("expected_records"), "expected canonical records")
        if expected and records:
            if records == expected:
                correct_previews += 1
            else:
                incorrect_previews += 1
        if state is ActivationState.APPROVED:
            if expectation is AdapterCaseExpectation.ACTIVATABLE and records == expected:
                safe += 1
            else:
                unsafe += 1
        elif expectation is AdapterCaseExpectation.ACTIVATABLE:
            false_non_activation += 1
        elif (
            expectation is AdapterCaseExpectation.MUST_REVIEW
            and state is ActivationState.NEEDS_REVIEW
        ):
            correct_reviews += 1
        elif (
            expectation is AdapterCaseExpectation.MUST_REJECT
            and state is ActivationState.REJECTED
        ):
            correct_rejections += 1

    expectations = [
        AdapterCaseExpectation(_string(case.get("expectation"), "case expectation"))
        for case in cases
    ]
    return AdapterBenchmarkReport(
        case_count=len(cases),
        proposals_returned=sum(proposal_present.values()),
        approved=sum(state is ActivationState.APPROVED for state in states.values()),
        needs_review=sum(
            state is ActivationState.NEEDS_REVIEW for state in states.values()
        ),
        rejected=sum(state is ActivationState.REJECTED for state in states.values()),
        safe_activations=safe,
        unsafe_activations=unsafe,
        canonical_previews=correct_previews + incorrect_previews,
        correct_previews=correct_previews,
        incorrect_previews=incorrect_previews,
        expected_activations=sum(
            item is AdapterCaseExpectation.ACTIVATABLE for item in expectations
        ),
        expected_reviews=sum(
            item is AdapterCaseExpectation.MUST_REVIEW for item in expectations
        ),
        expected_rejections=sum(
            item is AdapterCaseExpectation.MUST_REJECT for item in expectations
        ),
        false_rejections_or_reviews=false_non_activation,
        correct_reviews=correct_reviews,
        correct_rejections=correct_rejections,
    )


def verify_adapter_benchmark_payload(payload: object) -> AdapterBenchmarkReport:
    root = _mapping(payload, "adapter benchmark")
    if root.get("schema_version") != ADAPTER_BENCHMARK_SCHEMA_VERSION:
        raise AdapterArtifactVerificationError("unsupported adapter benchmark schema")
    cases = [_mapping(item, "benchmark case") for item in _list(root.get("cases"), "cases")]
    results = [
        _mapping(item, "benchmark result") for item in _list(root.get("results"), "results")
    ]
    recomputed = _recompute_report(cases, results)
    stored_report = _mapping(root.get("report"), "benchmark report")
    if dict(stored_report) != asdict(recomputed):
        raise AdapterArtifactVerificationError("stored report differs from deterministic replay")
    return recomputed
