# ReFlow Evaluation Plan

## Principle

The evaluation is a product feature. Track 04 explicitly asks for throughput, measured accuracy and unresolved exceptions across a batch. Razorpay's own engineering writing also emphasizes representative corpora, same-item comparisons, deterministic selection, safe failure and evidence-driven evaluation.

Source: https://razorpay.com/blog/?p=27428

No model or policy is allowed to see evaluation ground truth.

## Evaluation questions

ReFlow must answer five separate questions:

1. **Financial correctness:** did it reconstruct the right money movements and settlement totals?
2. **Identity correctness:** did it link the right entities together?
3. **Safety:** when uncertain, did it refuse to create a false financial match?
4. **Exception usefulness:** did it classify and investigate discrepancies correctly?
5. **Operational quality:** can it do this fast and reproducibly across a non-trivial batch?

A single “accuracy” number is insufficient.

## Dataset design

### Minimum published benchmark

Target at least:

- 1,000 merchant orders;
- 1,000+ payment attempts (more than orders because retries can exist);
- 10–30 grouped settlements;
- corresponding bank ledger entries;
- payments, refunds and adjustments;
- duplicate and out-of-order event journal entries;
- at least 12 anomaly families;
- deterministic seed recorded in the report.

We may use smaller quick-test corpora during development. The published benchmark must exceed Razorpay's 50-record minimum substantially.

## Synthetic world separation

Keep generation in two logical layers:

### World generator

Creates hidden financial truth:

- orders;
- payment attempts and final truth;
- refunds;
- adjustments;
- settlement composition;
- true bank credits;
- canonical identity links.

### Observation generator

Transforms truth into imperfect source feeds:

- merchant ledger;
- webhook/event journal;
- Razorpay recon feed;
- settlement records;
- bank ledger.

It injects corruption, missingness, duplication, delay and reordering.

The reconciliation engine receives only observations.
Ground truth lives in a separate file/object consumed only by the evaluator.

This prevents the system from being correct by construction.

## Adversarial scenario matrix

Every scenario gets an explicit fixture or generated category and at least one regression test.

| Family | Example | Expected safe behavior |
|---|---|---|
| Clean grouped settlement | 80 payment/recon rows → one bank credit | prove reconciliation |
| Duplicate webhook | same event delivered 2–4 times | count economic movement once |
| Out-of-order events | captured arrives before earlier failed delivery | same final state as correctly ordered history |
| Late authorization | failure observation later superseded by captured truth | capture exactly once |
| Missing event | recon says payment exists but webhook missing | use authoritative available evidence; flag source gap if relevant |
| Refund | captured payment later refunded and debit appears in settlement | exact net arithmetic |
| Adjustment | adjustment explains otherwise unexplained residual | resolve with evidence |
| Missing recon row | settlement amount cannot be reconstructed | composition exception |
| Wrong recon amount | entity IDs align but money does not | fail closed |
| Bank credit delayed | settlement processed; credit not yet observed | pending/wait, not immediate missing |
| Missing bank credit | observation horizon elapsed | missing-credit exception |
| Same-amount settlements | two settlements have identical amount | do not cross-match; prefer UTR |
| Exact UTR, wrong amount | identity points to row but amount impossible | mismatch exception |
| Duplicate bank row | same UTR/credit duplicated | do not credit twice |
| Unknown bank credit | unrelated credit exists | leave unmatched |
| Garbled narration | UTR omitted or damaged | candidate generation only, no unsafe fuzzy auto-match |
| Timestamp skew | otherwise valid records slightly shifted | bounded policy, deterministic outcome |
| Currency corruption | INR settlement + wrong-currency row | source integrity exception |
| Integer overflow/boundary | very large paise values | reject safely |
| Conflicting IDs | payment/order relationship impossible | integrity/review exception |
| Agent hallucination | model cites nonexistent evidence ID | proposal rejected |
| Agent timeout | provider stalls | deterministic result remains; investigation unresolved |
| Agent unavailable | no API key/network | core benchmark still runs |

## Deterministic-core metrics

### 1. Settlement amount correctness

For each settlement:

`predicted_expected_net_paise == ground_truth_expected_net_paise`

Report exact count and percentage.

### 2. Entity-link precision and recall

For proven edges such as payment→settlement and settlement→bank:

- precision;
- recall;
- F1.

Incorrect auto-links are false positives and should be treated more severely than unresolved candidates.

### 3. Silent false-match rate

The key safety metric:

`wrong auto-approved matches / all auto-approved matches`

Target is **0 in the published synthetic benchmark**. This is a target, not a result claim. If it is non-zero, publish it and fix the architecture rather than hiding the case.

### 4. Exception classification

Per-class precision/recall/F1 and confusion matrix over anomaly classes that have enough support.

### 5. Unresolved rate

`REQUIRES_REVIEW / total scoped cases`

Report it honestly. Lower is not always better: an engine that guesses can artificially drive this to zero.

### 6. Residual money

Sum absolute unexplained residual paise after deterministic reconciliation:

- before investigation;
- after safe deterministic rechecks;
- after bounded agent investigation.

Do not count an AI explanation as “money resolved” unless deterministic invariants subsequently prove the resolution.

### 7. Coverage

Every input record must land in one of:

- contributing to a proven reconciliation;
- explicitly pending;
- explicitly excepted;
- explicitly rejected as malformed/duplicate with audit status.

No dropped rows.

## Agent metrics

The AI should be evaluated only on cases where AI is actually useful.

Create a held-out exception corpus with ground-truth investigation labels unavailable to the agent.

Measure:

### Tool selection accuracy

Did the agent choose a useful allowed tool sequence for the exception?

### Root-cause classification

Macro precision/recall/F1 over the finite root-cause taxonomy plus `UNKNOWN`.

### Evidence faithfulness

Every evidence ID named by the model must exist in its tool observations.

`unsupported_evidence_claim_rate` should be reported.

### Numeric faithfulness

Numbers in displayed prose must be extractable from deterministic tool output. A validator can reject or regenerate unfaithful narration.

### Safe-action accuracy

Did the proposal choose an allowed next step? Did the deterministic validator accept or reject it appropriately?

### Abstention quality

On deliberately ambiguous cases, does the model choose `UNKNOWN` / human review rather than manufacture certainty?

### Latency and cost

Record:

- p50/p95 agent latency;
- token/input/output counts where provider supports it;
- approximate cost;
- timeout/failure rate.

## Baselines

We need fair baselines, not intentionally weak ones.

### Baseline A — exact IDs/UTR only

Strong deterministic baseline using exact entity IDs and exact UTR, with no exception investigation.

### Baseline B — deterministic ReFlow core

Full state reducer + settlement math + candidate/match policies + typed exceptions, no LLM.

### Candidate C — ReFlow core + bounded AI investigation

Same deterministic core. Agent can gather evidence and propose safe next steps.

The interesting question is not “does an LLM beat no logic?” It is:

**Does bounded AI resolve/investigate more genuinely ambiguous operational cases without increasing silent financial error?**

If it does not, report that. A negative result can still demonstrate sound engineering.

## Fair-comparison protocol

- identical generated world and observations for all arms;
- fixed public seeds for reproducibility;
- separate hidden/held-out seed for final run created only after core policy is frozen;
- no per-arm corruption differences;
- no baseline denied evidence that ReFlow receives unless the experiment explicitly studies that evidence;
- raw decisions persisted;
- evaluation scripts recompute metrics from raw outputs rather than trusting precomputed totals.

## Statistical reporting

For core deterministic metrics on sufficiently large datasets, exact counts are primary.

For agent classification/decision metrics, report bootstrap confidence intervals where practical. Do not imply significance from tiny samples.

Use multiple seeds for robustness:

- development seeds;
- regression seed set;
- final held-out seed set.

## Property-based / metamorphic tests

Some correctness properties are stronger than example fixtures.

### Event permutation invariance

For a semantically identical event set, randomly permuting delivery order must not change final financial state.

### Duplicate invariance

Adding another copy of an already-seen source event must not change economic totals.

### Row-order invariance

Shuffling recon and bank input rows must not change results.

### Paise conservation

For a proven settlement, sum of its signed component movements must equal the settlement amount exactly.

### Irrelevant-noise invariance

Adding unrelated bank rows must not change an already-proven settlement link.

### Ambiguity monotonicity

Adding a second equally plausible bank candidate must never increase confidence to auto-match.

## Failure log

Create `FAILURE_LOG.md` during implementation. Every meaningful evaluation bug or architecture mistake should record:

- symptom;
- test/eval that exposed it;
- root cause;
- whether engine, dataset or evaluator was wrong;
- fix;
- regression test;
- impact on previously reported numbers.

This is not cosmetic. Strong public competitors already show that transparent failure analysis is persuasive, and Razorpay's engineering culture clearly values evaluation infrastructure.

## Publication artifacts

The final repo should contain machine-readable and human-readable results:

```text
data/eval/final_manifest.json
out/eval/core_metrics.json
out/eval/agent_metrics.json
out/eval/exceptions.csv
out/eval/confusion_matrix.csv
out/eval/run_metadata.json
EVALUATION.md
FAILURE_LOG.md
```

Charts should be generated by scripts from raw metrics, never manually edited.

## Gate to move from implementation to polish

Before spending significant time on visual polish, all must be true:

- ≥50 records run end to end;
- no data disappears from denominator;
- event duplicate/reordering tests pass;
- settlement equation tests pass;
- bank-match ambiguity tests pass;
- evaluation can detect a deliberately inserted false match;
- benchmark command produces a report from scratch.

Then increase scale and build the final UI/demo.
