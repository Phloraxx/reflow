from dataclasses import replace

import pytest

from reflow.ingestion import AdapterError, adapt_observed_batch
from reflow.simulator import CorruptionKind, CorruptionPlan, generate_world, observe_world


def _observed(*kinds: CorruptionKind):
    world = generate_world(20260829)
    return observe_world(
        world,
        seed=77,
        plan=CorruptionPlan(kinds=tuple(kinds)),
    ).observed


def test_clean_known_sources_canonicalize() -> None:
    observed = _observed()
    canonical = adapt_observed_batch(observed)
    assert len(canonical.orders) == len(observed.merchant_rows)
    assert len(canonical.payment_events) == len(observed.razorpay_events)
    assert len(canonical.recon_entries) == len(observed.recon_rows)
    assert len(canonical.settlements) == len(observed.settlement_rows)
    assert len(canonical.bank_entries) == len(observed.bank_rows)


@pytest.mark.parametrize(
    "kind",
    [
        CorruptionKind.SCHEMA_RENAME,
        CorruptionKind.RUPEE_PAISE_TRAP,
        CorruptionKind.SIGN_TRAP,
        CorruptionKind.MALFORMED_DATE,
        CorruptionKind.WRONG_RECON_AMOUNT,
    ],
)
def test_known_unit_sign_and_schema_corruptions_fail_closed(kind: CorruptionKind) -> None:
    with pytest.raises(AdapterError):
        adapt_observed_batch(_observed(kind))


def test_wrong_refund_effect_fails_closed_even_when_still_negative() -> None:
    observed = _observed()
    rows = [dict(row) for row in observed.recon_rows]
    refund = next(row for row in rows if row["entity_kind"] == "refund")
    effect = refund["settlement_effect_paise"]
    assert isinstance(effect, int)
    refund["settlement_effect_paise"] = effect + 1
    malformed = replace(observed, recon_rows=tuple(rows))
    with pytest.raises(AdapterError):
        adapt_observed_batch(malformed)


def test_refund_lifecycle_cannot_masquerade_as_payment_event() -> None:
    observed = _observed()
    rows = [dict(row) for row in observed.razorpay_events]
    rows[0]["event_kind"] = "refunded"
    malformed = replace(observed, razorpay_events=tuple(rows))
    with pytest.raises(AdapterError, match="unsupported payment event kind"):
        adapt_observed_batch(malformed)


def test_prompt_like_bank_narration_is_data_not_instruction() -> None:
    canonical = adapt_observed_batch(_observed(CorruptionKind.PROMPT_LIKE_NARRATION))
    assert any("IGNORE PREVIOUS" in row.narration for row in canonical.bank_entries)


def test_failed_then_captured_evidence_is_accepted_as_evidence() -> None:
    canonical = adapt_observed_batch(_observed(CorruptionKind.FAILED_THEN_CAPTURED))
    kinds = {event.kind.value for event in canonical.payment_events}
    assert "failed" in kinds
    assert "captured" in kinds
