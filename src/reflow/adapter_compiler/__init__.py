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
    AdapterSpec,
    CanonicalRecordKind,
    DriftState,
    FieldMapping,
    TransformKind,
)
from .lifecycle import ApprovedAdapterVersion, InMemoryAdapterStore, detect_drift
from .migration import CanonicalMigrationDiff, MigrationEvaluation, evaluate_migration
from .openai_provider import OpenAIAdapterProposalProvider, OpenAIProposalError
from .profile import ColumnProfile, StructuralProfile, profile_rows
from .spec_io import AdapterSpecParseError, adapter_spec_json_schema, parse_adapter_spec_payload
from .provider import (
    AdapterProposalProvider,
    ProposalContext,
    ProposalEvaluation,
    propose_and_validate,
)

__all__ = [
    "ActivationState",
    "AdapterCompileError",
    "AdapterProposalProvider",
    "AdapterSpecParseError",
    "AdapterSpec",
    "ApprovedAdapterVersion",
    "CanonicalMigrationDiff",
    "CanonicalRecordKind",
    "ColumnProfile",
    "CompiledAdapter",
    "DriftState",
    "FieldMapping",
    "InMemoryAdapterStore",
    "MigrationEvaluation",
    "OpenAIAdapterProposalProvider",
    "OpenAIProposalError",
    "ProposalContext",
    "ProposalEvaluation",
    "SampleValidationReport",
    "StructuralProfile",
    "TransformKind",
    "adapter_spec_json_schema",
    "compile_adapter",
    "detect_drift",
    "evaluate_migration",
    "parse_adapter_spec_payload",
    "profile_rows",
    "propose_and_validate",
    "required_target_fields",
    "target_fields",
    "validate_sample",
]
