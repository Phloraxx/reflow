from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

from reflow.observability import MetricsRegistry
from reflow.webhook_api import create_webhook_app
from reflow.webhook_ingress import (
    MAX_WEBHOOK_BODY_BYTES,
    WebhookAuthenticationError,
    WebhookIngressResult,
    WebhookPersistenceError,
    WebhookProcessingOutcome,
    WebhookReceiptConflictError,
    WebhookReceiptDisposition,
)


@dataclass
class StubIngress:
    result: WebhookIngressResult | None = None
    failure: Exception | None = None
    seen_body: bytes | None = None

    def receive(self, *, raw_body, headers, received_at):
        self.seen_body = raw_body
        if self.failure is not None:
            raise self.failure
        assert self.result is not None
        return self.result


def _client(
    ingress: StubIngress,
    *,
    ready: bool = True,
    metrics: MetricsRegistry | None = None,
    metrics_token: str | None = None,
    event_sink=None,
) -> TestClient:
    def readiness() -> None:
        if not ready:
            raise RuntimeError("database unavailable")

    return TestClient(
        create_webhook_app(
            ingress,  # type: ignore[arg-type]
            readiness_probe=readiness,
            metrics=metrics,
            metrics_token=metrics_token,
            event_sink=event_sink,
        )
    )


def test_health_and_readiness_are_non_sensitive() -> None:
    ingress = StubIngress(
        result=WebhookIngressResult(
            WebhookReceiptDisposition.STORED,
            WebhookProcessingOutcome.PROCESSED,
            "canonicalized",
        )
    )
    client = _client(ingress)
    assert client.get("/health").json() == {
        "status": "ok",
        "provider": "razorpay",
        "financial_truth_mutation": False,
        "request_correlation": "generated",
        "metrics": "disabled",
    }
    assert client.get("/internal/metrics").status_code == 404
    assert client.get("/ready").status_code == 200
    failed = _client(ingress, ready=False).get("/ready")
    assert failed.status_code == 503
    assert "unavailable" not in failed.text


def test_body_limit_is_enforced_before_ingress_processing() -> None:
    ingress = StubIngress(
        result=WebhookIngressResult(
            WebhookReceiptDisposition.STORED,
            WebhookProcessingOutcome.PROCESSED,
            "canonicalized",
        )
    )
    response = _client(ingress).post(
        "/api/v1/webhooks/razorpay",
        content=b"x" * (MAX_WEBHOOK_BODY_BYTES + 1),
    )
    assert response.status_code == 413
    assert ingress.seen_body is None


def test_stored_and_duplicate_receipts_return_provider_success() -> None:
    stored = StubIngress(
        result=WebhookIngressResult(
            WebhookReceiptDisposition.STORED,
            WebhookProcessingOutcome.REJECTED,
            "provider_payload_rejected",
        )
    )
    stored_response = _client(stored).post(
        "/api/v1/webhooks/razorpay",
        content=b"signed-but-malformed",
    )
    assert stored_response.status_code == 202
    assert stored_response.json()["processing_outcome"] == "rejected"

    duplicate = StubIngress(
        result=WebhookIngressResult(
            WebhookReceiptDisposition.DUPLICATE,
            WebhookProcessingOutcome.REJECTED,
            "provider_payload_rejected",
        )
    )
    duplicate_response = _client(duplicate).post(
        "/api/v1/webhooks/razorpay",
        content=b"signed-but-malformed",
    )
    assert duplicate_response.status_code == 200
    assert duplicate_response.json()["disposition"] == "duplicate"


def test_auth_conflict_and_persistence_failures_are_non_2xx() -> None:
    cases = (
        (WebhookAuthenticationError("secret detail"), 401),
        (WebhookReceiptConflictError("secret detail"), 409),
        (WebhookPersistenceError("database dsn detail"), 503),
    )
    for failure, expected_status in cases:
        response = _client(StubIngress(failure=failure)).post(
            "/api/v1/webhooks/razorpay",
            content=b"body",
        )
        assert response.status_code == expected_status
        assert "secret detail" not in response.text
        assert "database dsn detail" not in response.text


def test_webhook_observability_is_correlated_bounded_and_secret_free() -> None:
    ingress = StubIngress(
        result=WebhookIngressResult(
            WebhookReceiptDisposition.STORED,
            WebhookProcessingOutcome.REJECTED,
            "provider_payload_rejected",
        )
    )
    metrics = MetricsRegistry()
    telemetry: list[dict[str, object]] = []
    token = "m" * 48
    client = _client(
        ingress,
        metrics=metrics,
        metrics_token=token,
        event_sink=telemetry.append,
    )
    raw = b"signed-but-malformed-secret-body"
    response = client.post("/api/v1/webhooks/razorpay", content=raw)
    assert response.status_code == 202
    correlation = response.headers["x-request-id"]
    webhook_event = next(
        event for event in telemetry if event.get("event.name") == "reflow.webhook.ingress"
    )
    assert webhook_event["reflow.request_id"] == correlation
    assert webhook_event["reflow.webhook.disposition"] == "stored"
    assert webhook_event["reflow.webhook.processing_outcome"] == "rejected"
    assert webhook_event["reflow.webhook.processing_code"] == "provider_payload_rejected"

    assert client.get("/internal/metrics").status_code == 401
    metric_response = client.get(
        "/internal/metrics",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert metric_response.status_code == 200
    assert "reflow_webhook_receipts_total" in metric_response.text
    assert 'processing_code="provider_payload_rejected"' in metric_response.text
    serialized = repr(telemetry) + metric_response.text
    assert raw.decode() not in serialized
    assert token not in serialized
    assert "x-razorpay-signature" not in serialized.lower()
