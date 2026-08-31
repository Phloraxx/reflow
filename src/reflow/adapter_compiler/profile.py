from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from reflow.ingestion import RawRecord


def _normalize_column(value: str) -> str:
    return " ".join(value.casefold().strip().split())


def _type_family(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    return "other"


@dataclass(frozen=True, slots=True)
class ColumnProfile:
    name: str
    normalized_name: str
    present_count: int
    null_count: int
    type_families: tuple[str, ...]
    unique_non_null_count: int


@dataclass(frozen=True, slots=True)
class StructuralProfile:
    row_count: int
    columns: tuple[ColumnProfile, ...]
    schema_fingerprint: str
    sample_rows: tuple[dict[str, object], ...]

    def column_names(self) -> frozenset[str]:
        return frozenset(column.name for column in self.columns)

    def column(self, name: str) -> ColumnProfile | None:
        return next((column for column in self.columns if column.name == name), None)


def profile_rows(rows: tuple[RawRecord, ...], *, sample_limit: int = 5) -> StructuralProfile:
    if sample_limit < 0:
        raise ValueError("sample limit cannot be negative")
    names = sorted({key for row in rows for key in row})
    columns: list[ColumnProfile] = []
    fingerprint_columns: list[dict[str, object]] = []
    for name in names:
        values = [row[name] for row in rows if name in row]
        non_null_values = [value for value in values if value is not None]
        families = tuple(sorted({_type_family(value) for value in values}))
        column = ColumnProfile(
            name=name,
            normalized_name=_normalize_column(name),
            present_count=len(values),
            null_count=sum(value is None for value in values),
            type_families=families,
            unique_non_null_count=len(
                {
                    json.dumps(value, sort_keys=True, default=str)
                    for value in non_null_values
                }
            ),
        )
        columns.append(column)
        fingerprint_columns.append(
            {
                "normalized_name": column.normalized_name,
                "type_families": list(column.type_families),
            }
        )
    encoded = json.dumps(
        fingerprint_columns,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    fingerprint = hashlib.sha256(encoded).hexdigest()
    samples = tuple(dict(row) for row in rows[:sample_limit])
    return StructuralProfile(
        row_count=len(rows),
        columns=tuple(columns),
        schema_fingerprint=fingerprint,
        sample_rows=samples,
    )
