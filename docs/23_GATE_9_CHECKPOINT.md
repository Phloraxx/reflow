# Gate 9 Checkpoint — Versioned Full Reconciliation Proof

**Date:** 2026-08-30  
**Branch:** `build/gate-9-versioned-reconciliation-proof`  
**Foundation:** audited `main` checkpoint `1c621c4fe770668acbe7ed79f940d3bbbbeec22d`

## Purpose

Gate 9 turns the independent Gate 7 settlement-composition proof and Gate 8 bank-receipt proof into immutable settlement-scoped reconciliation history. It is a combiner/versioning layer, not another matcher.

## Supported full states

- `PROVEN_RECONCILED`
- `PENDING_BANK_CREDIT`
- `RESIDUAL`
- `INCOMPLETE`
- `CONTRADICTED`

`PROVEN_RECONCILED` is possible only when both required proof fragments are independently `PROVEN`.

## Version identity

Each full proof records both a settlement-scoped authoritative input SHA-256 and the global canonical batch compilation SHA-256. Only the scoped authoritative hash decides whether a new settlement proof version is necessary.

This prevents unrelated source rows, same-amount diagnostics, or delivery-order changes from manufacturing financial history while still preserving the reproducible batch context in which a proof was emitted.

## Temporal rules

- `knowledge_cutoff` and `generated_at` must be timezone-aware.
- `generated_at >= knowledge_cutoff`.
- all raw source envelopes represented by the recorded batch compilation must have been received by the cutoff.
- later versions cannot move either cutoff or generation time backwards relative to their prior series state.
- authoritative source evidence cannot silently disappear from a later version.

## Immutable history and reopening

Late authoritative evidence creates a new version rather than rewriting a prior proof. A settlement can move from `PENDING_BANK_CREDIT` to `PROVEN_RECONCILED`, or a previously proven settlement can reopen to `CONTRADICTED`/another non-proven state when later authoritative contradictory evidence arrives.

The `reopened` flag and `REOPENED_AFTER_PROVEN` reason preserve that transition explicitly.

## Atomic ledger semantics

`InMemoryProofLedger.apply_batch()` validates and stages the complete batch before appending any new versions. A failure in a later settlement cannot leave earlier settlements partially committed.

This is still an in-memory reference ledger. Persistence, database transactions, retention and crash/restart durability remain future integration work.

## Self-verification

`ReconciliationProofVersion` re-derives and validates:

- authoritative source-envelope union from its embedded Gate 7/8 fragments;
- settlement-scoped input SHA-256;
- Gate 7, Gate 8 and Gate 9 ruleset versions;
- deterministic `proofv_...` identity;
- fragment settlement/amount agreement;
- derived full status and reason codes;
- predecessor presence rules.

A proof object cannot keep a valid-looking identity while silently changing these fields.

## Gate 7/8 prerequisite repair discovered by Gate 9

Batch-global contradictions must cite all raw evidence needed to demonstrate them. Gate 7 cross-settlement economic-identity conflicts now include counterparty recon envelopes. Gate 8 reused-settlement-UTR contradictions now include counterparty settlement envelopes.

## Gate 9 implementation failures preserved

- `F-0029` — batch-global contradictions omitted counterparty raw evidence.
- `F-0030` — proof-ledger batch update was not atomic.
- `F-0031` — recorded batch compilation could contain evidence later than the declared knowledge cutoff.
- `F-0032` — full-proof metadata was not fully self-verifying.

See [`../FAILURE_LOG.md`](../FAILURE_LOG.md) for symptom, root cause, fix and regression protection.

## Adversarial regression surface

The Gate 9 suite covers first-version creation, time-only reruns, delivery permutations, unrelated same-amount evidence, late bank receipt, late recon evidence, post-proof bank contradiction, post-proof recon contradiction, reopening, disappearing evidence, incomplete proof fragment sets, cross-series diffs, batch atomicity, knowledge-cutoff violations, ruleset/source-union/scoped-hash forgery, typed proof IDs, and backwards temporal metadata.

## Latest validated code head before documentation checkpoint

`f4e3c7fdfbe41adfccbd3259dc49560225708992`

GitHub Actions result:

```text
Ruff         PASS
strict mypy  PASS — 19 source files
pytest       PASS — 137 tests
```

The final documentation commit and PR-triggered exact-head CI must also pass before Gate 9 is merged.

## Explicit non-claims

Gate 9 does not add source matching, fuzzy reconciliation, production persistence, provider authentication, Instant Settlement payout topology, multi-currency/FX, residual explanation solving, AI investigation, ERP writeback, or final benchmark/throughput claims.

## Next phase

After this checkpoint is merged and `main` CI is green, Phase 10 begins on a fresh branch: a deterministic residual-explanation solver that may propose bounded hypotheses but can never upgrade a hypothesis to financial proof without external authoritative evidence.
