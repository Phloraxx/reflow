from datetime import UTC, datetime

import pytest

from reflow.domain.models import SourceEnvelope
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


def test_valid_source_envelope_retains_provenance() -> None:
    envelope = SourceEnvelope(
        id=SourceEnvelopeId("src_2"),
        source_kind=SourceKind.RAZORPAY_RECON,
        source_record_id="recon-row-2",
        occurred_at=NOW,
        received_at=NOW,
        payload_sha256="a" * 64,
        schema_version="rzp-recon-v1",
        payload={"settlement_id": "setl_2"},
    )
    assert envelope.source_record_id == "recon-row-2"
    assert envelope.payload["settlement_id"] == "setl_2"
