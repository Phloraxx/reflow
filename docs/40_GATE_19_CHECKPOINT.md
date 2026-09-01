# Gate 19 Checkpoint — Final Failure Campaign + Held-Out Evidence + Submission Hardening

## Status

Gate 19 starts from final verified Gate 18 `main`:

`601f14835d177ea538f61502680527d70069f092`

Gate 18 final `main` CI run `33542781784` passed on that exact SHA.

Gate 19 evidence checkpoints on `build/gate-19-final-campaign-submission`:

- held-out contract + seed manifest frozen before execution: `f50e96751d747577f4a5cdf79293b875013410d1`;
- aggregate campaign runner frozen before held-out execution: `fcb65ce50d13ae42e911ff5917c782d57bf9e0b3`;
- first held-out v1 artifact preserved unchanged: `4686608f23798c874579969e4896431899595256`;
- final representative failure campaign + F-0084 regression: `6d6f0af5c7f537bc2a47812cbe51ee53499238ad`;
- generated human-readable final evaluation report: `77198fb57be8eb03218abc6442d97162cd9513c5`.

PR/merge CI is pending at this checkpoint.

## 1. Frozen-before-seeing-results protocol

Gate 19 does not select a favorable seed after seeing results.

Before the first held-out execution, `data/eval/gate19/heldout_manifest.json` fixed:

- 12 primary held-out cases;
- 768 requested settlements total;
- four clean cases and eight reconciliation-adversarial cases;
- four additional source-schema safety cases;
- exact world and observation seeds;
- exact B0/B1/B2/ReFlow candidate implementation SHA-256;
- exact Gate 11 scorer SHA-256;
- a rule that source rejection cannot silently disappear from the requested-settlement denominator.

The first v1 result is the submission result. It is not overwritten after inspection.

## 2. Primary held-out corpus

The frozen primary corpus contains:

- **12 cases**;
- **768 settlements**;
- **87,364 observed records**;
- 4 clean cases / 256 settlements;
- 8 reconciliation-adversarial cases / 512 settlements.

The first run completed successfully and independently verified its own contents.

The checked-in raw artifact is:

`data/eval/gate19/final-heldout.json`

It preserves hidden truth projections, all candidate decisions, recomputed reports, every non-green ReFlow decision and all corruption manifests needed to challenge the aggregate numbers.

## 3. Final headline metrics

The important distinction is between **coverage**, **precision** and **recall**.

ReFlow Core:

- automatic matches: **512 / 768 = 66.67%** of all requested settlements;
- true automatic matches: **512**;
- false automatic matches: **0**;
- auto-match precision: **512 / 512 = 100%**;
- hidden-truth reconciled settlements: **624**;
- truth-reconciled recall: **512 / 624 = 82.05%**;
- silent false auto-match rate: **0 / 512 = 0%**.

`66.67%` is therefore a conservative automatic match/coverage rate, **not an accuracy percentage**.

## 4. Baseline comparison

The same frozen primary corpus produced:

| System | Auto matched | True auto | False auto | Auto precision | Truth-reconciled recall |
|---|---:|---:|---:|---:|---:|
| B0 naive 1:1 | 0 | 0 | 0 | n/a | 0.00% |
| B1 grouped exact | 512 | 512 | 0 | 100.00% | 82.05% |
| B2 fuzzy threshold | 521 | 512 | 9 | 98.27% | 82.05% |
| ReFlow Core | 512 | 512 | 0 | 100.00% | 82.05% |

Two conclusions matter:

1. ReFlow does **not** claim a recall win over the strong B1 grouped-exact baseline on this corpus.
2. The fuzzy baseline bought nine extra green decisions by making **nine silent false matches**. ReFlow refused those instead.

The product value beyond B1 is the evidence-first proof protocol, source/provenance validation, immutable proof history, typed exception lifecycle, close controls, durable audit state, bounded investigation and operator control tower.

## 5. Edge evidence

On the frozen primary corpus, ReFlow Core produced:

- composition-edge precision: **99.96%**;
- composition-edge recall: **99.93%**;
- bank-edge precision: **100%**;
- bank-edge recall: **85.49%**.

The missing edge recall is not hidden: corrupted/missing observed evidence can make truth edges unavailable to deterministic proof, and ReFlow intentionally fails closed instead of synthesizing those edges.

## 6. Clean vs adversarial behavior

ReFlow Core by profile:

| Profile | Settlements | Truth reconciled | Auto matched | Precision | Truth-reconciled recall | Non-green |
|---|---:|---:|---:|---:|---:|---:|
| clean | 256 | 208 | 208 | 100% | 100% | 48 |
| reconciliation adversarial | 512 | 416 | 304 | 100% | 73.08% | 208 |

The clean corpus still contains truth states where an automatic green proof is not expected, so its automatic match rate is not 100% of all requested settlements. Against the hidden-truth reconciled denominator it is 100% recall.

## 7. Honest exception list

The primary corpus produced **256 non-green ReFlow decisions**:

- `unresolved`: **170**;
- `residual`: **78**;
- `contradicted`: **8**.

Reason-code occurrences, which may overlap on one case:

- `BANK:BANK_RECEIPT_NOT_OBSERVED`: 173;
- `BANK:BANK_AMOUNT_MISMATCH`: 64;
- `COMPOSITION:SETTLEMENT_COMPOSITION_RESIDUAL`: 15;
- `BANK:SAME_AMOUNT_NOT_IDENTITY`: 11;
- `COMPOSITION:DUPLICATE_ECONOMIC_ROW`: 8.

No exception was manually removed from the result. The full machine-readable list is stored under `primary.reflow_exceptions` in the raw v1 artifact.

## 8. Source-schema safety corpus

The four frozen source-schema adversarial cases cover malformed dates, schema rename, rupee/paise traps and sign traps.

Result:

- **4 / 4 source-schema cases failed closed**;
- **0 candidate decisions were emitted**;
- raw evidence was retained before canonical interpretation failed.

These cases are reported separately from the primary reconciliation match-rate denominator because they intentionally attack source interpretability rather than settlement truth once a source is canonical.

## 9. Final representative failure campaign

`data/eval/gate19/failure-campaign.json` is independently verifiable and records **12 / 12** passing representative checks:

- missing/late bank source semantics;
- case auto-close/history retention;
- changed economic identity supersession;
- investigation-provider outage;
- prompt-like source injection;
- hallucinated evidence citation rejection;
- out-of-proof tool denial;
- PostgreSQL raw-evidence conflict retention;
- PostgreSQL restart/idempotency;
- optimistic current-pointer CAS;
- SPA history fallback while preserving API 404 authority;
- Source Lab raw-payload minimization.

## 10. F-0084 — final campaign harness quiet-pytest assumption

The first representative failure-campaign run stopped on its first selector even though the selected regression itself passed.

Root cause: the campaign verifier assumed quiet pytest output would contain the literal text `1 passed`. This repository's global `-q` configuration suppresses that summary.

The harness was fixed to run with `-rA` and require the exact `PASSED <node-id>` marker plus exit code zero. This also prevents skipped database tests from being accepted as campaign success.

Financial-truth impact: none. The defect was in submission-evidence orchestration only.

## 11. Scale evidence

Gate 19 does not rerun/tune the already-frozen Gate 17 scale result.

The verified 10k clean artifact records:

- **10,000 settlements**;
- **1,203,220 raw rows**;
- proof-pipeline throughput: **206.97 settlements/s**;
- total runtime: **267.56 s**;
- process RSS: about **3.18 GiB**;
- hardware: disclosed 4-vCPU aarch64 Oracle VM.

The separate durability benchmark records approximately **76.1 cold source writes/s** and **90.2 cold immutable-artifact writes/s** for the fine-grained reference PostgreSQL path.

These are measured reference results, not a production capacity/SLO claim.

## 12. Fresh-clone reproducibility

A new clone of pushed Gate 19 SHA `77198fb57be8eb03218abc6442d97162cd9513c5` was created outside the working repository.

From that clean checkout, with a disposable PostgreSQL 16 container, validation passed:

- **402 Python/PostgreSQL tests**;
- Ruff;
- strict mypy across **64 source files**;
- **5 / 5** React tests;
- TypeScript project build;
- Vite production build;
- frozen held-out artifact verification;
- frozen failure-campaign artifact verification;
- generated `EVALUATION.md` equality check.

This is stronger evidence than only validating the long-lived development working tree.

## 13. Secret/history scan

A high-confidence pattern scan was run over both:

- the current tracked repository tree; and
- Git patch history.

Patterns included private-key headers, Razorpay live/test keys, GitHub token forms, OpenAI-style secret keys and AWS access-key forms.

Result: **0 high-confidence matches**.

This is not a formal secret-audit product and does not replace GitHub secret scanning or external security review.

## 14. AI evidence boundary

No OpenAI/AI provider key was configured on the final Oracle evaluation host.

Therefore Gate 19 makes **no live-model Gate 12 or Gate 16 quality, cost or latency claim**.

What is proven instead:

- deterministic source-compiler contracts and proposal validation;
- fake/provider-transport protocol tests;
- bounded read-only investigation tool surface;
- deterministic final-output validation;
- outage behavior;
- prompt-injection/hallucinated-citation rejection in the final failure campaign.

The submission must not convert this safety evidence into a live-model accuracy number.

## 15. Razorpay real-data boundary

No Razorpay API key was configured on the final Oracle evaluation host.

The earlier authenticated connected-account inspection exposed payments but no settlement/recon corpus suitable for a real Test Mode settlement benchmark.

Therefore ReFlow makes **no real Test Mode or live merchant settlement-accuracy claim**.

Gate 15's provider-document fixtures validate current provider-shaped contracts but remain labelled as provider-document evidence rather than private real transaction evidence.

## 16. Public application boundary

The repository is public.

The Gate 18 application remains a synthetic/local reviewer demo unless separately deployed behind an appropriate public-demo boundary. The current web product has no authentication/RBAC and a `scope_id` is not authorization, so real merchant evidence must not be exposed publicly through it.

A synthetic-only public demo may be deployed later without changing the evaluation result.

## 17. Reviewer command

Gate 19 adds:

```bash
make submission-check
```

This runs the normal static/unit/frontend checks and then **verifies** the frozen Gate 19 and Gate 17 evidence artifacts. It does not rerun or overwrite the held-out v1 corpus.

## 18. Generated final evaluation report

`EVALUATION.md` is generated by `reflow.evaluation.final_report` from checked-in machine-verifiable artifacts.

The report contains the denominators and non-claims needed to avoid misleading judge-facing metrics. `python -m reflow.evaluation.final_report --check EVALUATION.md` fails if the checked-in report no longer matches the evidence.

## 19. Submission-ready story

The final evidence supports the following concise claims:

1. ReFlow processed a frozen 768-settlement held-out synthetic/adversarial corpus.
2. It auto-reconciled 512 settlements with **100% precision and zero silent false auto-matches**.
3. Its truth-reconciled recall was **82.05%**.
4. It left 256 cases explicitly non-green rather than guessing.
5. A fuzzy alternative produced nine wrong automatic matches on the same corpus.
6. A separate 12-check failure campaign passed end to end.
7. The measured 10k proof pipeline sustained **206.97 settlements/s** on the disclosed Oracle VM.
8. The product exposes those proofs/exceptions through a read-only Operator Control Tower.
9. AI is bounded to source understanding/investigation and never defines reconciliation truth.

## 20. Remaining submission tasks outside code correctness

The following are intentionally not represented as completed by this checkpoint:

- recording/uploading the five-minute pitch video;
- entering the final form submission;
- selecting a software license (repository currently has none; this is an owner/legal publishing choice);
- optional synthetic-only public deployment with stable URL/monitoring.

These do not alter the frozen evaluation result.
