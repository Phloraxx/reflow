from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from .observability import (
    EventSink,
    MetricsRegistry,
    install_http_observability,
    json_event_sink,
    metrics_response,
    metrics_token_from_env,
    normalize_metrics_token,
    request_id,
)
from .persistence import PostgresApplicationStore
from .webhook_ingress import (
    MAX_WEBHOOK_BODY_BYTES,
    RazorpayWebhookIngress,
    WebhookAuthenticationError,
    WebhookIngressError,
    WebhookPersistenceError,
    WebhookReceiptConflictError,
    razorpay_webhook_ingress_from_env,
)

__all__ = ["app_from_env", "create_webhook_app"]


async def _bounded_body(request: Request) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid content length") from exc
        if declared < 0:
            raise HTTPException(status_code=400, detail="invalid content length")
        if declared > MAX_WEBHOOK_BODY_BYTES:
            raise HTTPException(status_code=413, detail="webhook body too large")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_WEBHOOK_BODY_BYTES:
            raise HTTPException(status_code=413, detail="webhook body too large")
    return bytes(body)


def create_webhook_app(
    ingress: RazorpayWebhookIngress,
    *,
    readiness_probe: Callable[[], None],
    metrics: MetricsRegistry | None = None,
    metrics_token: str | None = None,
    event_sink: EventSink | None = None,
) -> FastAPI:
    metrics_token = normalize_metrics_token(metrics_token)

    app = FastAPI(
        title="ReFlow Razorpay Webhook Ingress",
        version="0.1.0",
        description="Public provider-authenticated receipt boundary; no reconciliation authority.",
    )
    metrics_registry = metrics if metrics is not None else MetricsRegistry()
    sink = event_sink if event_sink is not None else json_event_sink("reflow-webhook")
    install_http_observability(app, metrics=metrics_registry, event_sink=sink)

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "provider": "razorpay",
            "financial_truth_mutation": False,
            "request_correlation": "generated",
            "metrics": "token_gated" if metrics_token is not None else "disabled",
        }

    @app.get("/ready")
    def ready() -> JSONResponse:
        try:
            readiness_probe()
        except Exception:
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "dependency": "postgresql"},
            )
        return JSONResponse(
            status_code=200,
            content={"status": "ready", "dependency": "postgresql"},
        )

    @app.get("/internal/metrics", include_in_schema=False)
    def internal_metrics(request: Request) -> PlainTextResponse:
        return metrics_response(request, metrics=metrics_registry, token=metrics_token)

    @app.post("/api/v1/webhooks/razorpay")
    async def razorpay_webhook(request: Request) -> JSONResponse:
        raw_body = await _bounded_body(request)
        try:
            result = ingress.receive(
                raw_body=raw_body,
                headers=dict(request.headers),
                received_at=datetime.now(tz=UTC),
            )
        except WebhookAuthenticationError as exc:
            raise HTTPException(
                status_code=401,
                detail="invalid webhook authentication",
            ) from exc
        except WebhookReceiptConflictError as exc:
            raise HTTPException(status_code=409, detail="webhook receipt conflict") from exc
        except WebhookPersistenceError as exc:
            raise HTTPException(
                status_code=503,
                detail="webhook persistence unavailable",
            ) from exc
        except WebhookIngressError as exc:
            raise HTTPException(status_code=400, detail="invalid webhook request") from exc
        metrics_registry.record_webhook(
            disposition=result.disposition.value,
            processing_outcome=result.outcome.value,
            processing_code=result.outcome_code,
        )
        sink(
            {
                "event.name": "reflow.webhook.ingress",
                "reflow.request_id": request_id(request),
                "reflow.webhook.disposition": result.disposition.value,
                "reflow.webhook.processing_outcome": result.outcome.value,
                "reflow.webhook.processing_code": result.outcome_code,
            }
        )
        return JSONResponse(
            status_code=202 if result.disposition.value == "stored" else 200,
            content={
                "status": "accepted",
                "disposition": result.disposition.value,
                "processing_outcome": result.outcome.value,
                "processing_code": result.outcome_code,
            },
        )

    return app


def app_from_env() -> FastAPI:
    dsn = os.getenv("REFLOW_POSTGRES_DSN")
    if dsn is None or not dsn.strip() or dsn != dsn.strip():
        raise RuntimeError("REFLOW_POSTGRES_DSN is required for webhook ingress")
    application_store = PostgresApplicationStore(dsn)
    ingress, webhook_readiness = razorpay_webhook_ingress_from_env(
        dsn=dsn,
        journal=application_store,
    )
    if ingress is None or webhook_readiness is None:
        raise RuntimeError("REFLOW_RAZORPAY_WEBHOOK_MODE=enabled is required for webhook serving")
    metrics_token = metrics_token_from_env()

    def readiness() -> None:
        application_store.check_ready()
        webhook_readiness()

    return create_webhook_app(
        ingress,
        readiness_probe=readiness,
        metrics_token=metrics_token,
    )
