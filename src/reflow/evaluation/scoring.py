from __future__ import annotations

from dataclasses import dataclass

from reflow import domain
from reflow.simulator.truth import BankExpectation, HiddenWorld

from .candidates import CandidateRun, CandidateStatus


@dataclass(frozen=True, slots=True)
class CountMetric:
    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        if self.numerator < 0 or self.denominator < 0 or self.numerator > self.denominator:
            raise ValueError("invalid count metric")


@dataclass(frozen=True, slots=True)
class EdgeMetrics:
    true_positive: int
    false_positive: int
    false_negative: int

    def __post_init__(self) -> None:
        if min(self.true_positive, self.false_positive, self.false_negative) < 0:
            raise ValueError("edge metric counts cannot be negative")


@dataclass(frozen=True, slots=True)
class EvaluationTruthSettlement:
    settlement_id: domain.SettlementId
    settlement_amount: domain.Money
    composition_component_ids: tuple[domain.ReconEntryId, ...]
    bank_entry_ids: tuple[domain.BankEntryId, ...]
    bank_expectation: BankExpectation

    def __post_init__(self) -> None:
        if self.composition_component_ids != tuple(
            sorted(set(self.composition_component_ids), key=str)
        ):
            raise ValueError("truth composition ids must be unique and sorted")
        if self.bank_entry_ids != tuple(sorted(set(self.bank_entry_ids), key=str)):
            raise ValueError("truth bank ids must be unique and sorted")

    @property
    def reconciled(self) -> bool:
        return self.bank_expectation is BankExpectation.MATCHED


@dataclass(frozen=True, slots=True)
class EvaluationTruth:
    settlements: tuple[EvaluationTruthSettlement, ...]

    def __post_init__(self) -> None:
        ids = [item.settlement_id for item in self.settlements]
        if len(set(ids)) != len(ids):
            raise ValueError("evaluation truth contains duplicate settlement ids")
        expected = tuple(sorted(self.settlements, key=lambda item: str(item.settlement_id)))
        if self.settlements != expected:
            raise ValueError("evaluation truth settlements must be sorted")


def project_hidden_truth(world: HiddenWorld) -> EvaluationTruth:
    """Expose only the minimal post-run truth needed to score candidate decisions."""
    settlements = tuple(
        EvaluationTruthSettlement(
            settlement_id=case.settlement.id,
            settlement_amount=case.settlement.amount,
            composition_component_ids=tuple(
                sorted((row.id for row in case.recon_entries), key=str)
            ),
            bank_entry_ids=tuple(sorted((row.id for row in case.bank_entries), key=str)),
            bank_expectation=case.bank_expectation,
        )
        for case in sorted(world.cases, key=lambda item: str(item.settlement.id))
    )
    return EvaluationTruth(settlements)


@dataclass(frozen=True, slots=True)
class DecisionStatusCounts:
    reconciled: int
    unresolved: int
    residual: int
    incomplete: int
    contradicted: int

    def __post_init__(self) -> None:
        if min(
            self.reconciled,
            self.unresolved,
            self.residual,
            self.incomplete,
            self.contradicted,
        ) < 0:
            raise ValueError("decision status counts cannot be negative")

    @property
    def total(self) -> int:
        return (
            self.reconciled
            + self.unresolved
            + self.residual
            + self.incomplete
            + self.contradicted
        )


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    system_name: str
    settlement_count: int
    auto_reconciled: int
    true_auto_reconciled: int
    false_auto_reconciled: int
    unresolved: int
    missing_decisions: int
    truth_reconciled: int
    decision_status_counts: DecisionStatusCounts
    reconciliation_recall: CountMetric
    silent_false_auto_match_rate: CountMetric
    settlement_amount_correct: CountMetric
    composition_amount_correct: CountMetric
    composition_edges: EdgeMetrics
    bank_edges: EdgeMetrics
    absolute_reported_residual_paise: int

    def __post_init__(self) -> None:
        if not self.system_name or self.system_name != self.system_name.strip():
            raise ValueError("evaluation report system name must be non-empty and trimmed")
        if self.settlement_count < 0:
            raise ValueError("settlement count cannot be negative")
        if not 0 <= self.truth_reconciled <= self.settlement_count:
            raise ValueError("truth-reconciled count must fit inside settlement count")
        if self.auto_reconciled != self.true_auto_reconciled + self.false_auto_reconciled:
            raise ValueError("auto-reconciled count must partition into true and false")
        if self.unresolved + self.auto_reconciled != self.settlement_count:
            raise ValueError("every truth settlement must be reconciled or unresolved")
        if not 0 <= self.missing_decisions <= self.unresolved:
            raise ValueError("missing decisions must be a subset of unresolved cases")
        decision_count = self.settlement_count - self.missing_decisions
        if self.auto_reconciled > decision_count:
            raise ValueError("auto-reconciled count cannot exceed emitted decisions")
        if self.decision_status_counts.total != decision_count:
            raise ValueError("decision status counts must equal emitted decision count")
        if self.decision_status_counts.reconciled != self.auto_reconciled:
            raise ValueError("reconciled status count must equal auto-reconciled count")
        if self.reconciliation_recall != CountMetric(
            self.true_auto_reconciled, self.truth_reconciled
        ):
            raise ValueError("reconciliation recall does not match report counts")
        if self.silent_false_auto_match_rate != CountMetric(
            self.false_auto_reconciled, self.auto_reconciled
        ):
            raise ValueError("silent false-match rate does not match report counts")
        for label, metric in (
            ("settlement amount correctness", self.settlement_amount_correct),
            ("composition amount correctness", self.composition_amount_correct),
        ):
            if metric.denominator != self.settlement_count:
                raise ValueError(f"{label} denominator must equal settlement count")
            if metric.numerator > decision_count:
                raise ValueError(f"{label} cannot exceed emitted decisions")
        if self.absolute_reported_residual_paise < 0:
            raise ValueError("absolute residual cannot be negative")


type ScoredEdge = tuple[str, str]


def _truth_edges(truth: EvaluationTruth) -> tuple[set[ScoredEdge], set[ScoredEdge]]:
    composition: set[ScoredEdge] = set()
    bank: set[ScoredEdge] = set()
    for item in truth.settlements:
        composition.update(
            (str(row_id), str(item.settlement_id))
            for row_id in item.composition_component_ids
        )
        bank.update((str(row_id), str(item.settlement_id)) for row_id in item.bank_entry_ids)
    return composition, bank


def _edge_metrics(predicted: set[ScoredEdge], truth: set[ScoredEdge]) -> EdgeMetrics:
    return EdgeMetrics(
        true_positive=len(predicted & truth),
        false_positive=len(predicted - truth),
        false_negative=len(truth - predicted),
    )


def score_candidate_run(truth: EvaluationTruth, run: CandidateRun) -> EvaluationReport:
    truth_by_settlement = {item.settlement_id: item for item in truth.settlements}
    decisions = {decision.settlement_id: decision for decision in run.decisions}
    unknown = set(decisions) - set(truth_by_settlement)
    if unknown:
        raise ValueError(f"candidate run contains unknown settlements: {sorted(map(str, unknown))}")

    truth_reconciled_ids = {
        item.settlement_id for item in truth.settlements if item.reconciled
    }
    predicted_reconciled_ids = {
        settlement_id
        for settlement_id, decision in decisions.items()
        if decision.auto_reconciled
    }
    true_auto_ids: set[domain.SettlementId] = set()
    for settlement_id in predicted_reconciled_ids:
        decision = decisions[settlement_id]
        expected = truth_by_settlement[settlement_id]
        if (
            expected.reconciled
            and decision.settlement_amount == expected.settlement_amount
            and decision.composition_amount == expected.settlement_amount
            and decision.bank_amount == expected.settlement_amount
            and decision.composition_component_ids == expected.composition_component_ids
            and decision.bank_entry_ids == expected.bank_entry_ids
        ):
            true_auto_ids.add(settlement_id)
    true_auto = len(true_auto_ids)
    false_auto = len(predicted_reconciled_ids) - true_auto
    missing_decisions = len(set(truth_by_settlement) - set(decisions))

    settlement_correct = 0
    composition_correct = 0
    reported_residual = 0
    predicted_composition_edges: set[ScoredEdge] = set()
    predicted_bank_edges: set[ScoredEdge] = set()
    for settlement_id, decision in decisions.items():
        expected = truth_by_settlement[settlement_id]
        if decision.settlement_amount == expected.settlement_amount:
            settlement_correct += 1
        if decision.composition_amount == expected.settlement_amount:
            composition_correct += 1
        reported_residual += abs(decision.composition_residual.amount_paise)
        reported_residual += abs(decision.bank_residual.amount_paise)
        predicted_composition_edges.update(
            (str(row_id), str(settlement_id)) for row_id in decision.composition_component_ids
        )
        predicted_bank_edges.update(
            (str(row_id), str(settlement_id)) for row_id in decision.bank_entry_ids
        )

    truth_composition_edges, truth_bank_edges = _truth_edges(truth)
    status_counts = {status: 0 for status in CandidateStatus}
    for decision in decisions.values():
        status_counts[decision.status] += 1
    auto_count = len(predicted_reconciled_ids)
    truth_count = len(truth_reconciled_ids)
    return EvaluationReport(
        system_name=run.system_name,
        settlement_count=len(truth.settlements),
        auto_reconciled=auto_count,
        true_auto_reconciled=true_auto,
        false_auto_reconciled=false_auto,
        unresolved=len(truth.settlements) - auto_count,
        missing_decisions=missing_decisions,
        truth_reconciled=truth_count,
        decision_status_counts=DecisionStatusCounts(
            reconciled=status_counts[CandidateStatus.RECONCILED],
            unresolved=status_counts[CandidateStatus.UNRESOLVED],
            residual=status_counts[CandidateStatus.RESIDUAL],
            incomplete=status_counts[CandidateStatus.INCOMPLETE],
            contradicted=status_counts[CandidateStatus.CONTRADICTED],
        ),
        reconciliation_recall=CountMetric(true_auto, truth_count),
        silent_false_auto_match_rate=CountMetric(false_auto, auto_count),
        settlement_amount_correct=CountMetric(settlement_correct, len(truth.settlements)),
        composition_amount_correct=CountMetric(composition_correct, len(truth.settlements)),
        composition_edges=_edge_metrics(predicted_composition_edges, truth_composition_edges),
        bank_edges=_edge_metrics(predicted_bank_edges, truth_bank_edges),
        absolute_reported_residual_paise=reported_residual,
    )
