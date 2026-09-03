from __future__ import annotations

import hmac
import json
import logging
import os
import sys
import threading
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from starlette.responses import Response

if TYPE_CHECKING:
    pass

OBSERVABILITY_SCHEMA_VERSION = 1
MIN_METRICS_TOKEN_BYTES = 32
MAX_METRICS_TOKEN_BYTES = 4096
HTTP_METHODS = frozenset(
    {"CONNECT", "DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT", "QUERY", "TRACE"}
)
HTTP_DURATION_BUCKETS_SECONDS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.075,
    0.1,
    0.25,
    0.5,
    0.75,
    1.0,
    2.5,
    5.0,
    7.5,
    10.0,
)

EventSink = Callable[[Mapping[str, object]], None]


def _json_logger(service_name: str) -> logging.Logger:
    logger = logging.getLogger(f"reflow.telemetry.{service_name}")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def json_event_sink(service_name: str) -> EventSink:
    if (
        not isinstance(service_name, str)
        or not service_name
        or service_name != service_name.strip()
    ):
        raise ValueError("observability service name is invalid")
    logger = _json_logger(service_name)

    def emit(fields: Mapping[str, object]) -> None:
        payload = {
            "schema_version": OBSERVABILITY_SCHEMA_VERSION,
            "service.name": service_name,
            **dict(fields),
        }
        logger.info(json.dumps(payload, sort_keys=True, separators=(",", ":")))

    return emit


def normalize_metrics_token(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if value != value.strip() or "\x00" in value:
        raise RuntimeError("REFLOW_METRICS_TOKEN is invalid")
    encoded = value.encode("utf-8")
    if not MIN_METRICS_TOKEN_BYTES <= len(encoded) <= MAX_METRICS_TOKEN_BYTES:
        raise RuntimeError("REFLOW_METRICS_TOKEN is invalid")
    return value


def metrics_token_from_env() -> str | None:
    return normalize_metrics_token(os.getenv("REFLOW_METRICS_TOKEN"))


def normalize_http_method(value: str) -> str:
    method = value.upper()
    return method if method in HTTP_METHODS else "_OTHER"


def _label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _labels(values: Mapping[str, str]) -> str:
    return ",".join(f'{key}="{_label(value)}"' for key, value in sorted(values.items()))


def _bucket_label(value: float) -> str:
    return format(value, ".12g")


class MetricsRegistry:
    """Bounded-cardinality process-local operational metrics."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_by_method: dict[str, int] = {}
        self._http_count: dict[tuple[str, str, int], int] = {}
        self._http_duration_sum: dict[tuple[str, str, int], float] = {}
        self._http_duration_buckets: dict[tuple[str, str, int], list[int]] = {}
        self._webhook_count: dict[tuple[str, str, str], int] = {}
        self._operator_count: dict[tuple[str, str], int] = {}

    def request_started(self, method: str) -> None:
        with self._lock:
            self._active_by_method[method] = self._active_by_method.get(method, 0) + 1

    def request_finished(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        key = (method, route, status_code)
        with self._lock:
            active = self._active_by_method.get(method, 0)
            self._active_by_method[method] = max(0, active - 1)
            self._http_count[key] = self._http_count.get(key, 0) + 1
            self._http_duration_sum[key] = self._http_duration_sum.get(key, 0.0) + duration_seconds
            buckets = self._http_duration_buckets.setdefault(
                key, [0 for _ in HTTP_DURATION_BUCKETS_SECONDS]
            )
            for index, boundary in enumerate(HTTP_DURATION_BUCKETS_SECONDS):
                if duration_seconds <= boundary:
                    buckets[index] += 1

    def record_webhook(
        self, *, disposition: str, processing_outcome: str, processing_code: str
    ) -> None:
        key = (disposition, processing_outcome, processing_code)
        with self._lock:
            self._webhook_count[key] = self._webhook_count.get(key, 0) + 1

    def record_operator_access(self, *, action: str, decision: str) -> None:
        key = (action, decision)
        with self._lock:
            self._operator_count[key] = self._operator_count.get(key, 0) + 1

    def render_prometheus(self) -> str:
        with self._lock:
            active = dict(self._active_by_method)
            http_count = dict(self._http_count)
            duration_sum = dict(self._http_duration_sum)
            duration_buckets = {
                key: tuple(value) for key, value in self._http_duration_buckets.items()
            }
            webhook_count = dict(self._webhook_count)
            operator_count = dict(self._operator_count)

        lines = [
            "# HELP reflow_http_server_active_requests In-flight HTTP requests by method.",
            "# TYPE reflow_http_server_active_requests gauge",
        ]
        for method, count in sorted(active.items()):
            lines.append(
                f"reflow_http_server_active_requests{{{_labels({'method': method})}}} {count}"
            )

        lines.extend(
            [
                "# HELP reflow_http_server_requests_total "
                "Completed HTTP requests by route template and status.",
                "# TYPE reflow_http_server_requests_total counter",
            ]
        )
        for (method, route, status), count in sorted(http_count.items()):
            labels = _labels({"method": method, "route": route, "status": str(status)})
            lines.append(f"reflow_http_server_requests_total{{{labels}}} {count}")

        lines.extend(
            [
                "# HELP reflow_http_server_request_duration_seconds "
                "HTTP server request duration in seconds.",
                "# TYPE reflow_http_server_request_duration_seconds histogram",
            ]
        )
        for key in sorted(http_count):
            method, route, status = key
            base = {"method": method, "route": route, "status": str(status)}
            for boundary, count in zip(
                HTTP_DURATION_BUCKETS_SECONDS, duration_buckets[key], strict=True
            ):
                labels = _labels({**base, "le": _bucket_label(boundary)})
                lines.append(
                    f"reflow_http_server_request_duration_seconds_bucket{{{labels}}} {count}"
                )
            labels = _labels({**base, "le": "+Inf"})
            lines.append(
                f"reflow_http_server_request_duration_seconds_bucket{{{labels}}} {http_count[key]}"
            )
            labels = _labels(base)
            lines.append(
                "reflow_http_server_request_duration_seconds_sum"
                f"{{{labels}}} {duration_sum[key]:.12g}"
            )
            lines.append(
                f"reflow_http_server_request_duration_seconds_count{{{labels}}} {http_count[key]}"
            )

        lines.extend(
            [
                "# HELP reflow_webhook_receipts_total "
                "Authenticated webhook receipt processing outcomes.",
                "# TYPE reflow_webhook_receipts_total counter",
            ]
        )
        for (disposition, outcome, code), count in sorted(webhook_count.items()):
            labels = _labels(
                {"disposition": disposition, "outcome": outcome, "processing_code": code}
            )
            lines.append(f"reflow_webhook_receipts_total{{{labels}}} {count}")

        lines.extend(
            [
                "# HELP reflow_operator_access_decisions_total "
                "Durable authenticated operator authorization decisions.",
                "# TYPE reflow_operator_access_decisions_total counter",
            ]
        )
        for (action, decision), count in sorted(operator_count.items()):
            labels = _labels({"action": action, "decision": decision})
            lines.append(f"reflow_operator_access_decisions_total{{{labels}}} {count}")
        return "\n".join(lines) + "\n"


def request_id(request: Request) -> str:
    value = getattr(request.state, "reflow_request_id", None)
    if not isinstance(value, str) or len(value) != 32:
        raise RuntimeError("request observability context is unavailable")
    return value


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path:
        return path
    return "unmatched"


def install_http_observability(
    app: FastAPI,
    *,
    metrics: MetricsRegistry,
    event_sink: EventSink,
) -> None:
    @app.middleware("http")
    async def observe(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        correlation_id = uuid.uuid4().hex
        request.state.reflow_request_id = correlation_id
        method = normalize_http_method(request.method)
        metrics.request_started(method)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration = time.perf_counter() - started
            route = _route_template(request)
            metrics.request_finished(
                method=method,
                route=route,
                status_code=500,
                duration_seconds=duration,
            )
            event_sink(
                {
                    "event.name": "http.server.request",
                    "reflow.request_id": correlation_id,
                    "http.request.method": method,
                    "http.route": route,
                    "http.response.status_code": 500,
                    "http.server.request.duration": duration,
                    "error.type": "unhandled_exception",
                }
            )
            response = PlainTextResponse("Internal Server Error", status_code=500)
            response.headers["X-Request-ID"] = correlation_id
            return response
        duration = time.perf_counter() - started
        route = _route_template(request)
        metrics.request_finished(
            method=method,
            route=route,
            status_code=response.status_code,
            duration_seconds=duration,
        )
        response.headers["X-Request-ID"] = correlation_id
        event_sink(
            {
                "event.name": "http.server.request",
                "reflow.request_id": correlation_id,
                "http.request.method": method,
                "http.route": route,
                "http.response.status_code": response.status_code,
                "http.server.request.duration": duration,
            }
        )
        return response


def metrics_response(
    request: Request,
    *,
    metrics: MetricsRegistry,
    token: str | None,
) -> PlainTextResponse:
    if token is None:
        raise HTTPException(status_code=404, detail="Not Found")
    authorization = request.headers.get("authorization")
    expected = f"Bearer {token}"
    if authorization is None or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="metrics authentication required")
    return PlainTextResponse(
        metrics.render_prometheus(),
        media_type="text/plain; version=0.0.4",
    )
