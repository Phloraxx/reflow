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

None currently known on the third whole-codebase audit branch after reproducing and fixing F-0098 through F-0112. Final PR/merge CI is still pending. Earlier audit PR #25 merged as `71ae9ad039a99b5cf06c1e71d513f99be3231687`. The frozen Gate 19 seeds, scorer and first-run v1 remain unchanged.

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

## F-0033 — Residual explanation state was implicit

**Date:** 2026-08-31
**Area:** Gate 10 safety boundary
**Severity:** high

### Symptom
The first residual-solver draft encoded “not proof” only through reason strings. A downstream caller could treat an exact arithmetic result as if it were a stronger financial state.

### Root cause
The output model lacked a typed state whose only allowed value was `HYPOTHESIS`.

### Fix
`ResidualExplanationState` now has only `HYPOTHESIS`, and every exact explanation also derives `NOT_FINANCIAL_PROOF`. Gate 10 has no API that promotes an explanation into Gate 7/8/9 truth.

---

## F-0034 — Residual candidate identity did not bind its full target and decision context

**Date:** 2026-08-31
**Area:** Gate 10 hypothesis integrity
**Severity:** high

### Symptom
Early candidate IDs were source-centric. During hardening, the same source candidate could retain identity across different target contexts, proof versions, or a changed blocked/admissible disposition.

### Root cause
The deterministic candidate hash did not initially include the complete hypothesis context.

### Fix
`ResidualCandidateId` now binds settlement, exact `ProofVersionId`, residual scope, candidate kind, source entity, amount/currency, disposition, normalized reason codes and raw source envelopes. Direct replacement of proof-version or disposition metadata invalidates the candidate identity.

---

## F-0035 — Bank evidence already identified to another settlement initially looked admissible

**Date:** 2026-08-31
**Area:** Gate 10 bank candidate enumeration
**Severity:** safety-critical

### Symptom
A bank row whose UTR already belonged to another settlement could still be surfaced as an amount-only admissible hypothesis for the current residual.

### Root cause
The first residual enumerator considered local amount fit but did not reuse batch-global settlement-UTR ownership.

### Fix
The candidate index records settlement ownership by UTR. A bank row identified to another settlement is retained only as `BLOCKED_EVIDENCE` with `BANK_ENTRY_IDENTIFIED_TO_OTHER_SETTLEMENT`; it cannot silently become an admissible explanation.

---

## F-0036 — Residual enumeration could rescan the full bank feed per target

**Date:** 2026-08-31
**Area:** Gate 10 scale shape
**Severity:** high

### Symptom
The initial candidate enumerator iterated bank/recon collections independently for each residual target, creating an avoidable residual-count × bank-row scan pattern at high volume.

### Root cause
Candidate discovery was implemented first as a per-target reference path without a reusable batch index.

### Fix
`ResidualCandidateIndex` now indexes bank amount/currency, settlement-local recon rows, UTR ownership and raw provenance once per canonical batch. `solve_all_residuals()` reuses that one index for the batch.

---

## F-0037 — Solution-cap truncation was not disclosed

**Date:** 2026-08-31
**Area:** Gate 10 search completeness
**Severity:** high

### Symptom
The solver had `max_solutions`, but returning exactly that many explanations did not explicitly tell callers that search had stopped at the configured result cap.

### Root cause
Only candidate truncation and node-budget exhaustion were represented in the result contract.

### Fix
`ResidualSolveResult.solution_limit_reached` now makes the result-cap boundary explicit. This is a completeness warning, not a claim that additional solutions definitely exist.

---

## F-0038 — Residual explanation metadata was not self-verifying

**Date:** 2026-08-31
**Area:** Gate 10 proof-carrying hypotheses
**Severity:** high

### Symptom
An explanation originally stored candidate IDs, source-envelope IDs, arithmetic and reason metadata as separate caller-supplied fields. A reconstructed object could keep a valid-looking explanation ID while drifting those fields.

### Root cause
The explanation carried references to candidates rather than the bounded candidate objects that actually generated it.

### Fix
`ResidualExplanation` now embeds its small bounded candidate tuple. Candidate IDs, explained amount, remaining residual, raw-envelope union, blocked-evidence flag and reason codes are derived properties. Constructor validation requires exact closure and target/proof-version consistency.

---

## F-0039 — Pre-settlement amount-only bank evidence could appear admissible

**Date:** 2026-08-31
**Area:** Gate 10 temporal causality
**Severity:** high

### Symptom
An unrelated positive bank row with a fitting amount but an occurrence time before settlement processing could be surfaced as an admissible residual hypothesis.

### Root cause
Gate 10 initially reused amount/currency filtering without applying Gate 8's causal lower bound to diagnostic bank candidates.

### Fix
Bank candidates occurring before the target settlement's `processed_at` are now `BLOCKED_EVIDENCE` with `BANK_CREDIT_PRECEDES_SETTLEMENT`. No arbitrary upper delay cutoff is introduced.

---

## F-0040 — Residual search could double-count duplicated or overlapping raw evidence

**Date:** 2026-08-31
**Area:** Gate 10 combination search
**Severity:** safety-critical

### Symptom
The public solver accepted duplicate candidate identities, and two distinct candidate objects that cited the same raw source envelope could theoretically be selected together and numerically double-count one piece of evidence.

### Root cause
The first bounded search assumed candidates came only from the internal enumerator rather than enforcing evidence uniqueness at the public solver boundary.

### Fix
`solve_residual()` rejects duplicate candidate identities. Combination search skips candidate sets with overlapping raw envelopes, and `ResidualExplanation` independently rejects reused raw evidence.

---

## F-0041 — Public residual solver accepted caller-constructed candidate sets

**Date:** 2026-08-31
**Area:** Gate 10 API boundary
**Severity:** high

### Symptom
The first public `solve_residual(target, candidates)` API allowed a caller to bypass canonical-batch candidate enumeration and submit handcrafted candidate objects directly. The result still could not become financial proof, but a future AI/UI caller could manufacture misleading hypothesis evidence.

### Root cause
The pure combination-search function was exposed as the supported single-residual API rather than kept as an internal solver seam.

### Fix
Public `solve_residual()` now requires the immutable `ReconciliationProofVersion`, its exact `CanonicalBatch` and the target. It derives candidates through the audited enumerator before invoking the private `_solve_candidate_set()` test seam. `solve_all_residuals()` uses the same safe path with one reusable batch index.

---

---

## F-0042 — Scorer treated settlement truth as sufficient for auto-match correctness

**Date:** 2026-08-31
**Area:** Gate 11 scorer
**Severity:** safety-critical

### Symptom
An auto-approved settlement could be counted as true merely because the settlement really reconciled, even when the candidate cited the wrong bank/recon evidence.

### Root cause
The first scorer classified settlement status rather than the candidate's exact financial proof claim.

### Fix
True auto-reconciliation now requires correct truth state, amount and semantically exact selected composition/bank evidence. Wrong identity contributes to the silent false-auto-match numerator.

---

## F-0043 — Candidate decisions could supply financial totals independently of selected evidence

**Date:** 2026-08-31
**Area:** Gate 11 candidate contract
**Severity:** high

### Symptom
A candidate could select one set of evidence while separately reporting composition/bank totals that made its residual look better.

### Fix
Candidate decisions now carry selected canonical recon/bank facts. Amounts, IDs and residuals are derived properties.

---
## F-0044 — Baseline implementations had unfair repeated full-feed scans

**Date:** 2026-08-31
**Area:** Gate 11 baseline fairness
**Severity:** high

### Symptom
B0/B1/B2 initially rescanned recon/bank collections per settlement while ReFlow already used indexed processing, making future throughput comparison structurally unfair.

### Fix
All baselines now build one-pass amount/UTR/settlement indexes before per-settlement work.

---

## F-0045 — Evaluation report fields were not fully self-verifying

**Date:** 2026-08-31
**Area:** Gate 11 metric integrity
**Severity:** high

### Symptom
Derived recall/false-match/count fields could be reconstructed inconsistently even when the underlying integer counts disagreed.

### Fix
`EvaluationReport` validates decision partitions, status totals, denominators, recall and silent-false-rate fields against its primitive counts.

---
## F-0046 — Benchmark artifacts could not independently reproduce stored metrics

**Date:** 2026-08-31
**Area:** Gate 11 reproducibility
**Severity:** high

### Symptom
The first JSON artifact stored raw decisions and reports but omitted the minimal post-run truth required to recompute scores independently.

### Fix
Artifacts now include a minimal financial truth projection plus a verifier that reconstructs candidate decisions and recomputes all reports from scratch.

---

## F-0047 — Stable evidence IDs could hide corrupted economic meaning

**Date:** 2026-08-31
**Area:** Gate 11 semantic scoring
**Severity:** safety-critical

### Symptom
A corrupted recon/bank fact could retain its original row ID. ID-only edge scoring could therefore count changed economic meaning as correct evidence.

### Fix
Candidate decisions carry selected canonical evidence objects. Semantic edge fingerprints include financially relevant normalized fields and causal validity; narration-only noise is excluded.

---
## F-0048 — Strong grouped baseline omitted deterministic identity safeguards

**Date:** 2026-08-31
**Area:** Gate 11 baseline design
**Severity:** high

### Symptom
The initial B1 grouped-exact arm could reconcile without checking duplicate economic identities, cross-settlement ownership reuse, or settlement-UTR reuse.

### Fix
B1 now applies those deterministic uniqueness checks and refuses structurally unsafe grouped matches.

---

## F-0049 — Evaluation artifact schema stored evidence references without semantic closure

**Date:** 2026-08-31
**Area:** Gate 11 artifact contract
**Severity:** high

### Symptom
The v1 artifact serialized selected evidence primarily as row IDs and independently supplied amounts, so a reviewer could not reconstruct the exact observed financial facts used by a candidate.

### Fix
`gate11-evaluation-v2` serializes selected canonical recon/bank evidence, derives decision amounts/IDs from those facts, and verifies the serialized derived totals during parsing.

---

## F-0050 — Parse success could not prove integer-looking rupee/paise semantics

**Date:** 2026-08-31
**Area:** Gate 12 adapter activation
**Severity:** safety-critical

### Symptom
A source value such as `"100"` could parse successfully under either `RUPEES_TO_PAISE` or `INTEGER_PAISE`. Sample parse success alone could therefore admit a 100x money-unit error.

### Fix
Financial controls can now independently reject unit mistakes. More importantly, first-seen AI proposals no longer auto-activate from parse success.

---

## F-0051 — Financial control totals did not prove identity/reference semantics

**Date:** 2026-08-31
**Area:** Gate 12 authorization policy
**Severity:** safety-critical

### Symptom
A proposal could map the correct amount column while swapping transaction/reference semantics. The aggregate paise total would still pass.

### Fix
A passing control total is rejection evidence, not authorization. First-seen proposals remain `NEEDS_REVIEW`; automatic activation requires deterministic canonical migration equivalence.

---

## F-0052 — Validation state was conflated with adapter authorization

**Date:** 2026-08-31
**Area:** Gate 12 lifecycle
**Severity:** safety-critical

### Symptom
The first lifecycle model allowed a sample-validation `APPROVED` state to flow too directly into `ApprovedAdapterVersion`, blurring “parses safely” with “authorized for operational use.”

### Fix
Activation now requires explicit typed approval evidence: `OPERATOR_REVIEW` or `MIGRATION_EQUIVALENCE`. Validation and authorization are separate contracts.

---

## F-0053 — Zero unsafe activations could become a vacuous benchmark result

**Date:** 2026-08-31
**Area:** Gate 12 evaluation
**Severity:** high

### Symptom
Once first-seen AI schemas were made review-only, a proposal benchmark could report zero unsafe activations simply because no case was allowed to activate.

### Fix
Gate 12 now has a separate migration benchmark that exercises the real automatic-activation path: one safe canonical-equivalent migration must activate and unsafe unit/identity migrations must be rejected.

---

## F-0054 — Adapter provider had an implicit model default

**Date:** 2026-08-31
**Area:** Gate 12 provider reproducibility
**Severity:** medium

### Symptom
The provider class embedded a default model name, making a live benchmark vulnerable to stale or silently changed model assumptions.

### Fix
Live provider use now requires an explicit model argument or `REFLOW_ADAPTER_MODEL`; artifacts record the selected model.

---

## F-0055 — Development adapter IDs leaked fixture intent

**Date:** 2026-08-31
**Area:** Gate 12 benchmark anti-leakage
**Severity:** high

### Symptom
Early development adapter IDs included labels such as `integer_rupees` or `negative_credit`, which a model could use as a shortcut.

### Fix
Provider-facing adapter IDs are neutral deterministic IDs. Descriptive case labels remain post-run benchmark metadata only.

---

## F-0056 — Normalized schema fingerprints disagreed with exact adapter lookup semantics

**Date:** 2026-08-31
**Area:** Gate 12 drift detection
**Severity:** high

### Symptom
A source key such as `Amount` could change to ` Amount ` while keeping the same normalized schema identity, even though the compiled adapter performs exact key lookup and would fail.

### Fix
Schema fingerprints now bind exact column names as well as normalized names/type families. Exact-key-breaking changes cannot be classified as `KNOWN_SCHEMA`.

---

## F-0057 — Compiler allowed overly broad source/target and constant mappings

**Date:** 2026-08-31
**Area:** Gate 12 static compiler
**Severity:** high

### Symptom
A caller/model contract could pair an incompatible source kind with a canonical record kind, and `CONSTANT` was not narrow enough to prevent invention of authoritative money/identity/time fields.

### Fix
The compiler enforces the one-to-one supported source-kind→record-kind contract and restricts constants to narrow categorical targets. Money and datetime targets require their typed transforms.

---

## F-0058 — Unknown-schema proposal path bypassed journal-first ingestion

**Date:** 2026-08-31
**Area:** Gate 12 raw evidence
**Severity:** high

### Symptom
The first proposal API profiled/modelled caller rows before they were retained as immutable source evidence.

### Fix
The supported operational API journals every unknown row first and profiles only retained payloads. Changed replay under the same raw identity is retained as conflicting evidence before failure. The pure row-level proposer is private to tests/benchmarks.

---

## F-0059 — Source lineage assumed raw source identity equalled canonical identity

**Date:** 2026-08-31
**Area:** Gate 12 / ingestion lineage
**Severity:** safety-critical

### Symptom
`SourceLink` originally assumed the raw source-record ID was the same identifier later used by the canonical financial fact. That is false for arbitrary CSV/JSON rows.

### Fix
`SourceLink` now preserves distinct raw and canonical identities while retaining the immutable envelope ID. Downstream proof APIs keep canonical-identity lookup and can still cite the original raw envelope.

---

## F-0060 — Reviewed adapters had no explicit activation/runtime bridge

**Date:** 2026-08-31
**Area:** Gate 12 integration
**Severity:** high

### Symptom
The compiler could propose/validate an adapter, but there was no explicit operator-review transition and approved runtime that converted retained unknown-source envelopes into a normal journal-backed `CanonicalBatch`.

### Fix
Gate 12 now has an explicit reviewed-approval action and approved-adapter runtime. Runtime rechecks schema fingerprint, reads retained journal payloads and emits raw→canonical source links. End-to-end tests feed those batches into the existing Money Graph/Gates 7–8.

---

## F-0061 — Validation and approval evidence were not bound to an exact adapter contract

**Date:** 2026-08-31
**Area:** Gate 12 approval integrity
**Severity:** safety-critical

### Symptom
A structurally valid validation report or approval record could theoretically be reused with another adapter version/schema.

### Fix
`SampleValidationReport` and `AdapterApprovalEvidence` now bind adapter ID, version and schema fingerprint; validation also binds record kind. `ApprovedAdapterVersion` rejects mismatched report/profile/evidence contracts.

---

## F-0062 — Migration artifact verifier had a JSON tuple/list boundary bug

**Date:** 2026-08-31
**Area:** Gate 12 benchmark reproducibility
**Severity:** medium

### Symptom
A generated migration artifact serialized tuple-based diff fields as JSON arrays, while verification compared them to freshly recomputed tuples and rejected its own valid artifact.

### Fix
Migration diff payloads use explicit JSON-native lists and the standalone generator/verifier regression now replays successfully.

---

## F-0063 — Model-bound sample rows lacked deterministic sensitive-value redaction

**Date:** 2026-08-31
**Area:** Gate 12 privacy boundary
**Severity:** high

### Symptom
Bounded sample rows were sent to the proposal transport without first masking obvious address-like identifiers, long numeric identifiers or known secret-token shapes.

### Fix
The OpenAI proposal path now redacts those obvious patterns and limits sample-string length before transport. This is explicitly a heuristic privacy layer, not a DLP guarantee. Prompt-like narration remains visible as untrusted data for injection testing.

---

## F-0064 — Adapter-store schema routing assumed one version per fingerprint

**Date:** 2026-08-31
**Area:** Gate 12 version routing
**Severity:** medium

### Symptom
A newer adapter implementation for an unchanged structural schema could create two versions with the same fingerprint, while the first store implementation treated that as an impossible ambiguity.

### Fix
Historical version lookup is explicit and preserved; schema routing selects the latest approved version for that fingerprint while older versions remain available for reproducibility. Source kind and record kind cannot change across the adapter lineage.

---

## F-0065 — Gate 13 coverage certificate trusted caller-supplied truth labels

**Date:** 2026-08-31
**Area:** Gate 13 evidence coverage
**Severity:** safety-critical

### Symptom
The first Gate 13 coverage builder accepted arbitrary `PROVEN` / residual bucket assignments from its caller and only checked that every manifest envelope appeared once.

### Root cause
Exhaustiveness and epistemic authority were conflated: exact-one-bucket coverage was enforced, but the financial meaning of the bucket was not derived from deterministic proof fragments.

### Why it matters
A caller could label unresolved canonical evidence `PROVEN`, producing a formally complete no-orphan certificate without a proof-backed justification.

### Fix
Coverage classification is now derived from the exact Gate 7/8/9 proof evidence plus canonical upstream state. Callers cannot label canonical evidence `PROVEN`; the only explicit assignment still permitted is `QUARANTINED` for retained evidence that did not canonicalize. Contradicted/residual proof evidence has conservative precedence and cannot be masked by a proven fragment. The coverage certificate binds exact proof-version IDs and self-validates its bucket summaries, orphan state, content hash and deterministic ID.

### Regression protection
`test_every_manifest_evidence_record_has_exactly_one_coverage_bucket`, `test_unclassified_relevant_evidence_becomes_orphan_and_blocks_close`, `test_noncanonical_retained_evidence_requires_explicit_quarantine`, `test_contradicted_fragment_cannot_be_masked_by_proven_fragment_coverage`, and direct certificate-tamper tests.

### Status
Resolved in Gate 13.

---

## F-0066 — Gate 13 run capsule did not require one proof per settlement

**Date:** 2026-08-31
**Area:** Gate 13 run integrity
**Severity:** safety-critical

### Symptom
The first run builder validated every supplied proof but did not require the supplied proof set to equal the canonical settlement set.

### Root cause
The implementation reused proof-integrity checks but omitted Gate 9's batch-completeness cardinality invariant at the new run boundary.

### Why it matters
A run could theoretically omit a non-green settlement proof while still binding valid coverage/balance artifacts, creating an incomplete run capsule.

### Fix
Coverage and run construction now index Gate 9 proofs against the canonical settlement set and require exact set equality: one proof per canonical settlement, with no missing, duplicate or extra settlement proof. Coverage, close readiness and the run capsule all bind the same canonical-sorted proof-version IDs. The run object self-validates its input/output hashes and deterministic content-addressed ID.

### Regression protection
Gate 13 tests reject incomplete proof sets and direct run-output tampering.

### Status
Resolved in Gate 13.

---

## F-0067 — Gate 13 row-permutation acceptance fixture was initially vacuous

**Date:** 2026-09-01
**Area:** Gate 13 test quality
**Severity:** medium

### Symptom
The first Gate 13 run-identity permutation test reversed each source tuple, but the fixture contained only one row per source. The test therefore passed without exercising a real source-row ordering change.

### Root cause
The acceptance assertion was correct, but the minimal fixture cardinality made the mutation a no-op.

### Why it matters
A green test could have overstated independent Gate 13 evidence for the required source-delivery permutation invariant. Gate 9 already had stronger permutation coverage, but Gate 13 needed its own non-vacuous run-level regression.

### Fix
The Gate 13 fixture now includes a second independent merchant row. Reversing the merchant source genuinely changes delivery order while the canonical compilation, manifest content and run identity remain deterministic.

### Regression protection
`test_source_row_delivery_permutation_does_not_change_run_identity` now runs against a multi-row source fixture.

### Status
Resolved in Gate 13.

---


## F-0068 — Gate 14 rerun fixture accidentally reused one deterministic Gate 13 run identity

**Date:** 2026-09-01
**Area:** Gate 14 test quality
**Severity:** medium

### Symptom
The first Gate 14 continuity tests changed only `completed_at` while reusing the same Gate 13 run inputs, policy, source manifests and knowledge cutoff. Gate 13 intentionally derives run identity from immutable financial inputs rather than execution timing, so the supposed “second run” had the same `ReconciliationRunId`.

### Root cause
The test fixture treated execution metadata as run identity even though Gate 13 explicitly proved that identical inputs/policy/cutoff reproduce the same run identity.

### Why it matters
A case-continuity test could have claimed cross-run behavior while actually replaying one deterministic run capsule.

### Fix
The Gate 14 rerun helper now emits a genuinely new source-delivery manifest set for the later execution while keeping the canonical economics unchanged. The second run therefore has a distinct immutable input capsule and run ID without changing the settlement tracking identity or incident semantics.

### Regression protection
The unchanged-economics, first/last-seen and out-of-order acceptance tests all use genuinely distinct Gate 13 run identities.

### Status
Resolved in Gate 14.

---

## F-0069 — Closed workflow could be reopened without an explicit REOPEN disposition

**Date:** 2026-09-01
**Area:** Gate 14 workflow lifecycle
**Severity:** high

### Symptom
After an operator `CLOSE` or `ACCEPT_OPERATIONAL_VARIANCE`, a later `ACKNOWLEDGE`, `DEFER` or source-correction disposition could derive a non-closed workflow state even though no `REOPEN` action had occurred.

### Root cause
Workflow state was folded from append-only dispositions, but the append boundary did not enforce the semantic transition rule that `REOPEN` is the only action allowed to reopen an operator-closed case.

### Why it matters
Financial truth remained unchanged, but case workflow/audit history could claim a reopened operational state without the explicit action required by the contract.

### Fix
New dispositions on an operator-closed, non-green case are rejected unless the disposition is exactly `REOPEN`. Financially reconciled or superseded cases remain closed to new workflow mutations.

### Regression protection
`test_closed_workflow_requires_explicit_reopen_before_other_status_changes` and `test_reopen_changes_workflow_only`.

### Status
Resolved in Gate 14.

---

## F-0070 — Stale prior economics could reverse a newer case supersession

**Date:** 2026-09-01
**Area:** Gate 14 case continuity
**Severity:** high

### Symptom
After a changed settlement amount/UTR created a new case and superseded the old one, applying an older run carrying the prior tracking identity could reactivate the old case and supersede the newer case in the opposite direction.

### Root cause
Chronology was enforced only inside each individual case history. The ledger did not maintain a monotonic last-observed timestamp for the scoped settlement across changes in tracking identity.

### Why it matters
Out-of-order processing could reverse economic supersession and reconnect current workflow to stale case identity/history. Gate 7–9 proof truth was not altered, but the operational audit trail would be wrong.

### Fix
Gate 14 now enforces settlement-level chronological monotonicity across all case identities and rejects reactivation of a tracking identity that has already been superseded. Run application remains staged/atomic, so a stale proof cannot partially append other cases before the failure is raised.

### Regression protection
`test_stale_prior_economic_identity_cannot_reverse_supersession` plus the atomic multi-case run regression.

### Status
Resolved in Gate 14.

---

## F-0071 — Provider recon UTR identity was discarded before Gate 7 proof

**Date:** 2026-09-01
**Area:** Gate 15 provider integration / Gate 7 identity proof
**Severity:** safety-critical

### Symptom
A provider-shaped settlement recon row could carry a `settlement_utr` different from the signed `settlement.processed` entity UTR while Gate 7 still returned `COMPOSITION_PROVEN` when the amounts summed exactly.

### Root cause
The pre-Gate-15 canonical `SettlementReconEntry` model was built for normalized synthetic fixtures and did not retain provider `settlement_utr`. Gate 7 therefore had no way to compare two authoritative Razorpay settlement identities and relied only on `settlement_id` plus arithmetic.

### Why it matters
Exact arithmetic under a contradictory provider payout identity is not proof. A real integration could otherwise present a settlement as composition-proven while its recon evidence names a different bank-transfer UTR.

### Fix
`SettlementReconEntry` now retains optional `settlement_utr`; the canonical compilation contract is bumped to `canonical-source-link-v3`; Gate 7 is bumped to `gate7-composition-v2`; and UTR-mismatched recon components are excluded from arithmetic and produce `SETTLEMENT_UTR_MISMATCH` with `COMPOSITION_CONTRADICTED`. Provider normalization preserves the raw UTR rather than discarding it.

### Regression protection
`test_recon_settlement_utr_mismatch_contradicts_existing_gate7_proof`.

### Status
Resolved in Gate 15.

---


## F-0072 — Standard settlement compiler required a provider field Razorpay does not expose

**Date:** 2026-09-01
**Area:** Gate 15 provider integration
**Severity:** high

### Symptom
The first Gate 15 `settlement.processed` compiler required `currency` inside the embedded standard settlement entity. The checked-in provider-shaped fixture had silently added `"currency": "INR"`, so the test passed even though Razorpay's documented standard settlement entity/webhook sample does not expose that field.

### Root cause
The implementation reused the intuition that every money-bearing provider entity carries its own currency. For standard settlements, the current Razorpay API/webhook contract instead exposes amount/status/fees/tax/UTR/timestamps without a settlement `currency` field.

### Why it matters
Gate 15's admission rule explicitly forbids presenting synthetic field semantics as Razorpay production semantics. A real documented settlement webhook would have failed canonicalization even though the provider evidence was valid.

### Fix
`RazorpayAccountContext` now carries the explicitly trusted settlement currency (currently INR). Standard settlement webhook/API normalization uses that account context when the provider entity omits currency and rejects a supplied currency that conflicts with context. The provider fixture no longer invents a settlement `currency` field.

For processed settlement API entities, ReFlow uses the observation `received_at` as the safe `Settlement.processed_at` fact: the API proves the entity is processed when observed, while Razorpay's `created_at` is retained/validated as provider entity timing rather than misrepresented as processing time.

### Regression protection
`test_processed_settlement_webhook_normalizes_amount_utr_and_event_time` and `test_processed_settlement_api_entity_uses_observation_time_and_retains_created_at`.

### Status
Resolved in Gate 15.

---

## F-0073 — Provider timestamp validation could bypass raw-evidence retention

**Date:** 2026-09-01
**Area:** Gate 15 raw provider provenance
**Severity:** high

### Symptom
An identity-recoverable recon item with an out-of-range integer `settled_at` failed while deriving journal metadata, before the raw provider payload was appended. The same pre-journal timestamp parsing pattern existed for signed webhook event time.

### Root cause
Optional `SourceEnvelope.occurred_at` metadata was being treated as a normalization prerequisite. That inverted Gate 15's raw-before-interpretation contract: malformed semantic time data could prevent retention of evidence whose provider identity/authenticity was already known.

### Why it matters
Malformed provider rows are often exactly the evidence an operator needs to investigate. Dropping them before the journal weakens auditability and can turn an explicit schema/provider defect into unexplained absence.

### Fix
Provider paths now derive envelope `occurred_at` with a fail-soft timestamp helper: valid timestamps become journal metadata, while malformed/out-of-range values produce `occurred_at=None`. After raw append, canonical normalization re-validates required timestamps and fails closed. Processed settlement API entities follow the same rule for provider `created_at`.

### Regression protection
`test_out_of_range_webhook_timestamp_is_retained_raw_then_rejected`, `test_out_of_range_recon_timestamp_is_retained_raw_then_rejected`, and `test_malformed_settlement_api_created_at_is_retained_then_rejected`.

### Status
Resolved in Gate 15.

---


## F-0074 — Recon semantic failure could prevent later raw rows from being journaled

**Date:** 2026-09-01
**Area:** Gate 15 provider recon ingestion
**Severity:** high

### Symptom
`compile_recon_items()` journaled and normalized one provider row at a time. If an early identity-recoverable row was semantically invalid (for example `settled=false`), normalization raised immediately and later rows from the same already-supplied recon response were never written to the raw journal.

### Root cause
Raw retention and canonical interpretation were interleaved instead of being separate phases at the provider-response boundary.

### Why it matters
One malformed transaction could turn later provider evidence into accidental absence. That violates ReFlow's raw-before-interpretation invariant and weakens source-completeness reasoning for exactly the batches most likely to need investigation.

### Fix
Gate 15 recon ingestion is now two-phase. It first scans and appends every safely identifiable row, continuing through journal identity conflicts that can themselves be retained. Only after raw retention completes does it normalize retained envelopes into canonical recon entries. A semantic failure therefore leaves the complete identifiable raw response evidence available for audit.

### Regression protection
`test_recon_batch_retains_all_identifiable_rows_before_semantic_failure` and `test_recon_identity_conflict_still_retains_later_rows_from_same_response`.

### Status
Resolved in Gate 15.

---

## F-0075 — Signed webhook schema drift could bypass the Razorpay event-envelope contract

**Date:** 2026-09-01
**Area:** Gate 15 webhook schema validation
**Severity:** high

### Symptom
A correctly HMAC-signed JSON body with a recognized `payment.captured` event and payment payload could be canonicalized even when its top-level `entity` was not `event`. The compiler also did not require the expected entity name in Razorpay's top-level `contains` declaration.

### Root cause
Webhook validation authenticated bytes and then jumped directly to event-name/payload parsing without validating the documented outer event envelope.

### Why it matters
Signature authenticity proves who signed the bytes, not that ReFlow understood the provider schema correctly. Accepting a structurally drifted signed payload risks silently interpreting a future/different Razorpay shape under old semantics.

### Fix
After raw signed evidence is retained, payment and settlement webhook compilers now require top-level `entity="event"` and the expected entity key in `contains` before canonicalization. Drift remains preserved in the journal and fails closed as an explicit provider-integration error.

### Regression protection
`test_signed_webhook_with_wrong_top_level_entity_is_retained_then_rejected` and `test_signed_webhook_with_wrong_contains_is_retained_then_rejected`.

### Status
Resolved in Gate 15.

---


## F-0076 — Gate 16 case-snapshot trace emitted noncanonical returned-reference order

**Date:** 2026-09-01
**Area:** Gate 16 tool-trace integrity
**Severity:** high

### Symptom
The first Gate 16 behavioral run caused a valid `CASE_SNAPSHOT` call to fail its own immutable `ToolTraceEntry` validation. The trace returned the observation ID and case ID in construction order rather than canonical lexical order.

### Root cause
The trace contract correctly required unique canonical-sorted returned references, but the case tool constructed its tuple without applying the same canonical ordering rule.

### Why it matters
Every valid provider investigation that touched the case snapshot was misclassified as a provider failure, and the trace could not serve as independently reproducible evidence.

### Fix
`CASE_SNAPSHOT` now canonical-sorts its returned immutable references before trace construction.

### Regression protection
`test_case_snapshot_is_bounded_and_traced`, deterministic result-identity tests, and trace reproducibility tests.

### Status
Resolved in Gate 16.

---

## F-0077 — Denied Gate 16 tool access was misclassified as provider outage

**Date:** 2026-09-01
**Area:** Gate 16 safety classification
**Severity:** high

### Symptom
A provider requesting a `SourceEnvelopeId` outside the bound Gate 9 proof produced `PROVIDER_ERROR` even though the read-only tool correctly denied and traced the request.

### Root cause
`run_investigation()` caught all provider-side exceptions in one generic provider-error branch, including `InvestigationToolError` raised by the deterministic capability boundary.

### Why it matters
A hallucinated or adversarial tool request would be reported as infrastructure failure instead of an explicit deterministic safety rejection, weakening independent evaluation of the agent.

### Fix
`InvestigationToolError` is now handled separately as `REJECTED` + `ABSTAIN`; genuine provider/transport exceptions remain `PROVIDER_ERROR` + `ABSTAIN`.

### Regression protection
`test_denied_tool_call_returns_rejected_not_provider_outage` and the denied-tool trace tests.

### Status
Resolved in Gate 16.

---


## F-0078 — Gate 16 OpenAI tool loop initially mixed `store:false` with stateful response chaining

**Date:** 2026-09-01
**Area:** Gate 16 OpenAI Responses transport
**Severity:** high

### Symptom
The first OpenAI investigation provider draft set `store=false` but used `previous_response_id` to continue after function calls. Current OpenAI guidance for stateless/Zero Data Retention Responses workflows recommends replaying the relevant returned output items instead of depending on retained response state.

### Root cause
The initial implementation copied the convenient stateful Responses chaining pattern without reconciling it with Gate 16's explicit no-storage transport posture.

### Why it matters
A production/ZDR deployment could fail tool continuation or acquire a hidden state-retention dependency that contradicts the provider privacy contract. Reasoning-model continuity also needs the relevant returned reasoning items when operating statelessly.

### Fix
Gate 16 now runs a fully stateless Responses loop: every request keeps `store=false`, asks for `reasoning.encrypted_content`, replays prior returned output items plus each `function_call_output`, repeats the safety instructions on every turn, and never uses `previous_response_id`.

### Regression protection
`test_responses_loop_uses_only_declared_read_only_tools_and_strict_output` verifies stateless replay, `store=false`, encrypted-reasoning inclusion and the absence of `previous_response_id`.

### Status
Resolved in Gate 16.

---

## F-0079 — Gate 16 transport requests retained a mutable conversation alias

**Date:** 2026-09-01
**Area:** Gate 16 provider transport integrity
**Severity:** medium

### Symptom
A fake transport that retained request payload objects observed source-tool output appearing retroactively inside the first request after later conversation items were appended.

### Root cause
The provider placed its mutable in-memory conversation list directly into every request payload instead of snapshotting the list at the transport boundary. The default HTTP transport serialized immediately, which hid the aliasing defect.

### Why it matters
Transport/evaluation traces could misrepresent what information was actually available to a model on an earlier turn, undermining prompt-injection and information-flow tests.

### Fix
Every provider request now receives a fresh list snapshot of the accumulated stateless conversation before transport invocation. Later tool results cannot mutate previously captured request payloads.

### Regression protection
`test_source_tool_output_marks_text_untrusted` verifies prompt-like source text is absent from the initial request and appears only after the explicit `source_evidence` tool call.

### Status
Resolved in Gate 16.

---


## F-0080 — Gate 16 OpenAI tool outputs exposed unnecessary external financial identifiers

**Date:** 2026-09-01
**Area:** Gate 16 model-data minimization
**Severity:** high

### Symptom
The first pushed OpenAI investigation-provider checkpoint serialized complete read-only tool DTOs into model-facing `function_call_output`. That included provider settlement IDs, settlement UTRs, source record IDs and unredacted source-text fields even though the model did not need those identifiers to propose a bounded next action.

### Root cause
Read-only capability safety was treated as sufficient provider safety. The transport reused the internal investigation view wholesale instead of defining a second, minimized model-facing projection.

### Why it matters
A read-only tool can still disclose unnecessary merchant/payment metadata to an external model provider. Gate 16 should minimize provider-visible data independently of whether the model can mutate financial state.

### Fix
OpenAI tool outputs now use explicit model-facing projections. Case/proof outputs omit external settlement identity and UTR fields; source outputs omit external source-record IDs. Untrusted source text is bounded and redacts email addresses, long numeric identifiers, known secret-token patterns and transaction-like IDs before transport. Internal case/proof/source-envelope IDs and exact typed financial facts remain available for deterministic citation/claim validation.

### Regression protection
`test_responses_loop_uses_only_declared_read_only_tools_and_strict_output` verifies case/proof external identities are absent, while `test_source_tool_output_redacts_external_sensitive_identifiers` verifies source-record/UTR omission and redaction of sensitive-looking text.

### Status
Resolved in Gate 16.

---


## F-0081 — Gate 7 provenance validation rescanned the full Money Graph per recon row

**Date:** 2026-09-01
**Area:** Gate 17 scale / Gate 7 composition execution
**Severity:** high

### Symptom
The first Oracle scale baseline made a 50-settlement clean workload (6,084 raw rows) spend 2.733 s inside the ReFlow proof core, only 18.3 settlements/s. A cProfile run attributed about 7.0 of 9.8 profiled seconds to Gate 7 composition generation and showed roughly 13.8 million `EntityId.__str__` calls. The pre-optimization 1,000-settlement clean run remained CPU-bound and had still not completed after 20m31s, at which point it was stopped and recorded only as a lower bound.

### Root cause
`_required_provenance_edges()` scanned every `MoneyGraph` edge for every recon component to rediscover two exact authoritative provenance edges. Work therefore scaled approximately with recon rows multiplied by graph edges even though the graph was immutable for the batch.

### Why it matters
The bottleneck was algorithmic waste in deterministic proof validation, not a database or infrastructure limitation. Building distributed infrastructure would have hidden the real problem while preserving poor single-process scaling.

### Fix
`prove_all_settlement_compositions()` now builds one batch-local provenance-edge index keyed by relationship/from/to identity and passes it through Gate 7 proof generation. Each recon component still requires the exact two authoritative edges, exact source-envelope evidence, `PROVEN` state and `EXACT_SOURCE_IDENTIFIER`; only lookup strategy changed. No index/cache survives the canonical batch call.

### Measured impact
On the same Oracle VM and 50-settlement clean workload, the optimized official proof pipeline measured 0.154 s / 325.43 settlements/s versus 2.733 s / 18.3 settlements/s in the original core baseline (about 17.8x faster by wall-time comparison). The optimized 1,000-settlement clean workload completed in 25.53 s total with 120,052 raw rows and a 4.17 s proof pipeline (~240 settlements/s). The old 1k run has no invented completion number; only the >20m31s lower bound is retained.

### Regression protection
Existing Gate 7 duplicate/conflict/late/UTR/provenance tests remain green, provider-shaped Gate 15 proof tests remain green, and a Gate 17 regression checks indexed lookup uses the same proof semantics without cross-batch cache state.

### Status
Resolved in Gate 17.

---


# Failure categories still targeted deliberately

These are test targets, not claimed failures:

- settlement debit/credit sign mistakes in the real Razorpay adapter;
- same-amount bank ambiguity beyond the current exact-UTR proof boundary;
- exact UTR with wrong amount in real provider fixtures;
- explicit Instant Settlement `setlod`/`setlodp` payout reconciliation;
- late source evidence reopening a proof;
- real-provider schema drift beyond the checked-in Gate 12 development corpus;
- live-model adapter inference of wrong amount units, debit/credit signs or identity fields;
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
### F-0082 — Gate 18 same-origin SPA direct navigation returned 404

- **Gate:** 18 — Operator Control Tower
- **Severity:** medium
- **Type:** product routing / deployment integration
- **Observed:** the built React UI loaded at `/`, but direct navigation to a client route such as `/exceptions?scope=...` returned HTTP 404 when served by FastAPI.
- **Cause:** Starlette `StaticFiles(..., html=True)` serves directory index files but is not a generic SPA history fallback for arbitrary non-file client routes.
- **Fix:** mount only built `/assets`, serve `/` explicitly, and add a non-API catch-all that returns the built `index.html`; unknown `/api/*` routes continue to return 404 rather than being masked by the SPA.
- **Regression:** Gate 18 API tests assert a direct client route returns the SPA shell while an unknown API route remains 404.
- **Financial truth impact:** none; read-only web routing only.
### F-0083 — Gate 18 documented `make check` assumed a `python` executable

- **Gate:** 18 — Operator Control Tower
- **Severity:** low
- **Type:** repository packaging / reviewer reproducibility
- **Observed:** the final documented-state validation failed immediately on Oracle with `make: python: No such file or directory`, even though Python 3.12 and the project venv were healthy.
- **Cause:** the Makefile hard-coded `python`; this Oracle image exposes `python3` globally and `.venv/bin/python` inside the project environment, with no global `python` alias.
- **Fix:** the Makefile now prefers `.venv/bin/python` when present and otherwise falls back to `python3`; README explicitly creates/activates `.venv` before installation.
- **Regression:** the exact `make check` reviewer command is rerun on Oracle as the final Gate 18 documented-state validation.
- **Financial truth impact:** none; build/reproducibility tooling only.

## F-0084 — Gate 19 regression campaign treated quiet pytest success as failure

**Date:** 2026-09-01
**Area:** final evaluation harness
**Severity:** medium

### Symptom

The first Gate 19 failure-campaign execution stopped at `source-late-vs-complete` even though the selected regression test itself returned exit code 0.

### Root cause

The campaign required the literal text `1 passed` in pytest output. This repository's quiet pytest configuration emits only the progress dot under `-q`, so a successful selector was incorrectly classified as failed.

### Fix

The campaign now invokes pytest with `-q -rA` and requires both exit code 0 and the exact `PASSED <node-id>` marker. A skipped or wrong selector therefore cannot be promoted to campaign success. The direct reproducer passed before this harness fix.

### Financial truth impact

None. The defect was in final regression-campaign result detection only; no proof, scorer, candidate or held-out v1 artifact changed.

## F-0085 — Generic durable artifact writes could forge the operator-facing current run

**Date:** 2026-09-02
**Area:** Gate 17 persistence / Gate 18 Control Tower
**Severity:** high

**Failure:** `ReflowApplicationService.persist_artifact()` accepted arbitrary JSON for typed finance artifact kinds. A reproduced payload copied a valid run, replaced both its embedded ID and `code_build_sha`, persisted it as a later `RECONCILIATION_RUN`, and `ControlTowerReader.overview()` displayed the forged run because currentness was inferred by maximum timestamp rather than Gate 17 `LATEST_RUN` CAS state.

**Invariant at risk:** durable/operator-facing finance state must be derived from self-validating typed artifacts; application persistence must not create financial or run truth from caller-authored JSON, and explicit current pointers must define operational currentness.

**Required fix:** keep the low-level PostgreSQL store generic, but require the public application service to accept the correct self-validating artifact type and intrinsic ID; make Control Tower current-run reads follow `LATEST_RUN`; publish the demo current run through the CAS pointer; add regressions for arbitrary run payload rejection and stale/newer unpointed artifacts.

**Financial truth impact:** the deterministic Gate 7/8/9 proof engine was not mutated. The defect could forge the read-model representation of durable/current run metadata for a caller with direct application-service write access.

## F-0086 — Evaluation Lab stopped at Gate 17 and omitted the frozen Gate 19 result

**Date:** 2026-09-02
**Area:** Gate 18 product / Gate 19 evaluation
**Severity:** medium

**Failure:** the Control Tower defaulted to `data/eval/gate17` and its Evaluation Lab understood only scale/persistence artifacts, so the final frozen held-out match/precision/recall/exception evidence was absent from the finished product UI.

**Required fix:** derive a compact self-verifying Gate 19 summary from the unchanged frozen first-run artifact, verify it against the source artifact, expose it through the read-only Evaluation API, and render it explicitly in Evaluation Lab without parsing the 47 MiB raw result on every request.

## F-0087 — Final evidence verification was not part of CI

**Date:** 2026-09-02
**Area:** CI / reproducibility
**Severity:** high

**Failure:** CI ran static checks, pytest and frontend validation but never invoked the Gate 19 held-out verifier, failure-campaign verifier, Gate 17 scale/persistence verifiers, or generated `EVALUATION.md` check. Frozen evidence could therefore drift while ordinary CI stayed green.

**Required fix:** make artifact verification a required CI step and regression-test the reviewer command contract.

## F-0088 — Test/bootstrap dependency policy allowed known-vulnerable pytest and unbounded CI resolution

**Date:** 2026-09-02
**Area:** development tooling / supply-chain reproducibility
**Severity:** medium

**Failure:** `pytest>=8.3,<9` resolved to 8.4.2, which is affected by PYSEC-2026-1845 and cannot resolve the fixed 9.0.3 release. Python dependencies were range-resolved afresh in CI while the frontend used a lockfile. CI also did not explicitly upgrade pip before installation.

**Required fix:** admit pytest 9.0.3+, add a clean checked-in CI/reviewer constraints set, pin the PEP 517 build tools, upgrade pip to a fixed modern line before dependency installation, and run the complete repository under the new toolchain before merging.

## F-0089 — `make submission-check` could silently skip PostgreSQL integration tests

**Date:** 2026-09-02
**Area:** reviewer workflow
**Severity:** medium

**Failure:** the submission command depended on ordinary pytest behavior, where PostgreSQL tests skip when `REFLOW_TEST_POSTGRES_DSN` is absent. A reviewer could receive a successful `submission-check` without exercising durability semantics.

**Required fix:** fail the submission command clearly when no test PostgreSQL DSN is configured, while preserving the lighter `make check` behavior for normal local development.

## F-0090 — Public current-pointer writes did not bind stream keys to typed artifact identity

**Date:** 2026-09-02
**Area:** Gate 17 persistence currentness
**Severity:** medium

**Failure:** after hardening typed artifact writes, `ReflowApplicationService.publish_current()` still validated the semantic stream key only for `LATEST_RUN`. A valid typed proof, case observation, adapter or investigation result could therefore be attached to an unrelated operational stream key even though the low-level artifact kind was correct.

**Invariant at risk:** operational currentness is separate from financial truth but must still be identity-coherent; `LATEST_PROOF` must key by settlement, `LATEST_CASE_OBSERVATION` and `LATEST_INVESTIGATION` by case, `LATEST_ADAPTER` by adapter identity, and scoped policy/run pointers by scope.

**Required fix:** derive the expected stream key from the typed payload (and scoped metadata for policy), reject mismatches at the public application boundary, and retain the low-level PostgreSQL store as the intentionally generic CAS primitive.

**Financial truth impact:** none directly; a malformed pointer cannot change immutable proof truth, but it can make an operational reader resolve the wrong current artifact if that reader trusts the pointer key.

## F-0091 — CI bootstrap still depended on mutable action and PostgreSQL tags

**Date:** 2026-09-02
**Area:** CI supply-chain reproducibility
**Severity:** medium

**Failure:** after pinning Python packages, CI still referenced `actions/checkout@v7`, `actions/setup-python@v7`, `actions/setup-node@v6` and `postgres:16.15-alpine` by mutable tags. Those references can resolve to different code/images without a repository diff, weakening the reviewer reproducibility claim.

**Required fix:** pin GitHub Actions to the exact commits currently resolved by their major tags and pin the PostgreSQL 16.15 Alpine service to its current OCI digest while retaining readable version comments/tags.

**Financial truth impact:** none; CI bootstrap integrity/reproducibility only.

## F-0092 — Final Evaluation card hardcoded campaign denominators in the frontend

**Date:** 2026-09-02
**Area:** Gate 18/19 read model and frontend evidence display
**Severity:** low

**Failure:** the first Gate 19 Evaluation Lab card rendered `4/4` schema fail-closed and `12/12` regression checks by hardcoding the denominators in React. The numerators came from the verified summary, but the denominator assumptions lived outside the evidence artifact.

**Invariant at risk:** the frontend may format and filter verified facts but must not invent or retain hidden evaluation facts that can drift independently of the checked artifact.

**Required fix:** include source-schema case count and failure-campaign check count in the compact Gate 19 summary, validate their partitions, and render both numerator and denominator from the API payload.

**Financial truth impact:** none; presentation/evaluation-evidence integrity only.

## F-0093 — Configurable OpenAI base URLs could send bearer credentials over insecure endpoints

**Date:** 2026-09-02
**Area:** Gate 12 / Gate 16 optional OpenAI transports
**Severity:** medium

**Failure:** both OpenAI provider classes accepted arbitrary `base_url` values while their default transport sends `Authorization: Bearer <api_key>` through `urllib.request.urlopen()`. A caller could therefore configure a plaintext HTTP or malformed/custom endpoint and expose provider credentials outside the intended TLS boundary.

**Invariant at risk:** optional AI providers have no financial authority, but their credentials and bounded source context must still use a secure transport boundary.

**Required fix:** require an absolute HTTPS base URL with a hostname, reject embedded URL credentials/fragments, refuse HTTP redirects in the default transport so bearer headers cannot be forwarded by urllib, and regression-test both the adapter-proposal and exception-investigation providers. Custom transport code remains caller-owned but receives only a validated endpoint configuration.

**Financial truth impact:** none; provider transport/credential security only.

## F-0094 — Public `service.journal` leaked the concrete PostgreSQL store and bypassed typed artifact writes

**Date:** 2026-09-02
**Area:** Gate 17 application-service capability boundary
**Severity:** high

**Failure:** `ReflowApplicationService.journal` was annotated as the narrow `Journal` protocol but returned the concrete `PostgresApplicationStore`. At runtime, callers could therefore reach `put_artifact()`, `advance_pointer()` and `publish_artifact_and_pointer()` through the public property and bypass the typed/self-validating application artifact boundary introduced for F-0085.

**Invariant at risk:** the public application service must not expose generic SQL/artifact/currentness mutation capabilities merely through a wider concrete object hidden behind a protocol annotation.

**Required fix:** return a concrete narrow Journal façade that delegates only append/get/get-by-id/entries/length raw-evidence operations, and regression-test the runtime public capability surface rather than relying on static typing.

**Financial truth impact:** the deterministic proof engine was unchanged, but the capability leak re-exposed the same durable/operator-facing artifact forgery class to any caller holding the public `journal` property.

## F-0095 — Direct proof reads trusted caller-supplied storage scope instead of run membership

**Date:** 2026-09-02
**Area:** Gate 17 persistence / Gate 18 Control Tower scope isolation
**Severity:** high

**Failure:** `ReconciliationProofVersion` is financially self-validating but intentionally has no intrinsic reconciliation `scope_id`. The application service accepted caller-supplied proof scope metadata, and `ControlTowerReader.proofs()` / `proof_detail()` trusted that storage scope directly. A valid proof could therefore be relabelled into an unrelated scope and appear in direct proof browsing even though no reconciliation run in that scope referenced it.

**Invariant at risk:** a proof may be visible inside a reconciliation scope only when its cited evidence belongs to that scope and a typed reconciliation run in that scope references the proof version. Storage metadata alone is not financial provenance.

**Fix:** application proof writes now require every cited raw evidence ID to be covered by typed source-delivery manifests already persisted for the supplied scope. Control Tower proof browsing independently derives the allowed proof ID set from typed reconciliation runs in the requested scope and rejects orphan/unreferenced proofs.

**Regression:** PostgreSQL persistence rejects a valid proof relabelled into a scope with no matching scoped manifest evidence; Control Tower hides and rejects a same-scope stored proof that no scoped run references.

**Financial truth impact:** Gate 7/8/9 proof semantics were unchanged. The defect affected durable scope metadata and operator-facing proof visibility.

## F-0096 — Default OpenAI transports had no HTTP response byte ceiling

**Date:** 2026-09-02
**Area:** Gate 12 / Gate 16 optional OpenAI transports
**Severity:** medium

**Failure:** both default OpenAI transports called `response.read()` without a byte limit. Logical model/tool outputs were bounded, but a malformed or hostile endpoint could still return an arbitrarily large HTTP body and consume memory before JSON/schema validation.

**Invariant at risk:** optional model integrations must fail closed under bounded resource use; model transport failure must not become an unbounded memory path.

**Fix:** shared transport security now reads at most 1 MiB plus one sentinel byte and rejects oversized bodies before JSON decoding. Both provider-specific transports convert that failure into their existing non-authoritative provider-error paths.

**Regression:** exact-limit bodies are accepted and one-byte-oversized bodies are rejected; the complete Gate 12/Gate 16 provider suites remain green.

**Financial truth impact:** none; transport resource safety only.

## F-0097 — Gate 12 documented bounded model profiles but allowed unbounded sample/schema width

**Date:** 2026-09-02
**Area:** Gate 12 Source Adapter Compiler
**Severity:** medium

**Failure:** `profile_rows()` only rejected negative `sample_limit` values. Callers could request arbitrarily many model-facing sample rows, and the structural profile accepted arbitrarily many or arbitrarily long source column names even though Gate 12 documentation explicitly described the model input as bounded.

**Invariant at risk:** AI may inspect only a finite bounded projection of retained source evidence; caller-controlled profile size must not silently defeat the bounded-agent contract.

**Fix:** model-facing profiles now allow at most 10 sample rows, 128 columns and 256 characters per column name. These bounds affect schema-understanding/model context only and do not grant the model any new parsing or reconciliation authority.

**Regression:** maximum legal samples pass; over-limit sample counts, schema width and header length fail closed, including bool/non-integer sample-limit misuse.

**Financial truth impact:** none; bounded AI input/resource semantics only.

## F-0098 — PostgreSQL duplicate raw-evidence replay disagreed with the in-memory journal

**Date:** 2026-09-03
**Area:** Gate 17 raw-evidence durability
**Severity:** medium

**Failure:** PostgreSQL compared the full reconstructed `SourceEnvelope` on duplicate replay. The stable envelope identity intentionally excludes local receipt/derived occurrence/schema metadata, so a replay of the same source record and immutable payload could conflict in PostgreSQL even though `InMemoryJournal` correctly treated it as a duplicate and retained the first observation metadata.

**Fix/regression:** PostgreSQL duplicate checks now compare only stable evidence identity plus immutable payload content and preserve the first retained metadata, matching the in-memory journal contract.

**Financial truth impact:** none; this was durability parity/idempotency, but inconsistent replay semantics could break restart/recovery workflows.

## F-0099 — Control Tower exposed exact paise values as JavaScript numbers

**Date:** 2026-09-03
**Area:** Gate 18 API/frontend exact-money representation
**Severity:** high

**Failure:** `MoneyView.amount_paise` was an integer in FastAPI JSON. Domain money is signed int64, while JavaScript numbers cannot exactly represent every int64 value. A sufficiently large exact paise amount could therefore be rounded after crossing the API boundary even though Python proof truth remained exact.

**Fix/regression:** raw paise values are serialized as base-10 strings; display strings remain presentation-only. FastAPI and React tests assert exact large-value preservation.

**Financial truth impact:** proof truth was unchanged, but operator-visible exact money could be corrupted in the browser.

## F-0100 — Raw double-slash API paths could fall through to the SPA shell

**Date:** 2026-09-03
**Area:** Gate 18 FastAPI/SPA routing
**Severity:** medium

**Failure:** the SPA fallback rejected `api/...` but did not normalize leading slashes in the captured path. A malformed path such as `//api/...` could be served the React shell instead of remaining an API 404 boundary.

**Fix/regression:** the fallback normalizes leading slashes before the API-prefix check; malformed API-like paths remain 404 while ordinary client routes still receive `index.html`.

**Financial truth impact:** none; routing/integrity semantics only.

## F-0101 — Optional OpenAI transports accepted non-finite or effectively unbounded timeouts

**Date:** 2026-09-03
**Area:** Gate 12 / Gate 16 model transport resource bounds
**Severity:** medium

**Failure:** provider constructors accepted `NaN`, infinity and arbitrarily large timeout values. HTTPS/redirect/response-size protections existed, but caller-controlled timeout values could still defeat the bounded-resource contract.

**Fix/regression:** shared transport validation requires a finite positive timeout no greater than 300 seconds; both OpenAI providers use the same validator and regressions cover NaN/infinity/over-limit values.

**Financial truth impact:** none; optional AI transport availability/resource safety only.

## F-0102 — `LATEST_PROOF` pointer namespaces could collide across reconciliation scopes

**Date:** 2026-09-03
**Area:** Gate 17 current-pointer identity / migration
**Severity:** high

**Failure:** latest-proof currentness was keyed only by settlement ID. Two reconciliation scopes can legally contain the same external settlement identifier, so operational current pointers were not scope-isolated even though proof artifacts remained scoped.

**Fix/regression:** `LATEST_PROOF` keys are now `scope_id:settlement_id`. PostgreSQL schema v2 migrates legacy v1 proof pointers in place and preserves scoped proof storage; the migration is idempotent and tested against legacy rows.

**Financial truth impact:** immutable proof truth was unchanged, but operational currentness could resolve the wrong scope's proof.

## F-0103 — Durable artifact metadata still allowed caller-controlled identity/chronology fields

**Date:** 2026-09-03
**Area:** Gate 17 typed application persistence
**Severity:** high

**Failure:** typed artifacts could still be stored with caller-supplied convenience scope/timestamps, and `ApprovedAdapterVersion` lacked a deterministic storage ID requirement. That allowed durable metadata to disagree with intrinsic typed chronology or gave callers an arbitrary adapter artifact identity.

**Fix/regression:** storage time is derived from intrinsic typed fields when one exists and conflicting overrides fail; policy/approved-adapter definitions are stored globally; approved adapters use a deterministic content-addressed artifact ID. Schema v2 migrates legacy convenience timestamps/global configuration scope without rewriting immutable payloads.

**Financial truth impact:** deterministic proof truth was unchanged, but durable/operator identity and chronology could drift from the typed artifact.

## F-0104 — A run could become current before its complete immutable dependency graph existed

**Date:** 2026-09-03
**Area:** Gate 17 current-run publication / Gate 18 overview
**Severity:** high

**Failure:** `LATEST_RUN` publication validated the typed run but did not require its policy, manifests, proofs, coverage, balance and close artifacts to already exist and agree. A pointer could therefore make an incomplete or contradictory durable packet operationally current.

**Fix/regression:** current-run publication now validates the complete persisted dependency graph and proof/manifest coverage before the transactional pointer advance. Control Tower independently rejects current control packets that disagree with run bindings.

**Financial truth impact:** proof constructors remained exact, but the operator-facing current packet could be incomplete or internally contradictory.

## F-0105 — Fixed 10k artifact scans could silently change correctness

**Date:** 2026-09-03
**Area:** Gate 17/18 scale/read integrity
**Severity:** high

**Failure:** Control Tower treated a 10,000-row artifact list as complete, and proof scope validation built source-manifest coverage from a generic list capped at 10,000. Large scopes could therefore show incomplete history or reject valid old proof evidence solely because data fell outside an arbitrary read window.

**Fix/regression:** Control Tower compares list size with an exact artifact count and fails closed with an explicit pagination/read-model requirement when history is truncated. Proof source-scope validation now uses targeted PostgreSQL manifest-coverage queries rather than a finite generic scan.

**Financial truth impact:** proof truth was unchanged; large-scope durable validation/operator visibility could become wrong due to pagination limits.

## F-0106 — Control Tower case observations were not fully rebound to their immutable run/proof/policy/source packet

**Date:** 2026-09-03
**Area:** Gate 14 persistence projection / Gate 18 Control Tower
**Severity:** high

**Failure:** low-level persisted observation JSON could disagree with its bound proof on settlement/status/reasons/amount/UTR, disagree with source manifests, use a materiality band inconsistent with the policy, drift economic identity under the same case ID, or exist without a valid scoped parent run while still being projected.

**Fix/regression:** the read model now fail-closes unless observation financial facts match the exact proof, source states exactly match the run manifests, policy/materiality agrees, run completion equals observation time, economic identity remains stable for the case, and all parent artifacts are present in the requested scope.

**Financial truth impact:** Gate 14 typed artifacts were unchanged; this closes forged/corrupted low-level durable data reaching the operator truth surface.

## F-0107 — Control Tower disposition replay accepted impossible or orphaned Gate 14 workflow history

**Date:** 2026-09-03
**Area:** Gate 14 lifecycle projection / Gate 18 Control Tower
**Severity:** high

**Failure:** the reader replayed disposition kinds but did not enforce key Gate 14 transition invariants. It could display a disposition before case creation, accept another status transition after CLOSE without explicit REOPEN, or silently ignore a disposition for a case with no observation history.

**Fix/regression:** disposition replay now requires a known case, contiguous sequence, monotonic time not predating first observation, and explicit REOPEN before any transition from an operator-closed workflow.

**Financial truth impact:** financial proof status was never changed, but operator workflow state could be impossible relative to the audited Gate 14 lifecycle.

## F-0108 — Incident-cluster projection trusted orphan references and caller-controlled storage chronology

**Date:** 2026-09-03
**Area:** Gate 14 incident clustering / Gate 18 Control Tower
**Severity:** medium

**Failure:** an incident cluster could reference a missing run/case observation, and competing clusters were ordered using artifact storage time. An old run's cluster could therefore masquerade as newest by using a later caller-supplied `observed_at`.

**Fix/regression:** clusters must bind to a real scoped run and a matching case observation in that run; one case cannot occupy multiple clusters in one run; recency is derived from immutable run completion chronology, not storage metadata.

**Financial truth impact:** none; incident grouping/operator presentation only.

## F-0109 — Investigation packets allowed temporal/citation inconsistency with their bound evidence

**Date:** 2026-09-03
**Area:** Gate 16 investigation core / Gate 18 Case File
**Severity:** high

**Failure:** Gate 16 required `as_of >= case.first_seen_at` but did not require `as_of` to be at or after the latest bound observation/proof. The Case File also could display a persisted investigation citing a source outside its exact proof packet.

**Fix/regression:** investigation construction now rejects `as_of` before the latest case observation or proof generation; the reader rejects out-of-proof citations and investigations predating their bound observation.

**Financial truth impact:** AI remained non-authoritative, but an advisory result could claim evidence/time context that did not exist at its declared investigation instant.

## F-0110 — Durable manifests/proofs did not require their raw source envelopes to exist

**Date:** 2026-09-03
**Area:** Gate 17 evidence-first persistence
**Severity:** high

**Failure:** a typed manifest could be persisted before its effective raw envelopes existed in PostgreSQL, and a proof could pass scoped-manifest coverage using manifest JSON even when the cited raw evidence was absent from the journal. After restart, the durable proof packet could therefore be non-retrievable despite claiming evidence-first retention.

**Fix/regression:** application manifest writes require every effective envelope ID to exist in the raw journal; proof writes require retained raw source IDs as well as scoped manifest coverage. Current-run publication inherits those guarantees.

**Financial truth impact:** deterministic proof computation was unchanged; this fixes durable provenance/restart completeness.

## F-0111 — Gate 16 bounded source extraction did not bound or redact field paths

**Date:** 2026-09-03
**Area:** Gate 16 model-facing source projection
**Severity:** medium

**Failure:** source text values were bounded/redacted, but recursively generated JSON paths were not. Deep structures or very long keys could inflate model context, and sensitive identifiers embedded in a JSON key could be sent to the model unredacted.

**Fix/regression:** extraction now bounds field count, collection fan-out, recursion depth, path length and value length. Model-facing paths pass through the same sensitive-data redactor as values.

**Financial truth impact:** none; optional advisory-model privacy/resource bounds only.

## F-0112 — Gate 12 could send sensitive identifiers embedded in source column names to the model

**Date:** 2026-09-03
**Area:** Gate 12 adapter proposal privacy boundary
**Severity:** medium

**Failure:** sample values were redacted, but exact column names must be preserved for adapter proposals and were transmitted unchanged. A source whose header itself contained an email/UPI-like address, credential token or long account/phone number could therefore leak that identifier into model context.

**Fix/regression:** because redacting column names would invalidate adapter semantics, the OpenAI proposal provider now refuses model transport entirely when a column name looks sensitive; deterministic/human review remains available. Ordinary schema names and existing sample-value redaction remain green.

**Financial truth impact:** none; model-facing privacy only.

## F-0113 — Schema-v1 proof-pointer migration could silently change contradictory legacy currentness

**Date:** 2026-09-03
**Area:** Gate 17 schema migration / current-pointer integrity
**Severity:** high

**Failure:** the v1→v2 migration rewrote every migratable `LATEST_PROOF` key from the referenced proof payload without first proving that the legacy v1 key actually equaled that proof's `settlement_id`. A contradictory legacy row such as `setl_wrong → proof(settlement_id=setl_actual)` was silently converted into `scope_id:setl_actual` and the database was stamped schema v2, changing operational currentness instead of failing closed on corrupt legacy state.

**Fix/regression:** schema-v1 migration now preflights each latest-proof pointer before any migration mutation. The row must reference a proof artifact with non-empty scope and settlement identity, and its legacy stream key must exactly equal the proof's settlement ID. Any disagreement aborts and rolls back the migration; regression coverage verifies the schema remains v1 and the original pointer key remains untouched. The compatibility test also verifies scoped policy/adapter cleanup, timestamp semantics, pointer generation preservation and repeat reopen/idempotence.

**Financial truth impact:** immutable proof payloads were not rewritten, but an upgrade could silently change which proof was operationally current for a settlement.

## F-0114 — Schema-v2 canonical storage metadata disagreed with its own v1 migration

**Date:** 2026-09-03
**Area:** Gate 17 schema migration / deterministic replay
**Severity:** high

**Failure:** schema-v2 migration deliberately cleared caller convenience `observed_at` values for reconciliation scopes, policies, evidence coverage, balance controls, close readiness, and approved adapters, but the current typed application write path still accepted those same caller timestamps. A database created by the actual schema-v1/base code migrated successfully, then replaying/reseeding the same deterministic artifacts under current code failed with an immutable-content conflict on the reconciliation-scope artifact.

**Fix/regression:** the typed application boundary now canonicalizes `observed_at` to `NULL` for the six artifact families that have no intrinsic domain observation time, matching the v1→v2 migration. The deterministic Control Tower demo no longer supplies misleading convenience timestamps for those artifacts. Regression coverage proves different caller timestamps replay as duplicates, and an isolated end-to-end check built a real v1 database from base `HEAD`, migrated it with current code, reseeded the same demo, reopened it, and preserved the migrated latest-proof pointer generation.

**Financial truth impact:** immutable financial payloads were unchanged, but a production upgrade could break deterministic replay/recovery immediately after migration.

## F-0115 — Schema-v1 approved-adapter identities were not canonicalized during migration

**Date:** 2026-09-03
**Area:** Gate 12 / Gate 17 adapter persistence migration
**Severity:** high

**Failure:** schema v2 requires approved adapters to use deterministic content-addressed artifact IDs, but the v1→v2 migration only cleared adapter scope/timestamp metadata. A genuine base-code v1 adapter with a caller-chosen artifact ID survived migration under that legacy ID; replaying the same typed adapter under v2 stored a second canonical artifact while `LATEST_ADAPTER` still pointed at the legacy artifact at generation 1.

**Fix/regression:** migration now verifies each legacy approved-adapter payload digest, derives the same `adapterv_<digest-prefix>` identity used by the typed v2 boundary, fails closed on incompatible canonical-ID collisions or wrong-kind adapter pointers, inserts/reuses the canonical row, rebinds current pointers without changing their generation/timestamp, and removes the obsolete caller-chosen row. Synthetic regressions and an actual base-HEAD schema-v1 database both prove replay returns `DUPLICATE` and currentness remains generation 1.

**Financial truth impact:** none to reconciliation arithmetic, but adapter operational identity/currentness could fork across an upgrade and deterministic replay was not idempotent.

## F-0116 — Missing schema metadata on a populated database was mistaken for a fresh schema-v2 database

**Date:** 2026-09-03
**Area:** Gate 17 schema initialization / migration safety
**Severity:** high

**Failure:** initialization created the schema metadata row as the current version whenever that singleton row was absent. If a populated v1 database had lost/corrupted only its metadata row, current code silently stamped it schema v2 without running v1 migrations; reproduced policy rows retained legacy scope and convenience timestamps.

**Fix/regression:** a missing metadata row is initialized only when all ReFlow data/current-pointer tables are empty. If any retained evidence, identity, artifact or current-pointer row exists, initialization fails closed and rolls back instead of guessing the schema version. Regressions cover both legitimate empty-database initialization and populated-database refusal.

**Financial truth impact:** immutable payloads were not rewritten, but silently misclassifying a populated legacy database could bypass every schema-v2 durability/currentness migration guarantee.
## F-0117 — Schema-v1 adapter migration accepted a latest-adapter pointer targeting the wrong artifact kind

**Date:** 2026-09-03
**Area:** Gate 12 / Gate 17 adapter current-pointer migration
**Severity:** high

**Failure:** the v1→v2 approved-adapter migration validated pointers that referenced approved-adapter artifacts, but it did not validate every `LATEST_ADAPTER` pointer. A legacy `LATEST_ADAPTER` row could therefore point at a different artifact kind (reproduced with a policy artifact), survive migration unchanged, and the database would still be stamped schema v2.

**Fix/regression:** adapter migration now preflights the union of all `LATEST_ADAPTER` pointers and all pointers targeting approved-adapter artifacts. Every such row must be exactly `LATEST_ADAPTER → approved_adapter`, its stream key must equal the adapter payload's `spec.adapter_id`, and any disagreement aborts/rolls back migration. PostgreSQL regression coverage verifies a wrong-kind target leaves schema version 1 and preserves the original invalid legacy row for operator repair rather than silently blessing it as v2.

**Financial truth impact:** reconciliation arithmetic is unchanged, but adapter operational currentness could otherwise reference non-adapter immutable content after an upgrade.
## F-0118 — Schema-v1 proof-pointer migration trusted proof payload content whose stored digest was invalid

**Date:** 2026-09-03
**Area:** Gate 17 schema migration / immutable proof integrity
**Severity:** high

**Failure:** v1→v2 migration derived the new scope-qualified `LATEST_PROOF` key from `payload_json.settlement_id` without first verifying that `payload_json` still matched the row's retained SHA-256. A reproduced proof row with a deliberately mismatched digest was accepted, its pointer was rewritten, and the database was stamped schema v2 even though later artifact integrity checks would reject that proof.

**Fix/regression:** latest-proof migration now performs a Python preflight over every legacy pointer, requires the referenced artifact to be a scoped proof, decodes an object payload, recomputes its canonical SHA-256 and compares it to `payload_sha256`, then requires the legacy stream key to equal the verified payload settlement ID. Any mismatch aborts and rolls back before migration mutation. PostgreSQL regression coverage verifies digest corruption leaves schema version 1 and the original pointer key untouched.

**Financial truth impact:** no proof arithmetic was recomputed, but migration previously trusted tampered/corrupt immutable proof content to establish operational currentness.
## F-0119 — Gate 12 sample redaction leaked long numeric identifiers represented as floats

**Date:** 2026-09-03
**Area:** Gate 12 model-facing adapter proposal privacy boundary
**Severity:** medium

**Failure:** sample-value redaction masked long integer identifiers and identifier-like strings, but returned all floats unchanged. A spreadsheet/CSV-style value such as `9876543210.0` therefore reached the captured model request verbatim even though the equivalent integer/string form was redacted. Non-finite floats could also enter the model prompt as non-standard JSON numeric tokens.

**Fix/regression:** Gate 12 now redacts finite float values whose magnitude has an eight-digit-or-longer integer part as `<LONG_NUMBER>` and converts non-finite floats to `<NON_FINITE_NUMBER>` before prompt serialization. A transport-level regression verifies the original long float and `Infinity` do not appear in model input.

**Financial truth impact:** none; deterministic adapter compilation and financial validation are unchanged. This closes an optional model-context privacy/serialization gap.
## F-0120 — Model-facing long-number redaction stopped at 19 digits

**Date:** 2026-09-03
**Area:** Gate 12 / Gate 16 model-facing privacy boundaries
**Severity:** medium

**Failure:** both model redactors recognized only numeric strings containing 8–19 consecutive digits. A longer identifier such as a 25-digit account/reference value bypassed redaction and was reproduced verbatim in both the Gate 12 adapter proposal prompt and Gate 16 source-evidence tool output. Integer-valued source data did not share this upper bound, making string handling inconsistent.

**Fix/regression:** both long-number matchers now redact any standalone run of eight or more digits, without an upper bound. Gate 12 and Gate 16 regressions include a 25-digit identifier and verify it never reaches model-facing text while `<LONG_NUMBER>` remains present.

**Financial truth impact:** none; deterministic financial computation is unchanged. This closes an optional model-context privacy gap.
## F-0121 — Gate 16 truncation could split a credential before redaction and leak its prefix/body fragment

**Date:** 2026-09-03
**Area:** Gate 16 model-facing source-evidence privacy boundary
**Severity:** medium

**Failure:** untrusted source strings are bounded before the OpenAI-facing redactor runs. If the value limit cut through a credential-like token, the retained fragment could fall below the redactor's eight-character token-body threshold. Reproduced evidence ended with `rzp_live_abcdefg`; that fragment was emitted unchanged to model-facing tool output even though the original full token would have been redacted.

**Fix/regression:** Gate 16's credential-pattern redactor now treats a recognized secret prefix followed by any non-empty token body as sensitive. This preserves conservative redaction even when bounding has truncated the original credential. A regression exercises the actual `_extract_untrusted_text` → model-tool-output path at the value boundary and requires `<SECRET_LIKE>`.

**Financial truth impact:** none; this is an optional advisory-model privacy boundary only.

## F-0122 — Root environment example advertised dead and misnamed runtime variables

**Date:** 2026-09-03
**Area:** configuration / operator startup contract
**Severity:** low

**Failure:** the checked-in root `.env.example` advertised `AI_API_KEY`/`AI_PROVIDER`, Razorpay credential names, `REFLOW_ENV` and `REFLOW_RANDOM_SEED`, but no production code consumed them. The optional OpenAI providers actually read `OPENAI_API_KEY` plus `REFLOW_ADAPTER_MODEL` or `REFLOW_INVESTIGATION_MODEL`. Copying the example therefore produced a misleading configuration that could not activate either model provider.

**Fix/regression:** the root example now contains only environment variables consumed by the Python runtime and names the exact OpenAI key/model variables used by both provider constructors. Frontend-only `VITE_REFLOW_SCOPE_ID` remains in `web/.env.example`. A regression asserts the root example's executable variable set exactly matches the supported Python environment contract.

**Financial truth impact:** none; deterministic reconciliation never depended on these variables. This fixes operator/configuration correctness for optional integrations and startup.

## F-0123 — Test-only HTTP client was shipped in the production web dependency extra

**Date:** 2026-09-03
**Area:** dependency surface / packaging
**Severity:** low

**Failure:** `httpx2` was declared in the runtime `web` extra even though no production ReFlow module imports it. Inspection of Starlette shows it is used by `starlette.testclient`; the serving stack (`FastAPI` + `Starlette` + `uvicorn`) does not require it. A web-only installation therefore pulled an unnecessary outbound HTTP client, `httpcore2` and `truststore` into production.

**Fix/regression:** `httpx2` moved to the `dev` extra, which is already installed by the reviewer/CI path. Focused FastAPI tests remain green, the combined `.[dev,postgres,web]` constrained install still resolves, and an `--ignore-installed` dry-run of `.[web]` confirms `httpx2`/`httpcore2`/`truststore` are absent from the runtime dependency set.

**Financial truth impact:** none; this reduces production dependency/attack surface without changing runtime behavior.
