# Gate 14 Contract and Acceptance Plan — Exception Case Lifecycle + Fingerprints

## Status

Frozen pre-implementation acceptance contract for New Gate 14, started from verified `main` at:

`bd6f8b224c3100cb9354d0c4695982d216b6a877`

Gate 13 is merged and green. This contract is implemented by code checkpoint `83a422b9bf171c27f3cd8011d6c921605b097ad8`; see `30_GATE_14_CHECKPOINT.md`. No investigation-agent code is admitted into this gate.

## Gate 14 thesis

> A financial break needs a stable operational identity across immutable reconciliation runs, while workflow actions remain completely separate from deterministic financial truth.

Gate 14 turns non-green Gate 9 settlement proofs into durable-in-semantics, append-only case history. The reference implementation remains in-memory; PostgreSQL durability is still Gate 17.

## Non-negotiable boundaries

1. A case never changes Gate 7/8/9 proof truth.
2. Operator closure never creates `PROVEN_RECONCILED`.
3. Materiality affects queue priority only.
4. A new run/proof creates a new immutable case observation; prior observations are not rewritten.
5. Case continuity is deterministic, not model-selected.
6. Changed authoritative economics may create a new case rather than inherit stale investigation state.
7. Case/incident code must not import simulator truth.
8. Case scope cannot cross merchant/provider/bank-account boundaries.
9. AI remains absent.

## Gate 14 v1 scope

Gate 14 v1 creates cases from **non-green Gate 9 settlement proofs**.

Run-level source/coverage/balance blockers remain first-class Gate 13 controls and close-readiness reasons. Gate 14 does not invent synthetic settlement cases for a source that never arrived.

A later product layer may expose run-control incidents alongside settlement cases, but this gate keeps the case identity contract narrow and auditable.

## Case tracking identity

The stable case tracking key represents the authoritative economic identity of the settlement break, not its current explanation.

Tracking-key material:

```text
reconciliation scope ID
settlement ID
settlement amount + currency
settlement UTR / provider payout identity when present
```

The tracking key deliberately excludes:

- run ID;
- proof version ID;
- reason codes;
- source completeness state;
- policy/materiality thresholds;
- owner/workflow status;
- incident fingerprint.

Why: the same settlement break should retain investigation continuity as new evidence changes the diagnostic reason, policy version or source state.

If authoritative settlement identity/value changes, the tracking key changes. The old case is superseded and a new case starts without inheriting stale workflow/disposition state.

## Case ID

`ExceptionCaseId` is deterministic from the tracking key. A case is therefore reproducible and cannot be arbitrarily renamed by a caller.

## Immutable case observations

Every run that contains the current economic identity emits at most one immutable observation for that case.

An observation binds:

- case/tracking identity;
- reconciliation scope;
- run ID;
- exact Gate 9 proof-version ID;
- policy-version ID;
- settlement ID;
- current financial proof status;
- exact proof reason codes;
- affected settlement amount;
- materiality band calculated from that run's policy;
- source completeness/late-state signature from the run manifests;
- deterministic incident fingerprint;
- observed-at timestamp derived from the immutable run completion time.

The same run/proof replay is idempotent and cannot append a duplicate observation.

## First seen / last seen / age

Case state is derived from observation history:

- `first_seen_at` = first observation's run completion;
- `last_seen_at` = latest observation's run completion;
- `first_seen_run_id` / `last_seen_run_id` are explicit;
- age is computed deterministically from a caller-supplied timezone-aware `as_of`, never stored as mutable truth.

Runs/observations cannot move backwards in time for one case.

## Financial state versus workflow state

Case state exposes two independent axes.

### Financial state

Always comes from the latest deterministic Gate 9 proof:

```text
PENDING_BANK_CREDIT
RESIDUAL
INCOMPLETE
CONTRADICTED
PROVEN_RECONCILED
```

### Workflow state

Operator/process state only:

```text
OPEN
ACKNOWLEDGED
AWAITING_SOURCE
DEFERRED
CLOSED
```

A case may be workflow `CLOSED` while its latest financial proof remains non-green. That is an explicit operational disposition, not reconciliation truth.

## Auto-close / supersede rules

### Proof becomes green

When a later run contains `PROVEN_RECONCILED` for the same tracking identity:

- append the green observation;
- financially resolve the case;
- derived lifecycle state becomes `CLOSED` with `PROOF_RECONCILED` resolution;
- preserve every prior observation and disposition.

### Authoritative economics change

When the same scoped settlement ID appears with a different tracking identity:

- prior active case is closed as `ECONOMIC_IDENTITY_CHANGED` / superseded;
- new tracking key creates a new case;
- prior owner/dispositions are not copied into the new case.

This prevents stale investigation state from attaching to a materially different payout.

## Materiality

Gate 14 uses the full authoritative settlement amount as `affected_amount` for workflow priority and cluster value.

Reason:

- the exact composition/bank residuals remain visible in the proof;
- one settlement can have more than one independent fragment problem;
- summing fragment residuals can double-count risk;
- the settlement amount is an unambiguous conservative exposure for queue prioritization.

Changing materiality thresholds changes only the latest observation's materiality band. It does not change the case tracking key, proof status, exact residual or incident fingerprint.

## Source completeness packet

Each observation carries a canonical-sorted source-state tuple for the run's required source classes:

```text
source kind
completeness: WAITING / LATE / PARTIAL / COMPLETE
received_late flag
manifest ID
```

This keeps absence epistemically scoped. A case investigator can later distinguish a financial absence from a source-delivery problem without querying mutable global state.

## Incident fingerprint

The deterministic incident fingerprint groups cases with the same current failure pattern inside one reconciliation scope.

Fingerprint material:

```text
scope ID
Gate 9 financial status
sorted Gate 9 reason codes
canonical source completeness/late signature
```

Fingerprint deliberately excludes:

- settlement ID;
- settlement amount;
- case ID;
- owner/status;
- materiality band;
- policy version.

This lets multiple settlements with the same operational failure pattern group together while preserving case-level exact economics.

A case can retain the same tracking identity while its incident fingerprint changes as new evidence changes the failure pattern.

## Incident cluster

Clusters are run-specific views, not mutable master cases.

A cluster binds:

- run ID;
- scope ID;
- incident fingerprint;
- canonical-sorted case IDs;
- affected case count;
- exact affected settlement value in one currency;
- current reason/source signature.

Only one current observation per case is counted for the target run. Historical observations are never double-counted.

## Append-only operator dispositions

Operator actions are separate immutable records.

Supported v1 disposition kinds:

- `ASSIGN_OWNER`;
- `ACKNOWLEDGE`;
- `REQUEST_SOURCE_CORRECTION`;
- `DEFER`;
- `ACCEPT_OPERATIONAL_VARIANCE`;
- `CLOSE`;
- `REOPEN`.

Every disposition binds:

- case ID;
- monotonic sequence number;
- actor identifier;
- occurred-at timestamp;
- disposition kind;
- optional owner;
- optional note.

Rules:

- `ASSIGN_OWNER` requires an owner;
- other dispositions cannot silently change owner unless explicitly allowed by the contract;
- timestamps cannot predate the case;
- sequence IDs are deterministic/content-addressed;
- disposition replay is idempotent only for exact same deterministic record;
- a conflicting record at the same sequence fails closed.

`ACCEPT_OPERATIONAL_VARIANCE` or `CLOSE` can close workflow state but cannot alter the financial proof.

`REOPEN` reopens workflow state only.

## Reference ledger

Gate 14 will use an `InMemoryExceptionCaseLedger` analogous to existing in-memory journal/proof reference stores.

It owns append-only:

- case observations;
- operator dispositions;
- deterministic state derivation.

It does not provide database durability, authentication, locks, queues or distributed workflow.

## Gate 14 acceptance tests to write before implementation

1. unchanged non-green economics across two immutable runs retains the same tracking key/case ID;
2. first/last seen and age advance from immutable run timestamps;
3. replaying the same run/proof is idempotent and does not duplicate an observation;
4. a later green proof auto-closes the case as `PROOF_RECONCILED` without rewriting history;
5. changed settlement amount creates a new case and supersedes the old one;
6. changed payout/UTR identity can create a new case and supersede the old one;
7. a reason/fingerprint change with unchanged economics keeps the same case ID;
8. a policy-version/materiality change is visible in the observation but keeps case identity and exact proof truth;
9. different reconciliation scope cannot inherit another scope's case;
10. run/proof ID set mismatches fail closed;
11. case observation ordering is deterministic under proof permutation;
12. dispositions are append-only, sequence-safe and content-addressed;
13. owner assignment and workflow statuses derive from dispositions;
14. operator close/accepted variance cannot make the current financial status green;
15. operator `REOPEN` affects workflow only;
16. incident grouping is deterministic under input permutation;
17. one run's cluster preserves exact affected case count and affected settlement value;
18. changed incident pattern splits/changes fingerprint without changing economic case identity;
19. out-of-order case observation time fails closed;
20. simulator truth remains absent from Gate 14 production imports.

## Deferred from Gate 14

- PostgreSQL persistence / crash recovery;
- authenticated operator identity and authorization;
- SLA notification jobs;
- real Razorpay API semantics;
- AI investigation;
- cross-provider generic case taxonomy;
- generic run-control cases for every possible source/coverage control;
- UI.

## Admission rule for Gate 15

Gate 14 is complete only when the deterministic case history, disposition separation and incident grouping are independently replayable and the acceptance suite is green.

Only then should ReFlow move to real Razorpay-shaped integration. Investigation AI remains Gate 16.
