"""Evaluation-only harness. Candidate systems never receive hidden truth."""

from .artifact import ArtifactVerificationError, verify_benchmark_payload
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
    "ArtifactVerificationError",
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
    "verify_benchmark_payload",
]
