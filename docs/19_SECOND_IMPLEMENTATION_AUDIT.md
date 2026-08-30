# Second Independent Implementation Audit — Gates 0–7

**Date:** 2026-08-29  
**Branch:** `build/phase-7-9-proof-engine`  
**Base audited:** `main` after PR #2 merge (`c58c186c98a34906464d429391bac8ed0b7d9c9d`)

## Why a second audit exists

PR #2 was already reviewed line by line and fixed eight genuine problems before being merged. Before allowing that foundation to support settlement proofs, we intentionally performed a second review that did **not** assume the first audit was correct.

This pass re-read the merged Gates 0–6 and then attacked the new Gate 7 implementation against the same financial invariants.

The second audit found additional real defects. That is not treated as an embarrassment to hide: it is evidence that the repository's gates are doing useful work before benchmark claims or AI are added.

---

## Audited deterministic pipeline

```text
raw source evidence
        ↓
append-only Raw Evidence Journal
        ↓
SourceEnvelope
(payload ↔ SHA-256 ↔ deterministic src_ identity)
        ↓
deterministic normalized fixture adapters
        ↓
CanonicalBatch + immutable raw SourceLinks
        ↓
Temporal Payment Reducer
        ↓
Money Graph
(edges cite raw src_ evidence)
        ↓
Settlement Composition Proof
(identity + arithmetic + time + provenance)
```

A later Gate 8 Bank Receipt Proof remains independent from settlement composition.

---

# Findings and repairs

## A. Canonicalization broke end-to-end raw provenance

### Finding

The first audit correctly moved the journal before adapters, but successful canonical objects were then produced separately. `CanonicalBatch` did not retain which `SourceEnvelope` produced each canonical row. Money Graph `evidence_ids` cited event/recon identifiers rather than the raw journal envelopes.

### Risk

A proof could describe canonical provenance without being able to walk all the way back to the immutable source payload that was actually journaled.

### Repair

- `CanonicalBatch` carries immutable `SourceLink` objects for successful journal-first ingestion.
- provenance identities must exactly match the canonical rows in the batch;
- `build_money_graph()` rejects adapter-only batches with no journal backing;
- authoritative graph edges cite actual `SourceEnvelopeId` values (`src_...`);
- Gate 7 proofs preserve the raw source envelope IDs used by their components.

### Regression protection

Tests prove that:

- a bare `adapt_observed_batch()` result cannot enter the Money Graph;
- graph edge evidence IDs resolve to raw journal entries;
- canonical source links exactly resolve to journal envelopes;
- a graph edge carrying the wrong raw evidence ID cannot satisfy Gate 7 provenance.

---

## B. Gate 7 duplicate detection compared values before economic identity

### Finding

The first Gate 7 implementation fingerprinted a recon row using economic values and timestamp. Two rows could therefore claim the same economic entity but differ by one paise or one timestamp and escape duplicate detection.

### Risk

Both rows could be summed, allowing contradictory evidence about one payment/refund/transfer/adjustment to contaminate settlement arithmetic.

### Repair

Rows are partitioned **first** by economic identity:

```text
(entity_kind, entity_id)
```

Then evidence is classified:

- same recon row ID + same payload → idempotent replay, collapse harmlessly;
- different recon row IDs + same economic payload → duplicate economic evidence, contradiction;
- same economic identity + differing values/time → identity conflict, contradiction.

Conflicting identities are not arbitrarily selected for arithmetic.

---

## C. Gate 7 accepted recon evidence created after settlement processing

### Finding

The initial composition proof summed a recon row even if its `occurred_at` was later than the settlement's `processed_at`.

### Risk

A mathematically exact proof could use future evidence to explain an earlier settlement.

### Repair

Such rows produce `RECON_AFTER_SETTLEMENT`, are excluded from the admissible arithmetic set, and force `COMPOSITION_CONTRADICTED`.

---

## D. One economic movement could be claimed by multiple settlements

### Finding

Per-settlement proof calls did not see that the same payment/refund/transfer/adjustment identity might appear in recon rows for two different settlement IDs.

### Risk

Two settlement proofs could both claim ownership of the same economic movement.

### Repair

`prove_all_settlement_compositions()` builds a batch-level ownership index. Any economic identity claimed by multiple settlements is contradicted in every affected proof with `ECONOMIC_ENTITY_IN_MULTIPLE_SETTLEMENTS` and is excluded from admissible arithmetic.

This is intentionally conservative for the normalized fixture contract. Real Razorpay integration must verify the exact provider identity semantics before broadening this rule.

---

## E. SourceEnvelope validated digest shape but not digest truth

### Finding

A `SourceEnvelope` required a 64-character hexadecimal `payload_sha256`, but did not verify that the digest actually represented its frozen payload.

### Risk

The repository could preserve an immutable payload next to a false but syntactically valid digest, invalidating provenance.

### Repair

One canonical deterministic JSON hashing function is shared by the journal and domain model. `SourceEnvelope` recomputes and verifies the digest after recursively freezing the payload.

---

## F. SourceEnvelope ID was only trustworthy when created through the helper

### Finding

The journal helper derived `src_...` from source kind, source record ID and payload digest, but the domain model did not verify that relationship. A manually constructed envelope could carry an unrelated valid-looking `SourceEnvelopeId`.

### Risk

A proof could cite a `src_...` identifier that was not cryptographically bound to the source facts stored beside it.

### Repair

Envelope identity derivation is centralized and checked by `SourceEnvelope` itself:

```text
source kind + source record id + verified payload SHA-256
                        ↓
                 deterministic src_ ID
```

The journal helper and domain model use the same function.

---

## G. Refund lifecycle semantics were mixed into the normalized payment-event reducer

### Finding

The canonical event enum included `REFUNDED`, and the reducer interpreted that generic event as a full refund. It also exposed an unused `PARTIALLY_REFUNDED` payment status.

### External semantics check

Razorpay documents payment entity statuses including `created`, `authorized`, `captured`, `refunded` and `failed`, but its documented payment webhook events are payment authorization/capture/failure, while refund webhooks are a separate lifecycle. Partial refunds leave the payment status captured and are represented through refund-specific fields such as `refund_status` and `amount_refunded`.

### Risk

A later real webhook adapter could accidentally invent a `payment.refunded` webhook or infer refund amount from insufficient evidence.

### Repair

- refund lifecycle is not accepted as the current normalized payment-event kind;
- the payment webhook reducer no longer manufactures refunded amount;
- the unused `PARTIALLY_REFUNDED` payment status was removed;
- Refund remains a first-class financial object/recon movement;
- the future real payment/refund adapter must use authoritative provider fields.

---

# Re-verified first-audit repairs

The second pass specifically re-checked the earlier fixes for:

- cross-period refund temporal causality;
- deep source-payload immutability;
- webhook retry receipt-time semantics;
- row-level recon graph topology;
- normalized refund recon arithmetic;
- high-cardinality event timing;
- typed ID suffix validation;
- journal-first malformed-evidence retention.

No regression was found in those repairs during this pass.

---

# Hidden-truth separation

A repository search found no production/reconciliation import of `reflow.simulator.truth`.

The current normalized evaluation transport (`ObservedBatch` / `RawRecord`) still lives under the simulator package and is imported by the fixture adapters. This is **not hidden-truth leakage**, but it is intentionally documented as a pre-production integration limitation. Real Razorpay/bank ingestion should later use integration-specific transport models.

> **Superseded on 2026-08-30 by the pre-Gate-9 audit:** the neutral transport contract was moved to `reflow.ingestion.records`; ingestion no longer depends on the simulator. The paragraph above is retained as historical audit state.

---

# Gate 7 invariants after the second pass

A settlement composition can be `COMPOSITION_PROVEN` only when all of the following hold:

1. the settlement is journal-backed;
2. every recon row is journal-backed;
3. required graph provenance edges point to the correct raw envelope;
4. every admissible component uses the settlement currency;
5. no economic identity has conflicting evidence;
6. no distinct source rows duplicate one economic movement;
7. no economic identity is claimed by another settlement;
8. no admitted recon row occurs after settlement processing;
9. exact component arithmetic equals the authoritative settlement amount;
10. no failure reason remains.

Therefore:

```text
zero residual != proof
```

A zero residual with duplicate identity, conflicting identity, wrong provenance or temporal contradiction remains non-proven.

---

# Validation status

During the audit, an intermediate Gate 7 build intentionally failed because the new Money Graph journal requirement exposed old tests that were still bypassing journal-first ingestion. The tests were corrected to exercise the production path rather than weakening the graph invariant.

Subsequent audit heads passed:

- Ruff;
- strict mypy;
- pytest.

The final branch head must remain green before this checkpoint is merged.

---

# What is deliberately still blocked

The second audit does **not** authorize moving financial truth forward by assumption.

Still blocked:

- Gate 8 Bank Receipt Proof;
- Gate 9 full Reconciliation Proof and versioning;
- residual solver;
- final benchmark and public metrics;
- AI adapter synthesis;
- AI exception investigation;
- production Razorpay adapters;
- production persistent journal;
- operator UI.

Gate 8 should begin only after the final second-audit head is green and the failure/limitations documentation matches the implementation.
