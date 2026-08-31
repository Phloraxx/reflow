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
    "adapter_spec_json_schema",
    "AdapterCompileError",
    "AdapterProposalProvider",
    "AdapterSpec",
    "AdapterSpecParseError",
    "ApprovedAdapterVersion",
    "CanonicalMigrationDiff",
    "CanonicalRecordKind",
    "ColumnProfile",
    "compile_adapter",
    "CompiledAdapter",
    "detect_drift",
    "DriftState",
    "evaluate_migration",
    "FieldMapping",
    "InMemoryAdapterStore",
    "MigrationEvaluation",
    "OpenAIAdapterProposalProvider",
    "OpenAIProposalError",
    "parse_adapter_spec_payload",
    "profile_rows",
    "ProposalContext",
    "ProposalEvaluation",
    "propose_and_validate",
    "required_target_fields",
    "SampleValidationReport",
    "StructuralProfile",
    "target_fields",
    "TransformKind",
    "validate_sample",
]
