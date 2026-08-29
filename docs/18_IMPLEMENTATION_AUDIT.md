# ReFlow Gates 0–6 Implementation Audit

**Audit date:** 2026-08-29  
**Scope:** repository foundation, domain contracts, hidden-world simulator, corruption engine, deterministic fixture adapters, raw evidence journal, payment reducer and Money Graph.

This document records implementation corrections discovered after the first Gates 0–6 build. Where this audit conflicts with an earlier planning document, this audit describes the implemented safety boundary that later phases must follow.

---

## 1. Audited ingestion order

The earlier architecture used the phrase **Immutable Canonical Journal** after the source adapters. The line-by-line review showed that this order is unsafe if malformed evidence must remain auditable.

The audited pipeline is:

```text
Raw merchant / Razorpay / bank evidence
                ↓
Append-only Raw Evidence Journal
                ↓
Deterministic Source Adapter
                ↓
Canonical Financial Objects
                ↓
Temporal Payment Reducer
                ↓
Money Graph
                ↓
Settlement Composition Proof
                ↓
Bank Receipt Proof
```

### Why raw evidence is journaled first

Canonical validation is intentionally strict. A source row can contain a malformed date, renamed column, wrong unit or invalid sign and still be important audit evidence. Therefore adapter rejection cannot be allowed to erase the original row.

`SourceEnvelope` is a raw-evidence contract, not a promise that every source field has already been semantically validated. It preserves:

- source kind;
- stable source record identity or deterministic fallback identity;
- immutable raw payload;
- deterministic payload SHA-256;
- local aware `received_at`;
- source `occurred_at` when it can be safely parsed, otherwise `None`;
- source schema/version label.

Canonical models remain stricter. For example, canonical payment events require valid timezone-aware source timestamps and reject impossible chronology.

---

## 2. Gates 0–6 status after audit

### Gate 0 — repository constitution

Passing:

- one-command validation;
- GitHub Actions CI;
- Ruff;
- strict mypy;
- pytest/Hypothesis;
- explicit engineering constitution and non-claims.

### Gate 1 — financial contracts

Passing with audit hardening:

- signed integer paise;
- explicit INR currency;
- typed IDs with non-empty typed suffixes;
- timezone-aware canonical timestamps;
- deep immutable raw evidence payloads;
- source hash integrity.

### Gate 2 — hidden financial world

Passing after causality corrections:

- arithmetic conservation;
- unique event/recon/entity identities;
- valid references;
- recon/economic movements occur before settlement processing;
- bank credits occur after settlement processing;
- bank UTR consistency in hidden truth;
- real cross-period refunds reference a prior-period payment;
- high-cardinality event timing remains causal.

### Gate 3 — corruption engine

Passing:

- deterministic corruptions by seed;
- hidden truth remains separate and immutable;
- malformed/schema/unit/sign/UTR/bank/outage/prompt-like cases remain available as observed evidence.

### Gate 4 — deterministic known-fixture adapters

Passing for the **normalized synthetic fixture schemas**.

This is an important boundary: the current recon adapter is not yet the production Razorpay Settlement Recon adapter. The later real Razorpay adapter must normalize the API's authoritative debit/credit semantics into ReFlow's signed canonical `settlement_effect` and prove that conversion against real fixtures.

### Gate 5 — raw journal + temporal state

Passing after the audit reopened the gate:

- raw evidence is journaled before adapters;
- malformed raw evidence is retained;
- replaying unchanged source records is idempotent;
- changed raw payload under the same source identity fails closed;
- duplicate provider events are compared by source facts, not local retry receipt time;
- arrival order does not define payment truth;
- failed→captured remains a supported contradictory observation sequence whose final truth is captured with a warning.

The journal is still in-memory; durable crash/restart persistence is explicitly not claimed.

### Gate 6 — Money Graph

Passing after provenance topology correction:

- order→payment identity comes from the validated payment reducer rather than raw event voting;
- contradictory order identity fails closed;
- recon entries are first-class graph nodes;
- graph exposes `entity_has_recon_entry` and `recon_entry_contributes_to_settlement` separately;
- duplicate recon evidence therefore remains visible to graph metrics and later proof logic;
- clean hidden worlds produce exact graph edge precision/recall under the current synthetic evaluator;
- missing evidence reduces recall rather than encouraging invented links.

No final benchmark claim is made from these development tests.

---

## 3. Audit failures that changed the design

The full reproducer/fix history is preserved in `FAILURE_LOG.md`. The most consequential findings were:

1. cross-period refund truth violated causality;
2. frozen source envelopes contained mutable nested evidence;
3. webhook retries could conflict solely because local receipt time changed;
4. Money Graph topology hid duplicate recon evidence from its own scorer;
5. refund fixture validation was weaker than the fixture contract;
6. high-cardinality timestamps could cross settlement processing time;
7. typed IDs accepted a bare prefix;
8. the append-only journal was not actually in the ingestion path.

No published benchmark number had to be withdrawn because the final benchmark has not started.

---

## 4. Source semantics boundary for the real Razorpay adapter

ReFlow's canonical model deliberately separates **raw provider representation** from **signed economic meaning**.

The normalized synthetic recon fixture contains fields such as:

```text
gross_amount_paise
fee_paise
tax_paise
settlement_effect_paise
```

A real Razorpay adapter must not assume that this synthetic shape is the provider API. It must translate authoritative Razorpay Recon fields such as debit, credit, amount, fee and tax into one canonical signed effect using source-specific, fixture-tested rules.

The same rule applies to refunds: generic full-refund payment evidence must not be used to invent a partial refund amount. Partial refund amount/state must come from authoritative refund/payment evidence.

---

## 5. Requirements imposed on Phase 7

The settlement composition engine may begin only under these rules:

- a settlement is proved from canonical evidence, never simulator truth;
- every recon component used in arithmetic has a provenance path through the Money Graph;
- duplicate economic evidence is a contradiction, not another amount to sum;
- duplicate detection must use economic identity independent of `recon_id`;
- same-amount settlements remain independent partitions;
- all arithmetic uses signed integer paise;
- a zero residual does not override an identity/provenance contradiction;
- composition proof is separate from bank receipt proof.

Recommended first proof states:

```text
COMPOSITION_PROVEN
COMPOSITION_RESIDUAL
COMPOSITION_INCOMPLETE
COMPOSITION_CONTRADICTED
```

A composition-proven settlement is **not** fully reconciled until Phase 8 independently proves bank receipt.

---

## 6. Requirements imposed on Phase 8

The first bank proof should be intentionally conservative.

Strong normal-case identity:

```text
exact settlement UTR
AND exact expected amount
AND valid currency/source partition
AND admissible temporal relationship
```

Split-credit proof may sum multiple bank credits only when source evidence binds every component to the settlement.

The following must not auto-prove identity:

```text
same amount + approximately same date
```

Exact UTR with the wrong amount is a contradiction/residual, not a successful match. Missing/corrupted UTR should fail closed unless another authoritative source identifier genuinely establishes identity.

Bank narration is supporting/untrusted text and cannot independently authorize reconciliation.

---

## 7. Requirements imposed on Phase 9

A full reconciliation proof requires independent composition and bank fragments. Proof versions must be immutable.

Late evidence must create a new proof version and preserve the old one. A late bank credit should not rewrite historical knowledge; it should change the current proof from waiting-for-bank to proven while retaining the earlier proof version.

Residual and exception objects remain first-class results rather than error strings.

---

## 8. Gate to continue

The next implementation branch may start Phases 7–9 only after:

- the final PR #2 head passes Ruff, strict mypy and pytest;
- the audit findings above are checked in;
- the PR description reflects the audited architecture;
- PR #2 is merged before creating the proof-engine branch.

This preserves the repository history as a sequence of proven financial invariants instead of one unreviewable feature dump.
