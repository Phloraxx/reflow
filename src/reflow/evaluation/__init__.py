"""Evaluation-only harness. Candidate systems never receive hidden truth."""

from .candidates import CandidateDecision, CandidateRun, CandidateStatus
from .harness import (
    EvaluationResult,
    EvaluationSourceRejected,
    SourceRejection,
    evaluate_observation,
)
from .scoring import (
    CountMetric,
    EdgeMetrics,
    EvaluationReport,
    EvaluationTruth,
    EvaluationTruthSettlement,
    project_hidden_truth,
    score_candidate_run,
)

__all__ = [
    "CandidateDecision",
    "CandidateRun",
    "CandidateStatus",
    "CountMetric",
    "EdgeMetrics",
    "EvaluationReport",
    "EvaluationResult",
    "EvaluationSourceRejected",
    "EvaluationTruth",
    "EvaluationTruthSettlement",
    "SourceRejection",
    "evaluate_observation",
    "project_hidden_truth",
    "score_candidate_run",
]
