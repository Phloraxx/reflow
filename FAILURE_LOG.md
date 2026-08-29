# ReFlow Failure Log

## Why this file exists

The Razorpay AI Builder Internship submission form explicitly asks about build challenges and technical obstacles. This log records genuine implementation/evaluation failures as they occur.

It is **not** a marketing page. Do not invent failures, hide regressions, or rewrite history after a fix.

Research-stage strategic decisions and the Track 03 → Track 04 pivot are documented separately in `docs/03_COMPETITIVE_ANALYSIS.md`.

---

## Rules

For every meaningful failure:

1. record it before or while fixing it;
2. preserve the test/fixture that exposed it;
3. state whether the bug was in the engine, generator, benchmark, model, connector, UI or assumption;
4. add a regression test where technically appropriate;
5. record benchmark impact if the fix changes published metrics;
6. retain embarrassing findings if they are true;
7. do not call a limitation “fixed” until the reproducer passes.

---

# Active failures

None at the end of the Gates 0–6 audit. The audit fixes below pass Ruff, strict mypy and pytest on the Phase 4–6 branch.

---

# Resolved failures

## F-0001 — Cross-period refund violated temporal causality

**Date:** 2026-08-29  
**Area:** simulator  
**Severity:** high

### Symptom

The `cross_period_refund` scenario created a refund two days after the case time while assigning it to a settlement processed only six hours after the case time.

### Initial assumption

Arithmetic conservation was treated as sufficient validation for synthetic settlement truth.

### Root cause

The generator modeled “cross-period” by pushing the refund timestamp into the future instead of linking a current-period refund to a payment captured in a prior period. `HiddenWorld.validate()` checked sums but not temporal causality.

### Why it matters

A settlement proof engine trained/evaluated on this world could be rewarded for accepting evidence that did not yet exist when the settlement was processed.

### Fix

Cross-period refunds now reference a captured payment from the prior settlement case and occur before the current settlement is processed. Hidden-world validation now checks event/recon/entity references, temporal ordering, UTR consistency and unique event/recon identities.

### Regression protection

`test_cross_period_refund_targets_prior_payment_before_current_settlement` plus multi-seed hidden-world validation.

### Metric impact

No published metric changed; final benchmark had not started.

### Remaining limitation

Synthetic timing distributions still need later calibration against real integration evidence.

---

## F-0002 — Frozen source envelope contained mutable evidence

**Date:** 2026-08-29  
**Area:** engine  
**Severity:** safety-critical

### Symptom

`SourceEnvelope` was a frozen dataclass, but its `payload` normally contained a mutable `dict`. A caller could mutate raw evidence after the SHA-256 digest had been computed.

### Initial assumption

A frozen dataclass was assumed to provide sufficient immutability.

### Root cause

Dataclass freezing is shallow.

### Why it matters

The stored payload and its recorded digest could diverge, invalidating provenance and any proof that cited the envelope.

### Fix

Source payloads are recursively frozen into immutable mappings/tuples and restricted to deterministic JSON-compatible values. NaN and infinity are rejected by the journal hash path.

### Regression protection

Deep mutation tests and frozen-payload rehash tests.

### Metric impact

No published metric changed.

### Remaining limitation

Persistent append-only storage is still a later infrastructure phase; the current journal is an in-memory reference implementation.

---

## F-0003 — Legitimate webhook retry could be treated as conflicting evidence

**Date:** 2026-08-29  
**Area:** engine  
**Severity:** high

### Symptom

The payment reducer compared duplicate `PaymentEvent` dataclasses for full equality. The dataclass includes `received_at`, so the same provider event redelivered later could be rejected as a conflicting payload.

### Initial assumption

Exact object equality was treated as equivalent to source-event identity.

### Root cause

Provider facts and local delivery metadata were not separated during deduplication.

### Why it matters

At-least-once webhook delivery can legitimately produce retries at different receive times. Rejecting those retries would make replay/idempotency brittle.

### Fix

Duplicate event comparison now ignores local `received_at` while requiring all source facts to remain identical. Conflicting source facts under the same event ID still fail closed.

### Regression protection

`test_retry_with_later_local_received_at_is_still_idempotent` and late-delivery state tests.

### Metric impact

No published metric changed.

### Remaining limitation

Crash/restart idempotency requires persistent journal storage later.

---

## F-0004 — Money Graph topology hid duplicate recon evidence

**Date:** 2026-08-29  
**Area:** evaluation  
**Severity:** high

### Symptom

A recon row produced a direct `economic entity → settlement` edge. If the same economic row was duplicated under a new recon ID, the edge-key scorer collapsed both rows into the same relationship and reported no false-positive edge.

### Initial assumption

A direct movement-to-settlement edge was considered enough provenance for Gate 6.

### Root cause

Recon entries were evidence strings rather than first-class graph nodes, so row identity disappeared from the graph topology and benchmark.

### Why it matters

The graph could hide a duplicated economic row exactly where later settlement arithmetic must detect double counting.

### Fix

Recon entries are now graph nodes. Each row creates `entity_has_recon_entry` and `recon_entry_contributes_to_settlement` edges. Order/payment edges are built from reduced payment truth, so contradictory order IDs fail closed before an authoritative graph edge is emitted.

### Regression protection

The duplicate-recon fixture now produces two measurable false-positive edges, missing recon produces two false negatives, and contradictory order identity raises before proof construction.

### Metric impact

The clean graph remains 100% precision/recall on current synthetic truth. The duplicate-row adversarial case now correctly shows degraded precision instead of a misleading perfect score. No result had been publicly published.

### Remaining limitation

Graph metrics remain synthetic until the held-out benchmark phase.

---

## F-0005 — Refund recon validation was under-constrained

**Date:** 2026-08-29  
**Area:** ingestion  
**Severity:** high

### Symptom

The normalized synthetic recon adapter accepted any negative refund `settlement_effect`, even when it differed from the row's signed refund amount.

### Initial assumption

Checking only that refund rows reduced settlement value was considered sufficient.

### Root cause

The adapter's refund invariant was weaker than the synthetic fixture contract.

### Why it matters

A malformed refund row could pass canonicalization and later contaminate settlement arithmetic.

### Fix

For the **normalized synthetic fixture schema**, refund rows now require negative gross amount, zero fee/tax and `settlement_effect == gross_amount`.

### Regression protection

A targeted test changes a refund effect by one paise while keeping it negative and requires the adapter to fail closed.

### Metric impact

No published metric changed.

### Remaining limitation

This is not claimed as the production Razorpay Settlement Recon conversion rule. The real Razorpay adapter must normalize authoritative `debit`/`credit` semantics from the actual API in the later integration phase.

---

## F-0006 — High-cardinality timestamps could cross the settlement boundary

**Date:** 2026-08-29  
**Area:** simulator  
**Severity:** medium

### Symptom

Synthetic payment events were spaced two seconds apart. At sufficiently high cardinality, later payments occurred after the settlement's fixed +6 hour processing time.

### Root cause

A human-readable event spacing choice was accidentally coupled to scale.

### Why it matters

Large-scale benchmark cases could become temporally impossible and invalidate performance/evaluation claims.

### Fix

Per-payment synthetic event spacing now uses microseconds, while recon and settlement stages retain explicit later boundaries.

### Regression protection

A 15,000-payment regression fixture verifies all payment events precede settlement processing.

### Metric impact

No published metric changed.

### Remaining limitation

Later performance tests must ensure generator overhead does not dominate engine measurements.

---

## F-0007 — Typed IDs accepted a prefix with no identifier

**Date:** 2026-08-29  
**Area:** engine  
**Severity:** low

### Symptom

`PaymentId("pay_")` and equivalent typed IDs passed validation.

### Fix

Typed IDs now require non-empty content after their declared prefix.

### Regression protection

`test_prefix_without_identifier_suffix_is_rejected`.

### Metric impact

None.

---

# Failure categories still targeted deliberately

These are test targets, not claimed failures:

- settlement debit/credit sign mistakes in the real Razorpay adapter;
- repeated economic-row counting in the Phase 7 proof engine;
- same-amount bank ambiguity;
- exact UTR with wrong amount;
- split bank-credit handling;
- late source evidence reopening a proof;
- schema drift;
- AI adapter inferring the wrong amount unit or debit/credit sign;
- prompt-like text inside bank narration;
- hallucinated evidence IDs;
- AI provider outage;
- unfair baseline construction;
- hidden-truth leakage into candidate pipeline;
- benchmark scorer bugs;
- residual solver combinatorial explosion;
- high-memory batch behaviour;
- crash/restart idempotency.
