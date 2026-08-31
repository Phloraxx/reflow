from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from reflow.domain import SourceKind


class CanonicalRecordKind(StrEnum):
    MERCHANT_ORDER = "merchant_order"
    PAYMENT_EVENT = "payment_event"
    SETTLEMENT_RECON = "settlement_recon"
    SETTLEMENT = "settlement"
    BANK_ENTRY = "bank_entry"


class TransformKind(StrEnum):
    TEXT = "text"
    OPTIONAL_TEXT = "optional_text"
    INTEGER_PAISE = "integer_paise"
    RUPEES_TO_PAISE = "rupees_to_paise"
    ISO_DATETIME = "iso_datetime"
    DATE_TO_ISO_DATETIME = "date_to_iso_datetime"
    CONSTANT = "constant"


class ActivationState(StrEnum):
    APPROVED = "approved"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


class DriftState(StrEnum):
    KNOWN_SCHEMA = "known_schema"
    BENIGN_DRIFT = "benign_drift"
    REQUIRES_MIGRATION = "requires_migration"
    BREAKING_DRIFT = "breaking_drift"
    UNRECOGNIZED_SOURCE = "unrecognized_source"


class ApprovalEvidenceKind(StrEnum):
    OPERATOR_REVIEW = "operator_review"
    MIGRATION_EQUIVALENCE = "migration_equivalence"


@dataclass(frozen=True, slots=True)
class AdapterApprovalEvidence:
    kind: ApprovalEvidenceKind
    reference: str
    adapter_id: str
    adapter_version: int
    schema_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ApprovalEvidenceKind):
            raise TypeError("approval evidence kind must be typed")
        if not self.reference or self.reference != self.reference.strip():
            raise ValueError("approval evidence reference must be non-empty and trimmed")
        if not self.adapter_id or self.adapter_id != self.adapter_id.strip():
            raise ValueError("approval evidence adapter id must be non-empty and trimmed")
        if isinstance(self.adapter_version, bool) or not isinstance(self.adapter_version, int):
            raise TypeError("approval evidence adapter version must be an integer")
        if self.adapter_version < 1:
            raise ValueError("approval evidence adapter version must be positive")
        if len(self.schema_fingerprint) != 64 or any(
            char not in "0123456789abcdef" for char in self.schema_fingerprint
        ):
            raise ValueError("approval evidence schema fingerprint must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class FinancialControlTotal:
    target_field: str
    expected_total_paise: int
    expected_row_count: int
    evidence_label: str

    def __post_init__(self) -> None:
        if not self.target_field or self.target_field != self.target_field.strip():
            raise ValueError("control target field must be non-empty and trimmed")
        if isinstance(self.expected_total_paise, bool) or not isinstance(
            self.expected_total_paise, int
        ):
            raise TypeError("control total must be integer paise")
        if isinstance(self.expected_row_count, bool) or not isinstance(
            self.expected_row_count, int
        ):
            raise TypeError("control row count must be an integer")
        if self.expected_row_count < 1:
            raise ValueError("control row count must be positive")
        if not self.evidence_label or self.evidence_label != self.evidence_label.strip():
            raise ValueError("control evidence label must be non-empty and trimmed")


@dataclass(frozen=True, slots=True)
class FieldMapping:
    target_field: str
    transform: TransformKind
    source_column: str | None = None
    constant: str | int | None = None
    date_format: str | None = None
    timezone_offset_minutes: int | None = None

    def __post_init__(self) -> None:
        if not self.target_field or self.target_field != self.target_field.strip():
            raise ValueError("target field must be non-empty and trimmed")
        if self.source_column is not None and (
            not self.source_column or self.source_column != self.source_column.strip()
        ):
            raise ValueError("source column must be non-empty and trimmed")
        if self.transform is TransformKind.CONSTANT:
            if self.source_column is not None or self.constant is None:
                raise ValueError("constant mapping requires constant and no source column")
        elif self.source_column is None or self.constant is not None:
            raise ValueError("non-constant mapping requires source column and no constant")
        if self.transform is TransformKind.DATE_TO_ISO_DATETIME:
            if self.date_format is None or self.timezone_offset_minutes is None:
                raise ValueError("date transform requires format and timezone offset")
        elif self.date_format is not None or self.timezone_offset_minutes is not None:
            raise ValueError("date metadata is only valid for date transform")


@dataclass(frozen=True, slots=True)
class AdapterSpec:
    adapter_id: str
    version: int
    source_kind: SourceKind
    record_kind: CanonicalRecordKind
    mappings: tuple[FieldMapping, ...]

    def __post_init__(self) -> None:
        if not self.adapter_id or self.adapter_id != self.adapter_id.strip():
            raise ValueError("adapter id must be non-empty and trimmed")
        if self.version < 1:
            raise ValueError("adapter version must be positive")
        if not self.mappings:
            raise ValueError("adapter spec requires at least one field mapping")
        targets = [mapping.target_field for mapping in self.mappings]
        if len(targets) != len(set(targets)):
            raise ValueError("adapter spec contains duplicate target fields")
        expected = tuple(sorted(self.mappings, key=lambda item: item.target_field))
        if self.mappings != expected:
            raise ValueError("adapter mappings must be sorted by target field")
