# Finance-Ops Problem Landscape

## Purpose

This document records the real operational problems ReFlow is designed around. It deliberately goes wider than the Razorpay Buildathon prompt so that the product is not a synthetic benchmark looking for a use case.

The core conclusion from the research is simple:

> The hard problem in modern payment operations is not generating an answer. It is establishing trustworthy financial truth from fragmented, asynchronous, partially contradictory evidence, and doing so fast enough that operators can act before the discrepancy becomes a month-end fire.

That conclusion aligns directly with the Buildathon's Track 04 framing: **“verification capacity, not generation speed, is the bottleneck.”**

---

## 1. What Razorpay explicitly says is hard

The Buildathon Track 04 asks for an agent that closes one finance-ops loop over **50+ synthetic records** and reports:

- throughput;
- measured accuracy;
- match rate;
- an honest list of exceptions it could not resolve.

Razorpay explicitly names multi-source reconciliation, settlement Q&A, cash forecasting and tax-line matching as example directions. The bar is not a cherry-picked demo; it is measured system behaviour over a batch.

Source: https://razorpay.com/buildathon/

Razorpay's own Agentic Platform also describes reconciliation as a manual operational burden and demonstrates an “Intelligent Reconciliation” experience that can extract bank statement information and cross-reference it against Razorpay records. This tells us two things:

1. reconciliation is strategically important to Razorpay;
2. simply uploading a statement and matching UTRs is **not sufficiently novel** for this Buildathon.

Source: https://razorpay.com/blog/razorpay-agentic-platform/

---

## 2. The problem is larger than row matching

A payment business has several different notions of “truth” at different moments:

1. **Commercial truth** — what the merchant believes was ordered/invoiced.
2. **Gateway truth** — what the processor observed about authorization, capture, refund, transfer, dispute and settlement.
3. **Settlement truth** — which economic movements were included in a settlement and which fees/taxes/adjustments affected the net amount.
4. **Bank truth** — what actually arrived in the merchant's account.
5. **Accounting truth** — how finance ultimately books the movement.

These systems do not update atomically.

Razorpay documents that webhook delivery is at-least-once and may be out of order. It also documents cases where `payment.failed` can later be followed by `payment.captured` for the same transaction. A settlement being `processed` does not prove the merchant's bank has already credited it; the UTR is the bridge to bank-side evidence.

Sources:

- https://razorpay.com/docs/webhooks/validate-test/
- https://razorpay.com/docs/webhooks/best-practices/
- https://razorpay.com/docs/webhooks/payments/
- https://razorpay.com/docs/webhooks/settlements/

Therefore a correct reconciliation system must handle **time, correction and incomplete evidence**, not just similarity matching.

---

## 3. Settlement decomposition is inherently many-to-one

Razorpay's Settlement Recon API returns transaction-level rows for:

- payments;
- refunds;
- transfers;
- adjustments.

Each row can include debit, credit, amount, fee, tax, settlement id, settlement UTR, order id, payment id, dispute id and timing information.

Source: https://razorpay.com/docs/api/settlements/fetch-recon/

A settlement is therefore not normally “payment A = bank row A”. It is an aggregate financial object composed from many economic movements.

Razorpay's Dashboard documentation similarly describes settlement breakup through payments, adjustments, tax, fees, transfers and refunds.

Source: https://razorpay.com/docs/payments/settlements/dashboard/

This is the core structural problem ReFlow should solve.

---

## 4. Real pain points observed across payment institutions and merchants

### 4.1 Fragmented data and no single source of truth

Razorpay has previously described finance teams manually downloading and reconciling data from multiple payment aggregators, with inconsistent settlement visibility and considerable month-end effort. Its Single View Recon product was created specifically to reduce this fragmentation.

Source: https://razorpay.com/blog/single-view-recon/

The problem gets worse when a merchant has an ERP/order database, multiple gateways, bank statements, refund exports and accounting records that all use different identifiers and formats.

**ReFlow implication:** the system must preserve source provenance and normalize into a canonical financial model without pretending all sources are equally authoritative.

### 4.2 Exceptions consume disproportionate effort

Swift describes exceptions and investigations as a major payment-operations burden. It notes that roughly **2–5% of payments can result in enquiries**, with operations teams spending several minutes investigating each payment instruction. It also highlights missing/unstructured data, duplicates and status discrepancies as drivers of investigation work.

Source: https://www.swift.com/standards/iso-20022/supercharge-your-payments-business/chapter-6

This is crucial: at scale, even a low exception percentage creates a large manual queue.

**ReFlow implication:** optimize not only match rate but **exception quality, prioritization and mean time to explanation**.

### 4.3 Rich data exists, but formats and semantics differ

Swift's ISO 20022 transition is explicitly motivated in part by richer, structured data and improved straight-through processing. Yet institutions continue to operate across legacy and new formats, creating translation and exception-handling requirements.

Sources:

- https://www.swift.com/news-events/news/transforming-exceptions-and-investigations
- https://www.swift.com/standards/iso-20022/iso-20022-faqs/mt-iso-20022-conversion

**ReFlow implication:** schema translation must be a first-class subsystem, not a pile of CSV-specific parsing code.

### 4.4 Real-time payments increase operational pressure

Instant and near-real-time rails remove waiting from the customer experience, but back-office truth still arrives asynchronously. Faster money movement increases the expectation that reconciliation, exception detection and cash visibility are also fast.

Razorpay's Instant/Smart Settlement products themselves create multiple shapes: IMPS-based instant settlement can create multiple bank credits, while Smart Settlement can appear as a single RTGS credit. Fees and tax can also affect the amount actually credited.

Sources:

- https://razorpay.com/docs/payments/settlements/instant/
- https://razorpay.com/docs/payments/settlements/faqs/

**ReFlow implication:** one settlement need not always map to one bank row, and one requested settlement may be split across bank credits. The graph model should support many-to-many evidence even if the first implementation proves a constrained subset.

### 4.5 Refunds, disputes and cross-period deductions destroy simple equations

Refunds may occur after the original payment period. Disputes can introduce later debits. Fees and tax may be structurally non-refundable depending on the payment/refund path. Reconciliation therefore must trace economic lineage across time instead of closing each day in isolation.

Sources:

- https://razorpay.com/docs/webhooks/refunds/
- https://razorpay.com/docs/webhooks/disputes/
- https://razorpay.com/blog/refunds-and-mdr-in-payment-gateways/

**ReFlow implication:** a refund is a new financial movement linked to an original payment, not a mutation that erases history.

### 4.6 Duplicate, delayed and reordered events are normal integration behaviour

Razorpay's webhook documentation explicitly states that duplicate events are expected under at-least-once delivery and that event order is not guaranteed.

Source: https://razorpay.com/docs/webhooks/best-practices/

**ReFlow implication:** raw event history must be immutable and reducers replayable. Business truth must not depend on arrival order.

### 4.7 Operational resilience and third-party dependency are regulatory concerns

RBI digital-payment security directions explicitly call out risks arising from third-party providers, integration with internal/external systems, reconciliation processes, operational risk, business continuity and service availability.

Sources:

- https://systemhealth.rbi.org.in/Scripts/BS_ViewMasDirections.aspx_id%3D12032%283%29.html
- https://systemhealth.rbi.org.in/Scripts/BS_ViewMasDirections.aspx_id%3D12715%281%29.html

**ReFlow implication:** the core must remain useful when an AI provider, one connector or one upstream feed is unavailable.

### 4.8 AI cannot be treated as financial authority

Razorpay Agent Studio's own architecture emphasizes:

- verified first-party data;
- merchant-controlled permissions;
- independent action validation;
- full audit trails;
- review-first operation for sensitive tasks.

Source: https://razorpay.com/blog/razorpay-agent-studio-principles-guardrails-and-merchant-control/

**ReFlow implication:** LLMs can perform semantic work and investigation, but must never be the final source of amount, match or settlement truth.

### 4.9 Model quality is not the only evaluation axis

Razorpay Engineering's August 2026 eval write-up argues that the object to evaluate is the **whole agentic system**, not merely the model. Their internal eval system emphasizes representative corpora, deterministic item selection, failure safety, reproducibility, stored raw results and multi-axis comparison.

Source: https://razorpay.com/blog/?p=27428

**ReFlow implication:** benchmark the complete workbench, including ingestion, normalization, matching, proof generation, exceptions and AI investigation.

---

## 5. Small-volume and high-volume users have different failure economics

### Small merchant / finance operator

Typical characteristics:

- tens to hundreds of transactions;
- data arrives as exported CSV/XLSX/bank statement files;
- no data-engineering team;
- one missed ₹5,000 item may matter more than aggregate throughput;
- setup cost is the biggest barrier.

Their problem is **friction and understandability**.

ReFlow should let them:

1. drop in files;
2. identify/mapping schemas quickly;
3. get a clear money-flow proof;
4. see only unresolved exceptions;
5. export an audit packet.

### High-volume merchant / payment institution

Typical characteristics:

- millions of events;
- many gateways/accounts/business units;
- continuous webhook/API ingestion;
- a tiny exception percentage can still mean thousands of cases;
- replay, late events and backfills are normal;
- latency and operational cost matter.

Their problem is **cardinality, drift and exception concentration**.

ReFlow should:

1. partition before expensive matching;
2. use exact identifiers and deterministic arithmetic for the overwhelming majority;
3. apply expensive search/AI only to a small exception frontier;
4. support incremental recomputation when late evidence arrives;
5. separate operational state from immutable evidence.

The same financial invariants should govern both modes.

---

## 6. Problem taxonomy ReFlow should explicitly test

| Problem family | Example | Failure if handled naively | ReFlow response |
|---|---|---|---|
| event duplication | same webhook delivered twice | double count | event-id + payload dedup |
| event reordering | capture arrives before authorize | false state regression | replayable state reducer |
| late status correction | failed → captured | false missing-payment case | temporal state reconstruction |
| aggregation | 300 payments + refunds → one settlement | impossible 1:1 matching | settlement composition proof |
| split bank credits | one instant settlement → multiple IMPS credits | unmatched residual | grouped bank-side evidence |
| fees/tax | gross ≠ net | false mismatch | signed movement equation |
| refunds | refund lands later | cross-period imbalance | linked negative movement |
| adjustments | correction inserted by provider | unexplained residual | explicit adjustment node |
| disputes | later chargeback/deduction | historical books diverge | versioned linked movement |
| missing rows | incomplete report | false successful close | fail closed + residual |
| schema drift | `Settlement UTR` becomes `Bank Ref` | ingestion silently breaks | connector contract + drift alarm |
| ambiguous same amounts | two ₹10,000 credits same day | wrong auto-match | uniqueness proof required |
| malformed units | rupees interpreted as paise | 100× error | unit/range invariants |
| source outage | bank feed missing | premature “reconciled” | evidence-state distinction |
| AI outage | model unavailable | workflow stops | deterministic core remains complete |
| prompt/data injection | narration contains instructions | tool abuse | data treated as data, bounded tools |

---

## 7. What we should not try to solve in the Buildathon

The research space is huge. ReFlow should not expand into:

- AML transaction monitoring;
- fraud scoring;
- customer credit underwriting;
- autonomous accounting journal posting;
- tax advice;
- full ERP replacement;
- chargeback adjudication;
- cross-border FX accounting;
- a universal bank statement parser for every bank on earth.

These are adjacent future extensions, not Buildathon scope.

---

## 8. Product opportunity

The useful gap is between two extremes:

**Traditional reconciliation:**

> import rows → match rows → dump exceptions

and

**naive AI reconciliation:**

> upload everything → ask an LLM what probably happened

ReFlow should instead provide:

> **compile messy evidence into an immutable financial model → reconstruct the money graph → prove what can be proven → quantify exactly what remains unexplained → use AI only to reduce the remaining investigation burden.**

That is the problem statement that should govern the rest of the project.
