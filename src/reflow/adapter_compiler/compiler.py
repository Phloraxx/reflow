from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from reflow import domain
from reflow.ingestion import (
    AdapterError,
    RawRecord,
    adapt_bank_row,
    adapt_merchant_row,
    adapt_payment_event,
    adapt_recon_row,
    adapt_settlement_row,
)

from .contracts import (
    ActivationState,
    AdapterSpec,
    CanonicalRecordKind,
    FieldMapping,
    TransformKind,
)
from .profile import StructuralProfile


class AdapterCompileError(ValueError):
    """Declarative adapter specification is unsafe or incompatible with the sample schema."""


_REQUIRED_FIELDS: dict[CanonicalRecordKind, frozenset[str]] = {
    CanonicalRecordKind.MERCHANT_ORDER: frozenset(
        {"order_id", "amount_paise", "currency", "created_at"}
    ),
    CanonicalRecordKind.PAYMENT_EVENT: frozenset(
        {
            "event_id",
            "payment_id",
            "event_kind",
            "amount_paise",
            "currency",
            "occurred_at",
            "received_at",
        }
    ),
    CanonicalRecordKind.SETTLEMENT_RECON: frozenset(
        {
            "recon_id",
            "settlement_id",
            "entity_kind",
            "entity_id",
            "gross_amount_paise",
            "fee_paise",
            "tax_paise",
            "settlement_effect_paise",
            "currency",
            "occurred_at",
        }
    ),
    CanonicalRecordKind.SETTLEMENT: frozenset(
        {"settlement_id", "amount_paise", "currency", "processed_at"}
    ),
    CanonicalRecordKind.BANK_ENTRY: frozenset(
        {"bank_entry_id", "amount_paise", "currency", "occurred_at", "narration"}
    ),
}

_OPTIONAL_FIELDS: dict[CanonicalRecordKind, frozenset[str]] = {
    CanonicalRecordKind.MERCHANT_ORDER: frozenset({"external_reference"}),
    CanonicalRecordKind.PAYMENT_EVENT: frozenset({"order_id", "error_code", "error_reason"}),
    CanonicalRecordKind.SETTLEMENT_RECON: frozenset(),
    CanonicalRecordKind.SETTLEMENT: frozenset({"utr"}),
    CanonicalRecordKind.BANK_ENTRY: frozenset({"utr"}),
}

_MONEY_TARGETS = frozenset(
    {"amount_paise", "gross_amount_paise", "fee_paise", "tax_paise", "settlement_effect_paise"}
)
_DATETIME_TARGETS = frozenset({"created_at", "occurred_at", "received_at", "processed_at"})

_EXPECTED_SOURCE_KIND = {
    CanonicalRecordKind.MERCHANT_ORDER: domain.SourceKind.MERCHANT,
    CanonicalRecordKind.PAYMENT_EVENT: domain.SourceKind.RAZORPAY_EVENT,
    CanonicalRecordKind.SETTLEMENT_RECON: domain.SourceKind.RAZORPAY_RECON,
    CanonicalRecordKind.SETTLEMENT: domain.SourceKind.RAZORPAY_SETTLEMENT,
    CanonicalRecordKind.BANK_ENTRY: domain.SourceKind.BANK,
}

_CONSTANT_TARGETS = frozenset({"currency", "event_kind", "entity_kind"})


def target_fields(record_kind: CanonicalRecordKind) -> tuple[str, ...]:
    return tuple(sorted(_REQUIRED_FIELDS[record_kind] | _OPTIONAL_FIELDS[record_kind]))


def required_target_fields(record_kind: CanonicalRecordKind) -> frozenset[str]:
    return _REQUIRED_FIELDS[record_kind]


def _validate_transform_target(mapping: FieldMapping) -> None:
    if (
        mapping.transform is TransformKind.CONSTANT
        and mapping.target_field not in _CONSTANT_TARGETS
    ):
        raise AdapterCompileError(
            f"constant transform is not allowed for target {mapping.target_field!r}"
        )
    if mapping.target_field in _MONEY_TARGETS and mapping.transform not in {
        TransformKind.INTEGER_PAISE,
        TransformKind.RUPEES_TO_PAISE,
    }:
        raise AdapterCompileError(
            f"money target {mapping.target_field!r} requires an exact money transform"
        )
    if mapping.target_field in _DATETIME_TARGETS and mapping.transform not in {
        TransformKind.ISO_DATETIME,
        TransformKind.DATE_TO_ISO_DATETIME,
    }:
        raise AdapterCompileError(
            f"datetime target {mapping.target_field!r} requires a datetime transform"
        )


def _validate_spec(spec: AdapterSpec, profile: StructuralProfile) -> None:
    expected_source = _EXPECTED_SOURCE_KIND[spec.record_kind]
    if spec.source_kind is not expected_source:
        raise AdapterCompileError(
            f"{spec.record_kind.value} adapter requires source kind {expected_source.value!r}"
        )
    allowed_targets = _REQUIRED_FIELDS[spec.record_kind] | _OPTIONAL_FIELDS[spec.record_kind]
    mapped_targets = {mapping.target_field for mapping in spec.mappings}
    unknown = mapped_targets - allowed_targets
    if unknown:
        raise AdapterCompileError(f"adapter maps unsupported target fields: {sorted(unknown)}")
    missing = _REQUIRED_FIELDS[spec.record_kind] - mapped_targets
    if missing:
        raise AdapterCompileError(f"adapter omits required target fields: {sorted(missing)}")

    profile_columns = profile.column_names()
    source_columns: list[str] = []
    for mapping in spec.mappings:
        _validate_transform_target(mapping)
        if mapping.source_column is not None:
            if mapping.source_column not in profile_columns:
                raise AdapterCompileError(
                    f"adapter references missing source column {mapping.source_column!r}"
                )
            source_columns.append(mapping.source_column)
    if len(source_columns) != len(set(source_columns)):
        raise AdapterCompileError("one source column cannot drive multiple canonical fields")


_INTEGER_RE = re.compile(r"^[+-]?\d+$")
_GROUPED_NUMBER_RE = re.compile(
    r"^[+-]?(?:\d+|\d{1,3}(?:,\d{3})+|\d{1,3}(?:,\d{2})*(?:,\d{3}))(?:\.\d{1,2})?$"
)


def _source_value(row: RawRecord, mapping: FieldMapping) -> object:
    assert mapping.source_column is not None
    if mapping.source_column not in row:
        raise AdapterError(f"missing mapped source column {mapping.source_column!r}")
    return row[mapping.source_column]


def _text(value: object, *, optional: bool) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise AdapterError("text transform requires a string")
    stripped = value.strip()
    if not stripped:
        if optional:
            return None
        raise AdapterError("required text value is blank")
    return stripped


def _integer_paise(value: object) -> int:
    if isinstance(value, bool):
        raise AdapterError("integer-paise transform rejects bool")
    if isinstance(value, int):
        return value
    if not isinstance(value, str) or not _INTEGER_RE.fullmatch(value.strip()):
        raise AdapterError("integer-paise transform requires an exact integer")
    return int(value.strip())


def _rupees_to_paise(value: object) -> int:
    if isinstance(value, (bool, float)):
        raise AdapterError("rupees transform rejects bool/float inputs")
    text = str(value).strip() if isinstance(value, (str, int)) else ""
    if not text or not _GROUPED_NUMBER_RE.fullmatch(text):
        raise AdapterError("rupees transform received an invalid exact decimal")
    try:
        decimal = Decimal(text.replace(",", ""))
    except InvalidOperation as exc:
        raise AdapterError("rupees transform received an invalid decimal") from exc
    paise = decimal * 100
    if paise != paise.to_integral_value():
        raise AdapterError("rupees value has sub-paise precision")
    return int(paise)


def _iso_datetime(value: object) -> str:
    text = _text(value, optional=False)
    assert text is not None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise AdapterError("ISO datetime transform could not parse value") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AdapterError("ISO datetime transform requires timezone information")
    return parsed.isoformat()


def _date_to_iso(value: object, mapping: FieldMapping) -> str:
    text = _text(value, optional=False)
    assert text is not None
    assert mapping.date_format is not None
    assert mapping.timezone_offset_minutes is not None
    try:
        parsed = datetime.strptime(text, mapping.date_format)
    except ValueError as exc:
        raise AdapterError("date transform could not parse declared format") from exc
    offset = mapping.timezone_offset_minutes
    if not -14 * 60 <= offset <= 14 * 60:
        raise AdapterError("timezone offset is outside supported range")
    return parsed.replace(tzinfo=timezone(timedelta(minutes=offset))).isoformat()


def _apply_mapping(row: RawRecord, mapping: FieldMapping) -> object:
    if mapping.transform is TransformKind.CONSTANT:
        return mapping.constant
    value = _source_value(row, mapping)
    if mapping.transform is TransformKind.TEXT:
        return _text(value, optional=False)
    if mapping.transform is TransformKind.OPTIONAL_TEXT:
        return _text(value, optional=True)
    if mapping.transform is TransformKind.INTEGER_PAISE:
        return _integer_paise(value)
    if mapping.transform is TransformKind.RUPEES_TO_PAISE:
        return _rupees_to_paise(value)
    if mapping.transform is TransformKind.ISO_DATETIME:
        return _iso_datetime(value)
    if mapping.transform is TransformKind.DATE_TO_ISO_DATETIME:
        return _date_to_iso(value, mapping)
    raise AssertionError(f"unhandled transform {mapping.transform}")


CanonicalRecord = (
    domain.MerchantOrder
    | domain.PaymentEvent
    | domain.SettlementReconEntry
    | domain.Settlement
    | domain.BankEntry
)

_ADAPTERS: dict[CanonicalRecordKind, Callable[[RawRecord], CanonicalRecord]] = {
    CanonicalRecordKind.MERCHANT_ORDER: adapt_merchant_row,
    CanonicalRecordKind.PAYMENT_EVENT: adapt_payment_event,
    CanonicalRecordKind.SETTLEMENT_RECON: adapt_recon_row,
    CanonicalRecordKind.SETTLEMENT: adapt_settlement_row,
    CanonicalRecordKind.BANK_ENTRY: adapt_bank_row,
}


@dataclass(frozen=True, slots=True)
class CompiledAdapter:
    spec: AdapterSpec
    schema_fingerprint: str

    def normalize(self, row: RawRecord) -> dict[str, object]:
        return {
            mapping.target_field: _apply_mapping(row, mapping)
            for mapping in self.spec.mappings
        }

    def canonicalize(self, row: RawRecord) -> CanonicalRecord:
        return _ADAPTERS[self.spec.record_kind](self.normalize(row))


def compile_adapter(spec: AdapterSpec, profile: StructuralProfile) -> CompiledAdapter:
    _validate_spec(spec, profile)
    return CompiledAdapter(spec=spec, schema_fingerprint=profile.schema_fingerprint)


@dataclass(frozen=True, slots=True)
class SampleValidationReport:
    state: ActivationState
    row_count: int
    parsed_rows: int
    duplicate_identity_count: int
    error_messages: tuple[str, ...]
    financial_control_verified: bool = False

    @property
    def parse_rate_numerator(self) -> int:
        return self.parsed_rows

    @property
    def parse_rate_denominator(self) -> int:
        return self.row_count


def canonical_record_identity(record: CanonicalRecord) -> str:
    if isinstance(record, domain.PaymentEvent):
        return record.source_event_id
    return str(record.id)


def validate_sample(
    adapter: CompiledAdapter, rows: tuple[RawRecord, ...]
) -> SampleValidationReport:
    parsed: list[CanonicalRecord] = []
    errors: list[str] = []
    for index, row in enumerate(rows):
        try:
            parsed.append(adapter.canonicalize(row))
        except (AdapterError, TypeError, ValueError) as exc:
            errors.append(f"row {index}: {type(exc).__name__}: {exc}")
    identities = [canonical_record_identity(record) for record in parsed]
    duplicate_count = len(identities) - len(set(identities))
    if not rows or errors or duplicate_count:
        state = ActivationState.REJECTED
    else:
        state = ActivationState.APPROVED
    return SampleValidationReport(
        state=state,
        row_count=len(rows),
        parsed_rows=len(parsed),
        duplicate_identity_count=duplicate_count,
        error_messages=tuple(errors),
    )
