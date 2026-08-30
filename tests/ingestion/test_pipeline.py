from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from reflow.domain import Money
from reflow.ingestion import AdapterError, ingest_observed_batch, journal_observed_batch
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
