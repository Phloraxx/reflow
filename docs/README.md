# ReFlow Research and Planning Index

This directory contains the research and implementation plan for ReFlow.

If you are reviewing the project for the first time, **do not read the files strictly by number**. The project went through a deliberate research-driven pivot and a second deeper research pass.

## Start here

1. [`32_GATE_15_CHECKPOINT.md`](32_GATE_15_CHECKPOINT.md) — **implemented journal-first Razorpay webhook/API/recon provider boundary and proof-kernel compatibility.**
2. [`31_GATE_15_REAL_RAZORPAY_CONTRACT_AND_ACCEPTANCE_PLAN.md`](31_GATE_15_REAL_RAZORPAY_CONTRACT_AND_ACCEPTANCE_PLAN.md) — frozen Gate 15 provider contract and acceptance plan.
3. [`30_GATE_14_CHECKPOINT.md`](30_GATE_14_CHECKPOINT.md) — deterministic ExceptionCase lifecycle, dispositions, supersession and incident fingerprints/clusters.
4. [`29_GATE_14_CONTRACT_AND_ACCEPTANCE_PLAN.md`](29_GATE_14_CONTRACT_AND_ACCEPTANCE_PLAN.md) — frozen Gate 14 contract and acceptance plan.
5. [`28_GATE_13_CHECKPOINT.md`](28_GATE_13_CHECKPOINT.md) — deterministic reconciliation control plane.
6. [`27_STRATEGIC_PAUSE_CURRENT_STATE_AND_REVISED_PLAN.md`](27_STRATEGIC_PAUSE_CURRENT_STATE_AND_REVISED_PLAN.md) — authoritative post-Gate-12 architecture review and revised Gates 13–19.
7. [`26_GATE_12_CHECKPOINT.md`](26_GATE_12_CHECKPOINT.md) — AI-assisted source-compiler checkpoint.
8. [`25_GATE_11_CHECKPOINT.md`](25_GATE_11_CHECKPOINT.md) — baseline evaluation/scorer/artifact checkpoint.
9. [`24_GATE_10_CHECKPOINT.md`](24_GATE_10_CHECKPOINT.md) — bounded residual-hypothesis checkpoint.
10. [`23_GATE_9_CHECKPOINT.md`](23_GATE_9_CHECKPOINT.md) — immutable versioned full-proof checkpoint.
11. [`22_THIRD_INDEPENDENT_PRE_GATE_9_AUDIT.md`](22_THIRD_INDEPENDENT_PRE_GATE_9_AUDIT.md) — pre-Gate-9 foundation audit.
12. [`16_MASTER_BUILD_PLAN.md`](16_MASTER_BUILD_PLAN.md) — pre-review roadmap; docs 27–32 supersede its post-Gate-12 sequence/status.

---

## Problem research

- [`01_BUILDATHON_BRIEF.md`](01_BUILDATHON_BRIEF.md) — initial Buildathon requirements.
- [`02_RAZORPAY_RESEARCH.md`](02_RAZORPAY_RESEARCH.md) — Razorpay settlement/recon/webhook research.
- [`03_COMPETITIVE_ANALYSIS.md`](03_COMPETITIVE_ANALYSIS.md) — public Buildathon field and Track 03 → Track 04 decision.
- [`10_FINANCE_OPS_PROBLEM_LANDSCAPE.md`](10_FINANCE_OPS_PROBLEM_LANDSCAPE.md) — real reconciliation/finance-ops pain points across merchants and institutions.

## Product and architecture

- [`04_PRODUCT_SPEC.md`](04_PRODUCT_SPEC.md) — original Track 04 product scope.
- [`05_ARCHITECTURE.md`](05_ARCHITECTURE.md) — initial evidence-first architecture.
- [`11_NOVEL_PRODUCT_THESIS.md`](11_NOVEL_PRODUCT_THESIS.md) — current product thesis.
- [`12_MONEY_GRAPH_AND_RECONCILIATION_PROOFS.md`](12_MONEY_GRAPH_AND_RECONCILIATION_PROOFS.md) — proof protocol.
- [`13_MESSY_DATA_AND_CONNECTOR_COMPILER.md`](13_MESSY_DATA_AND_CONNECTOR_COMPILER.md) — adapter compiler.
- [`14_SCALE_PERFORMANCE_AND_RESILIENCE.md`](14_SCALE_PERFORMANCE_AND_RESILIENCE.md) — performance/resilience.
- [`18_CREATIVE_FEATURE_CATALOG.md`](18_CREATIVE_FEATURE_CATALOG.md) — creative features and priority.

## Evaluation and safety

- [`06_EVALUATION_PLAN.md`](06_EVALUATION_PLAN.md) — initial hidden-truth adversarial evaluation plan.
- [`07_FAILURE_SAFETY_MODEL.md`](07_FAILURE_SAFETY_MODEL.md) — failure taxonomy and AI boundaries.
- [`15_RAZORPAY_ALIGNMENT_AND_JUDGING_STRATEGY.md`](15_RAZORPAY_ALIGNMENT_AND_JUDGING_STRATEGY.md) — judging metrics, baselines and final evidence requirements.
- [`../FAILURE_LOG.md`](../FAILURE_LOG.md) — genuine implementation failures and fixes as they happen.
- [`../LIMITATIONS.md`](../LIMITATIONS.md) — current limitations and explicit non-claims.
- [`22_THIRD_INDEPENDENT_PRE_GATE_9_AUDIT.md`](22_THIRD_INDEPENDENT_PRE_GATE_9_AUDIT.md) — pre-Gate-9 line-by-line implementation audit.
- [`23_GATE_9_CHECKPOINT.md`](23_GATE_9_CHECKPOINT.md) — Gate 9 implementation, failure findings, versioning invariants and checkpoint evidence.
- [`24_GATE_10_CHECKPOINT.md`](24_GATE_10_CHECKPOINT.md) — Gate 10 bounded residual hypotheses, scale shape, failure findings and checkpoint evidence.
- [`25_GATE_11_CHECKPOINT.md`](25_GATE_11_CHECKPOINT.md) — Gate 11 baselines, semantic scorer, verifiable artifacts, failure findings and checkpoint evidence.
- [`26_GATE_12_CHECKPOINT.md`](26_GATE_12_CHECKPOINT.md) — Gate 12 journal-first source compiler, approval lifecycle, adapter benchmarks and end-to-end runtime lineage.
- [`28_GATE_13_CHECKPOINT.md`](28_GATE_13_CHECKPOINT.md) — Gate 13 scope/run/source-completeness, evidence-coverage, balance-control and close-readiness checkpoint.
- [`29_GATE_14_CONTRACT_AND_ACCEPTANCE_PLAN.md`](29_GATE_14_CONTRACT_AND_ACCEPTANCE_PLAN.md) — Gate 14 frozen contract/acceptance plan.
- [`30_GATE_14_CHECKPOINT.md`](30_GATE_14_CHECKPOINT.md) — Gate 14 case lifecycle, workflow separation, supersession and incident-grouping checkpoint.
- [`31_GATE_15_REAL_RAZORPAY_CONTRACT_AND_ACCEPTANCE_PLAN.md`](31_GATE_15_REAL_RAZORPAY_CONTRACT_AND_ACCEPTANCE_PLAN.md) — Gate 15 frozen provider contract/acceptance plan.
- [`32_GATE_15_CHECKPOINT.md`](32_GATE_15_CHECKPOINT.md) — Gate 15 Razorpay provider boundary, failure findings and proof-kernel compatibility checkpoint.

## Execution and submission

- [`08_EXECUTION_ROADMAP.md`](08_EXECUTION_ROADMAP.md) — first roadmap.
- [`09_DEMO_SUBMISSION_PLAN.md`](09_DEMO_SUBMISSION_PLAN.md) — initial five-minute pitch plan.
- [`16_MASTER_BUILD_PLAN.md`](16_MASTER_BUILD_PLAN.md) — comprehensive pre-review roadmap; post-Gate-12 sequencing is superseded by doc 27.

---

## Current hierarchy of truth

If two planning documents conflict, use this order:

1. implementation + tests
2. latest implemented checkpoint (`32_GATE_15_CHECKPOINT.md`)
3. frozen current gate contract (`31_GATE_15_REAL_RAZORPAY_CONTRACT_AND_ACCEPTANCE_PLAN.md`)
4. `30_GATE_14_CHECKPOINT.md` / `29_GATE_14_CONTRACT_AND_ACCEPTANCE_PLAN.md`
5. `27_STRATEGIC_PAUSE_CURRENT_STATE_AND_REVISED_PLAN.md` for the revised post-Gate-12 architecture/sequence
6. `28_GATE_13_CHECKPOINT.md` and earlier implemented checkpoints
7. `16_MASTER_BUILD_PLAN.md`
8. `15_RAZORPAY_ALIGNMENT_AND_JUDGING_STRATEGY.md`
9. `11`–`14` and `18`
10. `17_RESEARCH_SOURCEBOOK.md` for sourced facts
11. `04`–`09` as earlier planning history

If implementation/evaluation contradicts any document, update the plan and preserve the finding in `FAILURE_LOG.md` where appropriate.

---

## Product in one sentence

> **ReFlow is an evidence-first finance controller that compiles messy payment data into reproducible reconciliation runs, exact money proofs, balance controls and explicit exceptions; AI assists with schema understanding and later investigation, but never defines financial truth.**
