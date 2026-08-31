"""Evaluation-only harness. Candidate systems never receive hidden truth."""

from .candidates import CandidateDecision, CandidateRun, CandidateStatus
from .harness import (
    EvaluationResult,
    EvaluationSourceRejected,
    SourceRejection,
    evaluate_observation,
)
from .scoring import CountMetric, EdgeMetrics, EvaluationReport, score_candidate_run

__all__ = [
    "CandidateDecision",
    "CandidateRun",
    "CandidateStatus",
    "CountMetric",
    "EdgeMetrics",
    "EvaluationReport",
    "EvaluationResult",
    "EvaluationSourceRejected",
    "evaluate_observation",
    "SourceRejection",
    "score_candidate_run",
]
