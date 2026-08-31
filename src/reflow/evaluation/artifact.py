from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
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

EVALUATION_SCHEMA_VERSION = "gate11-evaluation-v2"


class ArtifactVerificationError(ValueError):
    """Serialized benchmark evidence is malformed or inconsistent with recomputed scores."""


def _recon_payload(row: domain.SettlementReconEntry) -> dict[str, Any]:
    return {
        "recon_id": str(row.id),
        "settlement_id": str(row.settlement_id),
        "entity_kind": row.entity_kind.value,
        "entity_id": str(row.entity_id),
        "gross_amount_paise": row.gross_amount.amount_paise,
        "fee_paise": row.fee.amount_paise,
        "tax_paise": row.tax.amount_paise,
        "settlement_effect_paise": row.settlement_effect.amount_paise,
        "currency": row.settlement_effect.currency.value,
        "occurred_at": row.occurred_at.isoformat(),
    }


def _bank_payload(row: domain.BankEntry) -> dict[str, Any]:
    return {
        "bank_entry_id": str(row.id),
        "amount_paise": row.amount.amount_paise,
        "currency": row.amount.currency.value,
        "occurred_at": row.occurred_at.isoformat(),
        "narration": row.narration,
        "utr": row.utr,
    }


def truth_payload(truth: EvaluationTruth) -> dict[str, Any]:
    return {
        "settlements": [
            {
                "settlement_id": str(item.settlement_id),
                "settlement_amount_paise": item.settlement_amount.amount_paise,
                "currency": item.settlement_amount.currency.value,
                "processed_at": item.processed_at.isoformat(),
                "settlement_utr": item.settlement_utr,
                "composition_components": [
                    _recon_payload(row) for row in item.composition_components
                ],
                "bank_entries": [_bank_payload(row) for row in item.bank_entries],
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
                "composition_components": [
                    _recon_payload(row) for row in item.composition_components
                ],
                "bank_entries": [_bank_payload(row) for row in item.bank_entries],
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
        "decision_status_counts": {
            "reconciled": report.decision_status_counts.reconciled,
            "unresolved": report.decision_status_counts.unresolved,
            "residual": report.decision_status_counts.residual,
            "incomplete": report.decision_status_counts.incomplete,
            "contradicted": report.decision_status_counts.contradicted,
        },
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


def _optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _string(value, label)


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ArtifactVerificationError(f"{label} must be an integer")
    return value


def _datetime(value: object, label: str) -> datetime:
    raw = _string(value, label)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ArtifactVerificationError(f"{label} must be an ISO datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ArtifactVerificationError(f"{label} must be timezone-aware")
    return parsed


def _string_list(value: object, label: str) -> tuple[str, ...]:
    return tuple(_string(item, label) for item in _list(value, label))


def _entity_id(kind: domain.ReconEntityKind, value: str) -> domain.EntityId:
    constructors: dict[domain.ReconEntityKind, type[domain.EntityId]] = {
        domain.ReconEntityKind.PAYMENT: domain.PaymentId,
        domain.ReconEntityKind.REFUND: domain.RefundId,
        domain.ReconEntityKind.TRANSFER: domain.TransferId,
        domain.ReconEntityKind.ADJUSTMENT: domain.AdjustmentId,
    }
    return constructors[kind](value)


def _parse_recon(payload: object, label: str) -> domain.SettlementReconEntry:
    item = _mapping(payload, label)
    currency = domain.Currency(_string(item.get("currency"), f"{label} currency"))
    kind = domain.ReconEntityKind(_string(item.get("entity_kind"), f"{label} entity kind"))
    return domain.SettlementReconEntry(
        id=domain.ReconEntryId(_string(item.get("recon_id"), f"{label} id")),
        settlement_id=domain.SettlementId(
            _string(item.get("settlement_id"), f"{label} settlement id")
        ),
        entity_kind=kind,
        entity_id=_entity_id(kind, _string(item.get("entity_id"), f"{label} entity id")),
        gross_amount=domain.Money(
            _integer(item.get("gross_amount_paise"), f"{label} gross amount"), currency
        ),
        fee=domain.Money(_integer(item.get("fee_paise"), f"{label} fee"), currency),
        tax=domain.Money(_integer(item.get("tax_paise"), f"{label} tax"), currency),
        settlement_effect=domain.Money(
            _integer(item.get("settlement_effect_paise"), f"{label} settlement effect"),
            currency,
        ),
        occurred_at=_datetime(item.get("occurred_at"), f"{label} occurred_at"),
    )


def _parse_bank(payload: object, label: str) -> domain.BankEntry:
    item = _mapping(payload, label)
    currency = domain.Currency(_string(item.get("currency"), f"{label} currency"))
    return domain.BankEntry(
        id=domain.BankEntryId(_string(item.get("bank_entry_id"), f"{label} id")),
        amount=domain.Money(
            _integer(item.get("amount_paise"), f"{label} amount"), currency
        ),
        occurred_at=_datetime(item.get("occurred_at"), f"{label} occurred_at"),
        narration=_string(item.get("narration"), f"{label} narration"),
        utr=_optional_string(item.get("utr"), f"{label} utr"),
    )


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
                processed_at=_datetime(item.get("processed_at"), "truth processed_at"),
                settlement_utr=_optional_string(
                    item.get("settlement_utr"), "truth settlement utr"
                ),
                composition_components=tuple(
                    _parse_recon(value, "truth recon")
                    for value in _list(
                        item.get("composition_components"), "truth composition components"
                    )
                ),
                bank_entries=tuple(
                    _parse_bank(value, "truth bank")
                    for value in _list(item.get("bank_entries"), "truth bank entries")
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
        decision = CandidateDecision(
            settlement_id=domain.SettlementId(
                _string(item.get("settlement_id"), "candidate settlement id")
            ),
            status=CandidateStatus(_string(item.get("status"), "candidate status")),
            settlement_amount=domain.Money(
                _integer(item.get("settlement_amount_paise"), "candidate settlement amount"),
                currency,
            ),
            composition_components=tuple(
                _parse_recon(value, "candidate recon")
                for value in _list(
                    item.get("composition_components"), "candidate composition components"
                )
            ),
            bank_entries=tuple(
                _parse_bank(value, "candidate bank")
                for value in _list(item.get("bank_entries"), "candidate bank entries")
            ),
            reason_codes=_string_list(item.get("reason_codes"), "candidate reason codes"),
        )
        if _integer(
            item.get("composition_amount_paise"), "candidate composition amount"
        ) != decision.composition_amount.amount_paise:
            raise ArtifactVerificationError(
                "candidate serialized composition amount differs from selected evidence"
            )
        if _integer(item.get("bank_amount_paise"), "candidate bank amount") != (
            decision.bank_amount.amount_paise
        ):
            raise ArtifactVerificationError(
                "candidate serialized bank amount differs from selected evidence"
            )
        decisions.append(decision)
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
