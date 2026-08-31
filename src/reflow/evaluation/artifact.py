from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from reflow import domain
from reflow.simulator.truth import BankExpectation

from .candidates import CandidateDecision, CandidateRun, CandidateStatus
from .scoring import (
    EvaluationReport,
    EvaluationTruth,
    EvaluationTruthSettlement,
    score_candidate_run,
)

EVALUATION_SCHEMA_VERSION = "gate11-evaluation-v1"


class ArtifactVerificationError(ValueError):
    """Serialized benchmark evidence is malformed or inconsistent with recomputed scores."""


def truth_payload(truth: EvaluationTruth) -> dict[str, Any]:
    return {
        "settlements": [
            {
                "settlement_id": str(item.settlement_id),
                "settlement_amount_paise": item.settlement_amount.amount_paise,
                "currency": item.settlement_amount.currency.value,
                "composition_component_ids": [
                    str(value) for value in item.composition_component_ids
                ],
                "bank_entry_ids": [str(value) for value in item.bank_entry_ids],
                "bank_expectation": item.bank_expectation.value,
            }
            for item in truth.settlements
        ]
    }


def decision_payload(run: CandidateRun) -> dict[str, Any]:
    return {
        "system_name": run.system_name,
        "decisions": [
            {
                "settlement_id": str(item.settlement_id),
                "status": item.status.value,
                "settlement_amount_paise": item.settlement_amount.amount_paise,
                "composition_amount_paise": item.composition_amount.amount_paise,
                "bank_amount_paise": item.bank_amount.amount_paise,
                "currency": item.settlement_amount.currency.value,
                "composition_component_ids": [
                    str(value) for value in item.composition_component_ids
                ],
                "bank_entry_ids": [str(value) for value in item.bank_entry_ids],
                "reason_codes": list(item.reason_codes),
            }
            for item in run.decisions
        ],
    }


def report_payload(report: EvaluationReport) -> dict[str, Any]:
    return {
        "system_name": report.system_name,
        "settlement_count": report.settlement_count,
        "auto_reconciled": report.auto_reconciled,
        "true_auto_reconciled": report.true_auto_reconciled,
        "false_auto_reconciled": report.false_auto_reconciled,
        "unresolved": report.unresolved,
        "missing_decisions": report.missing_decisions,
        "truth_reconciled": report.truth_reconciled,
        "reconciliation_recall": {
            "numerator": report.reconciliation_recall.numerator,
            "denominator": report.reconciliation_recall.denominator,
        },
        "silent_false_auto_match_rate": {
            "numerator": report.silent_false_auto_match_rate.numerator,
            "denominator": report.silent_false_auto_match_rate.denominator,
        },
        "settlement_amount_correct": {
            "numerator": report.settlement_amount_correct.numerator,
            "denominator": report.settlement_amount_correct.denominator,
        },
        "composition_amount_correct": {
            "numerator": report.composition_amount_correct.numerator,
            "denominator": report.composition_amount_correct.denominator,
        },
        "composition_edges": {
            "tp": report.composition_edges.true_positive,
            "fp": report.composition_edges.false_positive,
            "fn": report.composition_edges.false_negative,
        },
        "bank_edges": {
            "tp": report.bank_edges.true_positive,
            "fp": report.bank_edges.false_positive,
            "fn": report.bank_edges.false_negative,
        },
        "absolute_reported_residual_paise": report.absolute_reported_residual_paise,
    }


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ArtifactVerificationError(f"{label} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ArtifactVerificationError(f"{label} keys must be strings")
    return value


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ArtifactVerificationError(f"{label} must be an array")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ArtifactVerificationError(f"{label} must be a string")
    return value


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ArtifactVerificationError(f"{label} must be an integer")
    return value


def _string_list(value: object, label: str) -> tuple[str, ...]:
    return tuple(_string(item, label) for item in _list(value, label))


def parse_truth(payload: object) -> EvaluationTruth:
    root = _mapping(payload, "truth")
    settlements: list[EvaluationTruthSettlement] = []
    for raw in _list(root.get("settlements"), "truth.settlements"):
        item = _mapping(raw, "truth settlement")
        currency = domain.Currency(_string(item.get("currency"), "truth currency"))
        settlements.append(
            EvaluationTruthSettlement(
                settlement_id=domain.SettlementId(
                    _string(item.get("settlement_id"), "truth settlement id")
                ),
                settlement_amount=domain.Money(
                    _integer(item.get("settlement_amount_paise"), "truth settlement amount"),
                    currency,
                ),
                composition_component_ids=tuple(
                    domain.ReconEntryId(value)
                    for value in _string_list(
                        item.get("composition_component_ids"),
                        "truth composition component ids",
                    )
                ),
                bank_entry_ids=tuple(
                    domain.BankEntryId(value)
                    for value in _string_list(item.get("bank_entry_ids"), "truth bank ids")
                ),
                bank_expectation=BankExpectation(
                    _string(item.get("bank_expectation"), "truth bank expectation")
                ),
            )
        )
    return EvaluationTruth(tuple(settlements))


def parse_candidate_run(payload: object) -> CandidateRun:
    root = _mapping(payload, "candidate run")
    system_name = _string(root.get("system_name"), "candidate system name")
    decisions: list[CandidateDecision] = []
    for raw in _list(root.get("decisions"), "candidate decisions"):
        item = _mapping(raw, "candidate decision")
        currency = domain.Currency(_string(item.get("currency"), "candidate currency"))
        decisions.append(
            CandidateDecision(
                settlement_id=domain.SettlementId(
                    _string(item.get("settlement_id"), "candidate settlement id")
                ),
                status=CandidateStatus(_string(item.get("status"), "candidate status")),
                settlement_amount=domain.Money(
                    _integer(item.get("settlement_amount_paise"), "candidate settlement amount"),
                    currency,
                ),
                composition_amount=domain.Money(
                    _integer(
                        item.get("composition_amount_paise"),
                        "candidate composition amount",
                    ),
                    currency,
                ),
                bank_amount=domain.Money(
                    _integer(item.get("bank_amount_paise"), "candidate bank amount"),
                    currency,
                ),
                composition_component_ids=tuple(
                    domain.ReconEntryId(value)
                    for value in _string_list(
                        item.get("composition_component_ids"),
                        "candidate composition component ids",
                    )
                ),
                bank_entry_ids=tuple(
                    domain.BankEntryId(value)
                    for value in _string_list(
                        item.get("bank_entry_ids"), "candidate bank ids"
                    )
                ),
                reason_codes=_string_list(item.get("reason_codes"), "candidate reason codes"),
            )
        )
    return CandidateRun(system_name=system_name, decisions=tuple(decisions))


def verify_benchmark_payload(payload: Mapping[str, object]) -> tuple[EvaluationReport, ...]:
    if payload.get("schema_version") != EVALUATION_SCHEMA_VERSION:
        raise ArtifactVerificationError("unsupported evaluation artifact schema")
    status = payload.get("status")
    if status == "source_rejected":
        if (
            payload.get("truth") is not None
            or payload.get("runs") != []
            or payload.get("reports") != []
        ):
            raise ArtifactVerificationError(
                "source-rejected artifact must not contain scored truth/runs"
            )
        return ()
    if status != "evaluated":
        raise ArtifactVerificationError("evaluation artifact has unknown status")

    truth = parse_truth(payload.get("truth"))
    raw_runs = _list(payload.get("runs"), "runs")
    raw_reports = _list(payload.get("reports"), "reports")
    if len(raw_runs) != len(raw_reports):
        raise ArtifactVerificationError("run/report counts differ")

    reports_by_name: dict[str, Mapping[str, object]] = {}
    for raw_report in raw_reports:
        stored_report = _mapping(raw_report, "report")
        system_name = _string(stored_report.get("system_name"), "report system name")
        if system_name in reports_by_name:
            raise ArtifactVerificationError("artifact contains duplicate report system names")
        reports_by_name[system_name] = stored_report

    recomputed: list[EvaluationReport] = []
    seen_runs: set[str] = set()
    for raw_run in raw_runs:
        run = parse_candidate_run(raw_run)
        if run.system_name in seen_runs:
            raise ArtifactVerificationError("artifact contains duplicate candidate system names")
        seen_runs.add(run.system_name)
        stored = reports_by_name.get(run.system_name)
        if stored is None:
            raise ArtifactVerificationError(f"missing report for {run.system_name}")
        recomputed_report = score_candidate_run(truth, run)
        if report_payload(recomputed_report) != dict(stored):
            raise ArtifactVerificationError(
                f"stored report does not match recomputed score for {run.system_name}"
            )
        recomputed.append(recomputed_report)

    if set(reports_by_name) != seen_runs:
        raise ArtifactVerificationError("artifact contains a report without a candidate run")
    return tuple(recomputed)
