from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, cast

from .journal import Journal, JournalConflictError
from .razorpay_integration import (
    RazorpayAccountContext,
    RazorpayEvidenceOrigin,
    RazorpayIntegrationError,
    compile_payment_webhook,
    compile_settlement_webhook,
)

WEBHOOK_SCHEMA_VERSION = 1
MAX_WEBHOOK_BODY_BYTES = 1024 * 1024
MAX_EVENT_ID_BYTES = 512
MAX_SIGNATURE_BYTES = 512
MAX_OUTCOME_CODE_BYTES = 96
MAX_RECEIPT_LIST_LIMIT = 100


class WebhookIngressError(RuntimeError):
    """Webhook delivery could not satisfy the ingress contract."""


class WebhookAuthenticationError(WebhookIngressError):
    """Provider signature or transport identity could not be established."""


class WebhookReceiptConflictError(WebhookIngressError):
    """One provider event identity was reused for different raw content."""


class WebhookPersistenceError(WebhookIngressError):
    """Durable webhook receipt state is unavailable or inconsistent."""


class WebhookSecretGeneration(StrEnum):
    CURRENT = "current"
    PREVIOUS = "previous"


class WebhookReceiptDisposition(StrEnum):
    STORED = "stored"
    DUPLICATE = "duplicate"


class WebhookProcessingOutcome(StrEnum):
    PROCESSED = "processed"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class WebhookSecrets:
    current: str
    previous: str | None = None

    def __post_init__(self) -> None:
        _secret(self.current, "current webhook secret")
        if self.previous is not None:
            _secret(self.previous, "previous webhook secret")
            if hmac.compare_digest(self.current, self.previous):
                raise WebhookIngressError("current and previous webhook secrets must differ")

    def value_for(self, generation: WebhookSecretGeneration) -> str:
        if generation is WebhookSecretGeneration.CURRENT:
            return self.current
        if self.previous is None:
            raise WebhookAuthenticationError("previous webhook secret is unavailable")
        return self.previous


@dataclass(frozen=True, slots=True)
class WebhookReceipt:
    provider: str
    account_id: str
    event_id: str
    body_sha256: str
    raw_body: bytes
    signature: str
    first_received_at: datetime
    secret_generation: WebhookSecretGeneration


@dataclass(frozen=True, slots=True)
class WebhookAttempt:
    attempt_id: int
    event_id: str
    attempted_at: datetime
    outcome: WebhookProcessingOutcome
    outcome_code: str


@dataclass(frozen=True, slots=True)
class WebhookReceiptSummary:
    event_id: str
    first_received_at: datetime
    body_sha256: str
    secret_generation: WebhookSecretGeneration
    latest_outcome: WebhookProcessingOutcome | None
    latest_outcome_code: str | None
    attempt_count: int


@dataclass(frozen=True, slots=True)
class WebhookReceiptResult:
    disposition: WebhookReceiptDisposition
    receipt: WebhookReceipt


@dataclass(frozen=True, slots=True)
class WebhookIngressResult:
    disposition: WebhookReceiptDisposition
    outcome: WebhookProcessingOutcome
    outcome_code: str


class WebhookReceiptStore(Protocol):
    def append_receipt(self, receipt: WebhookReceipt) -> WebhookReceiptResult: ...

    def get_receipt(self, account_id: str, event_id: str) -> WebhookReceipt | None: ...

    def attempts(self, account_id: str, event_id: str) -> tuple[WebhookAttempt, ...]: ...

    def record_attempt(
        self,
        *,
        account_id: str,
        event_id: str,
        attempted_at: datetime,
        outcome: WebhookProcessingOutcome,
        outcome_code: str,
    ) -> WebhookAttempt: ...

    def list_receipts(
        self, account_id: str, *, limit: int
    ) -> tuple[WebhookReceiptSummary, ...]: ...


def _text(value: object, label: str, *, max_bytes: int = 512) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise WebhookIngressError(f"{label} must be a non-empty trimmed string")
    if len(value.encode("utf-8")) > max_bytes or "\x00" in value:
        raise WebhookIngressError(f"{label} is invalid")
    return value


def _secret(value: object, label: str) -> str:
    return _text(value, label, max_bytes=4096)


def _aware(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise WebhookIngressError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _header(headers: Mapping[str, str], name: str) -> str | None:
    target = name.casefold()
    for key, value in headers.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise WebhookAuthenticationError("webhook headers must map strings to strings")
        if key.casefold() == target:
            return value.strip() or None
    return None


def verify_razorpay_webhook(
    *,
    raw_body: bytes,
    headers: Mapping[str, str],
    secrets: WebhookSecrets,
) -> tuple[str, str, WebhookSecretGeneration]:
    if not isinstance(raw_body, bytes):
        raise TypeError("raw webhook body must be bytes")
    if len(raw_body) > MAX_WEBHOOK_BODY_BYTES:
        raise WebhookAuthenticationError("webhook body is too large")
    event_id = _header(headers, "x-razorpay-event-id")
    signature = _header(headers, "x-razorpay-signature")
    if event_id is None:
        raise WebhookAuthenticationError("missing Razorpay webhook event id")
    if signature is None:
        raise WebhookAuthenticationError("missing Razorpay webhook signature")
    try:
        event_id = _text(event_id, "Razorpay webhook event id", max_bytes=MAX_EVENT_ID_BYTES)
        signature = _text(signature, "Razorpay webhook signature", max_bytes=MAX_SIGNATURE_BYTES)
    except WebhookIngressError as exc:
        raise WebhookAuthenticationError(str(exc)) from exc
    candidates = (
        (WebhookSecretGeneration.CURRENT, secrets.current),
        (WebhookSecretGeneration.PREVIOUS, secrets.previous),
    )
    for generation, secret in candidates:
        if secret is None:
            continue
        expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        if hmac.compare_digest(signature, expected):
            return event_id, signature, generation
    raise WebhookAuthenticationError("Razorpay webhook signature verification failed")


def _event_name(raw_body: bytes) -> str:
    try:
        value = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RazorpayIntegrationError("signed webhook body is not valid JSON") from exc
    if not isinstance(value, Mapping):
        raise RazorpayIntegrationError("Razorpay webhook body must be a JSON object")
    event = value.get("event")
    if not isinstance(event, str) or not event or event != event.strip():
        raise RazorpayIntegrationError("webhook event must be a non-empty string")
    return event


def _receipt(
    *,
    raw_body: bytes,
    event_id: str,
    signature: str,
    generation: WebhookSecretGeneration,
    context: RazorpayAccountContext,
    received_at: datetime,
) -> WebhookReceipt:
    return WebhookReceipt(
        provider="razorpay",
        account_id=context.account_id,
        event_id=event_id,
        body_sha256=hashlib.sha256(raw_body).hexdigest(),
        raw_body=raw_body,
        signature=signature,
        first_received_at=_aware(received_at, "received_at"),
        secret_generation=generation,
    )


class RazorpayWebhookIngress:
    def __init__(
        self,
        *,
        receipt_store: WebhookReceiptStore,
        journal: Journal,
        context: RazorpayAccountContext,
        secrets: WebhookSecrets,
    ) -> None:
        self.receipt_store = receipt_store
        self.journal = journal
        self.context = context
        self.secrets = secrets

    def _secret_for_receipt(self, receipt: WebhookReceipt) -> str:
        headers = {
            "x-razorpay-event-id": receipt.event_id,
            "x-razorpay-signature": receipt.signature,
        }
        _event_id, _signature, generation = verify_razorpay_webhook(
            raw_body=receipt.raw_body,
            headers=headers,
            secrets=self.secrets,
        )
        return self.secrets.value_for(generation)

    def _process(self, receipt: WebhookReceipt, *, attempted_at: datetime) -> WebhookAttempt:
        outcome = WebhookProcessingOutcome.PROCESSED
        code = "canonicalized"
        try:
            secret = self._secret_for_receipt(receipt)
            headers = {
                "x-razorpay-event-id": receipt.event_id,
                "x-razorpay-signature": receipt.signature,
            }
            event_name = _event_name(receipt.raw_body)
            if event_name.startswith("payment."):
                compile_payment_webhook(
                    raw_body=receipt.raw_body,
                    headers=headers,
                    webhook_secret=secret,
                    context=self.context,
                    journal=self.journal,
                    received_at=receipt.first_received_at,
                )
            elif event_name.startswith("settlement."):
                compile_settlement_webhook(
                    raw_body=receipt.raw_body,
                    headers=headers,
                    webhook_secret=secret,
                    context=self.context,
                    journal=self.journal,
                    received_at=receipt.first_received_at,
                )
            else:
                raise RazorpayIntegrationError("unsupported Razorpay webhook event family")
        except WebhookAuthenticationError:
            outcome = WebhookProcessingOutcome.REJECTED
            code = "verification_key_unavailable"
        except JournalConflictError:
            outcome = WebhookProcessingOutcome.REJECTED
            code = "journal_conflict"
        except RazorpayIntegrationError:
            outcome = WebhookProcessingOutcome.REJECTED
            code = "provider_payload_rejected"
        except Exception:
            outcome = WebhookProcessingOutcome.REJECTED
            code = "internal_processing_error"
        return self.receipt_store.record_attempt(
            account_id=self.context.account_id,
            event_id=receipt.event_id,
            attempted_at=_aware(attempted_at, "attempted_at"),
            outcome=outcome,
            outcome_code=code,
        )

    def receive(
        self,
        *,
        raw_body: bytes,
        headers: Mapping[str, str],
        received_at: datetime,
    ) -> WebhookIngressResult:
        event_id, signature, generation = verify_razorpay_webhook(
            raw_body=raw_body,
            headers=headers,
            secrets=self.secrets,
        )
        result = self.receipt_store.append_receipt(
            _receipt(
                raw_body=raw_body,
                event_id=event_id,
                signature=signature,
                generation=generation,
                context=self.context,
                received_at=received_at,
            )
        )
        attempts = self.receipt_store.attempts(self.context.account_id, event_id)
        if result.disposition is WebhookReceiptDisposition.DUPLICATE and attempts:
            latest = attempts[-1]
            return WebhookIngressResult(
                result.disposition,
                latest.outcome,
                latest.outcome_code,
            )
        attempt = self._process(result.receipt, attempted_at=received_at)
        return WebhookIngressResult(
            result.disposition,
            attempt.outcome,
            attempt.outcome_code,
        )

    def replay(self, event_id: str, *, attempted_at: datetime) -> WebhookAttempt:
        event_id = _text(event_id, "Razorpay webhook event id", max_bytes=MAX_EVENT_ID_BYTES)
        receipt = self.receipt_store.get_receipt(self.context.account_id, event_id)
        if receipt is None:
            raise WebhookIngressError("webhook receipt not found")
        return self._process(receipt, attempted_at=attempted_at)

    def list_receipts(self, *, limit: int = 50) -> tuple[WebhookReceiptSummary, ...]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MAX_RECEIPT_LIST_LIMIT
        ):
            raise WebhookIngressError("webhook receipt limit is invalid")
        return self.receipt_store.list_receipts(self.context.account_id, limit=limit)

    def receipt_attempts(self, event_id: str) -> tuple[WebhookAttempt, ...]:
        event_id = _text(event_id, "Razorpay webhook event id", max_bytes=MAX_EVENT_ID_BYTES)
        if self.receipt_store.get_receipt(self.context.account_id, event_id) is None:
            raise WebhookIngressError("webhook receipt not found")
        return self.receipt_store.attempts(self.context.account_id, event_id)


class _Cursor(Protocol):
    def __enter__(self) -> _Cursor: ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...

    def execute(self, query: str, params: Sequence[object] | None = None) -> object: ...

    def fetchone(self) -> tuple[object, ...] | None: ...

    def fetchall(self) -> list[tuple[object, ...]]: ...


class _Connection(Protocol):
    def cursor(self) -> _Cursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...


ConnectionFactory = Callable[[str], _Connection]


def _default_connection_factory(dsn: str) -> _Connection:
    try:
        module = importlib.import_module("psycopg")
    except ModuleNotFoundError as exc:
        raise WebhookPersistenceError("PostgreSQL webhook support requires psycopg") from exc
    connect = getattr(module, "connect", None)
    if not callable(connect):
        raise WebhookPersistenceError("psycopg.connect is unavailable")
    return cast(_Connection, connect(dsn))


_WEBHOOK_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS reflow_webhook_schema_meta (
        singleton SMALLINT PRIMARY KEY CHECK (singleton = 1),
        schema_version INTEGER NOT NULL CHECK (schema_version > 0)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reflow_webhook_receipts (
        provider TEXT NOT NULL,
        account_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        body_sha256 CHAR(64) NOT NULL,
        raw_body BYTEA NOT NULL,
        signature TEXT NOT NULL,
        first_received_at TIMESTAMPTZ NOT NULL,
        secret_generation TEXT NOT NULL,
        PRIMARY KEY (provider, account_id, event_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reflow_webhook_attempts (
        attempt_id BIGSERIAL PRIMARY KEY,
        provider TEXT NOT NULL,
        account_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        attempted_at TIMESTAMPTZ NOT NULL,
        outcome TEXT NOT NULL,
        outcome_code TEXT NOT NULL,
        FOREIGN KEY (provider, account_id, event_id)
          REFERENCES reflow_webhook_receipts(provider, account_id, event_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS reflow_webhook_attempts_receipt_idx
      ON reflow_webhook_attempts(provider, account_id, event_id, attempt_id)
    """,
)


class PostgresWebhookReceiptStore:
    def __init__(
        self,
        dsn: str,
        *,
        connection_factory: ConnectionFactory = _default_connection_factory,
        initialize: bool = True,
    ) -> None:
        self._dsn = _text(dsn, "PostgreSQL DSN", max_bytes=8192)
        self._connection_factory = connection_factory
        if initialize:
            self.migrate()

    def _connect(self) -> _Connection:
        return self._connection_factory(self._dsn)

    def migrate(self) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                for statement in _WEBHOOK_SCHEMA:
                    cursor.execute(statement)
                cursor.execute(
                    "SELECT schema_version FROM reflow_webhook_schema_meta WHERE singleton = 1"
                )
                row = cursor.fetchone()
                if row is None:
                    cursor.execute(
                        """
                        SELECT EXISTS (
                          SELECT 1 FROM reflow_webhook_receipts
                          UNION ALL
                          SELECT 1 FROM reflow_webhook_attempts
                        )
                        """
                    )
                    populated = cursor.fetchone()
                    if populated is None or not isinstance(populated[0], bool):
                        raise WebhookPersistenceError("webhook schema population check failed")
                    if populated[0]:
                        raise WebhookPersistenceError(
                            "webhook schema metadata is missing for non-empty tables"
                        )
                    cursor.execute(
                        """
                        INSERT INTO reflow_webhook_schema_meta(singleton, schema_version)
                        VALUES (1, %s)
                        """,
                        (WEBHOOK_SCHEMA_VERSION,),
                    )
                    row = (WEBHOOK_SCHEMA_VERSION,)
                if row[0] != WEBHOOK_SCHEMA_VERSION:
                    raise WebhookPersistenceError(
                        "unsupported webhook persistence schema version"
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def check_ready(self) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT schema_version FROM reflow_webhook_schema_meta WHERE singleton = 1"
                )
                row = cursor.fetchone()
            if row is None or row[0] != WEBHOOK_SCHEMA_VERSION:
                raise WebhookPersistenceError("webhook persistence schema is not ready")
        finally:
            connection.close()

    @staticmethod
    def _row_to_receipt(row: tuple[object, ...]) -> WebhookReceipt:
        if len(row) != 8:
            raise WebhookPersistenceError("webhook receipt row shape is invalid")
        provider, account_id, event_id, digest, raw_body, signature, received_at, generation = row
        if not all(
            isinstance(value, str)
            for value in (provider, account_id, event_id, digest, signature)
        ):
            raise WebhookPersistenceError("webhook receipt text fields are invalid")
        if isinstance(raw_body, memoryview):
            raw_body = raw_body.tobytes()
        if not isinstance(raw_body, bytes) or not isinstance(received_at, datetime):
            raise WebhookPersistenceError("webhook receipt binary/time fields are invalid")
        try:
            typed_generation = WebhookSecretGeneration(cast(str, generation))
        except ValueError as exc:
            raise WebhookPersistenceError("webhook secret generation is invalid") from exc
        receipt = WebhookReceipt(
            provider=cast(str, provider),
            account_id=cast(str, account_id),
            event_id=cast(str, event_id),
            body_sha256=cast(str, digest),
            raw_body=raw_body,
            signature=cast(str, signature),
            first_received_at=received_at,
            secret_generation=typed_generation,
        )
        if hashlib.sha256(receipt.raw_body).hexdigest() != receipt.body_sha256:
            raise WebhookPersistenceError("webhook receipt body digest mismatch")
        return receipt

    def append_receipt(self, receipt: WebhookReceipt) -> WebhookReceiptResult:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO reflow_webhook_receipts(
                      provider, account_id, event_id, body_sha256, raw_body,
                      signature, first_received_at, secret_generation
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (provider, account_id, event_id) DO NOTHING
                    RETURNING event_id
                    """,
                    (
                        receipt.provider,
                        receipt.account_id,
                        receipt.event_id,
                        receipt.body_sha256,
                        receipt.raw_body,
                        receipt.signature,
                        receipt.first_received_at,
                        receipt.secret_generation.value,
                    ),
                )
                stored = cursor.fetchone() is not None
                cursor.execute(
                    """
                    SELECT provider, account_id, event_id, body_sha256, raw_body,
                           signature, first_received_at, secret_generation
                    FROM reflow_webhook_receipts
                    WHERE provider='razorpay' AND account_id=%s AND event_id=%s
                    """,
                    (receipt.account_id, receipt.event_id),
                )
                row = cursor.fetchone()
                if row is None:
                    raise WebhookPersistenceError("webhook receipt disappeared after append")
                retained = self._row_to_receipt(row)
                if (
                    retained.body_sha256 != receipt.body_sha256
                    or retained.raw_body != receipt.raw_body
                ):
                    raise WebhookReceiptConflictError(
                        "same Razorpay webhook event id arrived with different raw body"
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return WebhookReceiptResult(
            WebhookReceiptDisposition.STORED
            if stored
            else WebhookReceiptDisposition.DUPLICATE,
            retained,
        )

    def get_receipt(self, account_id: str, event_id: str) -> WebhookReceipt | None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT provider, account_id, event_id, body_sha256, raw_body,
                           signature, first_received_at, secret_generation
                    FROM reflow_webhook_receipts
                    WHERE provider='razorpay' AND account_id=%s AND event_id=%s
                    """,
                    (account_id, event_id),
                )
                row = cursor.fetchone()
            return None if row is None else self._row_to_receipt(row)
        finally:
            connection.close()

    @staticmethod
    def _row_to_attempt(row: tuple[object, ...]) -> WebhookAttempt:
        if len(row) != 5:
            raise WebhookPersistenceError("webhook attempt row shape is invalid")
        attempt_id, event_id, attempted_at, outcome, outcome_code = row
        if not isinstance(attempt_id, int) or not isinstance(event_id, str):
            raise WebhookPersistenceError("webhook attempt identity is invalid")
        if not isinstance(attempted_at, datetime) or not isinstance(outcome_code, str):
            raise WebhookPersistenceError("webhook attempt fields are invalid")
        try:
            typed_outcome = WebhookProcessingOutcome(cast(str, outcome))
        except ValueError as exc:
            raise WebhookPersistenceError("webhook attempt outcome is invalid") from exc
        return WebhookAttempt(
            attempt_id,
            event_id,
            attempted_at,
            typed_outcome,
            outcome_code,
        )

    def attempts(self, account_id: str, event_id: str) -> tuple[WebhookAttempt, ...]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT attempt_id, event_id, attempted_at, outcome, outcome_code
                    FROM reflow_webhook_attempts
                    WHERE provider='razorpay' AND account_id=%s AND event_id=%s
                    ORDER BY attempt_id
                    """,
                    (account_id, event_id),
                )
                rows = cursor.fetchall()
            return tuple(self._row_to_attempt(row) for row in rows)
        finally:
            connection.close()

    def record_attempt(
        self,
        *,
        account_id: str,
        event_id: str,
        attempted_at: datetime,
        outcome: WebhookProcessingOutcome,
        outcome_code: str,
    ) -> WebhookAttempt:
        code = _text(
            outcome_code,
            "webhook outcome code",
            max_bytes=MAX_OUTCOME_CODE_BYTES,
        )
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO reflow_webhook_attempts(
                      provider, account_id, event_id, attempted_at, outcome, outcome_code
                    ) VALUES ('razorpay',%s,%s,%s,%s,%s)
                    RETURNING attempt_id, event_id, attempted_at, outcome, outcome_code
                    """,
                    (
                        account_id,
                        event_id,
                        _aware(attempted_at, "attempted_at"),
                        outcome.value,
                        code,
                    ),
                )
                row = cursor.fetchone()
                if row is None:
                    raise WebhookPersistenceError("webhook attempt was not retained")
                result = self._row_to_attempt(row)
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list_receipts(
        self,
        account_id: str,
        *,
        limit: int,
    ) -> tuple[WebhookReceiptSummary, ...]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MAX_RECEIPT_LIST_LIMIT
        ):
            raise WebhookIngressError("webhook receipt limit is invalid")
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT r.event_id, r.first_received_at, r.body_sha256,
                           r.secret_generation, latest.outcome,
                           latest.outcome_code, COALESCE(counts.attempt_count, 0)
                    FROM reflow_webhook_receipts r
                    LEFT JOIN LATERAL (
                      SELECT outcome, outcome_code
                      FROM reflow_webhook_attempts a
                      WHERE a.provider=r.provider
                        AND a.account_id=r.account_id
                        AND a.event_id=r.event_id
                      ORDER BY a.attempt_id DESC LIMIT 1
                    ) latest ON TRUE
                    LEFT JOIN LATERAL (
                      SELECT COUNT(*)::BIGINT AS attempt_count
                      FROM reflow_webhook_attempts a
                      WHERE a.provider=r.provider
                        AND a.account_id=r.account_id
                        AND a.event_id=r.event_id
                    ) counts ON TRUE
                    WHERE r.provider='razorpay' AND r.account_id=%s
                    ORDER BY r.first_received_at DESC, r.event_id DESC
                    LIMIT %s
                    """,
                    (account_id, limit),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
        result: list[WebhookReceiptSummary] = []
        for row in rows:
            if len(row) != 7:
                raise WebhookPersistenceError("webhook receipt summary row is invalid")
            event_id, received_at, digest, generation, outcome, code, count = row
            if not isinstance(event_id, str) or not isinstance(received_at, datetime):
                raise WebhookPersistenceError("webhook receipt summary identity is invalid")
            if not isinstance(digest, str) or not isinstance(count, int):
                raise WebhookPersistenceError("webhook receipt summary fields are invalid")
            try:
                typed_generation = WebhookSecretGeneration(cast(str, generation))
                typed_outcome = (
                    None
                    if outcome is None
                    else WebhookProcessingOutcome(cast(str, outcome))
                )
            except ValueError as exc:
                raise WebhookPersistenceError("webhook receipt summary enum is invalid") from exc
            if code is not None and not isinstance(code, str):
                raise WebhookPersistenceError(
                    "webhook receipt summary outcome code is invalid"
                )
            result.append(
                WebhookReceiptSummary(
                    event_id,
                    received_at,
                    digest,
                    typed_generation,
                    typed_outcome,
                    code,
                    count,
                )
            )
        return tuple(result)

    def integrity_counts(self) -> tuple[int, int]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT provider, account_id, event_id, body_sha256, raw_body,
                           signature, first_received_at, secret_generation
                    FROM reflow_webhook_receipts
                    ORDER BY provider, account_id, event_id
                    """
                )
                receipts = tuple(
                    self._row_to_receipt(row) for row in cursor.fetchall()
                )
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM reflow_webhook_attempts a
                    LEFT JOIN reflow_webhook_receipts r
                      ON r.provider=a.provider
                        AND r.account_id=a.account_id
                        AND r.event_id=a.event_id
                    WHERE r.event_id IS NULL
                    """
                )
                orphan = cursor.fetchone()
                cursor.execute("SELECT COUNT(*) FROM reflow_webhook_attempts")
                attempts = cursor.fetchone()
        finally:
            connection.close()
        if (
            orphan is None
            or orphan[0] != 0
            or attempts is None
            or not isinstance(attempts[0], int)
        ):
            raise WebhookPersistenceError("webhook persistence integrity check failed")
        return len(receipts), attempts[0]


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value or value != value.strip():
        raise RuntimeError(
            f"{name} is required when Razorpay webhook ingress is enabled"
        )
    return value


def razorpay_webhook_ingress_from_env(
    *,
    dsn: str,
    journal: Journal,
) -> tuple[RazorpayWebhookIngress | None, Callable[[], None] | None]:
    mode = os.getenv("REFLOW_RAZORPAY_WEBHOOK_MODE", "disabled")
    if mode != mode.strip() or mode not in {"disabled", "enabled"}:
        raise RuntimeError(
            "REFLOW_RAZORPAY_WEBHOOK_MODE must be 'disabled' or 'enabled'"
        )
    if mode == "disabled":
        return None, None
    origin_value = _required_env("REFLOW_RAZORPAY_EVIDENCE_ORIGIN")
    try:
        origin = RazorpayEvidenceOrigin(origin_value)
    except ValueError as exc:
        raise RuntimeError("REFLOW_RAZORPAY_EVIDENCE_ORIGIN is invalid") from exc
    if origin not in {
        RazorpayEvidenceOrigin.REAL_TEST_MODE,
        RazorpayEvidenceOrigin.REAL_LIVE,
    }:
        raise RuntimeError(
            "webhook ingress requires real Test Mode or Live evidence origin"
        )
    context = RazorpayAccountContext(
        account_id=_required_env("REFLOW_RAZORPAY_ACCOUNT_ID"),
        evidence_origin=origin,
    )
    current = _required_env("REFLOW_RAZORPAY_WEBHOOK_SECRET")
    previous = os.getenv("REFLOW_RAZORPAY_WEBHOOK_PREVIOUS_SECRET") or None
    secrets = WebhookSecrets(current=current, previous=previous)
    store = PostgresWebhookReceiptStore(dsn)
    return (
        RazorpayWebhookIngress(
            receipt_store=store,
            journal=journal,
            context=context,
            secrets=secrets,
        ),
        store.check_ready,
    )
