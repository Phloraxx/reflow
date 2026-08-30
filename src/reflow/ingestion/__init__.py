"""Deterministic source adapters and journal-first ingestion."""

from .adapters import (
    AdapterError,
    CanonicalBatch,
    SourceIdentity,
    SourceLink,
    adapt_bank_row,
    adapt_merchant_row,
    adapt_observed_batch,
    adapt_payment_event,
    adapt_recon_row,
    adapt_settlement_row,
)
from .pipeline import ingest_observed_batch, journal_observed_batch
from .records import ObservedBatch, RawRecord

__all__ = [
    "AdapterError",
    "CanonicalBatch",
    "SourceIdentity",
    "SourceLink",
    "adapt_bank_row",
    "adapt_merchant_row",
    "adapt_observed_batch",
    "adapt_payment_event",
    "adapt_recon_row",
    "adapt_settlement_row",
    "ingest_observed_batch",
    "journal_observed_batch",
    "ObservedBatch",
    "RawRecord",
]
