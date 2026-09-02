from __future__ import annotations

import io
import urllib.error
import urllib.request
from email.message import Message

import pytest

from reflow.openai_transport_security import (
    MAX_OPENAI_RESPONSE_BYTES,
    RejectRedirectHandler,
    read_bounded_openai_response,
    validate_openai_https_endpoint,
)


def test_openai_endpoint_requires_https_without_credentials_or_fragment() -> None:
    assert validate_openai_https_endpoint("https://api.openai.com/v1/responses") == (
        "https://api.openai.com/v1/responses"
    )
    for value in (
        "http://api.openai.com/v1/responses",
        "file:///tmp/responses",
        "https://user:secret@api.openai.com/v1/responses",
        "https://api.openai.com/v1/responses#fragment",
        "not-a-url",
    ):
        with pytest.raises(ValueError):
            validate_openai_https_endpoint(value)


def test_redirect_handler_fails_closed_before_creating_forward_request() -> None:
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": "Bearer test-secret"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError, match="redirects are not permitted"):
        RejectRedirectHandler().redirect_request(
            request,
            fp=io.BytesIO(),
            code=302,
            msg="Found",
            headers=Message(),
            newurl="https://attacker.invalid/capture",
        )

class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def read(self, size: int = -1) -> bytes:
        return self.body if size < 0 else self.body[:size]


def test_openai_response_reader_rejects_body_over_one_mibibyte() -> None:
    exact = b"x" * MAX_OPENAI_RESPONSE_BYTES
    assert read_bounded_openai_response(_FakeResponse(exact)) == exact
    oversized = b"x" * (MAX_OPENAI_RESPONSE_BYTES + 1)
    with pytest.raises(ValueError, match="byte limit"):
        read_bounded_openai_response(_FakeResponse(oversized))

