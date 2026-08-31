from __future__ import annotations

from dataclasses import replace

import pytest

from reflow.adapter_compiler import (
    ActivationState,
    AdapterCompileError,
    AdapterSpec,
    CanonicalRecordKind,
    FieldMapping,
    TransformKind,
    compile_adapter,
    profile_rows,
    validate_sample,
)
from reflow.domain import BankEntry, SourceKind


def _bank_rows() -> tuple[dict[str, object], ...]:
    return (
        {
            "Txn Ref": "bank_custom_001",
            "Amount Cr": "1,234.56",
            "Value Date": "31/08/2026",
            "Narrative": "SETTLEMENT UTR1001",
            "Bank Ref": "UTR1001",
        },
        {
            "Txn Ref": "bank_custom_002",
            "Amount Cr": "250.00",
            "Value Date": "31/08/2026",
            "Narrative": "SETTLEMENT UTR1002",
            "Bank Ref": "UTR1002",
        },
    )


def _bank_spec(*, money_transform: TransformKind = TransformKind.RUPEES_TO_PAISE) -> AdapterSpec:
    return AdapterSpec(
        adapter_id="bank_custom",
        version=1,
        source_kind=SourceKind.BANK,
        record_kind=CanonicalRecordKind.BANK_ENTRY,
        mappings=tuple(
            sorted(
                (
                    FieldMapping("amount_paise", money_transform, "Amount Cr"),
                    FieldMapping("bank_entry_id", TransformKind.TEXT, "Txn Ref"),
                    FieldMapping("currency", TransformKind.CONSTANT, constant="INR"),
                    FieldMapping("narration", TransformKind.TEXT, "Narrative"),
                    FieldMapping(
                        "occurred_at",
                        TransformKind.DATE_TO_ISO_DATETIME,
                        "Value Date",
                        date_format="%d/%m/%Y",
                        timezone_offset_minutes=330,
                    ),
                    FieldMapping("utr", TransformKind.OPTIONAL_TEXT, "Bank Ref"),
                ),
                key=lambda item: item.target_field,
            )
        ),
    )


def test_profile_fingerprint_depends_on_schema_not_values_or_row_order() -> None:
    rows = _bank_rows()
    changed_values = tuple(
        {**row, "Amount Cr": str(index + 10), "Narrative": f"different {index}"}
        for index, row in enumerate(reversed(rows))
    )
    first = profile_rows(rows)
    second = profile_rows(changed_values)
    assert first.schema_fingerprint == second.schema_fingerprint
    assert first.row_count == 2
    assert first.column("Amount Cr") is not None


def test_bank_adapter_compiles_rupees_date_and_existing_canonical_contract() -> None:
    rows = _bank_rows()
    adapter = compile_adapter(_bank_spec(), profile_rows(rows))
    first = adapter.canonicalize(rows[0])
    assert isinstance(first, BankEntry)
    assert first.amount.amount_paise == 123456
    assert first.occurred_at.utcoffset() is not None
    assert int(first.occurred_at.utcoffset().total_seconds()) == 19800
    assert first.utr == "UTR1001"
    report = validate_sample(adapter, rows)
    assert report.state is ActivationState.APPROVED
    assert report.parsed_rows == 2


def test_wrong_rupee_paise_proposal_is_rejected_by_sample_execution() -> None:
    rows = _bank_rows()
    adapter = compile_adapter(
        _bank_spec(money_transform=TransformKind.INTEGER_PAISE),
        profile_rows(rows),
    )
    report = validate_sample(adapter, rows)
    assert report.state is ActivationState.REJECTED
    assert report.parsed_rows == 0
    assert all("integer-paise" in message for message in report.error_messages)


def test_negative_bank_credit_proposal_cannot_activate() -> None:
    rows = ({**_bank_rows()[0], "Amount Cr": "-10.00"},)
    adapter = compile_adapter(_bank_spec(), profile_rows(rows))
    report = validate_sample(adapter, rows)
    assert report.state is ActivationState.REJECTED
    assert "cannot be negative" in report.error_messages[0]


def test_missing_source_column_fails_static_compilation() -> None:
    rows = _bank_rows()
    broken = replace(
        _bank_spec(),
        mappings=tuple(
            replace(mapping, source_column="Missing")
            if mapping.target_field == "utr"
            else mapping
            for mapping in _bank_spec().mappings
        ),
    )
    with pytest.raises(AdapterCompileError, match="missing source column"):
        compile_adapter(broken, profile_rows(rows))


def test_one_source_column_cannot_drive_multiple_financial_fields() -> None:
    rows = _bank_rows()
    mappings = tuple(
        replace(mapping, source_column="Txn Ref")
        if mapping.target_field == "narration"
        else mapping
        for mapping in _bank_spec().mappings
    )
    with pytest.raises(AdapterCompileError, match="cannot drive multiple"):
        compile_adapter(replace(_bank_spec(), mappings=mappings), profile_rows(rows))


def test_duplicate_canonical_source_identity_rejects_activation() -> None:
    row = _bank_rows()[0]
    rows = (row, {**_bank_rows()[1], "Txn Ref": row["Txn Ref"]})
    report = validate_sample(compile_adapter(_bank_spec(), profile_rows(rows)), rows)
    assert report.state is ActivationState.REJECTED
    assert report.duplicate_identity_count == 1
