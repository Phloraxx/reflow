# Strategic Pause — Current State, Architecture Review, and Revised Plan

**Review date:** 2026-08-31  
**Checkpoint reviewed:** `main` at `a7bf0d134dcd524a370591b023986a42c72bcae6`  
**Status:** Gates 0–12 implemented and green; Phase 13 implementation deliberately paused.

This document is the authoritative post-Gate-12 design review for ReFlow. It records what exists, what has survived repeated audits, what is missing, what should *not* be built, the external systems researched for inspiration, and the revised critical path.

## Executive decision

Do **not** continue directly into the Exception Investigation Agent.

ReFlow has built a strong financial proof kernel, but it is missing the deterministic operational control plane that should sit between proofs and an agent:

- reconciliation scope and run identity;
- source delivery/snapshot semantics and completeness;
- process/configuration versioning;
- cross-run exception continuity, ageing and ownership;
- balance/clearing-position control;
- close/readiness and evidence-coverage certification.

The next phase should build those deterministic primitives first. The agent should consume a stable `ExceptionCase` / case packet rather than inventing workflow state from raw proofs.

## 1. What ReFlow is now

ReFlow is best described as an **evidence-first reconciliation control system**, not a generic matching engine and not a ledger.

The implemented deterministic path is:

```text
raw source evidence
  -> immutable SourceEnvelope journal
  -> deterministic canonicalization / approved Gate 12 adapter
  -> temporal payment reconstruction
  -> Money Graph
  -> settlement composition proof
  -> bank receipt proof
  -> immutable versioned reconciliation proof
  -> bounded residual hypotheses
  -> hidden-truth evaluation
```

AI exists only in Gate 12 as an optional schema-semantic proposer. It cannot approve a first-seen schema, create canonical money facts, alter financial proof, or mark anything reconciled.

The strongest product thesis remains valid:

> Every rupee should have a path, a proof, or an explicit exception.

The next improvement is to make that statement true at the **whole-run / whole-period level**, not only settlement-by-settlement.

## 2. Current implementation inventory

| Gate | Implemented capability | Review verdict |
|---|---|---|
| 0 | Engineering constitution, CI, strict typing/lint/tests | Keep |
| 1 | Typed IDs, integer-paise money, immutable financial contracts | Keep |
| 2 | Hidden financial-world generator | Keep; evaluation-only |
| 3 | Adversarial observation corruption | Keep; evaluation-only |
| 4 | Strict normalized known-source adapters | Keep as canonical safety funnel |
| 5 | Append-only raw journal + temporal payment reducer | Keep |
| 6 | Provenance-preserving Money Graph | Keep |
| 7 | Batch-safe Settlement Composition Proof | Keep |
| 8 | Conservative Bank Receipt Proof | Keep |
| 9 | Immutable versioned full Reconciliation Proof | Keep |
| 10 | Bounded residual hypotheses | Keep; hypotheses only |
| 11 | Hidden-truth benchmark with B0/B1/B2/ReFlow | Keep; final held-out run still pending |
| 12 | AI-assisted Source Adapter Compiler + approval lifecycle | Freeze; do not expand before submission |

Verified `main` currently passes Ruff, strict mypy and 221 tests.

Approximate source size at this review is 9.3k Python lines plus 4.8k test lines. Gate 12 is now a substantial subsystem, so future work should prefer **reuse and orchestration** over additional framework-building.

## 3. What is already unusually strong

The following are differentiators and should not be diluted during simplification:

- exact integer money and fail-closed currency/unit semantics;
- raw evidence retained before interpretation;
- raw-to-canonical provenance;
- source authority separation;
- zero-residual-is-not-proof semantics;
- bank receipt proven independently from settlement composition;
- immutable temporal proof versions and reopening;
- bounded residual search that cannot promote itself to proof;
- benchmark scorer that is harder to fool than row-ID matching;
- AI isolated from financial authority.

## 4. External systems reviewed and what to borrow

### Razorpay

Razorpay's 2026 Agent Studio emphasizes verified first-party data, merchant-defined permissions, review-first operation, independent validation of every action, and complete audit trails. Its settlement docs continue to distinguish `settlement.processed` from actual bank credit and use UTR as the bank reconciliation reference.

**Borrow:** platform guardrails outside the model; source-specific authority; review-first sensitive actions.  
**Do not copy:** a conversational interface as the primary product surface.

### Stripe

Stripe exposes two distinct reconciliation views: payout/batch reconciliation and balance reconciliation. Balance Transactions are immutable and replayable; payout reconciliation is naturally modeled through a clearing account.

**Borrow:** add a period/balance control above settlement proofs; explicitly distinguish transaction-level proof from account-level position proof.

### Adyen

Adyen separates transaction-level and batch-level reconciliation, combines multiple reports, stresses reporting periods/timezones, and recommends automated report ingestion for scalable full reconciliation.

**Borrow:** source period, timezone, account scope and report completeness must be first-class run metadata.

### Modern Treasury

Modern Treasury exposes explicit 1:1, 1:many and many:1 reconciliation strategies, prioritizes specific rules over broad rules, abstains when multiple expected payments match, and separately performs account reconciliation between internal and bank-reported balances.

**Borrow:** explicit reconciliation process/scope metadata, balance variance controls, and ambiguity-as-exception.  
**Do not copy now:** a generic many-to-many rules engine; ReFlow's Razorpay settlement problem does not require it for the Buildathon.

### Duco

Duco's current best practices separate data preparation from reconciliation, distinguish replacement snapshots from delta feeds, track records across runs, preserve exception age/ownership, and version configuration changes. It also recommends submission windows and missed-data notifications.

**Borrow:** `SNAPSHOT` vs `DELTA`, source submission windows, stable exception tracking keys, ageing, ownership and configuration-version linkage.

### BlackLine / Trintech

Enterprise close products emphasize exception-first review, materiality/risk prioritization, continuous reconciliation, standardized controls and audit-ready certification. They also support complex matching patterns at large scale.

**Borrow:** materiality should prioritize review, not weaken proof; expose close/readiness and certification artifacts.  
**Do not copy now:** ERP journal-posting automation or huge configurable rule catalogs.

### Swift Case Management

Swift's 2026 exception/investigation direction uses structured cases, business validation, pre-checks, pre-populated data, smart routing, reminders and end-to-end tracking around a stable transaction reference.

**Borrow:** exceptions need stable case identity and lifecycle before an AI investigator is useful.

### Formance / TigerBeetle

Formance cleanly separates external payment data, ledger truth and reconciliation controls; its reconciliation controls compare balances at aligned points in time. TigerBeetle keeps financial transfers immutable and corrects history through new records rather than mutation.

**Borrow:** point-in-time balance controls and append-only corrections.  
**Do not copy:** building a full double-entry/product ledger inside ReFlow.

### Modern Treasury Bank Operations Agent / agent best practices

Modern Treasury's July 2026 Bank Operations Agent gives every tool an explicit epistemic role, queries multiple systems for evidence, treats absence carefully, and prefers a scoped unanswered question over a confident guess. OpenAI and Razorpay likewise recommend layered guardrails and human review for high-risk actions.

**Borrow:** the Phase 13+ agent should operate on a deterministic case file, use read-only role-labelled tools, cite evidence for claims, and abstain when the necessary authority is absent.

## 5. The major architectural holes

### Hole A — no first-class reconciliation run

`CanonicalBatch.compilation_sha256` proves a compiled batch, and Gate 9 proofs have cutoffs, but there is no object representing the **business run** that produced a set of proofs.

We need a `ReconciliationRun` carrying at minimum:

- run ID;
- reconciliation scope ID;
- process/policy version;
- knowledge cutoff;
- source snapshot/delivery IDs;
- canonical compilation SHA(s);
- proof ruleset versions;
- started/completed timestamps;
- run outcome and counts;
- code/build SHA for reproducibility where available.

This should become the root object for UI, audit and final benchmark evidence.

### Hole B — source completeness is implicit

Today ReFlow can say evidence is absent, but not always whether it is **late, partial, stale, outside the reporting window, or genuinely missing**.

That distinction is operationally critical. A missing bank file should not create the same case as a bank file that arrived and lacks the expected credit.

Add a `SourceDeliveryManifest` / `SourceSnapshot` with:

- source kind + source account;
- `SNAPSHOT` vs `DELTA` delivery mode;
- period start/end and timezone;
- expected-by/submission-window metadata;
- received-at and completeness state;
- row count/control totals where available;
- raw envelope set / content hash;
- adapter/version/schema fingerprint.

### Hole C — scope/account boundaries are under-modeled

Current proofs are batch-safe, but production reconciliation must explicitly scope identities by merchant/provider account, destination bank account, channel and currency. Razorpay and Adyen both support multi-account reporting, and consolidated reports make accidental cross-account matching a real class of error.

Add `ReconciliationScope` containing only the identifiers needed to partition financial truth, for example:

```text
merchant / legal entity
provider + provider account
bank destination account
currency
channel / product where material
```

UTR, economic-ownership and source-completeness checks must be evaluated inside the appropriate scope rather than across unrelated accounts.

### Hole D — no period/balance control proof

ReFlow proves individual settlement composition and bank receipt, but Track 04 also asks for books/cash position. We do **not** need a full ledger to address this.

Add a lightweight `BalanceControlProof` / `ClearingPositionProof` that checks a scoped period equation such as:

```text
opening unsettled / clearing position
+ new provider-side activity
- bank-proven payouts
± authoritative adjustments
= closing unsettled / clearing position
```

Where an external opening/closing balance is available, compare the derived position at the same point in time. Exact transaction proofs remain the explanation beneath the control.

This is inspired by Stripe balance/payout reconciliation, Modern Treasury account reconciliation and Formance controls, but remains a verification layer rather than a new accounting ledger.

### Hole E — no durable exception lifecycle

A proof can be contradicted/residual/incomplete, but there is no stable operational object that follows the break across runs.

Introduce deterministic `ExceptionCase` before any investigation agent:

- stable tracking key and case ID;
- reconciliation scope;
- first seen / last seen / age;
- current proof version and prior proof history;
- reason/fingerprint;
- affected amount and materiality band;
- source completeness state;
- owner/team and workflow status;
- linked raw evidence and residual hypotheses;
- resolution/closure reason.

Changing proof/configuration must not silently destroy case history.

### Hole F — no complete process/policy version

Adapters and proof rules have versions, but the whole reconciliation process does not. Add `ReconciliationPolicyVersion` for:

- required source classes;
- scope definition;
- reporting timezone;
- source submission windows;
- bank waiting/SLA policy;
- materiality bands for prioritization;
- enabled deterministic controls;
- case tracking-key definition.

Crucially, materiality and SLA policy may change **workflow priority**, never exact financial proof.

### Hole G — no operator disposition separate from financial truth

A human eventually needs to acknowledge or operationally close some cases. That must not rewrite a failed proof as `PROVEN_RECONCILED`.

Store a separate append-only `OperatorDisposition`: acknowledge, request source correction, accept operational variance, defer, close case, reopen. Keep the financial proof immutable beside it.

### Hole H — no whole-run evidence coverage certificate

Settlement proofs can be correct while some source records remain outside every proof. We need a run-level conservation check answering:

> Did every financially relevant record in scope land in a proven path, a waiting/open bucket, quarantine, or an explicit exception?

Add an `EvidenceCoverageCertificate` with exact counts and values for:

- proven/consumed evidence;
- open/unsettled evidence;
- waiting-for-source evidence;
- contradicted/residual evidence;
- quarantined invalid source evidence;
- orphan/unclassified evidence.

A close/readiness artifact must be `NOT_READY` if financially relevant orphan evidence remains.

This is the strongest extension of the existing tagline: **no orphan money**.

### Hole I — application orchestration/persistence is still missing

The code is currently an excellent deterministic Python reference engine, but durable product operation will need one simple application layer and persistent storage for runs, source manifests, cases, proof versions and approvals.

Do not create microservices. Preferred Buildathon shape:

```text
FastAPI / application service
        ↓
PostgreSQL
        ↓
existing deterministic Python domain engine
```

The in-memory implementations remain valuable tests/reference stores. Kafka, Redis, Kubernetes and distributed workflow infrastructure should not be introduced without measured need.

### Hole J — real provider evidence still comes too late in the old roadmap

Before an AI investigator is polished, ReFlow should validate at least one real Razorpay Test Mode / documented Settlement Recon adapter path. Agent reasoning should be tested against real provider-shaped semantics, not only synthetic normalized fixtures.

## 6. Simplification decisions — what not to build

### Do not build a full double-entry ledger

Stripe/Modern Treasury/Formance show why ledgers matter, but ReFlow's Buildathon value is **verification across merchant, Razorpay and bank evidence**, not becoming a product ledger. A small clearing/balance control is sufficient.

### Do not build a generic many-to-many matching platform

Modern Treasury, Duco and BlackLine support broad matching strategies because they serve many finance processes. ReFlow should remain optimized for the concrete many-to-one settlement problem plus provider-specific extensions. Many-to-many may exist as manual/hypothesis support later.

### Do not make tolerances equal truth

Materiality/tolerance can reduce alert noise or prioritize review. It must never turn ₹99.99 into exact proof of ₹100.00. The exact residual remains visible.

### Do not make the UI chat-first

The primary product is a control tower: run health, close readiness, proofs, source state and exception cases. AI belongs inside a case as an investigator, not as the only navigation model.

### Do not expand Gate 12 before submission

The Source Adapter Compiler is already large and well-guarded. Freeze its transform language and approval model unless real provider integration exposes a concrete missing primitive.

### Do not add multi-agent architecture

One bounded investigation agent with deterministic tools is enough. Multiple agents add coordination/evaluation surface without improving the core finance-control story.

### Do not add infrastructure theatre

Stay monolithic and modular. Add PostgreSQL/API only when the application layer needs durability. No Kafka, Redis, Kubernetes or workflow engine until measurements prove a requirement.

## 7. New product primitives worth adding

### 7.1 Reconciliation Run Capsule

A content-addressed run manifest containing scope, source snapshots, policy version, canonical hashes, proof-rule versions, code/build SHA and outputs.

Think of it as **software-build provenance for financial reconciliation**. A reviewer should be able to reproduce exactly what ReFlow knew and which rules produced a result.

### 7.2 No-Orphan-Money Certificate

A run-level `EvidenceCoverageCertificate` proving that every relevant source fact belongs to an explicit financial state. This is more defensible than a simple “97% matched” metric because the unmatched remainder is classified and valued.

### 7.3 Close Readiness / Cash Position Certificate

Combine source completeness, balance/clearing control, proof coverage and material unresolved cases into:

```text
READY
NOT_READY — BANK_SOURCE_LATE
NOT_READY — ₹42,300 UNEXPLAINED
NOT_READY — 3 ORPHAN ECONOMIC RECORDS
```

This directly turns ReFlow from a matching demo into a finance controller.

### 7.4 Exception Passport

A stable case that survives reruns and includes proof history, age, owner, materiality, evidence diff and resolution state. The case is the unit of investigation, not an individual raw row.

### 7.5 Materiality without truth weakening

Compute materiality/risk for queue ordering and approval workflow only. Preserve the exact proof/residual underneath. This gives enterprise-style prioritization without sacrificing ReFlow's evidence standard.

### 7.6 Source Authority Map

Make the existing design rule explicit and machine-readable:

- merchant source: expected commercial intent;
- Razorpay event/recon/settlement: provider lifecycle/composition facts;
- bank: actual cash movement;
- ReFlow proof engine: derived verification;
- operator: workflow disposition;
- AI: no financial authority.

### 7.7 Epistemic Case Packet for the agent

Before calling a model, deterministically build a bounded packet:

- exact case ID and scope;
- current proof + relevant prior proof diff;
- residual targets/candidates;
- source completeness/health;
- evidence IDs and source authority roles;
- already-known contradictions;
- allowed questions/actions.

The model should investigate the packet and invoke read-only tools to fill gaps. It should not search the entire financial world by default.

### 7.8 Claim-carrying investigation output

Every material agent claim should be typed as one of:

```text
SOURCE_FACT
DERIVED_FACT
HYPOTHESIS
UNKNOWN
```

and cite the evidence/tool result that supports it. Numeric claims should come from deterministic tool output rather than model arithmetic.

This is inspired by Modern Treasury's separation of what documentation says, what code/data proves, and what remains unresolved.

### 7.9 Correction without rewriting history

If an operator resolves a case or a source corrects data, create a new source/proof/case event. Never mutate the historical proof that was correct at its prior knowledge cutoff.

### 7.10 Two-level reconciliation UX

Expose both:

1. **transaction/settlement proof** — why this payout is correct;
2. **run/account control** — whether the whole scoped cash position is complete and close-ready.

This mirrors how mature payment platforms separate payout reconciliation from balance/account reconciliation while preserving ReFlow's proof-first novelty.

## 8. Revised architecture after this review

```text
Sources
  merchant / Razorpay / bank
       ↓
SourceDeliveryManifest + ReconciliationScope
       ↓
Immutable Raw Evidence Journal
       ↓
Known Adapter or Gate 12 Approved Adapter
       ↓
CanonicalBatch / canonical compilation binding
       ↓
┌────────────────────────────────────────────┐
│ Deterministic financial proof kernel       │
│ payment reducer → Money Graph              │
│ → composition proof → bank proof           │
│ → versioned full proof → residual solver   │
└────────────────────────────────────────────┘
       ↓
ReconciliationRun
  ├─ EvidenceCoverageCertificate
  ├─ BalanceControlProof
  ├─ CloseReadinessCertificate
  └─ ExceptionCase lifecycle
              ↓
      bounded case packet
              ↓
     Investigation Agent
              ↓
 typed evidence-backed hypothesis / safe next action
```

The deterministic run/control layer owns truth and workflow state. The agent owns **investigation assistance only**.

## 9. Revised phase order

The old post-Gate-12 ordering is superseded by this section.

### New Gate 13 — Reconciliation Control Plane

Build the minimum deterministic run layer:

- `ReconciliationScope`;
- `SourceDeliveryManifest` with `SNAPSHOT` / `DELTA`;
- source completeness/watermark states;
- `ReconciliationPolicyVersion`;
- `ReconciliationRun`;
- `EvidenceCoverageCertificate`;
- minimal `BalanceControlProof` / clearing-position control.

**Gate:** replay/permutation-safe run identity; missing/late/partial sources distinguished; no orphan economic evidence can disappear; balance control has exact integer arithmetic and aligned scope/time.

### New Gate 14 — Exception Case Lifecycle + Fingerprints

Build deterministic cases before AI:

- stable case tracking key;
- first/last seen + age;
- materiality band;
- owner/status;
- proof/version linkage;
- append-only operator disposition;
- deterministic exception fingerprint/incident grouping;
- carry-forward/auto-close rules across runs.

**Gate:** same break across runs retains continuity; changed economics can create a new case; configuration version is always visible; clusters preserve exact affected count/value.

### New Gate 15 — Real Razorpay Integration

Move real provider-shaped validation earlier:

- actual webhook semantics;
- Settlement Recon API `debit` / `credit` / `amount` / `fee` / `tax` normalization;
- settlement entity/webhook shape;
- Test Mode evidence where records exist;
- explicit `REAL TEST MODE` vs `SYNTHETIC` labels.

**Gate:** no synthetic field semantics are presented as Razorpay production semantics.

### New Gate 16 — Bounded Exception Investigation Agent

Now add the agent on top of deterministic `ExceptionCase` packets.

Tools remain read-only and role-labelled. Output is a typed hypothesis with cited evidence and one allowed next action:

```text
WAIT
RECHECK
REQUEST_SOURCE
REQUEST_HUMAN_REVIEW
ABSTAIN
```

No `MARK_RECONCILED`, arbitrary SQL, adapter approval, ledger mutation, refund, payout or evidence attachment is available.

**Gate:** hallucinated evidence rejected; unsupported numbers rejected; prompt-like source text inert; provider outage harmless to financial truth; model abstention accepted; tool traces independently evaluable.

### New Gate 17 — Scale + Durability/Application Layer

Benchmark first; add only the persistence needed for the product:

- 50 / 1k / 10k / 100k / 1M-if-feasible;
- exception densities;
- run/case/control proof throughput and memory;
- PostgreSQL persistence for product state;
- minimal application service/API.

No distributed infrastructure unless the benchmark proves one-process/Postgres is insufficient.

### New Gate 18 — Operator Control Tower

Primary surfaces:

1. **Run / Close Overview** — source completeness, proven/waiting/residual/contradicted value, balance control, readiness;
2. **Settlement Proof** — exact equation, bank proof and timeline;
3. **Exception Queue** — age, materiality, owner, fingerprint/incident, source blocker;
4. **Case File** — proof diff, evidence, residual hypotheses, agent investigation, operator disposition;
5. **Source Lab** — delivery manifest, schema fingerprint, adapter/version/drift;
6. **Evaluation Lab** — benchmark artifacts and safety metrics.

The agent appears inside Case File. There is no chatbot as the product homepage.

### New Gate 19 — Final Failure Campaign + Held-Out Evidence + Submission

Freeze policies/scorers first, then run:

- held-out reconciliation seeds;
- held-out adapter/provider evaluation when a real model/key is available;
- scale benchmarks with hardware disclosure;
- source outage/late-file tests;
- case carry-forward tests;
- agent outage/prompt-injection/tool-evidence tests;
- crash/replay/idempotency tests;
- final demo corpus.

Publish failures and unresolved limitations honestly. No hand-edited headline metric.

## 10. Submission-critical priority

Not every idea above deserves equal build priority.

### P0 — must exist for the strongest ReFlow story

1. Reconciliation scope + run manifest.
2. Source delivery/completeness state.
3. Evidence coverage / no-orphan-money certificate.
4. Minimal balance/clearing control and close-readiness result.
5. Stable deterministic `ExceptionCase` lifecycle.
6. Real Razorpay-shaped adapter/test evidence.
7. Bounded investigation agent operating on case files.
8. Usable control-tower UI.
9. Reproducible scale + held-out benchmark and failure campaign.

### P1 — add if time remains

- deterministic incident clustering/fingerprints beyond basic case grouping;
- materiality/risk queue ranking;
- PostgreSQL durability beyond the minimum demo application state;
- source-health trends and submission-window notifications;
- richer operator dispositions/segregation of duties;
- Close Readiness certificate export.

### P2 — explicitly defer

- generic many-to-many automatic matching;
- full product/general ledger;
- ERP writeback/journal posting;
- Instant Settlement `setlod`/`setlodp` support unless needed for the demo;
- OCR/PDF ingestion;
- multi-agent orchestration;
- multi-provider production connectors;
- distributed infrastructure.

## 11. Non-negotiable invariants for the next phases

1. **Proof remains exact.** Workflow materiality/tolerance never alters exact money residuals.
2. **Raw evidence precedes interpretation.** New source/control/agent paths remain journal-first where source evidence is involved.
3. **No source can prove another source's fact.** Bank proves cash; Razorpay proves provider facts; merchant proves expectation.
4. **Absence is not evidence without completeness.** A missing item is actionable only in the context of the relevant source delivery state/window.
5. **Runs are immutable/reproducible.** New evidence creates a new run/proof/case event rather than rewriting history.
6. **Operator workflow is separate from financial truth.** Human disposition never forges a green deterministic proof.
7. **AI has no authority.** It can read, explain, hypothesize and request bounded next actions only.
8. **Evaluation remains hidden-truth isolated.** New run/case code must not import simulator truth.
9. **Scope is explicit.** Matching/uniqueness/completeness controls cannot accidentally cross merchant/provider/bank-account boundaries.
10. **Every financially relevant record is classified.** Orphan evidence is a failing run-level control, not ignored noise.

## 12. Gate 13 acceptance tests to write before implementation

- same exact source snapshots + policy + cutoff produce the same run identity;
- source-row delivery permutation does not change run identity;
- a late source changes completeness from `WAITING/LATE` to `COMPLETE` without rewriting the prior run;
- snapshot and delta feeds have different carry-forward semantics;
- one merchant/provider account cannot satisfy another scope's proof/control;
- missing bank delivery is distinguishable from complete bank delivery with missing credit;
- every canonical economic record is represented in exactly one coverage bucket;
- orphan relevant evidence makes Close Readiness `NOT_READY`;
- materiality changes priority but never a proof status/residual;
- balance control rejects mismatched point-in-time/timezone boundaries;
- case tracking survives an unchanged break across runs;
- changed economic identity/value can create a new case rather than inheriting stale investigation state.

## 13. Research references reviewed in this pause

Primary/current sources used to challenge the design:

- Razorpay Buildathon Track 04: https://razorpay.com/buildathon/
- Razorpay Agent Studio guardrails: https://razorpay.com/blog/razorpay-agent-studio-principles-guardrails-and-merchant-control/
- Razorpay settlement webhook semantics: https://razorpay.com/docs/webhooks/settlements/
- Razorpay settlement dashboard/reporting: https://razorpay.com/docs/payments/settlements/dashboard/
- Stripe reporting/reconciliation: https://docs.stripe.com/plan-integration/get-started/reporting-reconciliation
- Stripe payout reconciliation: https://docs.stripe.com/reports/payout-reconciliation
- Stripe report selection / clearing-account model: https://docs.stripe.com/reports/select-a-report
- Adyen settlement reconciliation: https://docs.adyen.com/reporting/settlement-reconciliation
- Adyen report preparation: https://docs.adyen.com/platforms/prepare-reports/
- Modern Treasury reconciliation rules: https://docs.moderntreasury.com/payments/docs/defining-reconciliation-rules
- Modern Treasury account reconciliation: https://docs.moderntreasury.com/ledgers/docs/account-reconciliation
- Modern Treasury balance timing: https://docs.moderntreasury.com/ledgers/docs/balances-used-in-account-reconciliation
- Modern Treasury ledger best practices: https://www.moderntreasury.com/journal/best-practices-for-maintaining-a-ledger
- Modern Treasury Bank Operations Agent: https://www.moderntreasury.com/journal/what-we-learned-building-a-bank-operations-agent
- Duco reconciliation setup: https://support.du.co/hc/en-us/articles/31787826069789-Best-practice-reconciliation-setup
- Duco exception management: https://support.du.co/hc/en-us/articles/31857114694045-Best-practice-exception-management
- Swift Case Management: https://www.swift.com/products/case-management
- Formance reconciliation controls: https://docs.formance.com/modules/reconciliation/controls
- TigerBeetle immutable transfers: https://docs.tigerbeetle.com/reference/transfer/
- OpenAI practical agent guide: https://openai.com/business/guides-and-resources/a-practical-guide-to-building-ai-agents/

## 14. Review verdict

ReFlow has **not** built itself into the wrong product. The deterministic proof kernel is the strongest part of the system and should remain the center.

The main architectural mistake would be to continue adding AI features before adding the operational objects that mature reconciliation systems rely on. The missing layer is not another matching algorithm. It is **control-plane state** around the proofs.

The recommended product sentence after this review is:

> **ReFlow is an evidence-first finance controller that compiles messy payment data into reproducible reconciliation runs, exact money proofs, balance controls and persistent exception cases; AI assists with schema understanding and investigation, but never defines financial truth.**

## 15. Immediate next action

1. Keep `build/gate-13-exception-investigation-agent` abandoned/frozen; no Phase 13 agent code has been written there.
2. Merge this strategic-review document into `main`.
3. Start a fresh branch for **New Gate 13 — Reconciliation Control Plane**.
4. Write the Gate 13 contracts/tests first: scope, source manifest, policy, run, coverage and minimal balance control.
5. Re-audit Gate 13 before introducing `ExceptionCase` persistence or AI.

The old master plan remains useful for historical context, but all post-Gate-12 sequencing must follow this document unless a later reviewed document explicitly supersedes it.
