from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime

import pytest

from reflow.webhook_ingress import (
    PostgresWebhookReceiptStore,
    WebhookProcessingOutcome,
    WebhookReceipt,
    WebhookReceiptConflictError,
    WebhookReceiptDisposition,
    WebhookSecretGeneration,
)

DSN = os.getenv("REFLOW_TEST_POSTGRES_DSN")
NOW = datetime(2026, 9, 3, 16, 30, tzinfo=UTC)
ACCOUNT = "acc_webhook_pg_test"

pytestmark = pytest.mark.skipif(DSN is None, reason="PostgreSQL test DSN is not configured")


def _receipt(event_id: str, raw_body: bytes) -> WebhookReceipt:
    return WebhookReceipt(
        provider="razorpay",
        account_id=ACCOUNT,
        event_id=event_id,
        body_sha256=hashlib.sha256(raw_body).hexdigest(),
        raw_body=raw_body,
        signature="a" * 64,
        first_received_at=NOW,
        secret_generation=WebhookSecretGeneration.CURRENT,
    )


def test_postgres_webhook_receipt_duplicate_attempt_and_listing() -> None:
    assert DSN is not None
    store = PostgresWebhookReceiptStore(DSN)
    store.check_ready()
    receipt = _receipt("evt_webhook_pg_1", b'{"event":"unsupported"}')
    first = store.append_receipt(receipt)
    second = store.append_receipt(receipt)
    assert first.disposition in {
        WebhookReceiptDisposition.STORED,
        WebhookReceiptDisposition.DUPLICATE,
    }
    assert second.disposition is WebhookReceiptDisposition.DUPLICATE

    existing_attempts = store.attempts(ACCOUNT, receipt.event_id)
    attempt = store.record_attempt(
        account_id=ACCOUNT,
        event_id=receipt.event_id,
        attempted_at=NOW,
        outcome=WebhookProcessingOutcome.REJECTED,
        outcome_code="provider_payload_rejected",
    )
    assert attempt.attempt_id > 0
    attempts = store.attempts(ACCOUNT, receipt.event_id)
    assert len(attempts) == len(existing_attempts) + 1
    assert attempts[-1].outcome is WebhookProcessingOutcome.REJECTED

    summary = next(
        item
        for item in store.list_receipts(ACCOUNT, limit=100)
        if item.event_id == receipt.event_id
    )
    assert summary.latest_outcome is WebhookProcessingOutcome.REJECTED
    assert summary.latest_outcome_code == "provider_payload_rejected"
    assert summary.attempt_count == len(attempts)


def test_postgres_webhook_event_identity_conflict_fails_closed() -> None:
    assert DSN is not None
    store = PostgresWebhookReceiptStore(DSN)
    first = _receipt("evt_webhook_pg_conflict", b"first")
    second = _receipt("evt_webhook_pg_conflict", b"second")
    store.append_receipt(first)
    with pytest.raises(WebhookReceiptConflictError):
        store.append_receipt(second)
    retained = store.get_receipt(ACCOUNT, first.event_id)
    assert retained is not None
    assert retained.raw_body == b"first"


def test_webhook_integrity_inventory_covers_receipts_and_attempts() -> None:
    assert DSN is not None
    store = PostgresWebhookReceiptStore(DSN)
    receipt_count, attempt_count = store.integrity_counts()
    assert receipt_count >= 2
    assert attempt_count >= 1
