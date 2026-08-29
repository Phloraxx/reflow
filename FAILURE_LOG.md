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

None currently known in the deterministic implementation through Gate 8. Gate 8 still requires exact-head PR validation and merge before Gate 9 begins.

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

For the **normalized synthetic fixture schema**, refund rows require negative gross amount, zero fee/tax and `settlement_effect == gross_amount`.

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

## F-0008 — Append-only journal was not on the ingestion path

**Date:** 2026-08-29  
**Area:** ingestion  
**Severity:** safety-critical

### Symptom

The repository contained an append-only journal implementation, but the known-source adapter path consumed `ObservedBatch` directly. A malformed row could therefore be rejected before any immutable raw evidence had been retained. In addition, `SourceEnvelope` required a valid parsed source timestamp, so a row with a malformed source date could not be preserved as raw evidence at all.

### Initial assumption

Having a tested journal abstraction was treated as equivalent to having journal-first ingestion.

### Root cause

The architecture diagram and implementation order conflated raw evidence retention with canonicalization. The journal sat beside the adapters instead of in front of them.

### Why it matters

A finance proof system must be able to explain rejected or quarantined evidence. If malformed source rows disappear before journaling, provenance is incomplete precisely when an operator most needs the original evidence.

### Fix

A journal-first ingestion pipeline stores each raw record before deterministic canonicalization. Raw envelopes permit `occurred_at=None` when the source time cannot be parsed, while always preserving an aware local `received_at`, immutable payload and deterministic content hash. Missing source record identifiers use a deterministic hash-derived fallback rather than dropping the row. Canonical financial models retain their strict timestamp validation.

### Regression protection

`tests/ingestion/test_pipeline.py` verifies raw retention before canonicalization, malformed-date retention, replay idempotency and changed-content conflicts.

### Metric impact

No published metric changed.

### Remaining limitation

The journal is currently an in-memory reference implementation. Durable crash/restart idempotency, database constraints and retention policy remain later infrastructure work.

---

## F-0009 — Canonical objects lost their raw-envelope provenance

**Date:** 2026-08-29  
**Area:** ingestion / Money Graph  
**Severity:** safety-critical

### Symptom

After journal-first ingestion, the adapter created canonical objects independently. `CanonicalBatch` did not retain which raw `SourceEnvelope` produced each object, and Money Graph edges cited canonical event/recon IDs rather than raw journal envelope IDs.

### Initial assumption

Journaling before adaptation was treated as sufficient end-to-end provenance.

### Root cause

Raw retention and canonical compilation were connected only by control flow, not by an explicit immutable identity link.

### Why it matters

A proof could cite a canonical relationship without being able to walk back to the immutable source payload actually ingested.

### Fix

`CanonicalBatch` now carries validated immutable `SourceLink`s after journal-first ingestion. The Money Graph rejects adapter-only batches and authoritative edges cite `SourceEnvelopeId` values. Gate 7 proofs also retain their raw source envelope IDs.

### Regression protection

Pipeline/graph/proof tests verify source-link completeness, journal resolution, graph rejection of adapter-only batches and exact raw-envelope evidence IDs.

### Metric impact

No published metric changed.

### Remaining limitation

Persistent raw evidence storage is still in-memory.

---

## F-0010 — Gate 7 compared row values before economic identity

**Date:** 2026-08-29  
**Area:** reconciliation engine  
**Severity:** safety-critical

### Symptom

The initial Gate 7 duplicate fingerprint included amount fields and timestamp. Two recon rows claiming the same economic entity but disagreeing by one paise or timestamp could therefore look like two separate admissible movements.

### Initial assumption

A full-row fingerprint was assumed to be a sufficient duplicate-economic identity.

### Root cause

Value equality was evaluated before asking whether two rows claimed ownership of the same payment/refund/transfer/adjustment.

### Why it matters

Contradictory evidence about one economic movement could be double-counted and potentially contribute to a false green composition proof.

### Fix

Gate 7 groups rows first by `(entity_kind, entity_id)`. Same-source exact replay is idempotent; distinct rows with the same payload are duplicate economic evidence; differing payloads under one identity are an identity conflict. Conflicts force `COMPOSITION_CONTRADICTED`.

### Regression protection

Dedicated tests cover exact replay, distinct duplicate rows and same-identity/different-value evidence.

### Metric impact

No published metric changed.

### Remaining limitation

Real Razorpay recon identity semantics must be verified before generalizing the normalized fixture rule to production inputs.

---

## F-0011 — Gate 7 could use future recon evidence

**Date:** 2026-08-29  
**Area:** reconciliation engine  
**Severity:** safety-critical

### Symptom

A recon entry whose `occurred_at` was later than the settlement's `processed_at` could still be admitted into settlement composition arithmetic.

### Initial assumption

The simulator's causal truth was assumed to make an explicit proof-level time check redundant.

### Root cause

The proof engine trusted fixture causality instead of independently validating temporal admissibility.

### Why it matters

Corrupted or real-world late/future evidence could create a mathematically exact proof for a settlement before that movement existed.

### Fix

Late rows are excluded from admissible arithmetic, recorded in `late_component_ids`, tagged `RECON_AFTER_SETTLEMENT` and force contradiction.

### Regression protection

`test_recon_after_settlement_is_contradicted_and_excluded_from_arithmetic`.

### Metric impact

No published metric changed.

### Remaining limitation

Production source clocks/time semantics require source-specific validation later.

---

## F-0012 — One economic movement could be claimed by multiple settlements

**Date:** 2026-08-29  
**Area:** reconciliation engine  
**Severity:** safety-critical

### Symptom

Per-settlement proof calls could independently accept the same payment/refund/transfer/adjustment identity under two settlement IDs.

### Initial assumption

Settlement-local identity checks were assumed to be enough.

### Root cause

No batch-level ownership index existed for economic identities.

### Why it matters

Two otherwise valid-looking settlement proofs could both claim the same money movement.

### Fix

Gate 7 builds a batch-level economic-ownership index. Identities claimed by multiple settlements are excluded from admissible arithmetic and force `ECONOMIC_ENTITY_IN_MULTIPLE_SETTLEMENTS` contradictions in every affected proof.

### Regression protection

`test_same_economic_entity_cannot_belong_to_two_settlements`.

### Metric impact

No published metric changed.

### Remaining limitation

The production adapter must confirm provider identity semantics for each real recon entity type.

---

## F-0013 — Raw envelope digest and ID were not self-verifying

**Date:** 2026-08-29  
**Area:** evidence/provenance  
**Severity:** safety-critical

### Symptom

`SourceEnvelope` checked only that `payload_sha256` looked like a SHA-256 digest. It did not recompute the digest from its immutable payload. It also did not verify that its `src_...` ID was the deterministic identity derived by the journal helper.

### Initial assumption

The journal helper was assumed to be the only construction path, so its correct derivation was treated as sufficient.

### Root cause

Integrity rules lived in the helper rather than in the domain object that promises immutable evidence.

### Why it matters

A manually constructed or future deserialized envelope could carry a false digest or unrelated valid-looking source ID and still enter the journal/proof chain.

### Fix

One canonical source hashing/identity module is shared by the journal and domain. `SourceEnvelope` freezes the payload, verifies the exact digest, derives the expected `src_...` identity from source kind + record ID + digest, and rejects any mismatch.

### Regression protection

Domain tests cover digest mismatch, source-envelope ID mismatch, deep immutability and successful rehashing of the frozen payload.

### Metric impact

No published metric changed.

### Remaining limitation

This proves internal evidence integrity, not external authenticity. Production webhook signature verification and authenticated source acquisition remain integration responsibilities.

---

## F-0014 — Refund lifecycle was mixed into the normalized payment-event model

**Date:** 2026-08-29  
**Area:** domain / ingestion  
**Severity:** medium

### Symptom

`PaymentEventKind` exposed a generic `REFUNDED` event and the reducer converted it directly into a full refunded amount. `PaymentStatus` also contained an unused `PARTIALLY_REFUNDED` state.

### Initial assumption

Payment entity statuses and payment webhook event kinds were treated as interchangeable.

### Root cause

Provider status semantics and provider event semantics were conflated in the normalized model.

### Why it matters

A future real Razorpay webhook adapter could invent unsupported payment webhook events or infer refund amount from insufficient evidence.

### Fix

Refund lifecycle is no longer accepted as the current normalized payment event. The payment reducer no longer manufactures refund amount. The unused `PARTIALLY_REFUNDED` status was removed. Refunds remain first-class financial evidence and real integration must use authoritative refund/payment fields.

### Regression protection

The known fixture adapter explicitly rejects `event_kind="refunded"` in the payment-event stream.

### Metric impact

No published metric changed.

### Remaining limitation

The current normalized event fixtures are not yet the final raw Razorpay webhook adapter; production event/status mapping remains a later integration gate.

---

## F-0015 — Synthetic split-bank truth conflated standard and Instant Settlements

**Date:** 2026-08-30  
**Area:** simulator / bank proof / provider semantics  
**Severity:** high

### Symptom

The hidden financial world contained a `split_bank_credit` scenario where two distinct bank transactions reused one standard settlement UTR and their values were summed to the settlement amount. The first Gate 8 implementation accepted this as a valid split bank receipt.

### Initial assumption

Because one settlement can conceptually result in multiple observed bank credits in some payout flows, reusing the standard settlement UTR across multiple synthetic bank rows was treated as sufficient explicit binding.

### Root cause

The simulator conflated Razorpay's standard settlement entity with the separate Instant Settlement payout topology.

Razorpay documents a normal `setl_...` settlement with a UTR used to track that particular settlement in the bank account. Instant Settlements instead use a `settlement.ondemand` parent (`setlod_...`) with explicit `ondemand_payout` children (`setlodp_...`) that carry payout-level evidence and UTRs.

### Why it matters

If left unchanged, the hidden benchmark would reward the engine for accepting a provider-inaccurate identity shortcut. A model or deterministic matcher could then appear correct by summing unrelated bank transactions that happened to reuse or resemble a settlement reference.

### Fix

The standard-settlement simulator no longer contains valid split-bank truth. Its bank transactions require globally unique UTRs, and matched standard settlements have exactly one bank transaction. An `immediate_bank_credit` fixture now exercises the exact causal lower boundary instead.

Gate 8 treats multiple distinct bank transactions sharing one standard settlement UTR as `BANK_RECEIPT_CONTRADICTED` with `BANK_UTR_REUSED_ACROSS_ENTRIES` and excludes those rows from accepted bank arithmetic.

True multi-credit Instant Settlement support is deferred until the domain explicitly models `setlod` parent and `setlodp` payout identities plus payout-level UTR evidence.

### Regression protection

- hidden-world validation rejects bank-UTR reuse for standard settlement truth;
- `test_standard_settlement_bank_utrs_are_unique_transactions`;
- `test_immediate_bank_credit_respects_exact_lower_causal_boundary`;
- `test_two_distinct_bank_transactions_reusing_standard_settlement_utr_are_contradicted`.

### Metric impact

No final benchmark had been published, so no external metric was withdrawn. The earlier passing development test that accepted split standard-settlement rows is intentionally superseded and preserved in git history.

### Remaining limitation

Instant Settlement reconciliation is not implemented. It requires a separate provider-specific adapter/proof for `setlod`/`setlodp` entities and cannot be inferred from arbitrary bank-row grouping.

---

# Failure categories still targeted deliberately

These are test targets, not claimed failures:

- settlement debit/credit sign mistakes in the real Razorpay adapter;
- same-amount bank ambiguity;
- exact UTR with wrong amount;
- explicit Instant Settlement `setlod`/`setlodp` payout reconciliation;
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
- crash/restart idempotency;
- production webhook signature/authenticity validation.
