from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .journal import InMemoryJournal
from .razorpay_integration import (
    RazorpayAccountContext,
    RazorpayEvidenceOrigin,
    compile_recon_items,
    compile_settlement_api_entity,
)

RAZORPAY_API_ROOT = "https://api.razorpay.com/v1"
SETTLEMENT_PAGE_SIZE = 100
RECON_PAGE_SIZE = 1000
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_TIMEOUT_SECONDS = 300.0
DEFAULT_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 64 * 1024 * 1024

JsonTransport = Callable[[str, Mapping[str, str], float, int], Mapping[str, object]]


class RazorpayAcceptanceError(ValueError):
    """Real-data acquisition or acceptance evidence is unsafe or invalid."""


class _RejectRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        del newurl
        raise urllib.error.HTTPError(
            req.full_url,
            code,
            f"Razorpay API redirects are not permitted: {msg}",
            headers,
            fp,
        )


def _default_transport(
    url: str,
    headers: Mapping[str, str],
    timeout_seconds: float,
    max_bytes: int,
) -> Mapping[str, object]:
    if not url.startswith(f"{RAZORPAY_API_ROOT}/"):
        raise RazorpayAcceptanceError("Razorpay acceptance transport requires fixed API origin")
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        opener = urllib.request.build_opener(_RejectRedirectHandler())
        with opener.open(request, timeout=timeout_seconds) as response:  # nosec B310
            body = response.read(max_bytes + 1)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RazorpayAcceptanceError(
            f"Razorpay API request failed: {type(exc).__name__}"
        ) from exc
    if not isinstance(body, bytes):
        raise RazorpayAcceptanceError("Razorpay API response body must be bytes")
    if len(body) > max_bytes:
        raise RazorpayAcceptanceError("Razorpay API response exceeded byte limit")
    try:
        decoded: object = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RazorpayAcceptanceError("Razorpay API response is not valid JSON") from exc
    if not isinstance(decoded, Mapping):
        raise RazorpayAcceptanceError("Razorpay API response root must be an object")
    if not all(isinstance(key, str) for key in decoded):
        raise RazorpayAcceptanceError("Razorpay API response keys must be strings")
    return dict(decoded)


def _digest_strings(values: Sequence[str]) -> str:
    rendered = json.dumps(sorted(values), separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(rendered).hexdigest()


@dataclass(frozen=True, slots=True)
class RazorpayAcceptanceClient:
    key_id: str
    key_secret: str
    account_id: str
    evidence_origin: RazorpayEvidenceOrigin
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    max_pages: int = 100
    max_records: int = 100_000
    transport: JsonTransport = _default_transport

    def __post_init__(self) -> None:
        if not self.key_id or self.key_id != self.key_id.strip():
            raise RazorpayAcceptanceError("Razorpay key id must be non-empty and trimmed")
        if not self.key_secret or not self.key_secret.strip():
            raise RazorpayAcceptanceError("Razorpay key secret must be non-empty")
        if not self.account_id or self.account_id != self.account_id.strip():
            raise RazorpayAcceptanceError("Razorpay account id must be non-empty and trimmed")
        if (
            not isinstance(self.evidence_origin, RazorpayEvidenceOrigin)
            or self.evidence_origin not in {
                RazorpayEvidenceOrigin.REAL_TEST_MODE,
                RazorpayEvidenceOrigin.REAL_LIVE,
            }
        ):
            raise RazorpayAcceptanceError("acceptance client requires a real evidence origin")
        expected_prefix = (
            "rzp_test_"
            if self.evidence_origin is RazorpayEvidenceOrigin.REAL_TEST_MODE
            else "rzp_live_"
        )
        if not self.key_id.startswith(expected_prefix):
            raise RazorpayAcceptanceError(
                "Razorpay key id prefix does not match configured evidence origin"
            )
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
            or self.timeout_seconds > MAX_TIMEOUT_SECONDS
        ):
            raise RazorpayAcceptanceError("Razorpay timeout must be finite and positive")
        if (
            isinstance(self.max_response_bytes, bool)
            or not isinstance(self.max_response_bytes, int)
            or self.max_response_bytes < 1
            or self.max_response_bytes > MAX_RESPONSE_BYTES
        ):
            raise RazorpayAcceptanceError("Razorpay response byte limit must be positive")
        if (
            isinstance(self.max_pages, bool)
            or not isinstance(self.max_pages, int)
            or not 1 <= self.max_pages <= 1_000
        ):
            raise RazorpayAcceptanceError("Razorpay page limit is invalid")
        if (
            isinstance(self.max_records, bool)
            or not isinstance(self.max_records, int)
            or not 1 <= self.max_records <= 1_000_000
        ):
            raise RazorpayAcceptanceError("Razorpay record limit is invalid")
        if not callable(self.transport):
            raise RazorpayAcceptanceError("Razorpay transport must be callable")

    def _headers(self) -> dict[str, str]:
        token = base64.b64encode(f"{self.key_id}:{self.key_secret}".encode()).decode("ascii")
        return {"Authorization": f"Basic {token}", "Accept": "application/json"}

    def _fetch_collection(
        self,
        *,
        path: str,
        params: Mapping[str, int],
        page_size: int,
    ) -> tuple[Mapping[str, object], ...]:
        rows: list[Mapping[str, object]] = []
        skip = 0
        for _page in range(self.max_pages):
            query = dict(params)
            query.update({"count": page_size, "skip": skip})
            url = f"{RAZORPAY_API_ROOT}{path}?{urlencode(query)}"
            payload = self.transport(
                url,
                self._headers(),
                self.timeout_seconds,
                self.max_response_bytes,
            )
            if payload.get("entity") != "collection":
                raise RazorpayAcceptanceError("Razorpay collection entity is invalid")
            items = payload.get("items")
            if not isinstance(items, list):
                raise RazorpayAcceptanceError("Razorpay collection items must be an array")
            count = payload.get("count")
            if isinstance(count, bool) or not isinstance(count, int) or count != len(items):
                raise RazorpayAcceptanceError("Razorpay collection count does not match items")
            normalized: list[Mapping[str, object]] = []
            for item in items:
                if not isinstance(item, Mapping) or not all(
                    isinstance(key, str) for key in item
                ):
                    raise RazorpayAcceptanceError("Razorpay collection item must be an object")
                normalized.append(dict(item))
            if len(rows) + len(normalized) > self.max_records:
                raise RazorpayAcceptanceError("Razorpay acceptance record limit exceeded")
            rows.extend(normalized)
            has_more = payload.get("has_more")
            if has_more is not None and not isinstance(has_more, bool):
                raise RazorpayAcceptanceError("Razorpay collection has_more must be boolean")
            if has_more is False:
                return tuple(rows)
            if has_more is True:
                if not normalized:
                    raise RazorpayAcceptanceError("Razorpay pagination did not advance")
                skip += len(normalized)
                continue
            if len(normalized) < page_size:
                return tuple(rows)
            if not normalized:
                raise RazorpayAcceptanceError("Razorpay pagination did not advance")
            skip += len(normalized)
        raise RazorpayAcceptanceError("Razorpay acceptance page limit exceeded")

    def fetch_settlements(
        self,
        *,
        from_timestamp: int | None = None,
        to_timestamp: int | None = None,
    ) -> tuple[Mapping[str, object], ...]:
        params: dict[str, int] = {}
        if from_timestamp is not None:
            if isinstance(from_timestamp, bool) or from_timestamp < 0:
                raise RazorpayAcceptanceError("settlement from timestamp is invalid")
            params["from"] = from_timestamp
        if to_timestamp is not None:
            if isinstance(to_timestamp, bool) or to_timestamp < 0:
                raise RazorpayAcceptanceError("settlement to timestamp is invalid")
            params["to"] = to_timestamp
        if (
            from_timestamp is not None
            and to_timestamp is not None
            and from_timestamp > to_timestamp
        ):
            raise RazorpayAcceptanceError("settlement time range is inverted")
        return self._fetch_collection(
            path="/settlements/",
            params=params,
            page_size=SETTLEMENT_PAGE_SIZE,
        )

    def fetch_recon(
        self,
        *,
        year: int,
        month: int,
        day: int | None = None,
    ) -> tuple[Mapping[str, object], ...]:
        if isinstance(year, bool) or not 1970 <= year <= 9999:
            raise RazorpayAcceptanceError("recon year is invalid")
        if isinstance(month, bool) or not 1 <= month <= 12:
            raise RazorpayAcceptanceError("recon month is invalid")
        params = {"year": year, "month": month}
        if day is not None:
            if isinstance(day, bool) or not 1 <= day <= 31:
                raise RazorpayAcceptanceError("recon day is invalid")
            params["day"] = day
        return self._fetch_collection(
            path="/settlements/recon/combined",
            params=params,
            page_size=RECON_PAGE_SIZE,
        )


@dataclass(frozen=True, slots=True)
class RazorpayAcceptanceReport:
    schema_version: str
    evidence_origin: str
    generated_at: str
    year: int
    month: int
    day: int | None
    settlement_count: int
    recon_count: int
    compiled_settlement_count: int
    compiled_recon_count: int
    source_envelope_count: int
    settlements_with_recon: int
    settlements_without_recon: int
    recon_rows_without_fetched_settlement: int
    account_id_sha256: str
    settlement_id_set_sha256: str
    recon_identity_set_sha256: str

    def to_json(self) -> str:
        return json.dumps(
            asdict(self),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )


def _aware(value: datetime, label: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{label} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise RazorpayAcceptanceError(f"{label} must be timezone-aware")


def run_real_data_acceptance(
    client: RazorpayAcceptanceClient,
    *,
    year: int,
    month: int,
    day: int | None = None,
    received_at: datetime | None = None,
) -> RazorpayAcceptanceReport:
    if not isinstance(client, RazorpayAcceptanceClient):
        raise TypeError("client must be RazorpayAcceptanceClient")
    observed_at = received_at or datetime.now(tz=UTC)
    _aware(observed_at, "acceptance received_at")

    settlements = client.fetch_settlements()
    if not settlements:
        raise RazorpayAcceptanceError("real acceptance requires a non-empty settlement corpus")
    recon = client.fetch_recon(year=year, month=month, day=day)
    if not recon:
        raise RazorpayAcceptanceError("real acceptance requires a non-empty recon corpus")

    journal = InMemoryJournal()
    context = RazorpayAccountContext(
        account_id=client.account_id,
        evidence_origin=client.evidence_origin,
    )
    settlement_ids: list[str] = []
    for entity in settlements:
        batch = compile_settlement_api_entity(
            entity=entity,
            context=context,
            journal=journal,
            received_at=observed_at,
        )
        settlement_ids.extend(str(item.id) for item in batch.settlements)

    recon_batch = compile_recon_items(
        items=recon,
        context=context,
        journal=journal,
        received_at=observed_at,
    )
    recon_ids = [str(item.id) for item in recon_batch.recon_entries]
    recon_settlement_ids = [str(item.settlement_id) for item in recon_batch.recon_entries]
    settlement_id_set = set(settlement_ids)
    recon_settlement_id_set = set(recon_settlement_ids)

    return RazorpayAcceptanceReport(
        schema_version="razorpay-real-acceptance-v1",
        evidence_origin=client.evidence_origin.value,
        generated_at=observed_at.isoformat(),
        year=year,
        month=month,
        day=day,
        settlement_count=len(settlements),
        recon_count=len(recon),
        compiled_settlement_count=len(settlement_ids),
        compiled_recon_count=len(recon_batch.recon_entries),
        source_envelope_count=len(journal),
        settlements_with_recon=len(settlement_id_set & recon_settlement_id_set),
        settlements_without_recon=len(settlement_id_set - recon_settlement_id_set),
        recon_rows_without_fetched_settlement=sum(
            settlement_id not in settlement_id_set for settlement_id in recon_settlement_ids
        ),
        account_id_sha256=hashlib.sha256(client.account_id.encode()).hexdigest(),
        settlement_id_set_sha256=_digest_strings(tuple(settlement_id_set)),
        recon_identity_set_sha256=_digest_strings(tuple(recon_ids)),
    )


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise RazorpayAcceptanceError(f"required environment variable {name} is missing")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run privacy-preserving acceptance against real Razorpay settlement/recon data"
    )
    parser.add_argument("--mode", choices=("test", "live"), required=True)
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--month", type=int, required=True)
    parser.add_argument("--day", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.mode == "live" and not args.allow_live:
        parser.error("live mode requires explicit --allow-live")
    origin = (
        RazorpayEvidenceOrigin.REAL_TEST_MODE
        if args.mode == "test"
        else RazorpayEvidenceOrigin.REAL_LIVE
    )

    client = RazorpayAcceptanceClient(
        key_id=_required_env("RAZORPAY_KEY_ID"),
        key_secret=_required_env("RAZORPAY_KEY_SECRET"),
        account_id=_required_env("REFLOW_RAZORPAY_ACCOUNT_ID"),
        evidence_origin=origin,
    )
    report = run_real_data_acceptance(
        client,
        year=args.year,
        month=args.month,
        day=args.day,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report.to_json() + "\n")
    print(
        json.dumps(
            {
                "status": "accepted",
                "evidence_origin": report.evidence_origin,
                "settlement_count": report.settlement_count,
                "recon_count": report.recon_count,
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
