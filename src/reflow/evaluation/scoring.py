from __future__ import annotations

from dataclasses import dataclass

from reflow.simulator.truth import BankExpectation, HiddenWorld

from .candidates import CandidateRun


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
class EvaluationReport:
    system_name: str
    settlement_count: int
    auto_reconciled: int
    true_auto_reconciled: int
    false_auto_reconciled: int
    unresolved: int
    missing_decisions: int
    truth_reconciled: int
    reconciliation_recall: CountMetric
    silent_false_auto_match_rate: CountMetric
    settlement_amount_correct: CountMetric
    composition_amount_correct: CountMetric
    composition_edges: EdgeMetrics
    bank_edges: EdgeMetrics
    absolute_reported_residual_paise: int

    def __post_init__(self) -> None:
        if self.settlement_count < 0:
            raise ValueError("settlement count cannot be negative")
        if self.auto_reconciled != self.true_auto_reconciled + self.false_auto_reconciled:
            raise ValueError("auto-reconciled count must partition into true and false")
        if self.unresolved + self.auto_reconciled != self.settlement_count:
            raise ValueError("every truth settlement must be reconciled or unresolved")
        if not 0 <= self.missing_decisions <= self.unresolved:
            raise ValueError("missing decisions must be a subset of unresolved cases")
        if self.absolute_reported_residual_paise < 0:
            raise ValueError("absolute residual cannot be negative")


type ScoredEdge = tuple[str, str]


def _truth_edges(world: HiddenWorld) -> tuple[set[ScoredEdge], set[ScoredEdge]]:
    composition: set[ScoredEdge] = set()
    bank: set[ScoredEdge] = set()
    for case in world.cases:
        composition.update((str(row.id), str(case.settlement.id)) for row in case.recon_entries)
        bank.update((str(row.id), str(case.settlement.id)) for row in case.bank_entries)
    return composition, bank


def _edge_metrics(predicted: set[ScoredEdge], truth: set[ScoredEdge]) -> EdgeMetrics:
    return EdgeMetrics(
        true_positive=len(predicted & truth),
        false_positive=len(predicted - truth),
        false_negative=len(truth - predicted),
    )


def score_candidate_run(world: HiddenWorld, run: CandidateRun) -> EvaluationReport:
    truth_by_settlement = {case.settlement.id: case for case in world.cases}
    decisions = {decision.settlement_id: decision for decision in run.decisions}
    unknown = set(decisions) - set(truth_by_settlement)
    if unknown:
        raise ValueError(f"candidate run contains unknown settlements: {sorted(map(str, unknown))}")

    truth_reconciled_ids = {
        case.settlement.id
        for case in world.cases
        if case.bank_expectation is BankExpectation.MATCHED
    }
    predicted_reconciled_ids = {
        settlement_id
        for settlement_id, decision in decisions.items()
        if decision.auto_reconciled
    }
    true_auto_ids: set[object] = set()
    for settlement_id in predicted_reconciled_ids:
        decision = decisions[settlement_id]
        truth = truth_by_settlement[settlement_id]
        truth_component_ids = {row.id for row in truth.recon_entries}
        truth_bank_ids = {row.id for row in truth.bank_entries}
        if (
            truth.bank_expectation is BankExpectation.MATCHED
            and decision.settlement_amount == truth.settlement.amount
            and decision.composition_amount == truth.settlement.amount
            and set(decision.composition_component_ids) == truth_component_ids
            and set(decision.bank_entry_ids) == truth_bank_ids
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
        truth = truth_by_settlement[settlement_id]
        if decision.settlement_amount == truth.settlement.amount:
            settlement_correct += 1
        if decision.composition_amount == truth.settlement.amount:
            composition_correct += 1
        reported_residual += abs(decision.composition_residual.amount_paise)
        reported_residual += abs(decision.bank_residual.amount_paise)
        predicted_composition_edges.update(
            (str(row_id), str(settlement_id)) for row_id in decision.composition_component_ids
        )
        predicted_bank_edges.update(
            (str(row_id), str(settlement_id)) for row_id in decision.bank_entry_ids
        )

    truth_composition_edges, truth_bank_edges = _truth_edges(world)
    auto_count = len(predicted_reconciled_ids)
    truth_count = len(truth_reconciled_ids)
    return EvaluationReport(
        system_name=run.system_name,
        settlement_count=len(world.cases),
        auto_reconciled=auto_count,
        true_auto_reconciled=true_auto,
        false_auto_reconciled=false_auto,
        unresolved=len(world.cases) - auto_count,
        missing_decisions=missing_decisions,
        truth_reconciled=truth_count,
        reconciliation_recall=CountMetric(true_auto, truth_count),
        silent_false_auto_match_rate=CountMetric(false_auto, auto_count),
        settlement_amount_correct=CountMetric(settlement_correct, len(world.cases)),
        composition_amount_correct=CountMetric(composition_correct, len(world.cases)),
        composition_edges=_edge_metrics(predicted_composition_edges, truth_composition_edges),
        bank_edges=_edge_metrics(predicted_bank_edges, truth_bank_edges),
        absolute_reported_residual_paise=reported_residual,
    )
