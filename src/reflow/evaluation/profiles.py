from __future__ import annotations

from enum import StrEnum

from reflow.simulator import CorruptionKind, CorruptionPlan


class EvaluationProfile(StrEnum):
    CLEAN = "clean"
    RECONCILIATION_ADVERSARIAL = "reconciliation_adversarial"


_RECONCILIATION_CORRUPTIONS = (
    CorruptionKind.DUPLICATE_WEBHOOK,
    CorruptionKind.REORDER_WEBHOOKS,
    CorruptionKind.FAILED_THEN_CAPTURED,
    CorruptionKind.DROP_WEBHOOK,
    CorruptionKind.DELAY_WEBHOOK,
    CorruptionKind.MISSING_RECON_ROW,
    CorruptionKind.DUPLICATE_RECON_ROW,
    CorruptionKind.WRONG_RECON_AMOUNT,
    CorruptionKind.BANK_CREDIT_DELAY,
    CorruptionKind.BANK_NARRATION_NOISE,
    CorruptionKind.UTR_REMOVED,
    CorruptionKind.UTR_CORRUPTED,
    CorruptionKind.PROMPT_LIKE_NARRATION,
    CorruptionKind.PARTIAL_SOURCE_OUTAGE,
)


def corruption_plan(profile: EvaluationProfile) -> CorruptionPlan:
    if profile is EvaluationProfile.CLEAN:
        return CorruptionPlan(kinds=())
    if profile is EvaluationProfile.RECONCILIATION_ADVERSARIAL:
        return CorruptionPlan(kinds=_RECONCILIATION_CORRUPTIONS)
    raise AssertionError(f"unhandled evaluation profile {profile}")
