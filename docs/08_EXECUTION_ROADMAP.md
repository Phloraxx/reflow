# ReFlow Execution Roadmap

> Planning date: 2026-08-29 (Asia/Kolkata).

## Deadline assumption

Razorpay's Buildathon landing page currently does not print a closing date in the page body. A current Razorpay Careers post says **apply by 5 September 2026**, and multiple current listings repeat that date. Treat **2026-09-05** as the submission deadline unless the application form states otherwise.

Official Buildathon page: https://razorpay.com/buildathon/

The internal target is to have the product feature-complete by **September 3**, leaving September 4 for verification/polish and September 5 for final submission only.

## Operating rule

Do not optimize for feature count. Optimize for reviewer signal per hour:

1. correctness;
2. evaluation credibility;
3. genuinely useful AI boundary;
4. failure handling;
5. product clarity;
6. visual polish;
7. optional features.

## Phase 0 — Research and architecture

**Status: in progress / planning package created**

Deliverables:

- competition brief;
- official Razorpay domain research;
- competitive scan;
- track decision;
- product spec;
- architecture;
- eval protocol;
- failure/safety model;
- roadmap and demo plan.

Gate to leave Phase 0:

- one-sentence problem is stable;
- exact finance loop is stable;
- schemas and safety boundaries are understood;
- evaluation denominator and metrics are defined;
- no major feature depends on unavailable live settlement data.

## Phase 1 — Financial constitution + simulator skeleton

**Target: August 30**

Build first:

- monorepo skeleton;
- typed money/ID/time contracts;
- source envelopes;
- seedable hidden-world generator;
- observation/corruption generator;
- ground-truth separation;
- first clean multi-payment settlement fixture;
- first 50+ record corpus;
- CLI that generates dataset and validates generator invariants.

Tests before moving on:

- no floats accepted for money;
- generated truth conserves money;
- every settlement composition is mathematically valid before corruption;
- observation generator cannot accidentally leak truth-only fields;
- deterministic seed reproduces byte-equivalent or logically equivalent corpus.

**No LLM integration in Phase 1.**

## Phase 2 — Event journal + payment-state reducer

**Target: August 30–31**

Build:

- source ingestion;
- deduplication;
- immutable event journal;
- payment reducer;
- late `failed → captured` handling;
- duplicate/out-of-order fixtures;
- event permutation/property tests.

Gate:

- duplicate events do not change economic totals;
- shuffled event order produces the same final state for equivalent event sets;
- late-capture scenario passes;
- malformed event is retained/rejected explicitly.

## Phase 3 — Settlement proof engine

**Target: August 31**

Build:

- normalized recon entries;
- settlement composition grouping;
- exact debit/credit equation;
- component provenance;
- deterministic reason codes;
- settlement proof object.

Gate:

- clean grouped settlements reconcile exactly;
- missing/duplicate/wrong component creates the correct exception;
- evaluator can detect an intentionally wrong proof;
- all arithmetic remains integer paise.

## Phase 4 — Bank matching + exception engine

**Target: September 1**

Build:

- bank-ledger schema;
- UTR/amount/time candidate generation;
- safe auto-match authorization;
- ambiguity detection;
- pending bank-credit timing state;
- typed exceptions;
- evidence graph/provenance API.

Gate:

- exact UTR + wrong amount never auto-matches;
- same-amount settlements do not cross-match;
- duplicate bank rows do not double-credit;
- settlement.processed can remain pending before bank proof;
- row ordering does not change outcomes.

At this point we must have a fully useful **non-AI** finance controller.

## Phase 5 — Evaluation harness v1

**Target: September 1**

Before adding AI, run a meaningful benchmark.

Build:

- Baseline A (exact IDs/UTR only);
- ReFlow deterministic core arm;
- raw decision export;
- metrics report;
- exception CSV;
- confusion matrix;
- throughput measurement;
- multi-seed runner.

Gate:

- ≥1,000 transaction-level records run end to end;
- denominator equals generated scope;
- no unexplained dropped rows;
- false-match detector has been proven by injecting one deliberate wrong link;
- all headline metrics can be regenerated from raw artifacts.

## Phase 6 — Bounded AI investigator

**Target: September 2**

Build only after deterministic core and eval exist.

Build:

- model-provider abstraction;
- finite read-only tool registry;
- typed structured output;
- evidence validator;
- numeric-faithfulness validator;
- action/proposal gate;
- timeout/fallback;
- agent audit record;
- offline recorded-decision/replay support if practical.

Start with one inexpensive/fast model. Model choice is not a product identity.

Candidate providers can be compared on a small held-out set using identical cases. Choose based on measured correctness/latency/cost, not reputation.

Gate:

- hallucinated evidence IDs are rejected;
- model outage does not affect deterministic batch result;
- ambiguous cases can abstain;
- agent improves investigation/resolution usefulness without increasing silent false financial matches;
- raw tool calls/results are retained for evaluation.

## Phase 7 — Product UI

**Target: September 2–3**

Build a focused operator console:

1. Overview — money reconciled, pending, exception amount.
2. Settlement proof — visual many-to-one flow and arithmetic.
3. Exceptions inbox — impact/age prioritized.
4. Investigation — evidence + AI reasoning + safe next step.
5. Audit — chronological provenance.
6. Evaluation — current benchmark with limitations.

UI principles:

- no generic chat-first homepage;
- proof before prose;
- progressive disclosure;
- one obvious action per exception;
- use whitespace and typography rather than excessive cards;
- desktop-first for judging, responsive enough for mobile;
- animations only when they explain money flow/state transition.

Gate:

A reviewer should understand the problem and the project's differentiator within 30 seconds without reading the README.

## Phase 8 — Razorpay Test Mode adapter

**Target: September 3; optional if it threatens core quality**

Use real Razorpay test APIs where they add signal:

- payment/order fetch;
- webhook verification/ingestion;
- payment status examples;
- optional settlement/recon fetch when data exists.

Do **not** fake a live settlement. The connected account currently has no settlements, so the demo must clearly label synthetic settlement data vs live Razorpay test data.

A useful live demo is proving that the same ingestion/state machinery can accept a real Razorpay Test Mode payment object/event while the settlement benchmark remains synthetic.

## Phase 9 — Adversarial pass + failure log

**Target: September 3**

Actively try to break ReFlow:

- duplicate everything;
- shuffle events/rows;
- delete recon components;
- wrong UTR amounts;
- same amounts;
- malformed timestamps;
- agent prompt injection inside description/narration;
- provider timeout;
- rerun same batch;
- inject evaluator bug checks.

Create `FAILURE_LOG.md` with genuine failures discovered.

Feature freeze after this phase.

## Phase 10 — Final benchmark and reproducibility

**Target: September 4 morning**

Freeze code/config, then generate final held-out corpus and run:

- Baseline A;
- deterministic ReFlow;
- bounded-AI arm on suitable exception subset;
- multiple seeds if compute/time permits.

Generate:

- exact result JSON;
- EVALUATION.md;
- exception list;
- failure slices;
- charts;
- environment/run metadata.

Do not edit headline numbers manually after generation.

## Phase 11 — README + architecture presentation + demo

**Target: September 4**

README order:

1. one-sentence claim;
2. measured result — only after final eval;
3. 30-second visual/GIF;
4. why the problem is hard;
5. architecture;
6. demo scenarios;
7. evaluation methodology;
8. failure/limitations;
9. run locally;
10. docs links.

Prepare architecture diagram specifically for the pitch; do not show a 40-box unreadable diagram.

## Phase 12 — Five-minute pitch and submission

**Target: September 4 evening; September 5 only as buffer**

Record after all numbers are frozen.

Do one full technical verification before submission:

- fresh clone works;
- README commands work;
- public repo contains no secret;
- deployed demo loads without auth surprise;
- demo fixture is deterministic;
- video links are public;
- architecture image is readable;
- final benchmark artifact matches README numbers;
- branch is clean and latest commit is pushed.

## Scope-sacrifice order if time slips

Cut in this order:

1. optional live settlement adapter;
2. fancy animation;
3. extra model providers;
4. hash-chained audit ledger;
5. transfer/Route support;
6. screenshot/OCR import;
7. advanced tax logic.

Never cut:

- many-to-one settlement proof;
- event idempotency/order handling;
- adversarial synthetic benchmark;
- honest exceptions;
- deterministic AI guard boundary;
- usable UI;
- reproducible README/demo.

## Definition of done

ReFlow is done when a skeptical reviewer can clone it, generate an unseen synthetic batch, run reconciliation, inspect a grouped settlement proof, see intentionally unresolved exceptions, run the bounded agent on one, and reproduce every reported metric without trusting us or the LLM.
