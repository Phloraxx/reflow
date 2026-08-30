from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from reflow.domain import Money, SourceKind
from reflow.ingestion import (
    AdapterError,
    adapt_bank_row,
    adapt_merchant_row,
    adapt_payment_event,
    adapt_recon_row,
    adapt_settlement_row,
    ingest_observed_batch,
    journal_observed_batch,
)
from reflow.journal import InMemoryJournal, JournalConflictError
from reflow.simulator import CorruptionKind, CorruptionPlan, generate_world, observe_world

RECEIVED = datetime(2026, 8, 29, 18, 0, tzinfo=UTC)


def _observed(*kinds: CorruptionKind):
    return observe_world(
        generate_world(303),
        seed=404,
        plan=CorruptionPlan(kinds=tuple(kinds)),
    ).observed


def test_clean_ingestion_journals_every_raw_record_before_returning_canonical() -> None:
    observed = _observed()
    journal = InMemoryJournal()
    canonical = ingest_observed_batch(observed, journal, received_at=RECEIVED)
    assert len(journal) == observed.record_count
    assert len(canonical.orders) == len(observed.merchant_rows)
    assert len(canonical.source_links) == len(journal)
    assert canonical.compilation_sha256 is not None
    journal_ids = {entry.id for entry in journal.entries()}
    assert {link.envelope_id for link in canonical.source_links} == journal_ids


def test_each_canonical_fact_recompiles_from_its_retained_raw_envelope() -> None:
    journal = InMemoryJournal()
    canonical = ingest_observed_batch(_observed(), journal, received_at=RECEIVED)

    for row in canonical.orders:
        envelope = journal.get(SourceKind.MERCHANT, str(row.id))
        assert envelope is not None
        assert adapt_merchant_row(envelope.payload) == row
    for row in canonical.payment_events:
        envelope = journal.get(SourceKind.RAZORPAY_EVENT, row.source_event_id)
        assert envelope is not None
        assert adapt_payment_event(envelope.payload) == row
    for row in canonical.recon_entries:
        envelope = journal.get(SourceKind.RAZORPAY_RECON, str(row.id))
        assert envelope is not None
        assert adapt_recon_row(envelope.payload) == row
    for row in canonical.settlements:
        envelope = journal.get(SourceKind.RAZORPAY_SETTLEMENT, str(row.id))
        assert envelope is not None
        assert adapt_settlement_row(envelope.payload) == row
    for row in canonical.bank_entries:
        envelope = journal.get(SourceKind.BANK, str(row.id))
        assert envelope is not None
        assert adapt_bank_row(envelope.payload) == row


def test_compilation_digest_is_invariant_to_source_row_order() -> None:
    observed = _observed()
    reversed_batch = replace(
        observed,
        merchant_rows=tuple(reversed(observed.merchant_rows)),
        razorpay_events=tuple(reversed(observed.razorpay_events)),
        recon_rows=tuple(reversed(observed.recon_rows)),
        settlement_rows=tuple(reversed(observed.settlement_rows)),
        bank_rows=tuple(reversed(observed.bank_rows)),
    )

    first = ingest_observed_batch(observed, InMemoryJournal(), received_at=RECEIVED)
    second = ingest_observed_batch(
        reversed_batch, InMemoryJournal(), received_at=RECEIVED
    )

    assert first.compilation_sha256 == second.compilation_sha256


def test_exact_source_replay_is_canonicalized_once_after_journaling() -> None:
    observed = _observed()
    replay = dict(observed.razorpay_events[0])
    replayed = replace(observed, razorpay_events=(*observed.razorpay_events, replay))
    journal = InMemoryJournal()

    canonical = ingest_observed_batch(replayed, journal, received_at=RECEIVED)

    assert len(journal) == observed.record_count
    assert len(canonical.source_links) == observed.record_count
    assert len(canonical.payment_events) == len(observed.razorpay_events)


def test_malformed_source_is_preserved_in_journal_before_adapter_rejects_batch() -> None:
    observed = _observed(CorruptionKind.MALFORMED_DATE)
    journal = InMemoryJournal()
    with pytest.raises(AdapterError):
        ingest_observed_batch(observed, journal, received_at=RECEIVED)
    assert len(journal) == observed.record_count
    assert any(entry.occurred_at is None for entry in journal.entries())


def test_reingesting_same_raw_batch_later_is_idempotent() -> None:
    observed = _observed()
    journal = InMemoryJournal()
    first_links = journal_observed_batch(observed, journal, received_at=RECEIVED)
    size = len(journal)
    second_links = journal_observed_batch(
        observed,
        journal,
        received_at=RECEIVED + timedelta(hours=1),
    )
    assert len(journal) == size
    assert second_links == first_links


def test_same_source_record_id_with_changed_raw_payload_is_retained_then_rejected() -> None:
    observed = _observed()
    journal = InMemoryJournal()
    journal_observed_batch(observed, journal, received_at=RECEIVED)
    original_size = len(journal)

    merchant_rows = [dict(row) for row in observed.merchant_rows]
    order_id = merchant_rows[0]["order_id"]
    merchant_rows[0]["external_reference"] = "changed-after-first-ingest"
    changed = replace(observed, merchant_rows=tuple(merchant_rows))

    with pytest.raises(JournalConflictError):
        journal_observed_batch(
            changed,
            journal,
            received_at=RECEIVED + timedelta(minutes=1),
        )

    assert len(journal) == original_size + 1
    versions = [
        entry
        for entry in journal.entries()
        if entry.source_kind.value == "merchant" and entry.source_record_id == order_id
    ]
    assert len(versions) == 2
    assert versions[0].payload_sha256 != versions[1].payload_sha256


def test_journal_backed_canonical_values_cannot_change_under_old_source_binding() -> None:
    journal = InMemoryJournal()
    canonical = ingest_observed_batch(_observed(), journal, received_at=RECEIVED)
    target = canonical.recon_entries[0]
    changed = replace(
        target,
        settlement_effect=Money(
            target.settlement_effect.amount_paise + 1,
            target.settlement_effect.currency,
        ),
    )

    with pytest.raises(ValueError, match="compiled source binding"):
        replace(
            canonical,
            recon_entries=(changed, *canonical.recon_entries[1:]),
        )
