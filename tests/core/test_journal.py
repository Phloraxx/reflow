from datetime import UTC, datetime, timedelta

import pytest

from reflow.domain import SourceKind
from reflow.journal import (
    AppendDisposition,
    InMemoryJournal,
    JournalConflictError,
    make_source_envelope,
)

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def _envelope(payload: dict[str, object], *, received_offset: int = 0):
    return make_source_envelope(
        source_kind=SourceKind.RAZORPAY_EVENT,
        source_record_id="evt_1",
        occurred_at=NOW,
        received_at=NOW + timedelta(seconds=received_offset),
        schema_version="rzp-event-v1",
        payload=payload,
    )


def test_exact_duplicate_delivery_is_idempotent() -> None:
    journal = InMemoryJournal()
    first = journal.append(_envelope({"payment_id": "pay_1", "status": "captured"}))
    duplicate = journal.append(
        _envelope({"status": "captured", "payment_id": "pay_1"}, received_offset=5)
    )
    assert first.disposition is AppendDisposition.STORED
    assert duplicate.disposition is AppendDisposition.DUPLICATE
    assert len(journal) == 1


def test_same_source_identity_with_changed_payload_fails_closed() -> None:
    journal = InMemoryJournal()
    journal.append(_envelope({"payment_id": "pay_1", "status": "failed"}))
    with pytest.raises(JournalConflictError):
        journal.append(_envelope({"payment_id": "pay_1", "status": "captured"}))
    assert len(journal) == 1


def test_payload_hash_is_independent_of_mapping_key_order() -> None:
    first = _envelope({"a": 1, "b": 2})
    second = _envelope({"b": 2, "a": 1})
    assert first.payload_sha256 == second.payload_sha256
    assert first.id == second.id
