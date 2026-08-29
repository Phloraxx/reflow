# ReFlow Research and Planning Index

This directory contains the research and implementation plan for ReFlow.

If you are reviewing the project for the first time, **do not read the files strictly by number**. The project went through a deliberate research-driven pivot and a second deeper research pass.

## Start here

1. [`16_MASTER_BUILD_PLAN.md`](16_MASTER_BUILD_PLAN.md) — current implementation contract and phase gates.
2. [`15_RAZORPAY_ALIGNMENT_AND_JUDGING_STRATEGY.md`](15_RAZORPAY_ALIGNMENT_AND_JUDGING_STRATEGY.md) — exactly what Razorpay asks for and how ReFlow will prove it.
3. [`11_NOVEL_PRODUCT_THESIS.md`](11_NOVEL_PRODUCT_THESIS.md) — why ReFlow is a financial truth compiler rather than an “AI makes financial decisions” demo.
4. [`12_MONEY_GRAPH_AND_RECONCILIATION_PROOFS.md`](12_MONEY_GRAPH_AND_RECONCILIATION_PROOFS.md) — core deterministic financial model.
5. [`13_MESSY_DATA_AND_CONNECTOR_COMPILER.md`](13_MESSY_DATA_AND_CONNECTOR_COMPILER.md) — safe AI use for unfamiliar financial sources and schema drift.
6. [`14_SCALE_PERFORMANCE_AND_RESILIENCE.md`](14_SCALE_PERFORMANCE_AND_RESILIENCE.md) — same correctness model from tiny CSV batches to high-volume event processing.
7. [`18_CREATIVE_FEATURE_CATALOG.md`](18_CREATIVE_FEATURE_CATALOG.md) — ranked differentiators and scope controls.
8. [`17_RESEARCH_SOURCEBOOK.md`](17_RESEARCH_SOURCEBOOK.md) — primary sources and the design implications taken from them.

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

## Execution and submission

- [`08_EXECUTION_ROADMAP.md`](08_EXECUTION_ROADMAP.md) — first roadmap.
- [`09_DEMO_SUBMISSION_PLAN.md`](09_DEMO_SUBMISSION_PLAN.md) — initial five-minute pitch plan.
- [`16_MASTER_BUILD_PLAN.md`](16_MASTER_BUILD_PLAN.md) — **authoritative current roadmap**.

---

## Current hierarchy of truth

If two planning documents conflict, use this order:

1. `16_MASTER_BUILD_PLAN.md`
2. `15_RAZORPAY_ALIGNMENT_AND_JUDGING_STRATEGY.md`
3. `11`–`14` and `18`
4. `17_RESEARCH_SOURCEBOOK.md` for sourced facts
5. `04`–`09` as earlier planning history

If implementation/evaluation contradicts any document, update the plan and preserve the finding in `FAILURE_LOG.md` where appropriate.

---

## Product in one sentence

> **ReFlow compiles messy payment evidence into a temporal Money Graph and machine-verifiable reconciliation proofs, using AI only where semantics are genuinely ambiguous and never as the authority on financial truth.**
