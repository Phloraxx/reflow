# ReFlow Master Build Plan

## Status

This is the implementation contract produced after the second research pass.

No implementation phase should skip its gate merely to make the UI look complete.

The final product thesis is:

> **ReFlow is a financial truth compiler. It compiles messy payment evidence into a temporal Money Graph and machine-verifiable reconciliation proofs. Every rupee gets a path, a proof, or an exception. AI helps compile unfamiliar source formats and investigate exceptions, but it never owns financial truth.**

Track: **Razorpay AI Buildathon 2026 — Track 04, AI Finance Controller**

---

# Part I — What we are building

## Core finance loop

```text
Merchant records
       +
Razorpay events/recon/settlements
       +
Bank evidence
       ↓
Source Adapter Layer
       ↓
Immutable Canonical Journal
       ↓
Temporal Payment Reducer
       ↓
Money Graph
       ↓
Settlement Composition Proof
       ↓
Bank Receipt Proof
       ↓
Reconciliation Proof
       ├── PROVEN
       └── RESIDUAL / EXCEPTION
                    ↓
         Bounded AI Investigator
```

## Two meaningful AI jobs

### 1. Source Adapter Synthesizer

Understands unfamiliar financial exports and proposes a constrained declarative adapter. The adapter must compile and pass deterministic validation before activation.

### 2. Exception Investigation Agent

Uses read-only tools over proof/evidence objects to identify missing evidence or propose a bounded next step. It cannot alter financial truth.

---

# Part II — Non-negotiable invariants

1. Money uses signed integer paise.
2. Currency is explicit.
3. Raw evidence is append-only.
4. Source identity/provenance is preserved.
5. Duplicate delivery cannot duplicate economic value.
6. Arrival order cannot silently define final payment truth.
7. Settlement composition arithmetic is deterministic.
8. Bank receipt is separate from settlement-processed state.
9. Ambiguity fails closed.
10. A zero residual does not prove identity by itself.
11. AI cannot mark a case reconciled.
12. Unknown schema/sign/unit cannot be guessed into production.
13. Every final metric must be reproducible.
14. Hidden evaluation truth never enters the candidate pipeline.
15. Every published limitation remains visible.

---

# Part III — Implementation phases

## Phase 0 — Repository constitution

### Deliverables

- `AGENTS.md`
- root project commands/conventions
- `.env.example`
- lint/type/test configuration
- `FAILURE_LOG.md`
- `LIMITATIONS.md`
- CI skeleton

### Gate 0

A fresh checkout can run validation/tests with one documented command even if tests are mostly scaffolding.

No credentials committed.

---

## Phase 1 — Domain contracts

### Build

Typed models for:

- Money
- SourceEnvelope
- MerchantOrder
- PaymentEvent
- PaymentCurrentState
- Refund
- Transfer
- Adjustment
- SettlementReconEntry
- Settlement
- BankEntry
- EvidenceEdge

Full-reconciliation proof/version/exception contracts are deliberately **not** predeclared in Phase 1. They must be defined at Gate 9 from the audited Gate 7 composition and Gate 8 bank-proof outputs rather than from speculative scaffolding.

### Required tests

- float rejected from money boundary;
- currency mismatch rejected;
- impossible timestamp/range rejected;
- canonical signs are unambiguous;
- IDs are strongly typed enough to avoid accidental cross-entity joins.

### Gate 1

Domain models pass unit/property tests with zero dependence on FastAPI, database or AI provider.

---

## Phase 2 — Hidden financial world generator

### Build

Generate authoritative hidden objects:

```text
orders
payments
refunds
adjustments
settlement compositions
settlements
bank credits
```

### Dataset shapes

- clean normal settlement;
- multiple payments per settlement;
- refunds;
- adjustments;
- cross-period refund;
- same-amount settlements;
- Instant Settlement multi-payout shape — deferred until explicit `setlod` / `setlodp` provider modeling;
- missing bank receipt;
- incorrect bank amount;
- duplicate economic row;
- high-cardinality settlement.

### Critical separation

`truth/` data is generated separately from `observed/` data.

The engine imports only observed data.

### Gate 2

Generator self-check proves internal conservation equations and graph references over multiple seeds.

---

## Phase 3 — Observation corruption engine

Transform hidden truth into realistic imperfect source evidence.

### Corruptions

- duplicate webhooks;
- reordered webhooks;
- failed→captured sequence;
- dropped webhook;
- delayed webhook;
- missing recon row;
- duplicate recon row;
- wrong recon amount;
- malformed date;
- bank credit delay;
- bank narration noise;
- UTR removed/corrupted;
- same amount collision;
- schema rename;
- rupee/paise trap;
- debit/credit sign trap;
- prompt-like narration string;
- partial source outage.

### Gate 3

Corruption generation cannot modify or expose the hidden truth file consumed by evaluation.

Adversarial fixtures are deterministic by seed.

---

## Phase 4 — Known-source deterministic adapters

Implement hard-coded canonical adapters first for known fixtures:

- Razorpay event JSON;
- Razorpay recon-shaped data;
- settlements;
- merchant CSV;
- bank CSV.

Do **not** start with AI adapter synthesis.

### Gate 4

Known clean/messy fixtures canonicalize correctly, and unit/sign mistakes fail loudly.

---

## Phase 5 — Immutable journal + payment reducer

### Journal

Store source envelopes idempotently.

### Reducer

Pure/replayable payment state reduction.

Test:

- arbitrary event permutations;
- duplicate events;
- failed→captured;
- late events;
- repeated replay.

### Gate 5

For each adversarial payment timeline, final current state matches hidden truth independent of delivery permutation.

---

## Phase 6 — Money Graph builder

Build graph relationships based on explicit identifiers and authoritative source semantics.

### Gate 6

Graph edge scorer against hidden truth reports exact edge precision/recall and never promotes fuzzy-only evidence to proven.

---

## Phase 7 — Settlement composition proof engine

For each settlement:

- collect authoritative recon entries;
- normalize signed contributions;
- deduplicate economic identity;
- calculate exact net;
- compare to settlement entity;
- emit component proof/residual.

### Gate 7

Zero arithmetic divergences on clean ground truth.

Injected missing/wrong rows become correct explicit residuals rather than false success.

---

## Phase 8 — Bank receipt proof engine

Standard-settlement proof hierarchy:

1. exact settlement UTR establishes candidate identity;
2. settlement UTR must be unique across settlement entities in the batch;
3. exactly one distinct bank transaction may carry that standard-settlement UTR;
4. exact amount/currency and causal timing are independently verified;
5. same amount, nearby time and narration remain diagnostics only and never establish identity.

Do **not** model arbitrary split credits for a standard `setl_...` settlement. Razorpay Instant Settlements require their own explicit `setlod` / `setlodp` payout topology.

### Gate 8

No ambiguous same-amount fixture is silently auto-matched.

Exact UTR + wrong amount is `BANK_RECEIPT_RESIDUAL` / `BANK_AMOUNT_MISMATCH`: identity evidence exists, financial equality does not, and the settlement is not reconciled.

---

## Phase 9 — Full Reconciliation Proof + versioning — IMPLEMENTED

Gate 9 consumes the complete **batch-safe** Gate 7 composition and Gate 8 bank-proof sets. It does not search recon rows, bank rows, fuzzy candidates or UTRs itself.

Implemented contract:

- deterministic typed `proofv_...` identity;
- settlement-scoped authoritative input SHA-256;
- reproducible batch compilation SHA-256;
- knowledge cutoff and generated-at validation;
- prior proof reference and immutable history;
- reopened state;
- deterministic proof diff;
- atomic batch validation/staging before ledger mutation;
- self-verification of embedded fragment source union and Gate 7/8/9 ruleset metadata.

### Gate 9

Late bank or recon evidence versions only affected settlement truth and preserves old versions. Unrelated evidence and delivery permutation do not manufacture versions. A previously proven settlement can reopen when later authoritative contradictory evidence appears.

---

## Phase 10 — Residual Solver

Start conservative.

### v1

- deterministic candidate enumeration;
- exact residual amount lookup;
- typed explanation candidates.

### v2 if needed

- bounded branch-and-bound / DP for small combination sets.

### stretch

- CP-SAT solver.

### Gate 10

Solver never upgrades a hypothesis to proof without required external evidence.

Runtime/time cap is deterministic.

---

## Phase 11 — Baseline evaluation harness

Implement baselines before AI:

- B0 naive 1:1;
- B1 strong grouped exact baseline;
- B2 fuzzy threshold baseline;
- ReFlow Core.

### Metrics

- proof/match rate;
- status accuracy;
- edge precision/recall;
- exception accuracy;
- false auto-match rate;
- contradiction acceptance rate;
- throughput;
- peak memory;
- incremental latency.

### Gate 11

The harness catches at least one intentionally injected bad implementation or mutation.

If it cannot distinguish a known-wrong engine, the benchmark is not trustworthy.

---

## Phase 12 — Source Adapter Compiler

Only now add the first LLM path.

### Build

- structural profiler;
- AdapterSpec schema;
- allowed transform registry;
- LLM provider interface;
- compiler;
- static validator;
- sample validation;
- schema fingerprint;
- drift detector;
- adapter version store.

### Gate 12

Benchmark unknown schemas.

Safety metric: zero wrong sign/unit adapter activations in the test corpus.

A wrong model proposal must demonstrably be rejected.

---

## Phase 13 — Exception Investigation Agent

### Tools

- get proof;
- get evidence;
- payment timeline;
- proof diff;
- residual candidates;
- source health;
- connector/schema state;
- re-fetch simulation where supported.

### Output

Typed hypothesis with evidence references and allowed next action.

### Gate 13

- hallucinated evidence ID rejected;
- unsupported financial claim rejected/flagged;
- provider outage does not affect core reconciliation;
- prompt-like narration does not control the agent;
- model can abstain.

---

## Phase 14 — Exception fingerprints / incident clusters

Implement deterministic clustering/fingerprinting before LLM summarization.

### Goal

Turn thousands of repeated failures into one operational incident.

### Gate 14

Synthetic systemic incidents are grouped with measured cluster quality and affected-value totals.

If clustering is weak or distracts from core submission, keep it as a documented stretch feature.

---

## Phase 15 — Scale benchmark

Run corpus sizes:

```text
50
1,000
10,000
100,000
1,000,000 if feasible
```

Across exception densities and messy-input modes.

### Gate 15

Publish only reproducible numbers with hardware/runtime disclosure.

Any scale claim that cannot be rerun is removed from README/pitch.

---

## Phase 16 — Razorpay Test Mode integration

Connect what is legitimately available:

- payment/order test data where useful;
- webhook payload-compatible ingestion;
- settlement/recon API adapter shape;
- connected account data for demo only where records exist.

Do not pretend synthetic settlement data is live Razorpay settlement data.

### Gate 16

README clearly separates:

```text
REAL RAZORPAY TEST MODE
SIMULATED FINANCIAL WORLD
```

---

## Phase 17 — Operator UI

Do not design the UI as a generic admin table.

### Primary screens

1. **Truth Overview**
   - observed value
   - proven value
   - waiting value
   - contradicted/unexplained value
   - source health

2. **Settlement Proof**
   - money-flow equation
   - contributing movements
   - UTR/bank evidence
   - proof timeline

3. **Exception Workbench**
   - exact residual
   - missing/contradictory evidence
   - AI investigation trace
   - allowed next steps

4. **Source Lab**
   - uploaded source
   - schema fingerprint
   - adapter mapping
   - drift diff

5. **Evaluation Lab**
   - baselines
   - dataset controls
   - accuracy/safety/performance results

### Gate 17

A judge can understand the product without opening a chatbot.

---

## Phase 18 — Failure campaign

Intentionally attack the finished system.

Test:

- reorder everything;
- duplicate everything;
- delay bank evidence;
- corrupt UTR;
- collide amounts;
- change schema;
- inject prompt strings;
- kill AI provider;
- kill/restart worker mid-run;
- replay entire batch;
- increase exception density;
- run memory stress.

Record genuine failures in `FAILURE_LOG.md`.

### Gate 18

At least one compelling failure/fix is demonstrable in the pitch, and unresolved limitations are documented.

---

## Phase 19 — Submission hardening

### Repository

- README reflects reality;
- architecture diagrams final;
- benchmark output checked in;
- limitations clear;
- source list clear;
- CI green;
- no secrets;
- clean setup.

### Pitch

- five minutes;
- one unfamiliar messy source;
- one proof;
- one unresolved exception;
- one real failure/fix;
- one scale/eval screen;
- actual metrics only.

### Gate 19

A reviewer can clone, run a deterministic benchmark and reproduce the headline core metrics without an API key.

---

# Part IV — Scope priorities

## P0 — must ship

- source journal;
- payment temporal reducer;
- grouped settlement decomposition;
- bank receipt proof;
- Reconciliation Proof;
- residual/exception taxonomy;
- hidden-truth benchmark;
- throughput/accuracy/exception metrics;
- Source Adapter Synthesizer;
- bounded investigation agent;
- usable operator UI;
- failure log;
- five-minute demo.

## P1 — should ship

- proof version timeline;
- schema drift migration;
- larger scale stress run;
- exact residual explanation candidates;
- source health/lag;
- model replay/caching for eval.

## P2 — differentiating stretch

- provider-specific Instant Settlement payout proof (`setlod` / `setlodp`);
- exception incident clustering;
- bounded combination solver;
- model fleet comparison;
- tamper-evident proof chain;
- multi-gateway adapter fixtures.

## Explicitly out

- full accounting/ERP posting;
- autonomous tax filing;
- production bank credentials;
- fraud/AML system;
- customer money movement;
- Kubernetes/microservice theatre;
- blockchain;
- fine-tuning a foundation model.

---

# Part V — Decisions that should remain reversible

Do not overcommit early to:

- PostgreSQL vs SQLite for every local component;
- Polars vs DuckDB for all batch operations;
- specific LLM provider/model;
- residual solver library;
- UI framework beyond React/TypeScript constraints;
- deployment platform.

Measure and choose.

This also matches Razorpay Engineering's published philosophy: model/tool choices should be empirical and replaceable rather than religious.

---

# Part VI — Definition of “winning submission”

ReFlow is ready only if the final pitch can truthfully say something like:

> We generated an unseen adversarial financial world, corrupted the observations the way payment systems fail in practice, and asked ReFlow to explain the money. It processed N records at X throughput. Y% of settlements were proven from evidence. Every unresolved case remained explicit. There were Z silent false auto-matches. We then gave it a new messy source format: AI proposed the adapter, deterministic tests verified it, and the same proof engine reconciled the data. When the model failed, the financial core continued working.

Every `N`, `X`, `Y`, and `Z` must come from a checked-in reproducible evaluation.

That is the standard for the rest of the build.
