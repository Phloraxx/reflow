from __future__ import annotations

import json
import re

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from reflow.observability import (
    HTTP_DURATION_BUCKETS_SECONDS,
    MetricsRegistry,
    install_http_observability,
    metrics_response,
    normalize_metrics_token,
)


def _app(*, metrics_token: str | None = None):
    metrics = MetricsRegistry()
    events: list[dict[str, object]] = []
    app = FastAPI()
    install_http_observability(app, metrics=metrics, event_sink=events.append)

    @app.get("/items/{item_id}")
    def item(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    @app.get("/internal/metrics")
    def internal_metrics(request: Request):
        return metrics_response(request, metrics=metrics, token=metrics_token)

    return TestClient(app), metrics, events


def test_http_observability_uses_generated_correlation_and_route_templates() -> None:
    client, metrics, events = _app()
    response = client.get("/items/scope_sensitive_123?secret=query-value")
    assert response.status_code == 200
    correlation = response.headers["x-request-id"]
    assert re.fullmatch(r"[0-9a-f]{32}", correlation)

    assert len(events) == 1
    event = events[0]
    assert event["event.name"] == "http.server.request"
    assert event["reflow.request_id"] == correlation
    assert event["http.request.method"] == "GET"
    assert event["http.route"] == "/items/{item_id}"
    assert event["http.response.status_code"] == 200
    assert isinstance(event["http.server.request.duration"], float)

    rendered = metrics.render_prometheus()
    serialized = json.dumps(events, sort_keys=True) + rendered
    assert "scope_sensitive_123" not in serialized
    assert "query-value" not in serialized
    assert 'route="/items/{item_id}"' in rendered
    assert "reflow_http_server_requests_total" in rendered
    assert f'le="{HTTP_DURATION_BUCKETS_SECONDS[0]}"' in rendered


def test_unhandled_exception_is_generic_and_keeps_correlation_header() -> None:
    app = FastAPI()
    metrics = MetricsRegistry()
    events: list[dict[str, object]] = []
    install_http_observability(app, metrics=metrics, event_sink=events.append)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("sensitive exception detail")

    response = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert len(response.headers["x-request-id"]) == 32
    assert "sensitive exception detail" not in response.text
    assert events[-1]["error.type"] == "unhandled_exception"
    assert events[-1]["reflow.request_id"] == response.headers["x-request-id"]
    assert "sensitive exception detail" not in repr(events[-1])


def test_arbitrary_http_methods_collapse_to_bounded_other_label() -> None:
    client, metrics, events = _app()
    for method in ("CUSTOM-A", "CUSTOM-B", "CUSTOM-C"):
        response = client.request(method, "/items/concrete-sensitive-id")
        assert response.status_code == 405
    rendered = metrics.render_prometheus()
    assert 'method="_OTHER"' in rendered
    assert "CUSTOM-A" not in rendered
    assert "CUSTOM-B" not in rendered
    assert "CUSTOM-C" not in rendered
    assert all(event.get("http.request.method") == "_OTHER" for event in events)


def test_metrics_endpoint_is_disabled_or_bearer_gated_without_logging_token() -> None:
    disabled, _metrics, _disabled_events = _app()
    assert disabled.get("/internal/metrics").status_code == 404

    token = "m" * 48
    client, _metrics, events = _app(metrics_token=token)
    client.get("/items/example")
    assert client.get("/internal/metrics").status_code == 401
    response = client.get(
        "/internal/metrics",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert "reflow_http_server_requests_total" in response.text
    assert token not in json.dumps(events, sort_keys=True)
    assert token not in response.text


def test_metrics_token_validation_is_bounded_and_fail_closed() -> None:
    assert normalize_metrics_token(None) is None
    assert normalize_metrics_token("") is None
    good = "x" * 32
    assert normalize_metrics_token(good) == good
    for invalid in ("short", " x" * 16, "x" * 4097, "x" * 31, "x\x00" + "y" * 30):
        with pytest.raises(RuntimeError, match="REFLOW_METRICS_TOKEN is invalid"):
            normalize_metrics_token(invalid)
