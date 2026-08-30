# Third Independent Pre-Gate-9 Logic and Architecture Audit

**Date:** 2026-08-30
**Scope:** merged Gates 0–8 plus the `audit/pre-gate-9-independent-review` branch
**PR:** #5
**Purpose:** independently re-check the deterministic foundation before Gate 9 combines proof fragments into durable reconciliation truth.

## Audit rule

Green tests are evidence, not proof that the architecture is correct. This pass re-read the implementation as if the earlier audits were wrong.

Gate 9 remains **NO-GO** until:

- every confirmed finding is fixed or explicitly retained as a non-claim;
- living architecture/evaluation/safety docs match implementation;
- `FAILURE_LOG.md` preserves genuine failures;
- exact-head Ruff, strict mypy and pytest are green;
- hidden-truth and dependency-boundary scans are clean;
- PR #5 is mergeable and merged into `main`.

## Reviewed surface

- all files under `src/reflow/`;
- all domain, ingestion, simulator and core proof tests;
- CI workflow and Python/tooling configuration;
- README, master plan, architecture, evaluation, safety, limitations and prior audit docs;
- current Razorpay payment lifecycle and settlement/UTR semantics where a code invariant depended on provider behavior.

## Current audited trust chain

```text
normalized source records
    ↓
immutable SourceEnvelope journal
    ↓
retain malformed/conflicting raw evidence
    ↓
read canonical input FROM retained primary journal payloads
    ↓
deterministic adapters
    ↓
canonical facts + exact SourceLinks
    ↓
source-order-invariant compilation SHA-256
    ↓
Temporal Payment Reducer + Money Graph
    ↓
Gate 7 batch-wide Settlement Composition Proof
    +
Gate 8 batch-wide Bank Receipt Proof
```

Nothing after the journal is allowed to silently replace source evidence. Gate 7 and Gate 8 are independent proof fragments; neither one implies full reconciliation.

## Domain review

`Money` remains signed integer paise with an int64 bound and exact currency equality. Float/bool money is rejected. Entity IDs are typed by prefix and now reject leading/trailing or suffix-only whitespace.

The earlier unused `PaymentStatus.REFUNDED`, synthetic source kind and `PaymentCurrentState.refunded_amount` were removed because refund truth is first-class refund/recon evidence, not payment-event state.

Premature Gate 9 domain classes (`ReconciliationProof`, `ProofVersion`, `Residual`, `ExceptionCase` and their unused IDs/status enums) were removed. They predated the actual Gate 7/8 contracts and would have forced future code to fit obsolete scaffolding.

## Raw journal and hashing review

`SourceEnvelope` verifies all three parts of its integrity chain:

```text
immutable payload -> SHA-256 -> deterministic src_... identity
```

The in-memory journal keeps the first source fact as the primary canonical source version, deduplicates exact replay, and now retains a distinct conflicting payload version before raising `JournalConflictError`.

This is append-only evidence behavior, not external authenticity. The current project does **not** yet implement webhook-signature validation, API authentication, persistent journal storage, ingress byte quotas or abuse-rate controls.

## Ingestion/compiler review

The neutral `RawRecord` / `ObservedBatch` contract now belongs to `reflow.ingestion.records`; ingestion no longer imports the simulator.

Journal-first ingestion now:

1. hashes and retains every raw record;
2. fails closed on conflicting stable source identity;
3. collapses only exact replay of the same source identity;
4. reads the retained immutable primary payload back from the journal;
5. adapts that retained payload into canonical facts;
6. privately binds canonical facts to exact source links with a compilation digest.

The compilation digest is deterministic over canonical facts plus `SourceLink`s and is now independent of incoming row order. This matters for Gate 9: replay/permutation must not manufacture a new proof-input version.

Adapter-only unbound `CanonicalBatch` objects remain useful for unit tests, but Money Graph and both proof engines reject them. The supported financial path is journal-backed ingestion.

## Payment reducer review

The reducer remains pure and delivery-order invariant. Stable source-event ID replay is idempotent; conflicting payload under one event ID fails closed; payment amount/currency and explicit order identity cannot change across one payment timeline.

Razorpay's documented late-authorisation case is preserved: a source-time `FAILED` observation may be followed by a later `CAPTURED` event. The inverse normalized chronology (`CAPTURED` followed by a later source-time `FAILED`) is now rejected.

Razorpay also documents that a `payment.authorized` webhook can be fired after the payment has already moved to captured while its payload represents the earlier authorization snapshot. Therefore this audit does **not** add a broader `AUTHORIZED webhook delivery time < CAPTURED` rule. A production adapter must define semantic `occurred_at` precisely before stronger provider-specific chronology is enforced.

## Money Graph review

The Money Graph is built only from journal-backed canonical batches. It uses indexed payment histories rather than repeatedly rescanning the entire event collection.

Recon rows are first-class nodes. Each recon relationship cites the exact raw Razorpay recon envelope with authoritative/exact-source reason codes. Orphan recon rows are not silently accepted by Gate 7; the batch composition API rejects recon entries that reference a settlement entity absent from the canonical batch.

No fuzzy amount/narration relationships are promoted into authoritative graph edges.

## Gate 7 review — Settlement Composition Proof

The supported API is `prove_all_settlement_compositions`. It computes batch-global economic-identity ownership before proving individual settlements.

A settlement cannot be proven merely because its arithmetic residual is zero. Gate 7 independently checks:

- settlement/recon raw provenance;
- graph provenance edges;
- exact currency;
- duplicate economic identity;
- conflicting values/timestamps under one economic identity;
- one economic movement being claimed by multiple settlements;
- recon evidence occurring after settlement processing;
- exact signed normalized settlement-effect arithmetic.

Rows involved in future-time or cross-settlement ownership contradictions are excluded from accepted arithmetic. Duplicate economic evidence under a distinct source ID is a contradiction, while exact replay of the same source record is idempotent.

The per-settlement proof function is now private and requires explicit cross-settlement context. Gate 9 must consume the batch proof set rather than calling the private seam.

## Gate 8 review — Bank Receipt Proof

The supported API is `prove_all_bank_receipts`. Standard settlement bank identity is exact UTR only; amount/time/narration never substitute for identity.

Batch-global UTR reuse is computed before individual proofs. One standard settlement can accept at most one distinct bank transaction with its UTR. Multiple distinct bank rows sharing that UTR, reused settlement UTRs, or bank evidence before settlement processing fail closed.

Exact UTR + wrong amount is deliberately `BANK_RECEIPT_RESIDUAL` with `BANK_AMOUNT_MISMATCH`, not a contradiction label and never a successful reconciliation. This preserves the distinction between proven identity and failed financial equality.

The proof payload remains bounded under common-amount volume: same-amount non-identity rows contribute a diagnostic count rather than being copied into every proof.

Standard `setl_...` settlements are not generalized into arbitrary split-bank groups. Multi-credit Instant Settlements require explicit `setlod` / `setlodp` payout identities and payout-level UTR evidence.

The per-settlement bank helper is private and requires explicit batch UTR-reuse context. Gate 9 must consume the batch proof set.

## Simulator and corruption review

Hidden truth remains isolated under `reflow.simulator.truth`. No deterministic engine module imports hidden truth.

Scenario positions are now shuffled deterministically by world seed so fixture IDs cannot become an anomaly-class shortcut. Coverage is preserved, and dependency scenarios such as cross-period refund cannot occupy an invalid first position.

`WRONG_RECON_AMOUNT` now produces an internally valid recon row whose gross/effect move together, so the corruption reaches Gate 7 and creates a financial residual. Malformed arithmetic remains an adapter/schema test, not a reconciliation benchmark shortcut.

The standard-settlement simulator requires unique settlement/bank UTR truth and exactly one bank transaction for matched standard settlements. The previously inaccurate split-standard-settlement fixture remains removed.

## Complexity review

A suspected quadratic rescan in Money Graph/Gate 7 was re-checked and rejected as a false alarm: current code already builds payment/recon/ownership indexes before inner proof work.

The real scale findings were elsewhere: exact replay propagated duplicate canonical work, same-amount bank diagnostics risked proof-payload growth (fixed in Gate 8), and compilation identity was order-sensitive. All three are now bounded/deterministic at the appropriate layer.

No Redis, Kafka, database event bus, rule engine or additional service was introduced. The implementation remains roughly a few thousand lines of dependency-light Python because current correctness does not require more infrastructure.

## CI/tooling review

GitHub Actions uses Python 3.12 and runs, in order:

1. editable install with development dependencies;
2. Ruff;
3. strict mypy over `src`;
4. the full pytest suite.

`actions/checkout` and `actions/setup-python` were upgraded to v7 to remove the Node-20 action-runtime deprecation warning observed during this audit.

A pre-documentation exact code head (`84759cd...`) passed Ruff, strict mypy and all 120 tests. The final audit head must pass again after documentation/status changes before this audit can be marked complete.

## Confirmed findings in this audit cycle

- F-0019 conflicting raw evidence retention;
- F-0020 payment source chronology;
- F-0021 canonical fact/source-link integrity binding;
- F-0022 replay canonicalization duplication;
- F-0023 synthetic scenario-position leakage;
- F-0024 wrong-recon corruption testing the wrong layer;
- F-0025 narrow proof APIs missing batch-global context;
- F-0026 ingestion depending on simulator transport;
- F-0027 order-sensitive compilation identity;
- F-0028 canonicalization reading caller rows rather than retained journal payloads.

## Documentation corrections made by this audit

The audit does not treat old plans as immutable. Current docs were corrected where implementation/provider research superseded them:

- architecture now shows raw journaling **before** validation/canonicalization;
- safety docs no longer claim ingress byte quotas or provider authenticity that are not implemented;
- the normalized recon engine is described as settlement-effect arithmetic, not a production debit/credit adapter;
- exact UTR + wrong bank amount is documented as residual/non-reconciled;
- arbitrary split standard-settlement support was removed from the master plan;
- Gate 9 proof/version/exception types are explicitly deferred until Gate 9;
- the simulator/ingestion dependency direction is documented correctly;
- AI safety controls are labeled planned because no AI layer exists yet.

## Explicit non-claims after this audit

ReFlow still does not claim:

- production Razorpay webhook/API adapters or webhook signature validation;
- authenticated/persistent raw journal storage;
- arbitrary bank-statement parsing;
- Instant Settlement payout reconciliation;
- multi-currency/FX support;
- final reconciliation accuracy, throughput, memory or maximum-volume numbers;
- an implemented Gate 9 full proof/version store;
- an implemented AI adapter synthesizer or investigation agent;
- ERP writeback or autonomous money movement.

## Gate 9 admission criteria

Gate 9 may start only when the audited branch satisfies all of the following on the exact final head:

- Ruff green;
- strict mypy green;
- full pytest green;
- `git diff --check` clean;
- zero hidden-truth imports outside the simulator/evaluator boundary;
- zero simulator imports under production-facing ingestion/core modules;
- no stale public imports of private Gate 7/8 single-settlement proof seams;
- secret-pattern scan finds no committed credential material;
- README, `LIMITATIONS.md`, failure log and architecture/master-plan docs agree on current status;
- PR #5 is mergeable and merged into `main`.

## Gate 9 architectural constraints

Gate 9 must be a **combiner and immutable versioning layer**, not another matcher.

It should consume the complete Gate 7 and Gate 8 batch proof sets keyed by settlement ID. It must not independently search recon rows, bank rows, fuzzy candidates or UTRs.

A full proof version must bind at minimum:

- settlement ID;
- canonical compilation SHA-256;
- Gate 7 proof fragment and deterministic ruleset version;
- Gate 8 proof fragment and deterministic ruleset version;
- knowledge/evidence cutoff;
- generated-at time;
- prior proof version reference when one exists;
- final derived state and reason codes.

Late evidence must create a new proof version; it must never mutate an earlier version in place. A typical state sequence may be:

```text
v1  composition proven + bank waiting
v2  composition proven + bank proven
v3  later authoritative contradiction -> reopened/non-reconciled
```

The historical v1/v2 facts remain exactly what the engine could prove at those earlier evidence cutoffs.

Gate 9 status combination must be conservative: `PROVEN_RECONCILED` is possible only when both required fragments are proven for the same settlement/evidence compilation and no contradiction/incomplete condition remains.

## Final audit verdict

**Gate 9 admission is conditional only on checkpoint closure:** this reviewed branch must pass exact-head CI and PR #5 must be merged into `main`. No further design or code condition is intentionally deferred outside the criteria above.

Once those two mechanical conditions are true, this audit grants **GO for Gate 9**. The merge commit and CI runs are authoritative repository history; this document deliberately does not predict a future merge SHA.
