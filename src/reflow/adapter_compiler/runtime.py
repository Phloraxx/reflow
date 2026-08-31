from __future__ import annotations

from reflow import domain, ingestion
from reflow.journal import InMemoryJournal

from .compiler import CanonicalRecord, canonical_record_identity, compile_adapter
from .contracts import CanonicalRecordKind
from .lifecycle import ApprovedAdapterVersion
from .profile import profile_rows


class AdapterRuntimeError(ValueError):
    pass


def _canonical_batch_for_records(
    record_kind: CanonicalRecordKind,
    records: tuple[CanonicalRecord, ...],
) -> ingestion.CanonicalBatch:
    orders = tuple(row for row in records if isinstance(row, domain.MerchantOrder))
    events = tuple(row for row in records if isinstance(row, domain.PaymentEvent))
    recon = tuple(row for row in records if isinstance(row, domain.SettlementReconEntry))
    settlements = tuple(row for row in records if isinstance(row, domain.Settlement))
    bank = tuple(row for row in records if isinstance(row, domain.BankEntry))
    expected_count = {
        CanonicalRecordKind.MERCHANT_ORDER: len(orders),
        CanonicalRecordKind.PAYMENT_EVENT: len(events),
        CanonicalRecordKind.SETTLEMENT_RECON: len(recon),
        CanonicalRecordKind.SETTLEMENT: len(settlements),
        CanonicalRecordKind.BANK_ENTRY: len(bank),
    }[record_kind]
    if expected_count != len(records):
        raise AdapterRuntimeError("compiled adapter emitted the wrong canonical record type")
    return ingestion.CanonicalBatch(
        orders=orders,
        payment_events=events,
        recon_entries=recon,
        settlements=settlements,
        bank_entries=bank,
    )


def apply_approved_adapter(
    version: ApprovedAdapterVersion,
    source_envelope_ids: tuple[domain.SourceEnvelopeId, ...],
    journal: InMemoryJournal,
) -> ingestion.CanonicalBatch:
    if not source_envelope_ids:
        raise AdapterRuntimeError("approved adapter application requires raw source evidence")
    if len(source_envelope_ids) != len(set(source_envelope_ids)):
        raise AdapterRuntimeError("approved adapter application contains duplicate source evidence")

    envelopes = []
    for envelope_id in source_envelope_ids:
        envelope = journal.get_by_id(envelope_id)
        if envelope is None:
            raise AdapterRuntimeError(f"raw source envelope {envelope_id} is not retained")
        if envelope.source_kind is not version.spec.source_kind:
            raise AdapterRuntimeError("raw source kind does not match approved adapter")
        envelopes.append(envelope)
    rows = tuple(envelope.payload for envelope in envelopes)
    profile = profile_rows(rows)
    if profile.schema_fingerprint != version.schema_fingerprint:
        raise AdapterRuntimeError("raw source schema does not match approved adapter fingerprint")
    compiled = compile_adapter(version.spec, profile)
    records = tuple(compiled.canonicalize(row) for row in rows)
    unbound = _canonical_batch_for_records(version.spec.record_kind, records)
    source_links = tuple(
        ingestion.SourceLink(
            source_kind=envelope.source_kind,
            source_record_id=envelope.source_record_id,
            envelope_id=envelope.id,
            canonical_record_id=canonical_record_identity(record),
        )
        for envelope, record in zip(envelopes, records, strict=True)
    )
    return unbound._bind_source_links(source_links)
