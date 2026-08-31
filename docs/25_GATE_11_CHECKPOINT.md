# Gate 11 Checkpoint — Baseline Evaluation Harness

**Status:** implementation complete. Checkpoint acceptance requires exact-head CI, PR-triggered CI, merge, and `main` CI.

Gate 11 exists to make ReFlow measurable without letting the benchmark become easier to fool than the financial engine it evaluates.

## Implemented comparison arms

- `B0_naive_1to1` — deliberately simplistic one-row amount matching.
- `B1_grouped_exact` — strong grouped deterministic baseline with exact UTR and identity-uniqueness safeguards.
- `B2_fuzzy_threshold` — deterministic fuzzy bank baseline using amount/time/narration/UTR signals.
- `ReFlow_Core` — Gates 5–9 deterministic reconciliation pipeline; no AI authority.

All four arms receive the **same journal-backed canonical batch**. Candidate code never receives `HiddenWorld`, scenario labels, or generator metadata.

## Evaluation boundary

```text
HiddenWorld
    ↓ observation corruption
ObservedBatch
    ↓ same journal-first deterministic ingestion
CanonicalBatch
    ├─ B0
    ├─ B1
    ├─ B2
    └─ ReFlow Core
          ↓
CandidateDecision objects
          ↓ post-run truth projection
semantic scorer
```

## Candidate decisions carry evidence, not claims

`CandidateDecision` carries the selected canonical `SettlementReconEntry` and `BankEntry` objects. These are derived from the exact evidence each arm selected.

The following are derived and therefore cannot be independently supplied by a candidate:

- composition amount;
- bank amount;
- composition residual;
- bank residual;
- recon row IDs;
- bank row IDs.

This prevents a candidate from selecting one set of evidence while reporting a more flattering amount or residual.

## Semantic correctness, not ID-only correctness

A stable row ID is not enough to establish that the selected observed fact still has the same financial meaning as hidden truth.

Composition evidence is scored using the row ID, claimed settlement, economic entity kind/ID, normalized gross/fee/tax/effect values, currency, and whether the row is causally before settlement processing.

Bank evidence is scored using row ID, amount/currency, UTR, and causal relationship to settlement processing. Narration is deliberately excluded from truth identity, and a later-but-causal bank time remains valid.

## True automatic reconciliation

An automatic decision counts as true only when all are satisfied:

1. hidden truth says the settlement is actually bank-reconciled;
2. candidate settlement amount equals truth;
3. derived composition amount equals the settlement amount;
4. derived selected-bank amount equals the settlement amount;
5. selected recon evidence is semantically identical to truth evidence;
6. selected bank evidence is semantically identical to truth evidence.

Anything else that is auto-approved contributes to the silent false auto-match numerator.

Abstention can reduce recall. It can never reduce the false-match numerator by relabeling a guessed match as correct.

## Metrics

Gate 11 stores exact integer counts and denominators for:

- automatic, true automatic, false automatic, unresolved and missing decisions;
- exact decision-state counts (`RECONCILED`, `UNRESOLVED`, `RESIDUAL`, `INCOMPLETE`, `CONTRADICTED`);
- reconciliation recall;
- silent false auto-match rate;
- settlement/composition amount correctness;
- semantic composition-edge TP/FP/FN;
- semantic bank-edge TP/FP/FN;
- absolute reported residual paise.

## Baseline fairness

All baselines build one-pass indexes before per-settlement work. Throughput comparisons must not reward ReFlow merely because a baseline performs avoidable full-feed rescans.

`B1_grouped_exact` also rejects:

- duplicate economic identity inside one settlement;
- one economic identity claimed by multiple settlements;
- settlement UTR reuse across settlements;
- non-unique exact-UTR bank candidates.

`B2_fuzzy_threshold` remains intentionally less safe. A dedicated regression injects an unrelated same-amount, plausible-time, Razorpay-looking bank row with the wrong UTR and proves that the fuzzy arm can silently auto-match it while ReFlow Core refuses.

## Mutation and metamorphic tests

The harness must detect an intentionally broken “reconcile everything” candidate.

Additional checked-in regressions cover:

- wrong bank identity on a real reconciled settlement;
- correct bank row ID with corrupted amount;
- same recon ID with changed economic entity meaning;
- bank narration-only noise;
- later-but-causal bank timing;
- source row permutation;
- exact source replay;
- scenario-position shuffle across seeds;
- source schema rejection after raw evidence retention.

## Reproducible artifacts

`python -m reflow.evaluation.runner` produces a deterministic `gate11-evaluation-v2` JSON artifact containing:

- world and observation seeds;
- evaluation profile and corruption manifest;
- minimal post-run financial truth projection;
- raw selected financial evidence for every candidate decision;
- recomputed evaluation reports.

`python -m reflow.evaluation.verify <artifact.json>` reconstructs truth and candidate decisions, re-derives candidate amounts/residuals, recomputes every report, and rejects stored metrics that disagree.

Scenario labels and generator internals are not exported to candidate systems. The truth projection exists only after candidate execution so the artifact can be independently audited.

## Development profiles

`clean` exercises ordinary valid evidence.

`reconciliation_adversarial` includes canonicalizable duplicate/reordered/delayed events, failed→captured, missing/duplicate/wrong recon evidence, bank delays, narration noise, missing/corrupted UTR, prompt-like narration and partial bank-source outage.

Schema rename, malformed date and unit/schema traps remain source-adapter evaluation cases rather than being mixed into reconciliation scoring.

## Development regression evidence

The fixed development seed matrix currently keeps `ReFlow_Core.false_auto_reconciled == 0` across the checked-in adversarial seeds. This is **regression evidence only**.

It is not the final held-out benchmark, not a production accuracy claim, and not yet suitable as the competition headline number.

The final held-out seeds must remain unseen until policy/baseline/scorer freeze. If that run produces non-zero silent false auto-matches, the repository must publish them rather than edit the corpus or metric.

## Known non-claims

Gate 11 does not yet claim:

- final held-out accuracy or reconciliation rate;
- production-data accuracy;
- throughput or peak-memory results;
- million-row scale performance;
- AI improvement over deterministic core;
- real Razorpay Settlement Recon correctness;
- source-adapter accuracy on unfamiliar schemas.

Throughput/memory benchmarking remains a later scale gate. Source Adapter Compiler evaluation is a separate later gate so source-schema failures do not distort reconciliation comparisons.

## Validation checkpoint

Before documentation reconciliation, commit `8479ac5cb5dc7f71959e7d9b4d069a4b50031a70` passed Ruff, strict mypy and **176 tests** on GitHub Actions.

The final Gate 11 branch must pass the same validation again after this documentation checkpoint and then pass PR-triggered CI before merge.
