from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from reflow.domain import SourceKind
from reflow.journal import InMemoryJournal, make_source_envelope, payload_sha256
from .records import ObservedBatch, RawRecord

from .adapters import CanonicalBatch, SourceIdentity, SourceLink, adapt_observed_batch


def _aware(value: datetime) -> None:
    if not isinstance(value, datetime):
        raise TypeError("received_at must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("received_at must be timezone-aware")


def _raw_source_time(row: RawRecord, key: str) -> datetime | None:
    value = row.get(key)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _raw_record_id(row: RawRecord, key: str) -> str:
    value = row.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return f"unidentified-{payload_sha256(row)[:24]}"


def _journal_rows(
    journal: InMemoryJournal,
    rows: Iterable[RawRecord],
    *,
    source_kind: SourceKind,
    record_id_key: str,
    source_time_key: str,
    schema_version: str,
    received_at: datetime,
) -> tuple[SourceLink, ...]:
    links: dict[SourceIdentity, SourceLink] = {}
    for row in rows:
        source_record_id = _raw_record_id(row, record_id_key)
        result = journal.append(
            make_source_envelope(
                source_kind=source_kind,
                source_record_id=source_record_id,
                occurred_at=_raw_source_time(row, source_time_key),
                received_at=received_at,
                schema_version=schema_version,
                payload=row,
            )
        )
        link = SourceLink(
            source_kind=source_kind,
            source_record_id=source_record_id,
            envelope_id=result.envelope.id,
        )
        existing = links.get(link.identity)
        if existing is not None and existing != link:
            raise AssertionError("journal returned conflicting envelope for one source identity")
        links[link.identity] = link
    return tuple(
        sorted(
            links.values(),
            key=lambda link: (link.source_kind.value, link.source_record_id),
        )
    )


def _rows_from_journal(
    journal: InMemoryJournal,
    rows: Iterable[RawRecord],
    *,
    source_kind: SourceKind,
    record_id_key: str,
) -> tuple[RawRecord, ...]:
    """Return one immutable primary payload per source identity, preserving input order."""
    seen: set[str] = set()
    retained: list[RawRecord] = []
    for row in rows:
        source_record_id = _raw_record_id(row, record_id_key)
        if source_record_id in seen:
            continue
        seen.add(source_record_id)
        envelope = journal.get(source_kind, source_record_id)
        if envelope is None:
            raise AssertionError(
                "journal-first ingestion lost a retained source identity: "
                f"{source_kind.value}/{source_record_id}"
            )
        retained.append(envelope.payload)
    return tuple(retained)


def _canonical_input_from_journal(
    batch: ObservedBatch,
    journal: InMemoryJournal,
) -> ObservedBatch:
    return ObservedBatch(
        merchant_rows=_rows_from_journal(
            journal,
            batch.merchant_rows,
            source_kind=SourceKind.MERCHANT,
            record_id_key="order_id",
        ),
        razorpay_events=_rows_from_journal(
            journal,
            batch.razorpay_events,
            source_kind=SourceKind.RAZORPAY_EVENT,
            record_id_key="event_id",
        ),
        recon_rows=_rows_from_journal(
            journal,
            batch.recon_rows,
            source_kind=SourceKind.RAZORPAY_RECON,
            record_id_key="recon_id",
        ),
        settlement_rows=_rows_from_journal(
            journal,
            batch.settlement_rows,
            source_kind=SourceKind.RAZORPAY_SETTLEMENT,
            record_id_key="settlement_id",
        ),
        bank_rows=_rows_from_journal(
            journal,
            batch.bank_rows,
            source_kind=SourceKind.BANK,
            record_id_key="bank_entry_id",
        ),
    )

def journal_observed_batch(
    batch: ObservedBatch,
    journal: InMemoryJournal,
    *,
    received_at: datetime,
) -> tuple[SourceLink, ...]:
    """Persist raw evidence before canonical validation and return immutable source links."""
    _aware(received_at)
    links = (
        *_journal_rows(
            journal,
            batch.merchant_rows,
            source_kind=SourceKind.MERCHANT,
            record_id_key="order_id",
            source_time_key="created_at",
            schema_version="merchant-normalized-v1",
            received_at=received_at,
        ),
        *_journal_rows(
            journal,
            batch.razorpay_events,
            source_kind=SourceKind.RAZORPAY_EVENT,
            record_id_key="event_id",
            source_time_key="occurred_at",
            schema_version="razorpay-event-normalized-v1",
            received_at=received_at,
        ),
        *_journal_rows(
            journal,
            batch.recon_rows,
            source_kind=SourceKind.RAZORPAY_RECON,
            record_id_key="recon_id",
            source_time_key="occurred_at",
            schema_version="razorpay-recon-normalized-v1",
            received_at=received_at,
        ),
        *_journal_rows(
            journal,
            batch.settlement_rows,
            source_kind=SourceKind.RAZORPAY_SETTLEMENT,
            record_id_key="settlement_id",
            source_time_key="processed_at",
            schema_version="razorpay-settlement-normalized-v1",
            received_at=received_at,
        ),
        *_journal_rows(
            journal,
            batch.bank_rows,
            source_kind=SourceKind.BANK,
            record_id_key="bank_entry_id",
            source_time_key="occurred_at",
            schema_version="bank-settlement-credit-normalized-v1",
            received_at=received_at,
        ),
    )
    indexed: dict[SourceIdentity, SourceLink] = {}
    for link in links:
        existing = indexed.get(link.identity)
        if existing is not None and existing != link:
            raise AssertionError("one batch produced conflicting source links")
        indexed[link.identity] = link
    return tuple(
        sorted(
            indexed.values(),
            key=lambda link: (link.source_kind.value, link.source_record_id),
        )
    )


def ingest_observed_batch(
    batch: ObservedBatch,
    journal: InMemoryJournal,
    *,
    received_at: datetime,
) -> CanonicalBatch:
    """Journal raw evidence, collapse exact replays, then compile canonical objects once."""
    source_links = journal_observed_batch(batch, journal, received_at=received_at)
    canonical = adapt_observed_batch(_canonical_input_from_journal(batch, journal))
    return canonical._bind_source_links(source_links)
