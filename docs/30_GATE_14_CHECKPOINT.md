# Gate 14 Checkpoint — Exception Case Lifecycle + Fingerprints

## Status

Gate 14 is implemented on `build/gate-14-exception-case-lifecycle` from verified Gate 13 `main` at `bd6f8b224c3100cb9354d0c4695982d216b6a877`.

Code/test checkpoint:

`83a422b9bf171c27f3cd8011d6c921605b097ad8`

Local checkpoint validation on 2026-09-01:

- Ruff: passed;
- strict mypy: passed across 51 source files;
- targeted Gate 14 suite: 29 passed;
- full pytest suite: 269 passed;
- direct production-module scan: no `reflow.simulator` / `simulator.truth` import;
- `git diff --check`: passed.

Gate 14 contains no investigation-agent code and grants no AI authority over case creation, reconciliation truth, closure or incident grouping.

## Gate 14 thesis

> A financial break has a deterministic economic identity across immutable reconciliation runs; workflow actions annotate that history but never redefine financial truth.

Gate 14 consumes the already-audited Gate 13 run capsule plus its exact Gate 9 proofs, policy and source manifests. It does not accept caller-authored exception classifications.

## Implemented contracts

### Stable tracking key and case ID

A case tracking key is content-addressed from:

- reconciliation scope ID;
- settlement ID;
- authoritative settlement amount and currency;
- settlement UTR when present.

The key excludes run/proof IDs, reason codes, materiality, policy, owner, workflow state and incident fingerprint.

`ExceptionCaseId` is deterministic from that tracking key. The same economic break therefore retains case identity across new runs and proof-version/reason changes.

If the authoritative amount or payout/UTR identity changes, Gate 14 creates a new case identity and supersedes the prior scoped-settlement case rather than carrying stale workflow state forward.

### Immutable case observations

`ExceptionCaseObservation` binds:

- deterministic case/tracking identity;
- scope;
- exact `ReconciliationRunId`;
- exact Gate 9 `ProofVersionId`;
- exact policy-version ID;
- settlement ID and amount;
- current Gate 9 financial status and reason codes;
- materiality band from that run's policy;
- settlement UTR;
- canonical source completeness/late packet with exact manifest IDs;
- deterministic incident fingerprint;
- immutable run completion timestamp;
- Gate 14 ruleset version.

Observation objects self-verify tracking identity, case ID, fingerprint and content-addressed observation ID.

A run/proof replay is idempotent. Conflicting content for the same run/settlement fails closed.

### First seen, last seen and age

Case first/last seen state is derived from immutable observation history. Age is computed from an explicit timezone-aware `as_of` value and is never stored as mutable truth.

Chronology is enforced both per case and per scoped settlement. An older economic identity cannot arrive after a superseding case and reverse the current case lineage.

A tracking identity that has already been superseded cannot later be silently reactivated.

### Financial state is separate from workflow state

The latest financial state is always the latest Gate 9 reconciliation status:

- `PENDING_BANK_CREDIT`;
- `RESIDUAL`;
- `INCOMPLETE`;
- `CONTRADICTED`;
- `PROVEN_RECONCILED`.

Workflow is separate:

- `OPEN`;
- `ACKNOWLEDGED`;
- `AWAITING_SOURCE`;
- `DEFERRED`;
- `CLOSED`.

An operator can close workflow while the proof remains non-green. That never changes the Gate 9 status.

When the same tracking identity later becomes `PROVEN_RECONCILED`, the derived case state auto-closes with `PROOF_RECONCILED` while preserving every earlier observation and disposition.

### Append-only operator dispositions

Supported v1 actions are:

- `ASSIGN_OWNER`;
- `ACKNOWLEDGE`;
- `REQUEST_SOURCE_CORRECTION`;
- `DEFER`;
- `ACCEPT_OPERATIONAL_VARIANCE`;
- `CLOSE`;
- `REOPEN`.

Each disposition is immutable and content-addressed from case ID, monotonic sequence, actor, timestamp, kind, optional owner and optional note.

Rules include:

- only `ASSIGN_OWNER` may carry/change owner;
- exact same-sequence replay is idempotent;
- conflicting same-sequence content fails closed;
- sequence gaps fail closed;
- timestamps cannot predate the case or move backwards;
- an operator-closed case requires explicit `REOPEN` before another workflow status transition;
- financially reconciled or economically superseded cases reject new workflow mutation.

Operator closure/variance acceptance never creates `PROVEN_RECONCILED`.

### Materiality remains workflow-only

The affected amount for a Gate 14 settlement case is the full authoritative settlement amount.

The policy's materiality thresholds produce the observation's queue band only. A policy change can alter materiality while leaving case identity, proof status, exact residuals and incident fingerprint unchanged.

### Deterministic incident fingerprints

The incident fingerprint groups current failure patterns inside one reconciliation scope using:

- scope ID;
- Gate 9 financial status;
- sorted Gate 9 reason codes;
- canonical source completeness/late signature.

It deliberately excludes settlement/case IDs, amount, owner, workflow state, policy version and materiality.

A case can therefore keep its economic identity while moving to a different incident fingerprint as evidence or source state changes.

### Run-specific incident clusters

`build_incident_clusters()` creates immutable run-specific cluster views from case observations.

Each cluster binds:

- run and scope;
- incident fingerprint;
- canonical-sorted case IDs;
- exact affected case count;
- exact integer-paise affected value;
- current financial status, reasons and source-state packet.

Input permutation cannot change cluster output. Green observations do not form incident clusters. One case cannot be counted twice in one run.

### Gate 13 boundary re-validation

Gate 14 does not trust a loose collection of IDs. `apply_run()` re-validates that:

- policy ID equals the Gate 13 run policy;
- exact manifest IDs equal the run manifest set;
- manifest scope, period, timezone, delivery cutoff and evaluation time align with the run;
- policy-required source classes are present;
- exact proof IDs equal the run proof set;
- proof compilation hash, knowledge cutoff and generation time align with the run.

Case construction begins only after those bindings pass.

### Atomic reference ledger

`InMemoryExceptionCaseLedger` stages a run before commit. If any settlement/case invariant fails, no earlier case observation or supersession from that run is partially appended.

The ledger owns append-only reference semantics for:

- observations;
- dispositions;
- case state derivation;
- scoped-settlement supersession lineage.

It is deliberately not a persistence or distributed-workflow implementation.

## Acceptance evidence

The original Gate 14 plan froze 20 acceptance functions before implementation. The hardened targeted suite now covers 29 cases, including:

1. unchanged non-green economics across genuinely distinct runs retains case identity;
2. first/last seen and age derive from run timestamps;
3. exact run replay is idempotent;
4. later green proof auto-closes without rewriting history;
5. changed settlement amount creates a new case and supersedes the old;
6. changed UTR creates a new case and supersedes the old;
7. reason/status changes can change fingerprint while case identity stays stable;
8. policy/materiality changes remain workflow-only;
9. scope isolation prevents cross-account case inheritance;
10. run/proof mismatch fails closed;
11. proof permutation cannot change observation ordering;
12. dispositions are sequence-safe, append-only and content-addressed;
13. owner/workflow state derives from dispositions;
14. operator close and accepted variance cannot change financial truth;
15. `REOPEN` affects workflow only;
16. incident grouping is input-order invariant;
17. cluster case count and settlement value are exact;
18. source completeness changes can change fingerprint without changing case identity;
19. out-of-order case time fails closed;
20. production case code imports no simulator truth;
21. closed workflow cannot transition without explicit `REOPEN`;
22. stale prior economics cannot reverse supersession;
23. direct observation tampering fails;
24. direct disposition tampering fails;
25. direct cluster tampering fails;
26. failed multi-case run application is atomic;
27. run/manifest mismatch fails closed;
28. run/policy mismatch fails closed;
29. parameterized operator-close variants independently preserve non-green financial truth.

## Failures discovered during Gate 14

The permanent records are in `FAILURE_LOG.md`.

### F-0068 — rerun fixture reused one Gate 13 run identity

Changing only run completion time did not create a distinct deterministic Gate 13 run. The fixture now changes the immutable source-delivery capsule while preserving economics.

### F-0069 — closed workflow could reopen without `REOPEN`

The disposition boundary now requires explicit `REOPEN` before another workflow transition from operator-closed state.

### F-0070 — stale economics could reverse supersession

The ledger now enforces scoped-settlement chronology across case identities and rejects reactivation of superseded tracking identities.

None of these failures changed Gate 7/8/9 proof truth.

## Non-goals and remaining limitations

Gate 14 does **not** claim:

- PostgreSQL durability or crash/restart recovery;
- authenticated operator identity or authorization;
- distributed locks, queues or workflow workers;
- SLA notifications/escalations;
- cases for every possible run-level Gate 13 blocker;
- production Razorpay Settlement Recon field semantics;
- real Razorpay Test Mode validation;
- Instant Settlement `setlod` / `setlodp` support;
- AI investigation;
- autonomous remediation or money movement;
- final benchmark/scale results.

The reference ledger is in-memory. Actor identifiers are audit fields supplied by the caller, not authenticated identities.

Changed-economics case tests validate the deterministic Gate 14 tracking/supersession contract using individually valid immutable run/proof artifacts. Production source-correction/version semantics remain governed by the later real integration and persistence layers.

## Next gate

New Gate 15 is **Real Razorpay Integration**.

The next implementation should validate real provider-shaped semantics earlier, including:

- actual webhook/entity shapes;
- Settlement Recon `debit` / `credit` / `amount` / `fee` / `tax` normalization;
- settlement entity/webhook evidence;
- Razorpay Test Mode evidence where available;
- explicit `REAL TEST MODE` versus `SYNTHETIC` labels.

The Exception Investigation Agent remains Gate 16 and must not begin before Gate 15's provider-shaped evidence boundary is green.
