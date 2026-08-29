from collections.abc import Mapping
from datetime import UTC, datetime

import pytest

from reflow.domain.models import SourceEnvelope
from reflow.domain.source_hash import source_payload_sha256
from reflow.domain.types import SourceEnvelopeId, SourceKind

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def test_source_hash_must_be_sha256_shape() -> None:
    with pytest.raises(ValueError):
        SourceEnvelope(
            id=SourceEnvelopeId("src_1"),
            source_kind=SourceKind.BANK,
            source_record_id="row-1",
            occurred_at=NOW,
            received_at=NOW,
            payload_sha256="bad",
            schema_version="bank-v1",
        )


def test_source_hash_must_match_payload() -> None:
    with pytest.raises(ValueError, match="does not match"):
        SourceEnvelope(
            id=SourceEnvelopeId("src_2"),
            source_kind=SourceKind.BANK,
            source_record_id="row-2",
            occurred_at=NOW,
            received_at=NOW,
            payload_sha256="a" * 64,
            schema_version="bank-v1",
            payload={"amount": 100},
        )


def test_valid_source_envelope_retains_provenance() -> None:
    payload = {"settlement_id": "setl_2"}
    envelope = SourceEnvelope(
        id=SourceEnvelopeId("src_3"),
        source_kind=SourceKind.RAZORPAY_RECON,
        source_record_id="recon-row-2",
        occurred_at=NOW,
        received_at=NOW,
        payload_sha256=source_payload_sha256(payload),
        schema_version="rzp-recon-v1",
        payload=payload,
    )
    assert envelope.source_record_id == "recon-row-2"
    assert envelope.payload["settlement_id"] == "setl_2"
    assert source_payload_sha256(envelope.payload) == envelope.payload_sha256


def test_source_payload_is_deeply_immutable_after_construction() -> None:
    payload = {"nested": {"amount": 100}, "rows": [{"id": "one"}]}
    envelope = SourceEnvelope(
        id=SourceEnvelopeId("src_4"),
        source_kind=SourceKind.BANK,
        source_record_id="row-3",
        occurred_at=NOW,
        received_at=NOW,
        payload_sha256=source_payload_sha256(payload),
        schema_version="bank-v1",
        payload=payload,
    )
    with pytest.raises(TypeError):
        envelope.payload["new"] = "value"  # type: ignore[index]

    nested = envelope.payload["nested"]
    assert isinstance(nested, Mapping)
    with pytest.raises(TypeError):
        nested["amount"] = 200  # type: ignore[index]

    rows = envelope.payload["rows"]
    assert isinstance(rows, tuple)
    assert isinstance(rows[0], Mapping)
    with pytest.raises(TypeError):
        rows[0]["id"] = "changed"  # type: ignore[index]
