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

## F-0016 — Reused settlement UTR still attributed the same bank transaction twice

**Date:** 2026-08-30
**Area:** bank proof / identity attribution  
**Severity:** safety-critical

### Symptom

An intermediate Gate 8 version correctly marked two settlement entities that reused one UTR as `BANK_RECEIPT_CONTRADICTED`, but each proof could still contain the same matching bank row in `bank_entry_ids` and count its amount as observed accepted bank credit.

### Initial assumption

A contradicted status was assumed to be enough to prevent downstream misuse of the bank relationship.

### Root cause

Proof status and proof attribution were treated as separate concerns. The status failed closed, but the proof payload still represented the ambiguous relationship as accepted evidence.

### Why it matters

Gate 9 or an operator UI could accidentally treat `bank_entry_ids` as an attribution graph even while the proof status was red, causing one bank transaction to appear owned by two settlements.

### Fix

Settlement-UTR ambiguity now makes bank identity non-attributable. Affected proofs preserve the raw source envelopes and contradiction reason, but `bank_entry_ids == ()` and `observed_bank_credit == 0` until identity is unambiguous.

### Regression protection

`tests/core/test_bank_proof_identity_regression.py::test_reused_settlement_utr_does_not_attribute_one_bank_row_to_two_settlements` plus assertions in the main Gate 8 suite.

### Metric impact

No published metric changed.

### Remaining limitation

Gate 9 must continue treating accepted attribution fields as proof-state-dependent rather than merely checking whether an evidence row exists.

---

## F-0017 — Same-amount diagnostics could make Gate 8 proof payloads approach quadratic growth

**Date:** 2026-08-30
**Area:** bank proof / scale  
**Severity:** high

### Symptom

The first conservative same-amount implementation preserved every later bank row with the same amount but a non-matching UTR as a rejected candidate ID and source envelope inside each settlement proof.

### Initial assumption

Keeping all rejected fuzzy candidates directly in the proof object was considered the most auditable design.

### Root cause

Non-identity investigation evidence was mixed into the authoritative proof payload. At a common price point, many settlements could each copy nearly the same large candidate set.

### Why it matters

A merchant with thousands of repeated amounts could drive proof output size and matching work toward quadratic growth even though same amount can never establish identity in Gate 8.

### Fix

The batch proof path now indexes exact UTR candidates and `(amount, currency)` counts. Authoritative proofs retain exact-UTR source evidence only and expose `same_amount_nonidentity_count` as a bounded diagnostic scalar instead of embedding fuzzy row IDs. Investigation layers can query non-identity rows separately when needed.

### Regression protection

`tests/core/test_bank_proof_scale_shape.py::test_common_amount_volume_does_not_embed_all_fuzzy_candidates_in_each_proof` forces 1,000 settlements to a common observed amount and verifies bounded proof source/identity payloads.

### Metric impact

No throughput claim had been published. This is a structural complexity hardening, not a benchmark result.

### Remaining limitation

Final throughput, memory and maximum-volume claims still require the dedicated benchmark harness and measured runtime data.

---

## F-0018 — Valid low-cardinality world configuration could create a non-positive cross-period settlement

**Date:** 2026-08-30
**Area:** simulator / evaluation  
**Severity:** high

### Symptom

The 1,000-settlement common-amount stress test used the valid configuration `min_payments=max_payments=high_cardinality_payments=1`. World generation failed before Gate 8 ran with `AssertionError: generator produced non-positive settlement`.

### Initial assumption

Bounding a refund only by the source payment amount was assumed to be enough to preserve valid settlement truth.

### Root cause

A cross-period refund references a prior payment. With only one small payment in the current settlement period, the refund from a much larger prior payment could exceed the current period's positive settlement composition even though the refund itself was valid relative to the original payment.

### Why it matters

`WorldConfig` explicitly accepts one-payment settlements. A supposedly valid configuration that cannot always generate valid hidden truth makes scale experiments seed-dependent and could silently bias evaluation toward easier cardinalities.

### Fix

Synthetic refund generation now also respects the current settlement's positive capacity. The refund remains bounded by the source payment and the synthetic ₹250 cap, but is additionally capped so the current settlement retains at least one paise of positive composition under the current positive-settlement domain contract.

### Regression protection

`test_low_cardinality_world_keeps_cross_period_refund_settlement_positive` regenerates the exact 1,000-settlement one-payment configuration that failed and validates the complete world. The unchanged Gate 8 common-amount stress fixture then runs on that world.

### Metric impact

The failed CI run had Ruff and strict mypy green with 106 tests passing and only this new stress test blocked in world generation. No external benchmark number had been published. After the generator fix, the exact configuration and full suite pass.

### Remaining limitation

The simulator currently models positive standard settlement entities. If zero/negative settlement behavior becomes a real target, it must be introduced as an explicit provider-backed domain case rather than reached accidentally through generator arithmetic.

---

## F-0019 — Conflicting raw source version was detected but not retained

**Date:** 2026-08-30
**Area:** source journal / evidence integrity
**Severity:** high

### Symptom
The journal raised on a stable source identity arriving with a different payload, but the conflicting second payload was not retained.

### Root cause
Conflict detection and append-only evidence retention were treated as the same operation; the exception happened before the conflicting evidence entered the retained record set.

### Fix
The journal now preserves every distinct immutable payload version before failing closed. The first version remains the primary lookup; exact replay of the same conflicting version does not create unbounded duplicate records.

### Regression protection
`tests/core/test_journal.py` and `tests/ingestion/test_pipeline.py` verify both retention and repeated-conflict idempotency.

---

## F-0020 — Payment reducer conflated delivery reordering with impossible source chronology

**Date:** 2026-08-30
**Area:** payment state reduction
**Severity:** high

### Symptom
A payment containing `CAPTURED` at an earlier semantic event time and `FAILED` at a later semantic event time still reduced to captured simply because capture evidence existed.

### Root cause
The reducer was intentionally delivery-order invariant but did not distinguish transport order from normalized financial event chronology.

### Fix
`failed -> captured` remains valid regardless of delivery order. A normalized failed event whose `occurred_at` is later than capture is now contradictory and fails closed.

### Regression protection
`tests/core/test_payment_state.py::test_failed_evidence_after_capture_is_rejected_independent_of_delivery_order`.

---

## F-0021 — Raw source links did not bind canonical financial values

**Date:** 2026-08-30
**Area:** ingestion / provenance
**Severity:** safety-critical

### Symptom
A journal-backed canonical object could theoretically be replaced with altered financial values while continuing to cite otherwise valid raw `SourceEnvelopeId`s.

### Root cause
Provenance proved that a raw envelope existed, but not that the complete canonical batch still matched the exact canonical facts and `SourceLink`s that had been compiled together.

### Fix
Journal-backed `CanonicalBatch` objects now require a deterministic compilation SHA-256 over canonical financial facts plus exact source links. Any post-compilation fact/link change fails before Money Graph or proof construction.

### Regression protection
`tests/ingestion/test_pipeline.py::test_journal_backed_canonical_values_cannot_change_under_old_source_binding` plus graph/proof tamper regressions.

---

## F-0022 — Exact source replay was canonicalized repeatedly downstream

**Date:** 2026-08-30
**Area:** ingestion / idempotency / complexity
**Severity:** medium

### Symptom
The raw journal correctly recognized exact replay, but the ingestion path still passed duplicate raw rows into canonicalization. Reducer/graph/proof layers therefore repeated defensive deduplication work.

### Root cause
Replay detection stopped at the journal API instead of becoming the canonicalization boundary.

### Fix
After journal validation, canonicalization now uses one retained primary raw payload per stable source identity. Distinct source IDs that represent duplicate economic evidence remain separate and are still caught by Gate 7/8.

### Regression protection
`tests/ingestion/test_pipeline.py::test_exact_source_replay_is_canonicalized_once_after_journaling` and existing replay/idempotency proof tests.

---

## F-0023 — Synthetic scenario class leaked through fixed settlement position

**Date:** 2026-08-30
**Area:** simulator / benchmark fairness
**Severity:** high

### Symptom
Scenario type was a fixed function of settlement index, so the same positional IDs implied the same anomaly family across seeds.

### Root cause
Coverage scheduling and fixture identity were coupled.

### Fix
Scenario coverage remains deterministic but scenario positions are shuffled by world seed. Required dependency cases are prevented from occupying an invalid first position.

### Regression protection
`tests/simulator/test_truth_world.py::test_scenario_positions_change_by_seed_without_losing_coverage`.

---

## F-0024 — “Wrong recon amount” corruption failed at the adapter instead of Gate 7

**Date:** 2026-08-30
**Area:** simulator / evaluation semantics
**Severity:** medium

### Symptom
`WRONG_RECON_AMOUNT` changed only `settlement_effect_paise`, breaking the normalized row's own arithmetic. The adapter rejected it, so the settlement proof never saw a plausible but financially wrong record.

### Root cause
Schema-integrity corruption and financial-mismatch corruption were conflated.

### Fix
The corruption now changes a payment row's gross and settlement effect together by the same paise delta, preserving row arithmetic while making the settlement total wrong. Gate 7 must therefore emit an explicit composition residual.

### Regression protection
`tests/core/test_settlement_proof.py::test_well_formed_wrong_recon_amount_reaches_proof_as_residual`.

---

## F-0025 — Narrow proof helper seams could omit batch-global safety context

**Date:** 2026-08-30
**Area:** Gate 7 / Gate 8 API architecture
**Severity:** high

### Symptom
Single-settlement helper functions could be called without the global economic-ownership or settlement-UTR-reuse information computed by the safe batch APIs.

### Root cause
Low-level test seams looked like supported orchestration APIs and supplied permissive defaults.

### Fix
The per-settlement helpers are private and require explicit global context. Public exports expose only `prove_all_settlement_compositions` and `prove_all_bank_receipts`. Gate 9 is required to consume those batch-safe outputs.

---

## F-0026 — Production-facing ingestion depended structurally on the simulator package

**Date:** 2026-08-30
**Area:** architecture / package boundaries
**Severity:** medium

### Symptom
`reflow.ingestion` imported `ObservedBatch` / `RawRecord` from `reflow.simulator.observed` even though hidden truth itself was not imported.

### Root cause
A neutral pre-canonical transport type was originally created inside the simulator for convenience and later reused by ingestion.

### Fix
The neutral transport contract now lives in `reflow.ingestion.records`. The simulator imports that contract; ingestion no longer depends on `reflow.simulator`.

### Regression protection
Repository dependency scans in the pre-Gate-9 audit require zero simulator imports under `src/reflow/ingestion`.

---

## F-0027 — Canonical compilation identity depended on source row order

**Date:** 2026-08-30
**Area:** provenance / future proof versioning
**Severity:** high

### Symptom
Two batches containing identical source facts in different row orders could produce different canonical compilation SHA-256 values.

### Root cause
The digest streamed canonical tuples in incoming order rather than stable source identity order.

### Fix
Each canonical source family and `SourceLink` set is sorted by stable identity before feeding the compilation digest. Delivery permutation no longer creates a different compilation identity.

### Regression protection
`tests/ingestion/test_pipeline.py::test_compilation_digest_is_invariant_to_source_row_order`.

---

## F-0028 — Canonicalization could read caller rows instead of retained journal evidence

**Date:** 2026-08-30
**Area:** ingestion / end-to-end provenance
**Severity:** safety-critical

### Symptom
The journal-first path stored immutable source envelopes, but after journaling it canonicalized the original in-memory caller batch. The later compilation digest bound canonical facts to source links, yet the compilation step itself was not forced to read the retained envelope payloads.

### Root cause
Journaling and canonicalization were sequenced correctly but still shared the caller's source object rather than making the journal the literal read boundary.

### Fix
After journaling, ingestion reconstructs the canonical input from the journal's retained immutable primary payload for every stable source identity. The source-binding method is private, and an end-to-end test recompiles every canonical fact directly from its retained envelope.

### Regression protection
`tests/ingestion/test_pipeline.py::test_each_canonical_fact_recompiles_from_its_retained_raw_envelope` plus exact-replay and compilation-integrity tests.

### Remaining limitation
The in-memory journal is an integrity reference implementation, not authenticated production storage. Provider webhook signatures/API authentication, persistence and ingress quotas remain future integration requirements.

---


## F-0029 — Batch-global contradictions omitted counterparty raw evidence

**Date:** 2026-08-30
**Area:** Gate 7 / Gate 8 provenance
**Severity:** high

### Symptom
A proof could report a cross-settlement economic-identity or reused-settlement-UTR contradiction while citing only the current settlement's evidence, not the other raw record that made the contradiction true.

### Root cause
Batch-global conflict detection returned conflict flags/IDs but did not propagate the counterparty source envelopes into each affected proof fragment.

### Fix
Gate 7 now cites all recon source envelopes participating in a cross-settlement economic claim. Gate 8 now cites the other settlement source envelopes when a UTR is reused.

### Regression protection
The cross-settlement composition and reused-UTR bank-proof tests require both affected proofs to carry the counterparty raw evidence.

---

## F-0030 — Gate 9 ledger update was not atomic

**Date:** 2026-08-30
**Area:** Gate 9 proof ledger
**Severity:** safety-critical

### Symptom
An early Gate 9 implementation appended proof versions settlement-by-settlement. A later validation failure could leave earlier settlements committed from a rejected batch.

### Root cause
Validation and mutation occurred in the same loop.

### Fix
Gate 9 now validates and stages every new proof version first, then mutates the append-only ledger only after the whole batch succeeds.

### Regression protection
A batch with a deliberately invalid final settlement must leave the proof ledger completely unchanged.

---

## F-0031 — Batch compilation hash could outrun the declared knowledge cutoff

**Date:** 2026-08-30
**Area:** Gate 9 temporal provenance
**Severity:** high

### Symptom
A settlement proof could cite only evidence received before its cutoff while also recording a global batch compilation SHA that included unrelated evidence received after that cutoff.

### Root cause
The first cutoff check covered settlement-scoped cited evidence but not every source envelope represented by the recorded batch compilation.

### Fix
Gate 9 now requires every source envelope in the canonical batch to have `received_at <= knowledge_cutoff` whenever that batch SHA is recorded in a proof version.

### Regression protection
A future unrelated bank row in the batch causes Gate 9 to reject an earlier knowledge cutoff even when that row does not version the settlement's scoped financial truth.

---

## F-0032 — Full proof metadata was not fully self-verifying

**Date:** 2026-08-30
**Area:** Gate 9 proof integrity
**Severity:** high

### Symptom
A reconstructed full proof could retain a valid-looking deterministic ID while carrying altered ruleset metadata, source-union metadata, or a stale settlement-scoped hash.

### Root cause
The first `ReconciliationProofVersion` constructor validated status/reasons/ID shape but trusted some metadata fields supplied by the caller.

### Fix
The proof now recomputes the authoritative source-envelope union and settlement-scoped input SHA from its embedded Gate 7/8 fragments, verifies all Gate 7/8/9 ruleset version strings, and re-derives its deterministic `proofv_...` identity.

### Regression protection
Direct replacement/forgery tests cover ruleset metadata, source-union metadata, scoped hash, typed proof IDs, backward cutoff, and backward generation time.

---

# Failure categories still targeted deliberately

These are test targets, not claimed failures:

- settlement debit/credit sign mistakes in the real Razorpay adapter;
- same-amount bank ambiguity beyond the current exact-UTR proof boundary;
- exact UTR with wrong amount in real provider fixtures;
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

---
