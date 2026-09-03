# ReFlow Research and Planning Index

This directory contains the research and implementation plan for ReFlow.

If you are reviewing the project for the first time, **do not read the files strictly by number**. The project went through a deliberate research-driven pivot and a second deeper research pass.

## Start here

1. [`49_PRODUCTION_OBSERVABILITY_AND_OPERATOR_AUDIT_CONTRACT.md`](49_PRODUCTION_OBSERVABILITY_AND_OPERATOR_AUDIT_CONTRACT.md) — merged request telemetry, bounded metrics and durable operator-access audit gate with exact PR/main CI closure evidence.
2. [`48_PRODUCTION_DEPLOYMENT_AND_PITR_CONTRACT.md`](48_PRODUCTION_DEPLOYMENT_AND_PITR_CONTRACT.md) — merged single-host deployment and real PostgreSQL PITR mechanics gate with PR/main CI closure evidence.
3. [`47_RAZORPAY_WEBHOOK_INGRESS_CONTRACT.md`](47_RAZORPAY_WEBHOOK_INGRESS_CONTRACT.md) — merged durable Razorpay webhook ingress gate with exact PR and `main` CI closure evidence.
4. [`46_POSTGRES_BACKUP_AND_RECOVERY_CONTRACT.md`](46_POSTGRES_BACKUP_AND_RECOVERY_CONTRACT.md) — merged restore-tested PostgreSQL logical-backup gate; physical PITR mechanics are covered by doc 48.
5. [`45_AUTH_AND_SCOPE_AUTHORIZATION_CONTRACT.md`](45_AUTH_AND_SCOPE_AUTHORIZATION_CONTRACT.md) — merged Cloudflare Access authentication and exact-scope authorization boundary.
6. [`44_PRODUCTION_READINESS_PHASE1.md`](44_PRODUCTION_READINESS_PHASE1.md) — merged readiness and real-Razorpay acceptance foundation.
7. [`43_THIRD_WHOLE_CODEBASE_AUDIT.md`](43_THIRD_WHOLE_CODEBASE_AUDIT.md) — latest closed whole-codebase audit and merge evidence.
8. [`../EVALUATION.md`](../EVALUATION.md) — frozen evaluation metrics, denominators, exception list and reproduction commands.
9. [`40_GATE_19_CHECKPOINT.md`](40_GATE_19_CHECKPOINT.md) — final held-out evidence and submission-hardening checkpoint.
10. [`39_GATE_19_CONTRACT_AND_HELDOUT_PLAN.md`](39_GATE_19_CONTRACT_AND_HELDOUT_PLAN.md) — pre-execution frozen Gate 19 seeds/scorer/campaign contract.
11. [`41_FINAL_5_MINUTE_PITCH.md`](41_FINAL_5_MINUTE_PITCH.md) — final timed pitch script and recording runbook.
12. [`38_GATE_18_CHECKPOINT.md`](38_GATE_18_CHECKPOINT.md) / [`37_GATE_18_CONTRACT_AND_ACCEPTANCE_PLAN.md`](37_GATE_18_CONTRACT_AND_ACCEPTANCE_PLAN.md) — Operator Control Tower implementation and contract.
13. [`36_GATE_17_CHECKPOINT.md`](36_GATE_17_CHECKPOINT.md) / [`35_GATE_17_CONTRACT_AND_ACCEPTANCE_PLAN.md`](35_GATE_17_CONTRACT_AND_ACCEPTANCE_PLAN.md) — measured scale and PostgreSQL durability.
14. [`34_GATE_16_CHECKPOINT.md`](34_GATE_16_CHECKPOINT.md) / [`33_GATE_16_CONTRACT_AND_ACCEPTANCE_PLAN.md`](33_GATE_16_CONTRACT_AND_ACCEPTANCE_PLAN.md) — bounded investigation agent.
15. [`32_GATE_15_CHECKPOINT.md`](32_GATE_15_CHECKPOINT.md) / [`31_GATE_15_REAL_RAZORPAY_CONTRACT_AND_ACCEPTANCE_PLAN.md`](31_GATE_15_REAL_RAZORPAY_CONTRACT_AND_ACCEPTANCE_PLAN.md) — Razorpay provider boundary.
16. [`30_GATE_14_CHECKPOINT.md`](30_GATE_14_CHECKPOINT.md) / [`29_GATE_14_CONTRACT_AND_ACCEPTANCE_PLAN.md`](29_GATE_14_CONTRACT_AND_ACCEPTANCE_PLAN.md) — exception lifecycle and incident grouping.
17. [`27_STRATEGIC_PAUSE_CURRENT_STATE_AND_REVISED_PLAN.md`](27_STRATEGIC_PAUSE_CURRENT_STATE_AND_REVISED_PLAN.md) + [`28_GATE_13_CHECKPOINT.md`](28_GATE_13_CHECKPOINT.md) — post-Gate-12 architecture and deterministic control plane.
18. [`16_MASTER_BUILD_PLAN.md`](16_MASTER_BUILD_PLAN.md) — historical comprehensive build plan; later checkpoints supersede its status.
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
- [`33_GATE_16_CONTRACT_AND_ACCEPTANCE_PLAN.md`](33_GATE_16_CONTRACT_AND_ACCEPTANCE_PLAN.md) — Gate 16 frozen bounded-investigation contract/acceptance plan.
- [`34_GATE_16_CHECKPOINT.md`](34_GATE_16_CHECKPOINT.md) — Gate 16 bounded investigator, tool trace, OpenAI transport and safety/privacy checkpoint.
- [`35_GATE_17_CONTRACT_AND_ACCEPTANCE_PLAN.md`](35_GATE_17_CONTRACT_AND_ACCEPTANCE_PLAN.md) — Gate 17 frozen measured-scale/PostgreSQL durability contract.
- [`36_GATE_17_CHECKPOINT.md`](36_GATE_17_CHECKPOINT.md) — Gate 17 performance finding, PostgreSQL application boundary, benchmark artifacts and limitations.
- [`37_GATE_18_CONTRACT_AND_ACCEPTANCE_PLAN.md`](37_GATE_18_CONTRACT_AND_ACCEPTANCE_PLAN.md) — Gate 18 frozen control-tower/API/frontend contract.
- [`38_GATE_18_CHECKPOINT.md`](38_GATE_18_CHECKPOINT.md) — Gate 18 scoped read model, React product surface, demo serving and F-0082 checkpoint.
- [`39_GATE_19_CONTRACT_AND_HELDOUT_PLAN.md`](39_GATE_19_CONTRACT_AND_HELDOUT_PLAN.md) — frozen final held-out/failure-campaign protocol committed before execution.
- [`40_GATE_19_CHECKPOINT.md`](40_GATE_19_CHECKPOINT.md) — first held-out v1 results, final failure campaign, reproducibility and non-claims.
- [`../EVALUATION.md`](../EVALUATION.md) — generated final evaluation report backed by checked-in artifacts.
- [`42_POST_FINAL_WHOLE_CODEBASE_AUDIT.md`](42_POST_FINAL_WHOLE_CODEBASE_AUDIT.md) — whole-repository post-final audit and repair evidence.
- [`43_THIRD_WHOLE_CODEBASE_AUDIT.md`](43_THIRD_WHOLE_CODEBASE_AUDIT.md) — closed third whole-codebase audit and merge evidence.
- [`44_PRODUCTION_READINESS_PHASE1.md`](44_PRODUCTION_READINESS_PHASE1.md) — merged readiness and real-Razorpay acceptance foundation.
- [`45_AUTH_AND_SCOPE_AUTHORIZATION_CONTRACT.md`](45_AUTH_AND_SCOPE_AUTHORIZATION_CONTRACT.md) — merged production human authentication and exact-scope authorization.
- [`46_POSTGRES_BACKUP_AND_RECOVERY_CONTRACT.md`](46_POSTGRES_BACKUP_AND_RECOVERY_CONTRACT.md) — merged logical backup/restore verification contract.
- [`47_RAZORPAY_WEBHOOK_INGRESS_CONTRACT.md`](47_RAZORPAY_WEBHOOK_INGRESS_CONTRACT.md) — merged durable provider-authenticated webhook receipt/replay contract.
- [`48_PRODUCTION_DEPLOYMENT_AND_PITR_CONTRACT.md`](48_PRODUCTION_DEPLOYMENT_AND_PITR_CONTRACT.md) — merged production deployment/PITR contract with real recovery-drill and failed-main/fix evidence.
- [`49_PRODUCTION_OBSERVABILITY_AND_OPERATOR_AUDIT_CONTRACT.md`](49_PRODUCTION_OBSERVABILITY_AND_OPERATOR_AUDIT_CONTRACT.md) — merged production observability/operator-audit contract.

## Execution and submission

- [`08_EXECUTION_ROADMAP.md`](08_EXECUTION_ROADMAP.md) — first roadmap.
- [`09_DEMO_SUBMISSION_PLAN.md`](09_DEMO_SUBMISSION_PLAN.md) — initial five-minute pitch plan.
- [`41_FINAL_5_MINUTE_PITCH.md`](41_FINAL_5_MINUTE_PITCH.md) — final timed recording script, Q&A and claim guardrails.
- [`16_MASTER_BUILD_PLAN.md`](16_MASTER_BUILD_PLAN.md) — comprehensive pre-review roadmap; post-Gate-12 sequencing is superseded by doc 27.

---

## Current hierarchy of truth

If two planning documents conflict, use this order:

1. implementation + tests
2. merged production observability/operator-audit contract (`49_PRODUCTION_OBSERVABILITY_AND_OPERATOR_AUDIT_CONTRACT.md`)
3. merged production deployment/PITR contract (`48_PRODUCTION_DEPLOYMENT_AND_PITR_CONTRACT.md`)
4. merged durable webhook-ingress contract (`47_RAZORPAY_WEBHOOK_INGRESS_CONTRACT.md`)
5. merged logical backup/recovery contract (`46_POSTGRES_BACKUP_AND_RECOVERY_CONTRACT.md`)
6. merged authentication/scope-authorization contract (`45_AUTH_AND_SCOPE_AUTHORIZATION_CONTRACT.md`)
7. production-readiness foundation (`44_PRODUCTION_READINESS_PHASE1.md`)
8. latest closed audit (`43_THIRD_WHOLE_CODEBASE_AUDIT.md`)
9. frozen first-run Gate 19 artifacts + generated `EVALUATION.md`
10. Gate 19 implementation checkpoint (`40_GATE_19_CHECKPOINT.md`)
11. frozen Gate 19 pre-execution contract (`39_GATE_19_CONTRACT_AND_HELDOUT_PLAN.md`)
12. `38_GATE_18_CHECKPOINT.md` / `37_GATE_18_CONTRACT_AND_ACCEPTANCE_PLAN.md`
13. `36_GATE_17_CHECKPOINT.md` / `35_GATE_17_CONTRACT_AND_ACCEPTANCE_PLAN.md`
14. `34_GATE_16_CHECKPOINT.md` / `33_GATE_16_CONTRACT_AND_ACCEPTANCE_PLAN.md`
15. `32_GATE_15_CHECKPOINT.md` / `31_GATE_15_REAL_RAZORPAY_CONTRACT_AND_ACCEPTANCE_PLAN.md`
16. `30_GATE_14_CHECKPOINT.md` / `29_GATE_14_CONTRACT_AND_ACCEPTANCE_PLAN.md`
17. `27_STRATEGIC_PAUSE_CURRENT_STATE_AND_REVISED_PLAN.md` for the revised post-Gate-12 architecture/sequence
18. `28_GATE_13_CHECKPOINT.md` and earlier implemented checkpoints
19. `16_MASTER_BUILD_PLAN.md`
20. `15_RAZORPAY_ALIGNMENT_AND_JUDGING_STRATEGY.md`
21. `11`–`14` and `18`
22. `17_RESEARCH_SOURCEBOOK.md` for sourced facts
23. `04`–`09` as earlier planning history

If implementation/evaluation contradicts any document, update the plan and preserve the finding in `FAILURE_LOG.md` where appropriate.
---

## Product in one sentence

> **ReFlow is an evidence-first finance controller that compiles messy payment data into reproducible reconciliation runs, exact money proofs, balance controls and explicit exceptions; AI assists with schema understanding and later investigation, but never defines financial truth.**
