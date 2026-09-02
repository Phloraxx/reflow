# ReFlow

**Every rupee gets a path, a proof, or an exception.**

> Razorpay AI Buildathon 2026 · Track 04 — AI Finance Controller
>
> **Current phase: Gates 1–19 remain merged green. A post-final whole-codebase audit is implemented on `audit/post-final-whole-codebase` and is pending PR/merge. The audit reproduced and fixed persistence/currentness, proof-scope, evidence-CI, model-transport/resource and reproducibility defects without changing the frozen Gate 19 held-out v1. The repaired tree passes 419 PostgreSQL-enabled Python tests with 79% branch-aware coverage; see `docs/42_POST_FINAL_WHOLE_CODEBASE_AUDIT.md`.**

ReFlow is an evidence-first **finance controller** built around a deterministic financial truth compiler for payment settlement reconciliation.

It compiles messy merchant, Razorpay and bank evidence into a temporal **Money Graph**, proves how payments/refunds/transfers/adjustments compose into settlements, proves bank receipt independently, and ultimately emits a versioned machine-verifiable **Reconciliation Proof**. Anything the deterministic engine cannot prove becomes a residual, contradiction, ambiguity or exception.

AI has two bounded jobs:

1. **Source Adapter Compiler (implemented in Gate 12)** — understand unfamiliar financial exports and propose a constrained adapter; first-seen AI proposals remain review-only and activation is deterministic/auditable.
2. **Exception Investigation Agent (implemented in Gate 16)** — inspect one immutable non-green case/proof packet through bounded read-only tools and propose only `WAIT`, `RECHECK`, `REQUEST_SOURCE`, `REQUEST_HUMAN_REVIEW` or `ABSTAIN`; deterministic code validates every citation, amount and action.

**The LLM never decides whether money reconciles.**

---

## Why this project

A simplistic reconciliation implementation matches one gateway row to one bank row. ReFlow deliberately targets the harder financial shape around a settlement: many economic movements can compose one settlement, while bank receipt is a separate fact that must be independently evidenced.

The core question is not:

> “Which row looks similar?”

It is:

> **“Can we produce an auditable proof of every financial movement that explains this settlement, prove its bank receipt independently, and state exactly what evidence is missing when we cannot?”**

---

## Current deterministic pipeline

```mermaid
flowchart LR
  A[Merchant / ERP evidence] --> J[(Append-only Raw Evidence Journal)]
  B[Razorpay webhook / API evidence] --> RZP[Gate 15 Raw-first Razorpay Boundary]
  RZP --> J
  C[Bank evidence] --> J

  J --> D[Deterministic Source Adapters]
  D --> E[Canonical Financial Objects + Raw SourceLinks]
  RZP --> E
  E --> T[Temporal Payment Reducer]
  E --> G[Money Graph]
  T --> G

  G --> S[Settlement Composition Proof]
  E --> K[Bank Receipt Proof]
  S --> P{Full Reconciliation Proof - Gate 9}
  K --> P

  M[Scope + SourceDeliveryManifest] --> CP[Gate 13 Reconciliation Control Plane]
  P --> CP
  CP --> CV[Evidence Coverage / No-Orphan Control]
  CP --> BL[Balance / Clearing Control]
  CV --> CR[Close Readiness]
  BL --> CR
  CR --> RR[Immutable Reconciliation Run]

  P -->|residual / contradiction / ambiguity| X[Gate 14 ExceptionCase Lifecycle]
  RR --> X
  X --> IC[Deterministic Incident Fingerprints / Clusters]
  X --> AI[Gate 16 Bounded Investigation Agent]
  AI --> NA[Validated Safe Next Action / Abstain]

  J -. durable evidence .-> PG[(Gate 17 PostgreSQL Durable State)]
  RR -. immutable artifact .-> PG
  X -. observations / dispositions .-> PG
  AI -. validated result / trace .-> PG
  U[Unknown Source] -.-> AS[Gate 12 Adapter Compiler]
```

Raw evidence is journaled **before** canonicalization. The compiler reads the journal’s retained immutable payloads, not mutable caller rows, then binds canonical facts plus exact `SourceLink`s with a source-order-invariant compilation SHA-256. Money Graph evidence and proof fragments cite raw envelope IDs rather than stopping at canonical row IDs.

---

## What exists today

### Gates 0–3 — foundation

- repository engineering constitution;
- one-command validation and GitHub Actions CI;
- signed integer-paise money contracts;
- strongly typed financial IDs;
- timezone-aware canonical models;
- hidden synthetic financial-world generator;
- adversarial observation corruption;
- explicit separation of hidden truth from candidate observations.

### Gates 4–6 — ingestion, temporal truth and Money Graph

- fail-closed adapters for the **normalized synthetic/known fixture schemas**;
- append-only raw source envelopes;
- deeply immutable source payloads;
- deterministic payload SHA-256 and deterministic `src_...` identity, both self-verified by `SourceEnvelope`;
- journal-first ingestion, including retention of malformed rows before adapter failure;
- immutable canonical `SourceLink`s back to journal envelopes;
- idempotent source replay;
- pure payment-state reconstruction independent of delivery order;
- safe handling of `failed → captured` evidence;
- retry deduplication that separates provider facts from local receive time;
- Money Graph construction only from journal-backed canonical batches;
- recon entries as first-class graph nodes;
- authoritative graph edges citing actual raw source-envelope evidence;
- graph edge precision/recall tests against hidden truth;
- duplicate recon evidence visible to evaluation rather than silently collapsed.

### Gate 7 — Settlement Composition Proof

For every settlement, the composition engine checks **identity, arithmetic, temporal admissibility and raw provenance** together.

A composition can be proven only when:

- settlement and recon rows are journal-backed;
- graph provenance resolves to the correct raw envelopes;
- currencies agree;
- one economic identity is not represented by contradictory rows;
- distinct source rows do not duplicate one economic movement;
- an economic movement is not claimed by multiple settlements;
- no admitted recon component occurs after settlement processing;
- exact signed component arithmetic equals the authoritative settlement amount;
- no contradiction or missing-evidence reason remains.

The key invariant is:

```text
zero residual != proof
```

A zero residual with duplicated identity, conflicting identity, wrong provenance or impossible timing remains non-proven.

### Gate 8 — Bank Receipt Proof

Gate 8 proves bank receipt **independently** from settlement composition.

For the current standard Razorpay settlement model, automatic proof requires:

```text
settlement UTR exists
AND exactly one distinct bank transaction has that UTR
AND exact amount and currency match
AND bank time is not before settlement processing
AND settlement UTR is not reused by another settlement
AND raw settlement/bank provenance is complete
```

Possible outcomes are:

```text
BANK_RECEIPT_PROVEN
BANK_RECEIPT_WAITING
BANK_RECEIPT_RESIDUAL
BANK_RECEIPT_INCOMPLETE
BANK_RECEIPT_CONTRADICTED
```

Important safety rules:

- same amount + nearby date is **not** identity;
- narration is untrusted/supporting text and cannot authorize a match;
- missing/corrupted UTR fails closed instead of switching to fuzzy matching;
- exact UTR + wrong amount produces an explicit residual;
- a bank row before settlement processing is contradictory and excluded;
- a bank observation may arrive later—there is no arbitrary maximum-delay cutoff;
- exact duplicate delivery of one bank source record is idempotent;
- conflicting payload under one bank-entry identity fails closed;
- multiple distinct bank transactions reusing one **standard settlement** UTR are contradictory rather than summed.

---

## Standard settlements are not Instant Settlements

Gate 8 research exposed and corrected an important simulator assumption.

Razorpay's standard settlement entity (`setl_...`) exposes a UTR that Razorpay documents for tracking that particular settlement in the bank account.

Razorpay **Instant Settlements** use a different topology: a `settlement.ondemand` parent (`setlod_...`) can expose explicit `ondemand_payouts` with child IDs such as `setlodp_...` and payout-level UTR evidence.

Therefore ReFlow does **not** treat multiple arbitrary bank rows under one standard `setl_...` UTR as a valid split settlement. True multi-credit Instant Settlement support will require an explicit future model:

```text
setlod parent
  ↓
setlodp payout(s)
  ↓
payout UTR(s)
  ↓
bank transaction(s)
```

The old synthetic `split_bank_credit` truth fixture was removed instead of teaching Gate 8 to reward an inaccurate provider model. The failure is preserved in `FAILURE_LOG.md`.

See [`docs/21_GATE_8_CHECKPOINT.md`](docs/21_GATE_8_CHECKPOINT.md) for the complete Gate 8 contract and source references.

---

## Audits and failure history

The first Gates 0–6 audit found eight real defects and fixed them before PR #2 was merged.

A second independent pass before accepting Gate 7 found six additional classes of problems, including end-to-end raw provenance, economic identity, future recon evidence, cross-settlement ownership, envelope self-integrity and refund-event semantics.

Gate 8 then found another provider-semantic failure in the synthetic bank truth: standard settlements and Instant Settlement payout topology had been conflated.

These findings are preserved rather than rewritten out of history.

See:

- [`FAILURE_LOG.md`](FAILURE_LOG.md) — numbered genuine failures and repairs;
- [`docs/18_IMPLEMENTATION_AUDIT.md`](docs/18_IMPLEMENTATION_AUDIT.md) — first implementation audit;
- [`docs/19_SECOND_IMPLEMENTATION_AUDIT.md`](docs/19_SECOND_IMPLEMENTATION_AUDIT.md) — independent second audit;
- [`docs/20_GATE_7_CHECKPOINT.md`](docs/20_GATE_7_CHECKPOINT.md) — Gate 7 checkpoint;
- [`docs/21_GATE_8_CHECKPOINT.md`](docs/21_GATE_8_CHECKPOINT.md)
- [`docs/22_THIRD_INDEPENDENT_PRE_GATE_9_AUDIT.md`](docs/22_THIRD_INDEPENDENT_PRE_GATE_9_AUDIT.md)
- [`docs/23_GATE_9_CHECKPOINT.md`](docs/23_GATE_9_CHECKPOINT.md)
- [`docs/24_GATE_10_CHECKPOINT.md`](docs/24_GATE_10_CHECKPOINT.md)
- [`docs/25_GATE_11_CHECKPOINT.md`](docs/25_GATE_11_CHECKPOINT.md)
- [`docs/26_GATE_12_CHECKPOINT.md`](docs/26_GATE_12_CHECKPOINT.md)
- [`docs/27_STRATEGIC_PAUSE_CURRENT_STATE_AND_REVISED_PLAN.md`](docs/27_STRATEGIC_PAUSE_CURRENT_STATE_AND_REVISED_PLAN.md) — authoritative revised roadmap
- [`docs/28_GATE_13_CHECKPOINT.md`](docs/28_GATE_13_CHECKPOINT.md) — deterministic control-plane checkpoint;
- [`docs/29_GATE_14_CONTRACT_AND_ACCEPTANCE_PLAN.md`](docs/29_GATE_14_CONTRACT_AND_ACCEPTANCE_PLAN.md) — frozen Gate 14 contract and acceptance plan;
- [`docs/30_GATE_14_CHECKPOINT.md`](docs/30_GATE_14_CHECKPOINT.md) — Gate 14 case-lifecycle/fingerprint checkpoint;
- [`LIMITATIONS.md`](LIMITATIONS.md) — current non-claims and unresolved scope.

---

## Important source boundaries

### Normalized fixtures are not production adapters

The current recon adapter consumes a normalized fixture schema containing fields such as:

```text
gross_amount_paise
fee_paise
tax_paise
settlement_effect_paise
```

It remains the **normalized fixture adapter**, not the Gate 15 provider parser. Gate 15 separately normalizes Razorpay's authoritative `debit`, `credit`, `amount`, `fee`, `tax`, settlement identity and UTR fields from raw provider-shaped evidence. Synthetic formulas are not allowed to masquerade as provider semantics. Authenticated settlement Test Mode fixtures remain unavailable in the connected account, so provider-document fixtures are labelled accordingly.

Likewise, the current bank adapter is a normalized positive settlement-credit feed contract, not a universal bank-statement parser.

### Payment state and refund lifecycle are distinct

Refunds remain first-class economic evidence. The normalized payment-event reducer does not invent refund amount from a generic payment event. Gate 15 preserves the provider distinction by deriving payment transitions from signed payment webhook names while refund economics enter through refund-specific Settlement Recon evidence. A dedicated refund-webhook ingestion path remains optional later work rather than being synthesized from payment state.

---

## Core boundaries

- Money is signed **integer paise**, never float.
- Currency and amount unit are explicit.
- Raw source evidence is append-only and provenance is preserved.
- A raw envelope's payload, digest and deterministic source ID must agree.
- A malformed source row is retained even when canonicalization fails.
- Duplicate/retried delivery cannot duplicate economic value.
- Arrival order cannot silently define final payment truth.
- `payment.failed → payment.captured` is a valid evidence sequence.
- Settlement composition arithmetic is deterministic.
- Settlement composition and bank receipt are independent proof fragments.
- UTR/authoritative IDs outrank fuzzy similarity.
- A zero residual is necessary but never sufficient proof of identity.
- Same amount + approximate date cannot establish bank identity.
- Bank narration cannot authorize a match.
- Ambiguity and contradiction fail closed.
- Unknown source unit/sign semantics quarantine evidence rather than guess.
- Hidden simulator truth cannot be imported by production/reconciliation modules.
- AI cannot mutate financial truth or independently mark a settlement reconciled.

---

## Final frozen evaluation

Gate 19 commits the held-out seeds and SHA-256 bindings for the existing scorer/candidate systems **before** the first final execution. The first v1 artifact is preserved unchanged and is independently re-verifiable.

Primary held-out corpus:

- **12 cases / 768 settlements / 87,364 observed records**;
- 4 clean cases and 8 reconciliation-adversarial cases;
- ReFlow automatic matches: **512 / 768 = 66.67% coverage**;
- correct automatic matches: **512 / 512 = 100% auto-match precision**;
- truth-reconciled recall: **512 / 624 = 82.05%**;
- silent false auto-matches: **0 / 512 = 0%**;
- explicit non-green decisions: **256** (170 unresolved, 78 residual, 8 contradicted).

The `66.67%` number is a conservative automatic match rate over every requested settlement, **not an accuracy percentage**.

On the same frozen corpus, the strong B1 grouped-exact baseline also produced 512 true automatic matches with zero false matches. ReFlow does **not** claim a recall win over B1. The fuzzy baseline automatically matched 521 settlements, but **9 were wrong** (1.73% silent false-match rate). ReFlow leaves those cases non-green instead of buying coverage with incorrect financial truth.

A separate frozen source-schema safety corpus failed closed **4/4** times with zero candidate decisions, and the final representative regression campaign passed **12/12** checks.

For scale, the independently verified Gate 17 clean 10k artifact records **206.97 settlements/s in the proof pipeline** over 10,000 settlements / 1,203,220 raw rows on the disclosed 4-vCPU aarch64 Oracle VM. This is not a production SLO or end-to-end throughput claim.

See [`EVALUATION.md`](EVALUATION.md) for exact denominators, edge metrics, exception reasons, reproduction commands and non-claims. The raw first-run result remains checked in under `data/eval/gate19/final-heldout.json`.

### Post-final whole-codebase audit

After Gates 1–19 merged, ReFlow was audited again from final `main` rather than treating green CI as proof that every runtime boundary matched the design. The audit reproduced F-0085 through F-0097 across durable artifact authority/currentness, proof scope isolation, final-evidence CI, dependency/bootstrap reproducibility, OpenAI transport/resource bounds and bounded Gate 12 model profiles.

The repaired branch passes **419 PostgreSQL-enabled Python tests** with **79% branch-aware coverage**; independent Bandit medium/high, Python advisory and npm production/dev scans are clean. The frozen first-run Gate 19 held-out artifact/seeds/scorer were not altered. See [`docs/42_POST_FINAL_WHOLE_CODEBASE_AUDIT.md`](docs/42_POST_FINAL_WHOLE_CODEBASE_AUDIT.md).

---

## Current deterministic gates

### Gate 9 — Versioned Full Reconciliation Proof

Gate 9 now combines only the audited batch-safe Gate 7 and Gate 8 fragments:

```text
Settlement Composition Proof
            +
      Bank Receipt Proof
            ↓
Versioned Full Reconciliation Proof
```

A settlement gets a new immutable proof version only when its authoritative financial input changes. Unrelated same-amount diagnostics and source delivery order do not manufacture new versions. Every version records a settlement-scoped input hash, the batch compilation hash, ruleset versions, knowledge cutoff, predecessor, reopening state and raw evidence union.

Late authoritative evidence creates a new version; a previously proven settlement can reopen to a non-reconciled state without rewriting history. Batch updates are staged and committed atomically.

### Gate 10 — Bounded Residual Hypotheses

Gate 10 now derives non-zero residual targets from immutable Gate 9 proofs and returns bounded, deterministic explanation hypotheses. Exact arithmetic is never promoted to financial proof. Candidate identities bind the settlement, exact proof version, scope, disposition, reason codes and raw evidence; blocked or pre-settlement evidence stays visibly blocked.

### Gate 11 — Baseline Evaluation Harness

Gate 11 compares B0 naive 1:1, B1 strong grouped exact, B2 fuzzy threshold and ReFlow Core on the same journal-backed canonical evidence. Candidate decisions carry the selected canonical financial facts themselves; the scorer checks semantic evidence identity rather than trusting row IDs or caller-supplied totals.

### Gate 12 — AI-assisted Source Adapter Compiler

Gate 12 journals an unfamiliar source before inference, profiles its exact schema, asks an optional model for a finite declarative `AdapterSpec`, and compiles that spec through the same audited canonical adapters used by the deterministic core. First-seen AI proposals never auto-activate: correct proposals remain `NEEDS_REVIEW`, deterministic controls may reject unsafe proposals early, and only explicit operator review or canonical-equivalent migration evidence can create an approved adapter version.

Approved adapters preserve both raw source identity and canonical financial identity in `SourceLink`, so unknown exports enter the existing Money Graph/proof pipeline without a second reconciliation path. Development adapter and migration artifacts are independently replayable; live-model accuracy remains unclaimed until an explicit model/key benchmark is run.

Benchmark JSON uses the `gate11-evaluation-v2` schema and includes a minimal post-run truth projection plus raw candidate decisions so `python -m reflow.evaluation.verify <artifact.json>` can recompute every stored report. Gate 11 development seeds remain regression evidence only; Gate 19 later froze and preserved the separate final held-out v1. Live-model quality remains unclaimed.

### Gate 13 — Reconciliation Control Plane

Gate 13 wraps the proof kernel with content-addressed `ReconciliationScope`, source-delivery manifests, policy versions, proof-derived evidence coverage, exact balance/clearing control, close readiness and immutable `ReconciliationRun` capsules. Source `WAITING`/`LATE`/`PARTIAL`/`COMPLETE` state is explicit, and SNAPSHOT versus DELTA deliveries have different carry-forward semantics.

Canonical coverage labels are derived from Gate 7/8/9 proof evidence rather than caller assertions. Every canonical settlement must have exactly one Gate 9 proof. Orphan or quarantined relevant evidence blocks close readiness, and contradicted/residual evidence cannot be masked by another proven fragment. Materiality changes workflow priority only; it never changes exact proof status or residuals.

See [`docs/28_GATE_13_CHECKPOINT.md`](docs/28_GATE_13_CHECKPOINT.md).

### Gate 14 — Exception Case Lifecycle + Fingerprints

Gate 14 derives stable economic case identity from the reconciliation scope, settlement identity, authoritative amount/currency and payout/UTR identity. Every immutable Gate 13 run can append a self-verifying case observation that binds the exact Gate 9 proof, policy, source completeness packet, materiality band and deterministic incident fingerprint.

Financial state and operator workflow are separate. Operator close/variance acceptance never changes Gate 9 truth; a later green proof auto-closes the case as reconciled, while changed authoritative economics creates a new case and supersedes the old one. Append-only dispositions require explicit `REOPEN` after operator closure, and stale prior economics cannot reverse a newer supersession.

Run-specific incident clusters preserve exact case count and integer-paise affected value and are invariant to input permutation. Gate 14's derivation ledger remains an in-memory reference, while Gate 17 can durably retain its immutable case observations/dispositions/incidents as application artifacts. Authenticated operator identity remains later work.

See [`docs/30_GATE_14_CHECKPOINT.md`](docs/30_GATE_14_CHECKPOINT.md).

### Gate 15 — Real Razorpay Integration

Gate 15 adds a journal-first provider boundary for signed Razorpay payment/settlement webhooks, Settlement Recon API items and processed standard settlement API entities. Webhook HMAC is verified over exact raw bytes; source event identity/replay conflicts are explicit; signed schema drift fails closed after raw retention.

Settlement Recon uses the provider's authoritative `credit - debit` effect rather than synthetic `gross - fee - tax` assumptions. Payment/refund/transfer/adjustment type identity is validated, provider settlement UTR reaches Gate 7, and contradictory recon-vs-settlement UTR produces `COMPOSITION_CONTRADICTED`. Standard settlement payloads use explicit account currency because Razorpay's documented settlement entity omits a currency field.

A processed settlement still does not prove bank credit. Provider-shaped recon + signed settlement + independent bank evidence passes through the unchanged Gate 7/8/9 proof kernel and becomes `PROVEN_RECONCILED` only when all exact evidence agrees. The connected account had no settlement/recon records to freeze, so no real Test Mode settlement accuracy claim is made.

See [`docs/31_GATE_15_REAL_RAZORPAY_CONTRACT_AND_ACCEPTANCE_PLAN.md`](docs/31_GATE_15_REAL_RAZORPAY_CONTRACT_AND_ACCEPTANCE_PLAN.md) and [`docs/32_GATE_15_CHECKPOINT.md`](docs/32_GATE_15_CHECKPOINT.md).

### Gate 16 — Bounded Exception Investigation Agent

Gate 16 binds one active Gate 14 case to its exact latest Gate 9 proof and proof-cited source envelopes, then exposes only three read-only capabilities: case snapshot, proof snapshot and one exact source envelope. Every tool call/denial is content-addressed in an independently evaluable trace.

The model can only propose `WAIT`, `RECHECK`, `REQUEST_SOURCE`, `REQUEST_HUMAN_REVIEW` or `ABSTAIN`. Deterministic validation rejects unread/hallucinated citations, wrong integer-paise claims, numeric prose, unsupported source requests and unsafe actions. Provider outage/refusal is harmless to financial truth and collapses to `ABSTAIN`.

The optional OpenAI Responses provider uses strict tools/output, `store=false`, stateless output-item replay, serialized tool calls, bounded rounds and a minimized/redacted model-facing evidence projection. Gate 17 can durably retain validated investigation result/trace artifacts, but no live-model Gate 16 quality number is claimed yet.

See [`docs/33_GATE_16_CONTRACT_AND_ACCEPTANCE_PLAN.md`](docs/33_GATE_16_CONTRACT_AND_ACCEPTANCE_PLAN.md) and [`docs/34_GATE_16_CHECKPOINT.md`](docs/34_GATE_16_CHECKPOINT.md).

### Gate 17 — Scale + Durability/Application Layer

Gate 17 measured the one-process proof engine before adding infrastructure. The first 50-settlement clean baseline exposed an O(recon rows × graph edges) Gate 7 provenance scan; the pre-optimization 1k run still had not completed after 20m31s. A batch-local exact provenance-edge index removed that waste without changing financial/provenance semantics. The final checked-in clean benchmarks process 50 / 1,000 / 10,000 settlements (6,084 / 120,052 / 1,203,220 raw rows), with the 10k proof pipeline sustaining 206.97 settlements/s at about 3.18 GiB peak RSS on the 4-vCPU Oracle VM.

Gate 17 also adds a PostgreSQL 16 durability boundary: append-only raw evidence with conflict retention, immutable canonical JSON product/audit artifacts with digest verification, optimistic compare-and-swap current pointers, and a deliberately small `ReflowApplicationService` with no generic SQL or financial-truth mutation surface. Real PostgreSQL integration tests run in CI.

The reference PostgreSQL path is durability-first rather than bulk optimized: the checked-in 1k cold/warm benchmark measures roughly 76 source writes/s and 87–90 artifact writes/s at fine transaction granularity. No 100k/1M, high-throughput PostgreSQL, HA, RBAC or production-readiness claim is made.

See [`docs/35_GATE_17_CONTRACT_AND_ACCEPTANCE_PLAN.md`](docs/35_GATE_17_CONTRACT_AND_ACCEPTANCE_PLAN.md), [`docs/36_GATE_17_CHECKPOINT.md`](docs/36_GATE_17_CHECKPOINT.md), and the self-verifying artifacts under [`data/eval/gate17/`](data/eval/gate17/).

### Gate 18 — Operator Control Tower

Gate 18 adds a scoped, read-only FastAPI projection over immutable run/proof/case/source/evaluation artifacts and a React/TypeScript control tower. The primary surfaces are Run / Close Overview, Settlement Proof, Exception Queue, Case File, Source Lab and Evaluation Lab. The bounded investigation agent appears only inside Case File; there is no chatbot homepage.

The frontend formats and filters API-provided facts but does not decide proof state or recompute financial truth. Every finance API read carries an explicit reconciliation scope, cross-scope artifact references fail closed, source raw payloads are omitted from Source Lab, and benchmark artifacts are verified by a simulator-free reader before display.

A deterministic synthetic demo seeder runs the existing Gates 7–16 pipeline into PostgreSQL. Same-origin FastAPI serving was smoke-tested with the built Vite app; F-0082 records/fixes the SPA direct-navigation 404 while preserving real `/api/*` 404 behavior. Final Oracle validation passed 396 Python/PostgreSQL tests, strict mypy across 61 source files, 5 React tests, TypeScript and the production Vite build.

See [`docs/37_GATE_18_CONTRACT_AND_ACCEPTANCE_PLAN.md`](docs/37_GATE_18_CONTRACT_AND_ACCEPTANCE_PLAN.md) and [`docs/38_GATE_18_CHECKPOINT.md`](docs/38_GATE_18_CHECKPOINT.md).

### Gate 19 — Final Failure Campaign + Held-Out Evidence

Gate 19 freezes the final evaluation protocol before execution, preserves the first held-out v1 unchanged, publishes the complete non-green exception set, and validates representative failure classes separately from the headline reconciliation denominator. The final human-readable metrics are generated from machine-verifiable artifacts rather than hand-edited numbers.

The submission evidence includes a fresh-clone validation, a high-confidence current-tree/Git-history secret-pattern scan, an exact five-minute pitch runbook, and a reviewer `make submission-check` target. No live-model quality number or real Razorpay Test Mode settlement-accuracy claim is made because neither final corpus was available on the Oracle evaluation host.

See [`docs/39_GATE_19_CONTRACT_AND_HELDOUT_PLAN.md`](docs/39_GATE_19_CONTRACT_AND_HELDOUT_PLAN.md), [`docs/40_GATE_19_CHECKPOINT.md`](docs/40_GATE_19_CHECKPOINT.md), [`docs/41_FINAL_5_MINUTE_PITCH.md`](docs/41_FINAL_5_MINUTE_PITCH.md) and [`EVALUATION.md`](EVALUATION.md).

---

## Commands

```bash
# Python + PostgreSQL/read-API + frontend development dependencies.
# make install uses the checked-in Python constraints and npm lockfile.
python3 -m venv .venv
. .venv/bin/activate
make install

# Full local static/unit/build path. PostgreSQL integration tests run when
# REFLOW_TEST_POSTGRES_DSN is configured.
make check

# Submission reviewer path. The preflight deliberately refuses to skip the
# PostgreSQL durability suite. The held-out v1 is verified, never overwritten.
docker run --rm -d --name reflow-review-postgres \
  -e POSTGRES_USER=reflow_review \
  -e POSTGRES_PASSWORD=reflow_review \
  -e POSTGRES_DB=reflow_review \
  -p 127.0.0.1:55433:5432 \
  postgres:16.15-alpine@sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685
until docker exec reflow-review-postgres pg_isready -U reflow_review -d reflow_review >/dev/null 2>&1; do sleep 1; done
export REFLOW_TEST_POSTGRES_DSN='postgresql://reflow_review:reflow_review@127.0.0.1:55433/reflow_review'
make submission-check
docker stop reflow-review-postgres

# Development-only deterministic evaluation artifact
python -m reflow.evaluation.runner --world-seed 401 --observation-seed 1401 --settlements 50 --profile reconciliation_adversarial --output /tmp/reflow-gate11.json
python -m reflow.evaluation.verify /tmp/reflow-gate11.json

# Gate 17 reproducible scale artifact
python -m reflow.evaluation.scale_runner --settlements 1000 --profile clean --output /tmp/reflow-scale.json
python -m reflow.evaluation.scale_runner --verify /tmp/reflow-scale.json
```

### Run the synthetic Gate 18 control-tower demo

```bash
docker run --rm -d --name reflow-demo-postgres \
  -e POSTGRES_USER=reflow_demo \
  -e POSTGRES_PASSWORD=reflow_demo \
  -e POSTGRES_DB=reflow_demo \
  -p 127.0.0.1:55432:5432 postgres:16.15-alpine

until docker exec reflow-demo-postgres pg_isready -U reflow_demo -d reflow_demo >/dev/null 2>&1; do sleep 1; done
export REFLOW_POSTGRES_DSN='postgresql://reflow_demo:reflow_demo@127.0.0.1:55432/reflow_demo'
SCOPE=$(python -m reflow.evaluation.control_tower_demo --dsn "$REFLOW_POSTGRES_DSN")
cd web && npm run build && cd ..
python -m uvicorn reflow.control_tower_api:app_from_env --factory --host 127.0.0.1 --port 8000
# Open: http://127.0.0.1:8000/?scope=<the printed SCOPE>
```

The demo is synthetic regression/demo data. It is not a Razorpay Test Mode or live merchant accuracy claim.

Equivalent explicit checks:

```bash
python -m ruff check .
python -m mypy src
python -m pytest
cd web && npm run check && npm test && npm run build
```

CI runs Python/PostgreSQL and frontend validation together.

---

## Research and planning

### Foundation

- [`docs/01_BUILDATHON_BRIEF.md`](docs/01_BUILDATHON_BRIEF.md) — challenge bar and success criteria
- [`docs/02_RAZORPAY_RESEARCH.md`](docs/02_RAZORPAY_RESEARCH.md) — settlement, recon, webhook and AI-platform research
- [`docs/03_COMPETITIVE_ANALYSIS.md`](docs/03_COMPETITIVE_ANALYSIS.md) — track decision and competitive scan
- [`docs/04_PRODUCT_SPEC.md`](docs/04_PRODUCT_SPEC.md) — original product scope and domain objects
- [`docs/05_ARCHITECTURE.md`](docs/05_ARCHITECTURE.md) — original evidence-first architecture
- [`docs/06_EVALUATION_PLAN.md`](docs/06_EVALUATION_PLAN.md) — adversarial evaluation protocol
- [`docs/07_FAILURE_SAFETY_MODEL.md`](docs/07_FAILURE_SAFETY_MODEL.md) — failure taxonomy and guard boundaries
- [`docs/08_EXECUTION_ROADMAP.md`](docs/08_EXECUTION_ROADMAP.md) — gated roadmap
- [`docs/09_DEMO_SUBMISSION_PLAN.md`](docs/09_DEMO_SUBMISSION_PLAN.md) — pitch and review questions

### Current direction

- [`docs/10_FINANCE_OPS_PROBLEM_LANDSCAPE.md`](docs/10_FINANCE_OPS_PROBLEM_LANDSCAPE.md)
- [`docs/11_NOVEL_PRODUCT_THESIS.md`](docs/11_NOVEL_PRODUCT_THESIS.md)
- [`docs/12_MONEY_GRAPH_AND_RECONCILIATION_PROOFS.md`](docs/12_MONEY_GRAPH_AND_RECONCILIATION_PROOFS.md)
- [`docs/13_MESSY_DATA_AND_CONNECTOR_COMPILER.md`](docs/13_MESSY_DATA_AND_CONNECTOR_COMPILER.md)
- [`docs/14_SCALE_PERFORMANCE_AND_RESILIENCE.md`](docs/14_SCALE_PERFORMANCE_AND_RESILIENCE.md)
- [`docs/15_RAZORPAY_ALIGNMENT_AND_JUDGING_STRATEGY.md`](docs/15_RAZORPAY_ALIGNMENT_AND_JUDGING_STRATEGY.md)
- [`docs/16_MASTER_BUILD_PLAN.md`](docs/16_MASTER_BUILD_PLAN.md) — implementation contract
- [`docs/17_RESEARCH_SOURCEBOOK.md`](docs/17_RESEARCH_SOURCEBOOK.md)
- [`docs/18_IMPLEMENTATION_AUDIT.md`](docs/18_IMPLEMENTATION_AUDIT.md)
- [`docs/19_SECOND_IMPLEMENTATION_AUDIT.md`](docs/19_SECOND_IMPLEMENTATION_AUDIT.md)
- [`docs/20_GATE_7_CHECKPOINT.md`](docs/20_GATE_7_CHECKPOINT.md)
- [`docs/21_GATE_8_CHECKPOINT.md`](docs/21_GATE_8_CHECKPOINT.md)
- [`docs/22_THIRD_INDEPENDENT_PRE_GATE_9_AUDIT.md`](docs/22_THIRD_INDEPENDENT_PRE_GATE_9_AUDIT.md)
- [`docs/23_GATE_9_CHECKPOINT.md`](docs/23_GATE_9_CHECKPOINT.md)
- [`docs/24_GATE_10_CHECKPOINT.md`](docs/24_GATE_10_CHECKPOINT.md)
- [`docs/25_GATE_11_CHECKPOINT.md`](docs/25_GATE_11_CHECKPOINT.md)
- [`docs/26_GATE_12_CHECKPOINT.md`](docs/26_GATE_12_CHECKPOINT.md)
- [`docs/27_STRATEGIC_PAUSE_CURRENT_STATE_AND_REVISED_PLAN.md`](docs/27_STRATEGIC_PAUSE_CURRENT_STATE_AND_REVISED_PLAN.md) — authoritative revised roadmap
- [`docs/28_GATE_13_CHECKPOINT.md`](docs/28_GATE_13_CHECKPOINT.md) — deterministic control-plane checkpoint
- [`docs/29_GATE_14_CONTRACT_AND_ACCEPTANCE_PLAN.md`](docs/29_GATE_14_CONTRACT_AND_ACCEPTANCE_PLAN.md) — frozen Gate 14 contract/acceptance plan
- [`docs/30_GATE_14_CHECKPOINT.md`](docs/30_GATE_14_CHECKPOINT.md) — exception case/fingerprint checkpoint
- [`docs/31_GATE_15_REAL_RAZORPAY_CONTRACT_AND_ACCEPTANCE_PLAN.md`](docs/31_GATE_15_REAL_RAZORPAY_CONTRACT_AND_ACCEPTANCE_PLAN.md) — frozen Gate 15 provider contract/acceptance plan
- [`docs/32_GATE_15_CHECKPOINT.md`](docs/32_GATE_15_CHECKPOINT.md) — current Razorpay provider-integration checkpoint
- [`docs/33_GATE_16_CONTRACT_AND_ACCEPTANCE_PLAN.md`](docs/33_GATE_16_CONTRACT_AND_ACCEPTANCE_PLAN.md) — frozen Gate 16 bounded-investigation contract/acceptance plan
- [`docs/34_GATE_16_CHECKPOINT.md`](docs/34_GATE_16_CHECKPOINT.md) — bounded investigation/provider checkpoint
- [`docs/35_GATE_17_CONTRACT_AND_ACCEPTANCE_PLAN.md`](docs/35_GATE_17_CONTRACT_AND_ACCEPTANCE_PLAN.md) — frozen Gate 17 scale/durability contract
- [`docs/36_GATE_17_CHECKPOINT.md`](docs/36_GATE_17_CHECKPOINT.md) — current scale/PostgreSQL durability/application checkpoint
- [`docs/37_GATE_18_CONTRACT_AND_ACCEPTANCE_PLAN.md`](docs/37_GATE_18_CONTRACT_AND_ACCEPTANCE_PLAN.md) — frozen Gate 18 control-tower contract
- [`docs/38_GATE_18_CHECKPOINT.md`](docs/38_GATE_18_CHECKPOINT.md) — current read-only Operator Control Tower checkpoint
- [`docs/39_GATE_19_CONTRACT_AND_HELDOUT_PLAN.md`](docs/39_GATE_19_CONTRACT_AND_HELDOUT_PLAN.md) — frozen final held-out/failure-campaign protocol
- [`docs/40_GATE_19_CHECKPOINT.md`](docs/40_GATE_19_CHECKPOINT.md) — final held-out evidence and submission-hardening checkpoint
- [`docs/41_FINAL_5_MINUTE_PITCH.md`](docs/41_FINAL_5_MINUTE_PITCH.md) — exact five-minute recording script/runbook

---

## Build status

### Research / planning

- [x] competition and application-form research
- [x] Razorpay domain/API research
- [x] competitive and finance-ops research
- [x] Track 04 decision
- [x] financial-truth-compiler thesis
- [x] Money Graph / proof protocol
- [x] connector compiler and safety model
- [x] evaluation strategy
- [x] master implementation plan

### Deterministic implementation

- [x] repository engineering constitution / CI
- [x] financial domain contracts
- [x] synthetic hidden world
- [x] observation corruption engine
- [x] normalized deterministic known-source adapters
- [x] append-only raw evidence journal
- [x] journal-first ingestion
- [x] temporal payment reducer
- [x] journal-backed provenance-preserving Money Graph
- [x] Settlement Composition Proof
- [x] Bank Receipt Proof
- [x] full proof versioning
- [x] residual solver
- [x] baseline evaluation harness
- [x] reconciliation scope + source-delivery manifests
- [x] policy-versioned immutable reconciliation runs
- [x] proof-derived evidence coverage / no-orphan-money control
- [x] exact balance/clearing-position control + close readiness
- [x] deterministic ExceptionCase lifecycle / fingerprinting
- [x] reproducible 50 / 1k / 10k scale benchmark + checked-in artifacts
- [x] PostgreSQL append-only evidence + immutable application artifacts/current pointers
- [x] minimal durability/application service boundary
- [x] provider-shaped Razorpay webhook / Settlement Recon / standard-settlement integration
- [ ] authenticated real Test Mode settlement/recon corpus (none currently available in connected account)
- [ ] Instant Settlement `setlod` / `setlodp` proof support

### AI / product surface

- [x] Source Adapter Compiler / bounded AI proposal path
- [x] bounded Exception Investigation Agent / validated read-only tool trace
- [x] read-only operator control tower UI / proof + case drill-down
- [x] final representative failure campaign
- [x] frozen final held-out benchmark
- [ ] optional synthetic-only public deployment
- [x] five-minute pitch script/runbook
- [ ] five-minute pitch video recording/upload

---

## Engineering rule

If implementation evidence contradicts the design, **the design changes**.

ReFlow will not preserve an attractive architecture, AI feature or benchmark claim after testing proves it wrong.
