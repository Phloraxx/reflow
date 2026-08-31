from __future__ import annotations

from collections.abc import Mapping

from reflow.domain import SourceKind

from .contracts import AdapterSpec, CanonicalRecordKind, FieldMapping, TransformKind


class AdapterSpecParseError(ValueError):
    """Structured model output did not satisfy the AdapterSpec wire contract."""


def adapter_spec_json_schema() -> dict[str, object]:
    mapping_schema: dict[str, object] = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "target_field",
            "transform",
            "source_column",
            "constant",
            "date_format",
            "timezone_offset_minutes",
        ],
        "properties": {
            "target_field": {"type": "string"},
            "transform": {"type": "string", "enum": [item.value for item in TransformKind]},
            "source_column": {"type": ["string", "null"]},
            "constant": {"type": ["string", "integer", "null"]},
            "date_format": {"type": ["string", "null"]},
            "timezone_offset_minutes": {"type": ["integer", "null"]},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["adapter_id", "version", "source_kind", "record_kind", "mappings"],
        "properties": {
            "adapter_id": {"type": "string"},
            "version": {"type": "integer", "minimum": 1},
            "source_kind": {"type": "string", "enum": [item.value for item in SourceKind]},
            "record_kind": {
                "type": "string",
                "enum": [item.value for item in CanonicalRecordKind],
            },
            "mappings": {"type": "array", "minItems": 1, "items": mapping_schema},
        },
    }


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise AdapterSpecParseError(f"{label} must be an object with string keys")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise AdapterSpecParseError(f"{label} must be a string")
    return value


def _optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _string(value, label)


def _optional_int(value: object, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise AdapterSpecParseError(f"{label} must be an integer or null")
    return value


def parse_adapter_spec_payload(payload: object) -> AdapterSpec:
    root = _mapping(payload, "adapter spec")
    raw_mappings = root.get("mappings")
    if not isinstance(raw_mappings, list):
        raise AdapterSpecParseError("adapter mappings must be an array")
    mappings: list[FieldMapping] = []
    for raw in raw_mappings:
        item = _mapping(raw, "field mapping")
        constant = item.get("constant")
        if constant is not None and (isinstance(constant, bool) or not isinstance(constant, (str, int))):
            raise AdapterSpecParseError("mapping constant must be string, integer or null")
        mappings.append(
            FieldMapping(
                target_field=_string(item.get("target_field"), "target field"),
                transform=TransformKind(_string(item.get("transform"), "transform")),
                source_column=_optional_string(item.get("source_column"), "source column"),
                constant=constant,
                date_format=_optional_string(item.get("date_format"), "date format"),
                timezone_offset_minutes=_optional_int(
                    item.get("timezone_offset_minutes"), "timezone offset"
                ),
            )
        )
    try:
        source_kind = SourceKind(_string(root.get("source_kind"), "source kind"))
        record_kind = CanonicalRecordKind(_string(root.get("record_kind"), "record kind"))
    except ValueError as exc:
        raise AdapterSpecParseError(str(exc)) from exc
    version = root.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise AdapterSpecParseError("adapter version must be an integer")
    return AdapterSpec(
        adapter_id=_string(root.get("adapter_id"), "adapter id"),
        version=version,
        source_kind=source_kind,
        record_kind=record_kind,
        mappings=tuple(sorted(mappings, key=lambda item: item.target_field)),
    )
