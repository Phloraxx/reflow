from __future__ import annotations

import json
from collections.abc import Mapping

from reflow.adapter_compiler.contracts import CanonicalRecordKind, FinancialControlTotal
from reflow.adapter_compiler.deepseek_provider import DeepSeekAdapterProposalProvider
from reflow.adapter_compiler.provider import _propose_and_validate_rows
from reflow.domain import SourceKind


def _response(payload: object) -> Mapping[str, object]:
    return {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": json.dumps(payload)}],
            }
        ]
    }


def _spec() -> dict[str, object]:
    mappings = [
        ("amount_paise", "rupees_to_paise", "Credit", None, None, None),
        ("bank_entry_id", "text", "Txn", None, None, None),
        ("currency", "constant", None, "INR", None, None),
        ("narration", "text", "Memo", None, None, None),
        ("occurred_at", "date_to_iso_datetime", "Date", None, "%d/%m/%Y", 330),
        ("utr", "optional_text", "Reference", None, None, None),
    ]
    return {
        "adapter_id": "deepseek_bank",
        "version": 1,
        "source_kind": "bank",
        "record_kind": "bank_entry",
        "mappings": [
            {
                "target_field": target,
                "transform": transform,
                "source_column": source,
                "constant": constant,
                "date_format": date_format,
                "timezone_offset_minutes": offset,
            }
            for target, transform, source, constant, date_format, offset in sorted(mappings)
        ],
    }


def test_deepseek_responses_schema_proposal_is_still_deterministically_validated() -> None:
    captured: dict[str, object] = {}

    def transport(url, headers, payload, timeout):
        captured.update({"url": url, "headers": headers, "payload": payload, "timeout": timeout})
        return _response(_spec())

    provider = DeepSeekAdapterProposalProvider(api_key="test-key", transport=transport)
    rows = (
        {
            "Txn": "bank_1",
            "Credit": "100.00",
            "Date": "04/09/2026",
            "Memo": "RAZORPAY SETTLEMENT",
            "Reference": "UTR-1",
        },
    )
    result = _propose_and_validate_rows(
        provider,
        rows,
        adapter_id="deepseek_bank",
        version=1,
        source_kind=SourceKind.BANK,
        record_kind=CanonicalRecordKind.BANK_ENTRY,
        financial_control=FinancialControlTotal(
            target_field="amount_paise",
            expected_total_paise=10_000,
            expected_row_count=1,
            evidence_label="test control",
        ),
    )
    assert result.sample_report is not None
    assert result.sample_report.financial_control_verified
    assert result.sample_report.state.value == "needs_review"
    assert captured["url"] == "https://api.deepseek.com/responses"
    request = captured["payload"]
    assert isinstance(request, Mapping)
    fmt = request["text"]
    assert isinstance(fmt, Mapping)
    schema_format = fmt["format"]
    assert isinstance(schema_format, Mapping)
    assert schema_format["type"] == "json_schema"
    assert "strict" not in schema_format
