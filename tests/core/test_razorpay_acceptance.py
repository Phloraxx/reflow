from __future__ import annotations

import urllib.error
import urllib.request
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import pytest

from reflow.razorpay_acceptance import (
    RazorpayAcceptanceClient,
    RazorpayAcceptanceError,
    _default_transport,
    _RejectRedirectHandler,
    run_real_data_acceptance,
)
from reflow.razorpay_integration import RazorpayEvidenceOrigin

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def _settlement(settlement_id: str = "setl_accept_1") -> dict[str, object]:
    return {
        "id": settlement_id,
        "entity": "settlement",
        "amount": 97100,
        "status": "processed",
        "fees": 2900,
        "tax": 0,
        "utr": "UTR-ACCEPT-1",
        "created_at": 1788436800,
    }


def _recon(settlement_id: str = "setl_accept_1") -> dict[str, object]:
    return {
        "entity_id": "pay_accept_1",
        "type": "payment",
        "settlement_id": settlement_id,
        "debit": 0,
        "credit": 97100,
        "amount": 100000,
        "fee": 2900,
        "tax": 0,
        "settled": True,
        "currency": "INR",
        "settled_at": 1788436800,
        "created_at": 1788433200,
        "settlement_utr": "UTR-ACCEPT-1",
    }


def _client(transport):
    return RazorpayAcceptanceClient(
        key_id="rzp_test_key",
        key_secret="secret-value",
        account_id="acc_private_merchant",
        evidence_origin=RazorpayEvidenceOrigin.REAL_TEST_MODE,
        transport=transport,
    )


def test_settlement_fetch_paginates_with_documented_page_size() -> None:
    seen: list[str] = []

    def transport(url: str, _headers, _timeout: float, _max_bytes: int):
        seen.append(url)
        query = parse_qs(urlsplit(url).query)
        skip = int(query["skip"][0])
        if skip == 0:
            items = [_settlement(f"setl_page_{index}") for index in range(100)]
        else:
            items = [_settlement("setl_page_last")]
        return {"entity": "collection", "count": len(items), "items": items}

    rows = _client(transport).fetch_settlements()
    assert len(rows) == 101
    assert parse_qs(urlsplit(seen[0]).query) == {"count": ["100"], "skip": ["0"]}
    assert parse_qs(urlsplit(seen[1]).query) == {"count": ["100"], "skip": ["100"]}


def test_recon_fetch_uses_1000_row_pages() -> None:
    seen: list[str] = []

    def transport(url: str, _headers, _timeout: float, _max_bytes: int):
        seen.append(url)
        query = parse_qs(urlsplit(url).query)
        skip = int(query["skip"][0])
        items = [_recon(f"setl_recon_{index}") for index in range(1000)] if skip == 0 else []
        return {"entity": "collection", "count": len(items), "items": items}

    rows = _client(transport).fetch_recon(year=2026, month=9)
    assert len(rows) == 1000
    first = parse_qs(urlsplit(seen[0]).query)
    second = parse_qs(urlsplit(seen[1]).query)
    assert first["count"] == ["1000"] and first["skip"] == ["0"]
    assert second["count"] == ["1000"] and second["skip"] == ["1000"]


def test_collection_shape_and_real_origin_fail_closed() -> None:
    def malformed(_url: str, _headers, _timeout: float, _max_bytes: int):
        return {"entity": "collection", "count": 1, "items": "not-an-array"}

    with pytest.raises(RazorpayAcceptanceError, match="items"):
        _client(malformed).fetch_settlements()

    with pytest.raises(RazorpayAcceptanceError, match="real evidence origin"):
        RazorpayAcceptanceClient(
            key_id="key",
            key_secret="secret",
            account_id="acc_merchant",
            evidence_origin=RazorpayEvidenceOrigin.PROVIDER_DOC_FIXTURE,
            transport=malformed,
        )


def test_real_acceptance_refuses_empty_corpus() -> None:
    def empty(_url: str, _headers, _timeout: float, _max_bytes: int):
        return {"entity": "collection", "count": 0, "items": []}

    with pytest.raises(RazorpayAcceptanceError, match="non-empty settlement"):
        run_real_data_acceptance(
            _client(empty),
            year=2026,
            month=9,
            received_at=NOW,
        )


def test_real_acceptance_report_contains_no_raw_private_payload() -> None:
    def transport(url: str, headers, _timeout: float, _max_bytes: int):
        assert headers["Authorization"].startswith("Basic ")
        if "/recon/combined" in url:
            return {"entity": "collection", "count": 1, "items": [_recon()]}
        return {"entity": "collection", "count": 1, "items": [_settlement()]}

    report = run_real_data_acceptance(
        _client(transport),
        year=2026,
        month=9,
        received_at=NOW,
    )
    rendered = report.to_json()
    assert report.settlement_count == 1
    assert report.recon_count == 1
    assert report.settlements_with_recon == 1
    assert report.source_envelope_count == 2
    assert "acc_private_merchant" not in rendered
    assert "secret-value" not in rendered
    assert "Authorization" not in rendered
    assert "UTR-ACCEPT-1" not in rendered
    assert "pay_accept_1" not in rendered
    assert "setl_accept_1" not in rendered
    assert report.evidence_origin == "real_test_mode"


def test_default_transport_refuses_other_origins_and_redirects() -> None:
    with pytest.raises(RazorpayAcceptanceError, match="fixed API origin"):
        _default_transport("https://example.invalid/v1/settlements", {}, 1.0, 1024)

    handler = _RejectRedirectHandler()
    request = urllib.request.Request("https://api.razorpay.com/v1/settlements/")
    with pytest.raises(urllib.error.HTTPError, match="redirects are not permitted"):
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://example.invalid/steal",
        )


def test_acceptance_client_rejects_invalid_resource_bounds() -> None:
    def transport(_url: str, _headers, _timeout: float, _max_bytes: int):
        return {"entity": "collection", "count": 0, "items": []}

    with pytest.raises(RazorpayAcceptanceError, match="timeout"):
        RazorpayAcceptanceClient(
            key_id="rzp_test_key",
            key_secret="secret",
            account_id="acc_merchant",
            evidence_origin=RazorpayEvidenceOrigin.REAL_TEST_MODE,
            timeout_seconds=True,
            transport=transport,
        )
    with pytest.raises(RazorpayAcceptanceError, match="timeout"):
        RazorpayAcceptanceClient(
            key_id="rzp_test_key",
            key_secret="secret",
            account_id="acc_merchant",
            evidence_origin=RazorpayEvidenceOrigin.REAL_TEST_MODE,
            timeout_seconds=301.0,
            transport=transport,
        )


def test_explicit_has_more_advances_even_for_short_page() -> None:
    seen: list[int] = []

    def transport(url: str, _headers, _timeout: float, _max_bytes: int):
        skip = int(parse_qs(urlsplit(url).query)["skip"][0])
        seen.append(skip)
        if skip == 0:
            return {
                "entity": "collection",
                "count": 1,
                "items": [_settlement()],
                "has_more": True,
            }
        return {"entity": "collection", "count": 0, "items": [], "has_more": False}

    assert len(_client(transport).fetch_settlements()) == 1
    assert seen == [0, 1]


def test_acceptance_origin_must_match_api_key_mode() -> None:
    def transport(_url: str, _headers, _timeout: float, _max_bytes: int):
        return {"entity": "collection", "count": 0, "items": []}

    with pytest.raises(RazorpayAcceptanceError, match="prefix"):
        RazorpayAcceptanceClient(
            key_id="rzp_live_wrong_mode",
            key_secret="secret",
            account_id="acc_merchant",
            evidence_origin=RazorpayEvidenceOrigin.REAL_TEST_MODE,
            transport=transport,
        )
    with pytest.raises(RazorpayAcceptanceError, match="prefix"):
        RazorpayAcceptanceClient(
            key_id="rzp_test_wrong_mode",
            key_secret="secret",
            account_id="acc_merchant",
            evidence_origin=RazorpayEvidenceOrigin.REAL_LIVE,
            transport=transport,
        )
