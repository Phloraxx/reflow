"""AI-bounded declarative source adapter compiler."""

from .compiler import (
    AdapterCompileError,
    CompiledAdapter,
    SampleValidationReport,
    compile_adapter,
    required_target_fields,
    target_fields,
    validate_sample,
)
from .contracts import (
    ActivationState,
    AdapterApprovalEvidence,
    AdapterSpec,
    ApprovalEvidenceKind,
    CanonicalRecordKind,
    DriftState,
    FieldMapping,
    FinancialControlTotal,
    TransformKind,
)
from .lifecycle import ApprovedAdapterVersion, InMemoryAdapterStore, detect_drift
from .migration import (
    CanonicalMigrationDiff,
    MigrationEvaluation,
    evaluate_migration,
    migration_approval_evidence,
)
from .openai_provider import OpenAIAdapterProposalProvider, OpenAIProposalError
from .profile import ColumnProfile, StructuralProfile, profile_rows
from .proposal_pipeline import (
    JournaledProposalEvaluation,
    approve_reviewed_proposal,
    propose_and_validate_journaled,
)
from .provider import AdapterProposalProvider, ProposalContext, ProposalEvaluation
from .runtime import AdapterRuntimeError, apply_approved_adapter
from .spec_io import AdapterSpecParseError, adapter_spec_json_schema, parse_adapter_spec_payload

__all__ = [
    "ActivationState",
    "AdapterApprovalEvidence",
    "AdapterCompileError",
    "AdapterProposalProvider",
    "AdapterRuntimeError",
    "AdapterSpec",
    "AdapterSpecParseError",
    "ApprovalEvidenceKind",
    "ApprovedAdapterVersion",
    "CanonicalMigrationDiff",
    "CanonicalRecordKind",
    "ColumnProfile",
    "CompiledAdapter",
    "DriftState",
    "FieldMapping",
    "FinancialControlTotal",
    "InMemoryAdapterStore",
    "JournaledProposalEvaluation",
    "MigrationEvaluation",
    "OpenAIAdapterProposalProvider",
    "OpenAIProposalError",
    "ProposalContext",
    "ProposalEvaluation",
    "SampleValidationReport",
    "StructuralProfile",
    "TransformKind",
    "adapter_spec_json_schema",
    "apply_approved_adapter",
    "approve_reviewed_proposal",
    "compile_adapter",
    "detect_drift",
    "evaluate_migration",
    "migration_approval_evidence",
    "parse_adapter_spec_payload",
    "profile_rows",
    "propose_and_validate_journaled",
    "required_target_fields",
    "target_fields",
    "validate_sample",
]
