from __future__ import annotations

from enum import StrEnum

from reflow.simulator import CorruptionKind, CorruptionPlan


class EvaluationProfile(StrEnum):
    CLEAN = "clean"
    RECONCILIATION_ADVERSARIAL = "reconciliation_adversarial"
    SOURCE_SCHEMA_ADVERSARIAL = "source_schema_adversarial"


_SOURCE_SCHEMA_CORRUPTIONS = (
    CorruptionKind.MALFORMED_DATE,
    CorruptionKind.SCHEMA_RENAME,
    CorruptionKind.RUPEE_PAISE_TRAP,
    CorruptionKind.SIGN_TRAP,
)


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
    if profile is EvaluationProfile.SOURCE_SCHEMA_ADVERSARIAL:
        return CorruptionPlan(kinds=_SOURCE_SCHEMA_CORRUPTIONS)
    raise AssertionError(f"unhandled evaluation profile {profile}")
