from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from reflow.ingestion import AdapterError, ObservedBatch, ingest_observed_batch
from reflow.journal import InMemoryJournal, JournalConflictError
from reflow.simulator.truth import HiddenWorld

from .candidates import (
    CandidateRun,
    run_fuzzy_threshold,
    run_grouped_exact,
    run_naive_one_to_one,
    run_reflow_core,
)
from .scoring import EvaluationReport, score_candidate_run

DEFAULT_EVALUATION_RECEIVED_AT = datetime(2027, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class SourceRejection:
    error_type: str
    message: str
    retained_raw_envelopes: int


class EvaluationSourceRejected(ValueError):
    def __init__(self, rejection: SourceRejection) -> None:
        super().__init__(rejection.message)
        self.rejection = rejection


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    reports: tuple[EvaluationReport, ...]
    runs: tuple[CandidateRun, ...]


def evaluate_observation(
    world: HiddenWorld,
    observed: ObservedBatch,
    *,
    received_at: datetime = DEFAULT_EVALUATION_RECEIVED_AT,
) -> EvaluationResult:
    journal = InMemoryJournal()
    try:
        batch = ingest_observed_batch(observed, journal, received_at=received_at)
    except (AdapterError, JournalConflictError) as exc:
        raise EvaluationSourceRejected(
            SourceRejection(
                error_type=type(exc).__name__,
                message=str(exc),
                retained_raw_envelopes=len(journal),
            )
        ) from exc
    runs = (
        run_naive_one_to_one(batch),
        run_grouped_exact(batch),
        run_fuzzy_threshold(batch),
        run_reflow_core(batch, journal, knowledge_cutoff=received_at),
    )
    return EvaluationResult(
        reports=tuple(score_candidate_run(world, run) for run in runs),
        runs=runs,
    )
