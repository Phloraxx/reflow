from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import pytest

from reflow.journal import InMemoryJournal
from reflow.razorpay_integration import RazorpayAccountContext, RazorpayEvidenceOrigin
from reflow.webhook_ingress import (
    RazorpayWebhookIngress,
    WebhookAttempt,
    WebhookAuthenticationError,
    WebhookIngressError,
    WebhookProcessingOutcome,
    WebhookReceipt,
    WebhookReceiptConflictError,
    WebhookReceiptDisposition,
    WebhookReceiptResult,
    WebhookReceiptSummary,
    WebhookSecretGeneration,
    WebhookSecrets,
    verify_razorpay_webhook,
)

NOW = datetime(2026, 9, 3, 16, 0, tzinfo=UTC)
ACCOUNT = "acc_webhook_ingress"
CURRENT = "webhook_current_secret"
PREVIOUS = "webhook_previous_secret"


class MemoryReceiptStore:
    def __init__(self) -> None:
        self.receipts: dict[tuple[str, str], WebhookReceipt] = {}
        self.attempt_rows: dict[tuple[str, str], list[WebhookAttempt]] = {}

    def append_receipt(self, receipt: WebhookReceipt) -> WebhookReceiptResult:
        key = (receipt.account_id, receipt.event_id)
        existing = self.receipts.get(key)
        if existing is None:
            self.receipts[key] = receipt
            return WebhookReceiptResult(WebhookReceiptDisposition.STORED, receipt)
        if existing.raw_body != receipt.raw_body:
            raise WebhookReceiptConflictError("conflict")
        return WebhookReceiptResult(WebhookReceiptDisposition.DUPLICATE, existing)

    def get_receipt(self, account_id: str, event_id: str) -> WebhookReceipt | None:
        return self.receipts.get((account_id, event_id))

    def attempts(self, account_id: str, event_id: str) -> tuple[WebhookAttempt, ...]:
        return tuple(self.attempt_rows.get((account_id, event_id), ()))

    def record_attempt(
        self,
        *,
        account_id: str,
        event_id: str,
        attempted_at: datetime,
        outcome: WebhookProcessingOutcome,
        outcome_code: str,
    ) -> WebhookAttempt:
        key = (account_id, event_id)
        rows = self.attempt_rows.setdefault(key, [])
        attempt = WebhookAttempt(
            len(rows) + 1,
            event_id,
            attempted_at,
            outcome,
            outcome_code,
        )
        rows.append(attempt)
        return attempt

    def list_receipts(
        self,
        account_id: str,
        *,
        limit: int,
    ) -> tuple[WebhookReceiptSummary, ...]:
        values = [
            value
            for (account, _event), value in self.receipts.items()
            if account == account_id
        ]
        values.sort(
            key=lambda item: (item.first_received_at, item.event_id),
            reverse=True,
        )
        result = []
        for receipt in values[:limit]:
            attempts = self.attempts(account_id, receipt.event_id)
            latest = attempts[-1] if attempts else None
            result.append(
                WebhookReceiptSummary(
                    receipt.event_id,
                    receipt.first_received_at,
                    receipt.body_sha256,
                    receipt.secret_generation,
                    None if latest is None else latest.outcome,
                    None if latest is None else latest.outcome_code,
                    len(attempts),
                )
            )
        return tuple(result)


def _context() -> RazorpayAccountContext:
    return RazorpayAccountContext(
        ACCOUNT,
        RazorpayEvidenceOrigin.REAL_TEST_MODE,
    )


def _payment_body(event: str = "payment.captured") -> bytes:
    return json.dumps(
        {
            "entity": "event",
            "account_id": ACCOUNT,
            "event": event,
            "contains": ["payment"],
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_webhook_ingress",
                        "entity": "payment",
                        "amount": 12345,
                        "currency": "INR",
                        "status": "captured",
                        "order_id": "order_webhook_ingress",
                        "error_code": None,
                        "error_reason": None,
                        "created_at": 1788451200,
                    }
                }
            },
            "created_at": 1788451200,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _headers(
    raw: bytes,
    *,
    event_id: str = "evt_webhook_ingress",
    secret: str = CURRENT,
) -> dict[str, str]:
    return {
        "x-razorpay-event-id": event_id,
        "X-Razorpay-Signature": hmac.new(
            secret.encode(),
            raw,
            hashlib.sha256,
        ).hexdigest(),
    }


def _service(store: MemoryReceiptStore | None = None):
    receipt_store = store or MemoryReceiptStore()
    return (
        RazorpayWebhookIngress(
            receipt_store=receipt_store,
            journal=InMemoryJournal(),
            context=_context(),
            secrets=WebhookSecrets(CURRENT, PREVIOUS),
        ),
        receipt_store,
    )


def test_signature_verification_supports_current_and_previous_rotation() -> None:
    raw = _payment_body()
    current = verify_razorpay_webhook(
        raw_body=raw,
        headers=_headers(raw),
        secrets=WebhookSecrets(CURRENT, PREVIOUS),
    )
    previous = verify_razorpay_webhook(
        raw_body=raw,
        headers=_headers(raw, secret=PREVIOUS),
        secrets=WebhookSecrets(CURRENT, PREVIOUS),
    )
    assert current[2] is WebhookSecretGeneration.CURRENT
    assert previous[2] is WebhookSecretGeneration.PREVIOUS


def test_invalid_signature_is_rejected_before_receipt() -> None:
    service, store = _service()
    raw = _payment_body()
    with pytest.raises(WebhookAuthenticationError):
        service.receive(
            raw_body=raw,
            headers=_headers(raw, secret="wrong"),
            received_at=NOW,
        )
    assert store.receipts == {}


def test_valid_payment_is_retained_then_canonicalized() -> None:
    service, store = _service()
    raw = _payment_body()
    result = service.receive(
        raw_body=raw,
        headers=_headers(raw),
        received_at=NOW,
    )
    assert result.disposition is WebhookReceiptDisposition.STORED
    assert result.outcome is WebhookProcessingOutcome.PROCESSED
    assert result.outcome_code == "canonicalized"
    receipt = store.get_receipt(ACCOUNT, "evt_webhook_ingress")
    assert receipt is not None
    assert receipt.raw_body == raw


def test_signed_malformed_json_is_durable_and_rejected() -> None:
    service, store = _service()
    raw = b"{not-json"
    result = service.receive(
        raw_body=raw,
        headers=_headers(raw, event_id="evt_bad_json"),
        received_at=NOW,
    )
    assert result.outcome is WebhookProcessingOutcome.REJECTED
    assert result.outcome_code == "provider_payload_rejected"
    assert store.get_receipt(ACCOUNT, "evt_bad_json") is not None


def test_exact_redelivery_is_idempotent_and_does_not_add_attempt() -> None:
    service, store = _service()
    raw = _payment_body()
    first = service.receive(raw_body=raw, headers=_headers(raw), received_at=NOW)
    second = service.receive(
        raw_body=raw,
        headers=_headers(raw),
        received_at=NOW + timedelta(seconds=3),
    )
    assert first.disposition is WebhookReceiptDisposition.STORED
    assert second.disposition is WebhookReceiptDisposition.DUPLICATE
    assert len(store.attempts(ACCOUNT, "evt_webhook_ingress")) == 1


def test_same_event_id_different_body_fails_closed() -> None:
    service, _store = _service()
    first = _payment_body()
    second = _payment_body("payment.failed")
    service.receive(raw_body=first, headers=_headers(first), received_at=NOW)
    with pytest.raises(WebhookReceiptConflictError):
        service.receive(
            raw_body=second,
            headers=_headers(second),
            received_at=NOW + timedelta(seconds=1),
        )


def test_replay_uses_immutable_retained_receipt_and_adds_attempt() -> None:
    service, store = _service()
    raw = b"{not-json"
    service.receive(
        raw_body=raw,
        headers=_headers(raw, event_id="evt_replay"),
        received_at=NOW,
    )
    replay = service.replay(
        "evt_replay",
        attempted_at=NOW + timedelta(minutes=1),
    )
    assert replay.attempt_id == 2
    assert replay.outcome is WebhookProcessingOutcome.REJECTED
    assert len(store.attempts(ACCOUNT, "evt_replay")) == 2


def test_old_receipt_replay_fails_closed_after_rotation_window() -> None:
    store = MemoryReceiptStore()
    old_service = RazorpayWebhookIngress(
        receipt_store=store,
        journal=InMemoryJournal(),
        context=_context(),
        secrets=WebhookSecrets(PREVIOUS),
    )
    raw = b"{not-json"
    old_service.receive(
        raw_body=raw,
        headers=_headers(raw, event_id="evt_old", secret=PREVIOUS),
        received_at=NOW,
    )
    new_service = RazorpayWebhookIngress(
        receipt_store=store,
        journal=InMemoryJournal(),
        context=_context(),
        secrets=WebhookSecrets(CURRENT),
    )
    replay = new_service.replay(
        "evt_old",
        attempted_at=NOW + timedelta(days=2),
    )
    assert replay.outcome is WebhookProcessingOutcome.REJECTED
    assert replay.outcome_code == "verification_key_unavailable"


def test_receipt_listing_contains_no_raw_body_or_signature() -> None:
    service, _store = _service()
    raw = _payment_body()
    service.receive(raw_body=raw, headers=_headers(raw), received_at=NOW)
    summary = service.list_receipts(limit=1)[0]
    assert summary.event_id == "evt_webhook_ingress"
    assert not hasattr(summary, "raw_body")
    assert not hasattr(summary, "signature")
    with pytest.raises(WebhookIngressError):
        service.list_receipts(limit=101)
