# Razorpay Alignment and Judging Strategy

## Purpose

This document turns Razorpay's public Buildathon brief and the actual submission form into an explicit build contract.

The goal is to prevent a common hackathon failure mode: building an impressive system that does not answer the questions the judges are actually asking.

---

## 1. What the official Buildathon page requires

Razorpay describes the program as a student-only hiring challenge for AI Builder Interns.

The public page states:

- students only;
- 6- or 12-month AI Builder Internship;
- in-person in Bangalore from September;
- no resume screening;
- no long application;
- pick a track;
- build something real;
- show the work through a **public repository, a five-minute pitch video, and the architecture**;
- strong submissions go to a panel.

Source: https://razorpay.com/buildathon/

For Track 04 — AI Finance Controller, Razorpay asks participants to:

> close one finance-ops loop across a 50+ record batch of synthetic data, reporting match rate and exceptions that could not be resolved.

The stated bar is:

> throughput + measured accuracy + an honest exception list.

Razorpay explicitly warns that one cherry-picked match proves nothing.

---

## 2. What the actual submission form asks

The public Google Form linked by Razorpay contains the following fields/questions as of the research date:

### Eligibility/profile

- Email
- Full Name
- College Name
- Graduation Year: 2027 / 2028 / 2029
- In-person Internship availability starting September: Yes / No
- Preferred Internship Duration: 6-Month Internship / 12-Month Internship

### Project submission

- Selected Track
- Project Name / Title
- Project Objectives — **“What does it solve?”**
- GitHub Repository URL
- 5-min Pitch Video Link
- **Build Challenges & Technical Obstacles — “What issues did you face while building, and how did you solve them?”**
- Final Submission Confirmation

This last technical-obstacles field is especially important. It means we should intentionally preserve:

- failed assumptions;
- benchmark bugs;
- architecture changes;
- incorrect baselines;
- adversarial failures;
- model failures;
- scale bottlenecks;
- what test exposed each problem;
- what changed after the failure.

We should not manufacture failures for storytelling. We should record the real ones as they occur.

---

## 3. Track 04 requirement → ReFlow evidence matrix

| Razorpay asks for | ReFlow deliverable | Evidence shown to judge |
|---|---|---|
| one finance-ops loop | payment/settlement/bank reconciliation | end-to-end batch run |
| 50+ synthetic records | seedable adversarial corpus | checked-in generator + manifest |
| match rate | proven reconciliation rate | generated evaluation report |
| throughput | records/settlements/proofs per second | reproducible benchmark |
| measured accuracy | compare proof graph to hidden truth | deterministic scorer |
| honest exceptions | typed residuals/contradictions | exception table + drilldown |
| meaningful AI | adapter synthesis + bounded investigation | unknown-file demo + investigation case |
| architecture | finance compiler + Money Graph + proofs | README diagram + architecture doc |
| something real | working app + CLI/API | live/local demo |
| public repo | complete reproducible repository | GitHub |
| 5-min pitch | tightly scripted demo | video link |
| technical challenges | FAILURE_LOG.md / build journal | submission-form answer |

---

## 4. What “meaningful AI” means for ReFlow

A Track 04 submission still needs AI. We should not hide behind a deterministic reconciliation engine and attach a decorative chatbot.

AI gets two substantive jobs.

### Job A — Source Adapter Synthesizer

AI understands an unfamiliar financial export and proposes a constrained semantic mapping to ReFlow's canonical schema.

It is meaningful because this is a genuinely semantic task with large format variation.

It is safe because:

- the output is a typed AdapterSpec;
- generated arbitrary code is forbidden;
- the adapter must compile;
- sample and financial invariants must pass;
- drift is quarantined;
- once compiled, production parsing is deterministic.

### Job B — Exception Investigation Agent

The agent receives a typed exception and uses bounded read-only tools to gather evidence.

It can:

- compare proof versions;
- inspect payment timelines;
- inspect source health;
- inspect residual candidates;
- identify missing evidence;
- propose the next investigation action.

It cannot:

- edit source amounts;
- attach a bank row as truth;
- mark a settlement reconciled;
- execute arbitrary SQL;
- create financial facts.

This mirrors Razorpay's own Agent Studio philosophy: verified data, bounded tools, independent validation and auditability.

Source: https://razorpay.com/blog/razorpay-agent-studio-principles-guardrails-and-merchant-control/

---

## 5. Why ReFlow should look novel to Razorpay

Razorpay itself already has:

- settlement reports/recon APIs;
- Single View Recon in Optimizer;
- an Agentic Dashboard that can assist reconciliation;
- Agent Studio;
- AI/payment products.

Therefore our novelty cannot be:

> “AI reads a bank statement and matches transactions.”

That would overlap a product Razorpay publicly describes.

Instead the novelty story is:

### A. Proof-carrying reconciliation

Every green result comes with a machine-verifiable financial proof.

### B. Temporal truth

Reconciliation evolves as evidence arrives; prior proof versions remain inspectable.

### C. Residual-first investigation

The product explains exact unexplained value rather than merely ranking row similarity.

### D. AI-compiled connectors

AI tackles source heterogeneity once, then gets removed from the runtime hot path.

### E. Exception-family detection

At enterprise scale, ReFlow recognizes systemic patterns instead of opening thousands of identical cases.

### F. One correctness model from CSV to stream

Small merchants and high-volume institutions use the same financial invariants.

---

## 6. Match Razorpay's engineering culture, not only the prompt

Razorpay Engineering's August 2026 evaluation write-up gives us unusually clear cultural signals.

They value:

- bespoke evaluation over generic benchmark claims;
- evaluating the whole workbench rather than the model alone;
- same corpus/same conditions for comparisons;
- deterministic seeded selection;
- validation before spend;
- stored raw decisions;
- safe failure;
- reproducibility;
- multiple metrics rather than one headline accuracy number;
- model optionality.

Source: https://razorpay.com/blog/?p=27428

ReFlow's evaluation should visibly adopt these principles.

Specific implementation consequences:

1. every benchmark has a run manifest;
2. corpus generation is seeded;
3. hidden truth is separate from observations;
4. baseline and candidate run on identical items;
5. deterministic metrics never use judge models;
6. agent outputs are stored/replayable where practical;
7. model provider is behind a small interface;
8. AI-off mode remains functional;
9. we publish failures/uncertainty rather than smoothing them away.

---

## 7. Metrics we should publish

### Core Track 04 metrics

- total records;
- total settlements;
- match/proven rate;
- status accuracy;
- relationship/edge accuracy;
- exception classification accuracy;
- throughput.

### Safety metrics

- silent false auto-match count/rate;
- ambiguous cases incorrectly auto-matched;
- contradictory evidence incorrectly accepted;
- duplicate economic movement count;
- amount/unit semantic errors reaching truth layer.

### Operational metrics

- p50/p95 proof latency;
- incremental recompute latency;
- source parse failure rate;
- schema drift detection;
- exception queue size;
- proof aging / waiting-for-evidence distribution.

### AI metrics

- adapter semantic field accuracy;
- unsafe adapter activation rate;
- investigation proposal validity;
- evidence citation faithfulness;
- unsupported financial claims;
- tool calls per exception;
- AI calls per 1M source records;
- cost/latency by model where evaluated.

---

## 8. Required baselines

Do not compare only against a deliberately terrible system.

Suggested baselines:

### B0 — exact naive 1:1

- payment/amount/reference direct row matching;
- no grouped settlement decomposition.

Shows why many-to-one matters.

### B1 — grouped deterministic baseline

- settlement grouping;
- exact arithmetic;
- exact UTR bank match;
- no residual solver;
- no adapter AI;
- no investigation AI.

This should be a strong baseline.

### B2 — fuzzy reconciliation baseline

- deterministic candidate blocking;
- amount/time/narration similarity;
- threshold-based match.

Used to quantify false-positive risk.

### ReFlow Core

- full Money Graph + proof system + residual logic;
- no AI.

### ReFlow + AI

- Core + Source Adapter Synthesizer + Investigation Agent.

This separation tells us whether AI actually adds value.

---

## 9. The five-minute pitch should answer the form before the reviewer asks

### 0:00–0:25 — Problem

Show one bank settlement and dozens/hundreds of contributing movements.

Message:

> Reconciliation isn't row matching. It is proving where money came from, what changed it, and whether it actually reached the bank.

### 0:25–0:55 — Novel idea

Show:

```text
Messy Sources → Finance Compiler → Money Graph → Proof / Residual
```

Say:

> Every rupee gets a path, a proof, or an exception.

### 0:55–1:45 — Messy data demo

Upload an unfamiliar bank/merchant export.

AI proposes adapter.

Compiler tests it.

One unsafe mapping is rejected or one schema drift is caught.

### 1:45–2:45 — Reconciliation proof

Run the batch.

Open one settlement proof and visually show the equation and bank evidence.

### 2:45–3:25 — Hard exception

Show a residual/ambiguous case.

Agent investigates, cites evidence, and correctly refuses to claim reconciliation without missing evidence.

### 3:25–4:10 — Scale/evaluation

Show actual measured results across multiple dataset sizes and adversarial conditions.

### 4:10–4:40 — What broke

Show one real technical failure and the test/fix.

### 4:40–5:00 — Finish

End with actual measured facts:

- records processed;
- proven rate;
- false auto-match rate;
- unresolved count;
- throughput.

No invented numbers before final benchmark.

---

## 10. “Project Objectives” draft direction

Do not use this exact text until implementation/results are real, but the intended form answer should be structurally similar:

> ReFlow is an evidence-first finance controller that reconciles merchant orders, Razorpay payment/refund/settlement data and bank credits. Instead of letting an LLM guess matches, it compiles messy sources into a canonical Money Graph and produces machine-verifiable reconciliation proofs. AI is used to safely compile unknown source formats and investigate unresolved exceptions using read-only evidence tools. The system is evaluated on seeded adversarial batches across duplicates, out-of-order events, late captures, refunds, adjustments, missing evidence, schema drift and ambiguous bank records, reporting throughput, measured accuracy and every unresolved case.

Update with real benchmark results later.

---

## 11. “Build Challenges & Technical Obstacles” strategy

Maintain `FAILURE_LOG.md` from the first implementation day.

Each entry:

```text
Date
Symptom
Initial assumption
Test/data that exposed it
Root cause
Why the old design was unsafe/wrong
Fix
Regression test
Metric impact
Remaining limitation
```

Candidate categories likely to generate legitimate entries:

- settlement sign semantics;
- duplicate handling;
- failed→captured reducer ordering;
- rupee/paise parsing;
- ambiguous bank matching;
- residual solver combinatorial explosion;
- synthetic generator leakage;
- unfair baseline;
- AI adapter wrong unit/sign inference;
- prompt injection in narration;
- model provider timeout;
- scale bottleneck;
- schema drift false positive.

This file should become one of the most credible parts of the submission.

---

## 12. Repository quality bar

Razorpay says “your code speaks louder than your resume.” Treat the repository as the interview.

Before submission it should have:

```text
README.md
AGENTS.md
ARCHITECTURE.md or docs/architecture
FAILURE_LOG.md
EVALUATION.md
SECURITY.md
LIMITATIONS.md
DEMO.md
```

And:

- one-command local run;
- one-command deterministic benchmark;
- `.env.example` with no credentials;
- test suite;
- typed contracts;
- screenshots/GIF after UI is real;
- current docs, not aspirational stale docs;
- no fake badges/results;
- clear “real vs simulated” section.

Razorpay Engineering also publicly emphasizes context, testing and CI/CD as pillars of an “agent ready” repository, which is another reason to keep repo guidance and validation strong.

Source: https://razorpay.com/blog/?p=26885

---

## 13. Final submission gate

Do not submit until all are true:

- [ ] Track 04 selected
- [ ] project name/title final
- [ ] public GitHub repository clean
- [ ] 50+ dataset requirement satisfied
- [ ] larger benchmark run complete
- [ ] throughput measured
- [ ] accuracy measured against hidden truth
- [ ] exception list included
- [ ] silent false-match metric included
- [ ] at least one meaningful AI workflow demonstrated
- [ ] AI-off deterministic core demonstrated
- [ ] one graceful failure demonstrated
- [ ] real technical obstacle documented
- [ ] five-minute video under limit
- [ ] no secrets in repository/video
- [ ] limitations explicitly stated
- [ ] all headline metrics reproducible from repo
- [ ] final form answers copied from measured evidence, not memory
