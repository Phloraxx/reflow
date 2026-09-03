from __future__ import annotations

import math
import urllib.error
import urllib.request
from typing import IO, Any
from urllib.parse import urlsplit

MAX_OPENAI_RESPONSE_BYTES = 1_048_576
MAX_OPENAI_TIMEOUT_SECONDS = 300.0


def validate_openai_timeout_seconds(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("OpenAI timeout must be a finite positive number")
    rendered = float(value)
    if not math.isfinite(rendered) or rendered <= 0 or rendered > MAX_OPENAI_TIMEOUT_SECONDS:
        raise ValueError(
            "OpenAI timeout must be finite and between 0 and "
            f"{MAX_OPENAI_TIMEOUT_SECONDS:g} seconds"
        )
    return rendered


def validate_openai_https_endpoint(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("OpenAI base URL must be a non-empty trimmed HTTPS URL")
    parsed = urlsplit(value)
    if parsed.scheme.casefold() != "https" or not parsed.hostname:
        raise ValueError("OpenAI base URL must be an absolute HTTPS URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("OpenAI base URL cannot contain embedded credentials")
    if parsed.fragment:
        raise ValueError("OpenAI base URL cannot contain a fragment")
    return value


class RejectRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Fail closed instead of forwarding bearer credentials across redirects."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        del newurl
        raise urllib.error.HTTPError(
            req.full_url,
            code,
            f"OpenAI endpoint redirects are not permitted: {msg}",
            headers,  # type: ignore[arg-type]
            fp,
        )


def open_no_redirect(request: urllib.request.Request, *, timeout_seconds: float) -> Any:
    validate_openai_https_endpoint(request.full_url)
    timeout_seconds = validate_openai_timeout_seconds(timeout_seconds)
    opener = urllib.request.build_opener(RejectRedirectHandler())
    return opener.open(request, timeout=timeout_seconds)  # nosec B310


def read_bounded_openai_response(
    response: Any, *, max_bytes: int = MAX_OPENAI_RESPONSE_BYTES
) -> bytes:
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError("OpenAI response byte limit must be a positive integer")
    body = response.read(max_bytes + 1)
    if not isinstance(body, bytes):
        raise TypeError("OpenAI response body must be bytes")
    if len(body) > max_bytes:
        raise ValueError("OpenAI response exceeded the configured byte limit")
    return body
