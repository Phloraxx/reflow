# Gate 13 Checkpoint — Reconciliation Control Plane

## Status

Gate 13 is implemented on branch `build/gate-13-reconciliation-control-plane`, based on the strategic-review `main` checkpoint `8c28a53370c4cb30c83b42d741a74667d607a5c6`.

Code/test checkpoint commit: `19530e3286a6a2ac05acf43d34c338d738641f49`.

Documentation/PR merge status is intentionally recorded separately so the checkpoint does not claim an unverified merge.

This checkpoint follows `docs/27_STRATEGIC_PAUSE_CURRENT_STATE_AND_REVISED_PLAN.md` and deliberately does **not** resume the abandoned exception-investigation-agent branch.

Local pre-commit validation on 2026-09-01 is green:

- Ruff: passed;
- strict mypy: passed across 50 source files;
- pytest: 240 passed;
- targeted Gate 13 suite: 19 passed;
- `git diff --check`: passed.

Gate 13 adds the deterministic operational layer that was missing between settlement proofs and future exception workflow/AI.

## Gate 13 thesis

> A settlement proof is not enough to close a period. ReFlow must also prove what scope was reconciled, what evidence arrived, whether the source set was complete, whether every relevant record was classified, and whether the scoped clearing position balances.

The control plane wraps the existing Gates 7–9 proof kernel. It does not replace or weaken it.

## Implemented primitives

Gate 13 introduces:

- `ReconciliationScope`;
- `SourceDeliveryManifest`;
- `DeliveryMode.SNAPSHOT` / `DeliveryMode.DELTA`;
- explicit source `WAITING`, `LATE`, `PARTIAL`, `COMPLETE` state plus `received_late`;
- `ReconciliationPolicyVersion`;
- `EvidenceCoverageCertificate`;
- `BalanceControlProof`;
- `CloseReadinessCertificate`;
- `ReconciliationRun`.

The new contracts use typed content-addressed IDs exported from `reflow.domain`.

## Reconciliation scope

A scope binds the identifiers that must partition financial truth:

```text
merchant account
provider
provider account
bank account
currency
optional channel/product boundary
```

The scope ID is deterministic over this immutable content. Source manifests must cite the source account that the scope authorizes for that source class.

This prevents the control layer from deliberately combining manifests declared for unrelated merchant/provider/bank-account scopes.

## Source delivery manifests

A `SourceDeliveryManifest` separates source availability from financial proof.

Each manifest binds:

- scope and source kind;
- source account;
- reporting period and timezone;
- expected delivery time;
- evaluation time;
- received time;
- source watermark;
- completeness state;
- late-receipt flag;
- delivered raw envelope IDs;
- effective raw envelope IDs;
- content SHA-256;
- adapter version and schema fingerprint;
- prior manifest identity where applicable.

### Missing versus missing evidence

Gate 8 may say an expected bank credit has not been observed. Gate 13 now distinguishes:

```text
bank source not delivered / late
        !=
bank source complete and expected credit absent
```

The first is a source-delivery blocker. The second is a financial absence inside a declared-complete source and is surfaced separately as `BANK_CREDIT_MISSING`.

Absence therefore never gains evidentiary meaning without an explicit source-completeness state.

## SNAPSHOT versus DELTA

The two delivery modes have intentionally different carry-forward semantics.

`SNAPSHOT`:

- the new delivery replaces the prior effective envelope set for the period.

`DELTA`:

- delivered envelopes are unioned with prior effective envelopes for the same scope/source/account/period/timezone lineage.

Manifest lineage cannot cross scopes, accounts, source kinds, reporting periods or timezones.

A late delivery creates a new manifest. Prior manifests remain immutable.

## Completeness and watermarks

Before delivery, a manifest is:

- `WAITING` when evaluated on/before `expected_by`;
- `LATE` when evaluated after `expected_by`.

After receipt it becomes:

- `PARTIAL` when the source is not declared complete;
- `COMPLETE` only when its watermark reaches at least the period end.

A delivery received after `expected_by` can be `COMPLETE` while independently retaining `received_late=True`.

This keeps source-quality history without pretending the old waiting/late run never existed.

## Policy version

`ReconciliationPolicyVersion` is a content-addressed deterministic configuration object for:

- required source classes;
- reporting timezone;
- bank waiting SLA metadata;
- materiality thresholds;
- enabled deterministic controls.

Materiality is exposed only as a workflow band (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`). It never changes Gate 7/8/9 residuals, status, identity rules or exact integer arithmetic. Gate 13 v1 requires both implemented core controls (`evidence_coverage` and `balance_control`) rather than accepting a policy flag the engine would silently ignore.

## Evidence coverage / no-orphan-money certificate

`EvidenceCoverageCertificate` answers the run-level conservation question:

> Did every retained financially relevant record in the source manifests enter an explicit state?

Canonical evidence is classified into:

- `PROVEN`;
- `OPEN_UNSETTLED`;
- `CONTRADICTED_RESIDUAL`;
- `ORPHAN`.

Retained evidence that did not canonicalize may be explicitly placed in:

- `QUARANTINED`.

`WAITING_FOR_SOURCE` remains part of the vocabulary for later application-level source windows, but Gate 13 does not invent evidence rows for a source that has not arrived.

### Proof-derived authority

The first implementation attempt allowed caller-supplied truth labels. That was unsafe and is recorded as F-0065.

The final builder derives canonical classifications from the exact Gate 7/8/9 proof evidence and canonical upstream state. A caller cannot label canonical financial evidence `PROVEN`.

Only non-canonical retained evidence can be explicitly marked `QUARANTINED`.

Contradicted/residual evidence has conservative precedence. A record touched by a failed fragment cannot be made green merely because another fragment also cites it.

### Exact proof-set binding

The coverage certificate requires exactly one Gate 9 proof for every canonical settlement and binds the canonical-sorted proof-version IDs.

The certificate self-validates:

- item uniqueness/order;
- bucket summaries;
- known values and unknown-value counts;
- orphan count/value;
- coverage status;
- ruleset version;
- content-addressed ID.

Any orphan record makes coverage `FAILED`.

## Balance / clearing-position control

Gate 13 adds a deliberately small balance control rather than a general ledger.

The exact equation is:

```text
opening position
+ provider activity
- bank-proven payouts
+ authoritative adjustments
= derived closing position
```

The derived closing position is compared with an observed closing position at the same scoped point in time.

All values are existing integer-paise `Money`. Currency mixing is rejected.

The control requires:

- period start/end;
- opening/closing points equal to those period boundaries;
- timezone-aware timestamps;
- the policy reporting timezone;
- one currency.

A non-zero exact residual is `RESIDUAL`; zero is `PROVEN`.

The proof self-validates its equation, residual, status, ruleset and content-addressed ID.

## Close readiness

`CloseReadinessCertificate` combines deterministic blockers without altering financial truth.

A run is `READY` only when no reason codes remain. Current blockers include:

- missing required source manifest;
- waiting/late/partial required source;
- orphan evidence;
- quarantined evidence;
- balance residual;
- non-green settlement proof;
- bank credit missing from a complete bank delivery.

Close readiness binds:

- policy version;
- exact source manifest IDs;
- exact Gate 9 proof-version IDs;
- evidence coverage certificate;
- balance-control proof.

Its status is derived from its canonical-sorted reason codes and its ID is content-addressed.

## Reconciliation run capsule

`ReconciliationRun` is the immutable root artifact for a business reconciliation execution.

Its deterministic input identity binds:

- scope ID;
- policy version ID;
- source-delivery manifest IDs;
- period and timezone;
- canonical compilation SHA-256;
- Gate 7, Gate 8, Gate 9 and Gate 13 ruleset versions;
- knowledge cutoff;
- optional code/build SHA.

The run output digest binds:

- the exact Gate 9 proof-version IDs;
- evidence coverage certificate ID;
- balance-control ID;
- close-readiness ID;
- final readiness outcome.

`started_at` and `completed_at` are audit metadata and do not manufacture a different run identity for otherwise identical reconciliation inputs.

A run cannot:

- know source evidence after its knowledge cutoff;
- start before its knowledge cutoff;
- complete before it starts;
- contain manifests evaluated after completion;
- omit a canonical settlement proof;
- mix another scope/policy/period/timezone;
- bind coverage/close artifacts from another proof set.

Direct dataclass tampering is rejected by the artifacts' own `__post_init__` invariants, not only by builder functions.

## Acceptance criteria covered

The Gate 13 targeted suite covers:

1. identical source snapshots + policy + cutoff produce the same run ID;
2. source-row permutation does not change run identity;
3. a late source produces a later complete manifest/run without rewriting the prior state;
4. `SNAPSHOT` and `DELTA` have different carry-forward semantics;
5. manifests for another account/scope cannot satisfy the target scope;
6. undelivered bank source differs from a complete bank source with missing credit;
7. every manifest evidence record has exactly one deterministic coverage bucket;
8. unclassified relevant evidence becomes orphan evidence and blocks close;
9. non-canonical evidence requires explicit quarantine rather than disappearing;
10. materiality changes priority band only, never Gate 9 truth/residual;
11. balance control rejects mismatched time/timezone boundaries;
12. coverage/run require an exact complete Gate 9 proof set;
13. contradicted/residual evidence cannot be masked by another proven fragment;
14. coverage certificate tampering fails closed;
15. balance proof tampering fails closed;
16. close-readiness tampering fails closed;
17. run output tampering fails closed;
18. Gate 13 v1 rejects a policy that disables one of its required core controls;
19. a source manifest directly rejects a declared provider account outside the scope.

The two strategic-review acceptance bullets about cross-run case continuity remain intentionally deferred to Gate 14 because no `ExceptionCase` persistence is introduced in Gate 13.

## Failures discovered during implementation

Two safety-critical design defects and one test-quality defect were found before checkpointing and are preserved in `FAILURE_LOG.md`:

- **F-0065:** coverage initially trusted caller-supplied `PROVEN` labels;
- **F-0066:** the first run boundary did not require one Gate 9 proof per canonical settlement;
- **F-0067:** the first Gate 13 row-permutation fixture was vacuous because each source contained only one row.

All three are resolved and regression-tested. They are retained in the failure history rather than erased.

## Non-goals and remaining limitations

Gate 13 is a deterministic domain/reference layer, not a production close platform.

It does **not** yet provide:

- durable database-backed run/manifest/certificate persistence;
- authenticated connector identity proving who supplied a `source_account_id`;
- external digital signatures over source-delivery manifests;
- automatic acquisition of authoritative bank/provider opening and closing balances;
- a full double-entry ledger;
- durable `ExceptionCase` lifecycle, owner, ageing or operator disposition;
- production Razorpay Settlement Recon integration;
- investigation AI;
- operator UI.

The balance control proves exact consistency of supplied authoritative control inputs. It does not independently authenticate those external balance inputs. `bank_wait_sla_seconds` is versioned in the Gate 13 policy for reproducibility, but detailed SLA-driven exception workflow is intentionally deferred to Gate 14; Gate 13 close readiness remains fail-closed for a non-green settlement proof.

The source manifest binds evidence to an explicit scoped source account inside ReFlow. Production connector/authentication work must ensure that account identity is derived from the authenticated connector/session rather than arbitrary user text.

## Architecture decision

Gate 13 remains a small module around the proof kernel:

```text
SourceDeliveryManifest + ReconciliationScope
                ↓
       journal-backed CanonicalBatch
                ↓
      Gates 7 / 8 / 9 proofs
                ↓
  EvidenceCoverageCertificate
                +
       BalanceControlProof
                ↓
    CloseReadinessCertificate
                ↓
       ReconciliationRun
```

No database, queue, microservice, ledger engine or AI framework was added.

## Validation commands

```bash
python -m ruff check .
python -m mypy src
python -m pytest
python -m pytest tests/core/test_reconciliation_control_plane.py
git diff --check
```

## Next gate

New Gate 14 is **Exception Case Lifecycle + Fingerprints**.

Before AI, ReFlow should add deterministic persistent case semantics:

- stable case tracking key;
- first/last seen and age;
- materiality band;
- owner/status;
- proof/run/version linkage;
- append-only operator disposition;
- deterministic exception fingerprint/incident grouping;
- carry-forward and auto-close rules across immutable runs.

No investigation agent should begin until that case lifecycle passes its own acceptance review.
