# ReFlow Research Sourcebook

## Purpose

This is the source index behind ReFlow's product and architecture decisions.

Rules:

1. Prefer primary/official sources for payment semantics.
2. Separate documented facts from our design inference.
3. Never treat a blog statistic as a system requirement without validation.
4. If Razorpay API behaviour contradicts a secondary source, Razorpay API/docs win for this project.
5. Synthetic probabilities/distributions must be labeled as synthetic rather than attributed to these sources.

Research snapshot: **2026-08-29**.

---

# A. Razorpay Buildathon

## A1. Razorpay AI Buildathon

https://razorpay.com/buildathon/

Verified points:

- student-only AI Builder Internship challenge;
- 6 or 12 months;
- in-person Bangalore from September;
- public repo + 5-minute pitch video + architecture;
- Track 04: close one finance-ops loop over 50+ synthetic records;
- report match rate and unresolved exceptions;
- bar includes throughput and measured accuracy;
- “verification capacity, not generation speed” framing.

Design implication:

ReFlow must be evaluated as a system, not presented as a concept demo.

---

## A2. Actual submission form linked from Buildathon

Google Form linked from the official Buildathon page.

Observed fields on 2026-08-29:

- Email
- Full Name
- College Name
- Graduation Year (2027/2028/2029)
- In-person internship availability starting September
- Preferred Internship Duration (6-month / 12-month)
- Selected Track
- Project Name / Title
- Project Objectives — “What does it solve?”
- GitHub Repository URL
- 5-min Pitch Video Link
- Build Challenges & Technical Obstacles — “What issues did you face while building, and how did you solve them?”
- Final Submission Confirmation

Design implication:

Maintain a real failure log during implementation.

---

# B. Razorpay settlement and reconciliation semantics

## B1. Settlement Recon API

https://razorpay.com/docs/api/settlements/fetch-recon/

Verified points:

- endpoint returns settled transactions for day/month;
- types include payment, refund, transfer, adjustment;
- fields include debit, credit, amount, currency, fee, tax, `on_hold`, `settled`, timestamps, settlement id, settlement UTR, payment id, order id and dispute id;
- count supports up to 1000 per request according to current docs.

Design implication:

Settlement reconciliation is many-to-one and must model heterogeneous economic movements.

---

## B2. Settlement entity

https://razorpay.com/docs/api/settlements/entity/

Verified points:

- settlement has id, amount, status, fees, tax, UTR, created timestamp;
- amount is in smallest currency unit;
- UTR is intended to track settlement in bank account.

Design implication:

UTR is strong bank-side identity evidence; settlement amount remains integer subunit.

---

## B3. Settlement webhook

https://razorpay.com/docs/webhooks/settlements/

Verified points:

- `settlement.processed` payload includes settlement financial data and UTR;
- docs explicitly warn that processed status does not necessarily mean the amount has already appeared in the bank account; normal bank rails can introduce delay.

Design implication:

`SETTLEMENT_PROCESSED` and `BANK_RECEIPT_PROVEN` are separate states.

---

## B4. Settlement Dashboard breakup

https://razorpay.com/docs/payments/settlements/dashboard/

Verified points:

- settlement detail includes payments, adjustments, tax, fees and related deductions/flows;
- dashboard exposes settlement breakdown and timeline.

Design implication:

Proof UI should visually reconstruct the settlement equation rather than only show a match status.

---

## B5. About Settlements

https://razorpay.com/docs/payments/settlements/

Verified points:

- captured payments become eligible for settlement;
- settlement occurs after applicable fees/deductions;
- settlement schedules govern timing.

Design implication:

Payment captured state is necessary economic evidence for normal settlement inclusion.

---

## B6. Settlement FAQ

https://razorpay.com/docs/payments/settlements/faqs/

Verified points:

- UTR is used to locate a settlement in a bank account;
- failed/blocked settlements can require support resolution;
- default/instant/smart settlement behaviours differ.

Design implication:

Source/settlement state should include delayed/failed paths instead of assuming all processed money arrives normally.

---

## B7. Instant Settlements

https://razorpay.com/docs/payments/settlements/instant/

Verified points:

- instant settlements are on-demand and 24x7 subject to product limits;
- fees/tax are deducted;
- IMPS path can cause multiple bank credits due to per-transaction limits;
- Smart Settlement can use RTGS and appear as a single bank credit.

Design implication:

Domain graph should support one settlement/request mapping to multiple bank credits even if Buildathon implementation initially constrains the scenario.

---

# C. Razorpay payment/event semantics

## C1. Payment webhooks

https://razorpay.com/docs/webhooks/payments/

Verified points:

- webhook payloads are snapshots at event time;
- current entity state can have advanced beyond the event snapshot;
- Razorpay explicitly documents `payment.failed` followed by `payment.captured` for the same transaction in some late authorization/retry scenarios.

Design implication:

Use an event reducer; do not map one event name directly to terminal business truth.

---

## C2. Webhook validation / idempotency / ordering

https://razorpay.com/docs/webhooks/validate-test/

https://razorpay.com/docs/webhooks/best-practices/

Verified points:

- duplicate delivery is expected under at-least-once semantics;
- `x-razorpay-event-id` can identify duplicate events;
- webhook ordering is not guaranteed;
- signature validation must use raw body;
- endpoint response behaviour affects retries.

Design implication:

Immutable event journal + idempotent reducer + permutation tests.

---

## C3. Refund webhooks

https://razorpay.com/docs/webhooks/refunds/

Verified points:

- refunds are distinct entities linked to payments;
- partial/full refund state exists;
- events have their own lifecycle.

Design implication:

Model refund as a linked negative economic movement rather than deleting/reducing original payment history.

---

## C4. Dispute webhooks

https://razorpay.com/docs/webhooks/disputes/

Verified points:

- disputes are linked to payment entities and have action-required/lifecycle events.

Design implication:

Keep graph extensible for later deductions/chargebacks without making disputes the initial Buildathon scope.

---

# D. Razorpay current product direction

## D1. Agentic Platform

https://razorpay.com/blog/razorpay-agentic-platform/

Verified product direction:

- Razorpay wants the merchant dashboard to move from data manipulation toward decisions/actions;
- reconciliation and edge cases are explicitly called operational burden;
- public Intelligent Reconciliation example can extract UTR/amount from a bank statement screenshot and cross-reference Razorpay records.

Design implication:

“AI reads bank statement and matches UTR” is not enough novelty for ReFlow.

---

## D2. Agent Studio principles and guardrails

https://razorpay.com/blog/razorpay-agent-studio-principles-guardrails-and-merchant-control/

Verified principles:

- merchant controls data/action permissions;
- review-first mode is supported;
- sensitive/irreversible actions need approval;
- agents use verified first-party data;
- platform independently validates actions;
- actions are fully audited;
- agent performance is continuously evaluated.

Design implication:

Use bounded tools, verified evidence and independent deterministic validation.

---

## D3. Agent Studio launch

https://razorpay.com/blog/?p=26292

Verified direction:

- post-payment operations such as disputes, reconciliation, failed-payment recovery, refunds and payouts are targeted agent workflows;
- workflows span multiple systems.

Design implication:

ReFlow should integrate multi-source operations rather than be only a settlement CSV utility.

---

## D4. Razorpay Vulcan

https://razorpay.com/blog/?p=27542

Verified direction:

- Razorpay is investing in payments-specific foundation-model research;
- AI is being applied to understanding transaction reliability/risk/behaviour.

Design implication:

Do not compete by claiming a generic LLM is a payment foundation model. Use models where semantic reasoning is appropriate and keep model provider replaceable.

---

# E. Razorpay engineering culture / evaluation

## E1. “The Winner Doesn't Take it All”

https://razorpay.com/blog/?p=27428

Verified principles:

- bespoke evaluations over relying only on public benchmarks;
- evaluate an agentic workbench, not only the base model;
- same items/same conditions for comparison;
- seeded deterministic selection;
- validation before spend;
- raw decisions retained;
- safe failure semantics;
- multiple axes such as quality, cost and latency;
- model optionality.

Design implication:

ReFlow's benchmark framework should be reproducible, seeded, model-optional and system-level.

---

## E2. Razorpay agent-ready repositories / Slash

https://razorpay.com/blog/?p=26885

Verified direction:

Razorpay Engineering publicly emphasizes repository context, tests and CI/CD as important for safe agentic engineering.

Design implication:

Treat repo quality as part of the interview: `AGENTS.md`, tests, clear docs and reliable CI.

---

# F. Broader reconciliation/payment-operations research

## F1. Swift — payments exceptions and investigations

https://www.swift.com/standards/iso-20022/supercharge-your-payments-business/chapter-6

Verified points:

- a minority of payments can create a disproportionate investigation burden;
- Swift cites roughly 2–5% of payments producing enquiries and several minutes of operational work per investigation;
- missing/unstructured data and lack of automation contribute to exceptions;
- structured ISO 20022 data enables better automation/classification.

Design implication:

Optimize the exception frontier and cluster systemic causes; do not spend AI on every normal payment.

---

## F2. Swift — transforming exceptions/investigations

https://www.swift.com/news-events/news/transforming-exceptions-and-investigations

Verified direction:

- 2026 work continues around ISO 20022-based case management for exceptions, investigations and payment cancellation;
- standardized identifiers and structured messages are important to resolution workflows.

Design implication:

Stable identifiers and structured case evidence are foundational.

---

## F3. Swift — ISO 20022 migration/translation

https://www.swift.com/standards/iso-20022/iso-20022-faqs/mt-iso-20022-conversion

https://www.swift.com/standards/iso-20022/iso-20022-bytes/journey-continues

Verified direction:

- migration from legacy message formats to richer ISO 20022 data creates compatibility/translation and operational-readiness requirements.

Design implication:

Source schema versioning and safe migration are realistic payment-ops concerns.

---

## F4. McKinsey Global Payments Report 2025

https://www.mckinsey.com/industries/financial-services/our-insights/global-payments-report

Verified direction:

- payments players are using AI in transaction optimization, fraud/risk and operations;
- reconciliation/settlement remain manual in many institutions and are targets for automation.

Design implication:

ReFlow targets a real industry productivity bottleneck, not an artificial competition-only problem.

---

## F5. RBI payment-system indicators

https://www.rbi.org.in/Scripts/PSIUserView.aspx

Verified direction:

- Indian payment and settlement systems operate at very large and growing transaction volumes.

Design implication:

Any architecture that depends on global pairwise fuzzy matching is structurally wrong for the high-volume case.

---

## F6. RBI digital payment security / resilience directions

https://systemhealth.rbi.org.in/Scripts/BS_ViewMasDirections.aspx_id%3D12032%283%29.html

https://systemhealth.rbi.org.in/Scripts/BS_ViewMasDirections.aspx_id%3D12715%281%29.html

Verified themes:

- third-party dependency;
- integrations with internal/external systems;
- reconciliation processes;
- operational/fraud risk;
- business continuity/service availability;
- security and resilience.

Design implication:

AI outage and connector outage must degrade safely; the core cannot depend on one external model call.

---

## F7. BIS — next-generation monetary/financial system

https://www.bis.org/publ/arpdf/ar2025e3.htm

Verified direction:

- tighter integration of messaging/clearing/settlement can reduce delays and manual reconciliation;
- financial infrastructure is moving toward more integrated, programmable flows.

Design implication:

ReFlow's domain model should focus on explicit financial movements and provenance, which remains useful as rails evolve.

---

# G. Comparative product research

## G1. Razorpay Optimizer Single View Recon

https://razorpay.com/docs/payments/optimizer/reconciliation/

https://razorpay.com/blog/single-view-recon/

Verified points:

- multi-gateway reconciliation and unified settlement visibility are existing Razorpay concerns/products;
- late authorization contributes to reconciliation friction.

Design implication:

Multi-source support is relevant, but a simple unified dashboard is not enough novelty.

---

## G2. Stripe balance transactions (comparative concept only)

https://docs.stripe.com/plan-integration/get-started/reporting-reconciliation

Verified concept:

- Stripe models immutable balance transactions as building blocks of balance movement;
- replaying such movements can explain balance state.

Design implication:

This supports the general ledger/event-sourcing direction, but ReFlow must remain grounded in Razorpay semantics for the competition.

---

# H. Public Buildathon competitor scan

Public GitHub search on 2026-08-29 showed multiple Revenue Recovery and Finance Controller submissions.

Notable findings are documented in:

- `docs/03_COMPETITIVE_ANALYSIS.md`

Key strategic inference:

- LLM + deterministic guardrail is already common;
- one strong public Finance Controller submission explicitly documents a 1:1 settlement limitation;
- ReFlow should differentiate through many-to-one decomposition, proof objects, temporal truth, safe connector compilation and scale-aware exception handling.

Competitor research is for differentiation only. Do not copy implementation/code/text.

---

# I. Claims we must NOT make from research alone

Do not claim, without our own benchmark:

- ReFlow is 99% accurate;
- ReFlow is faster than existing commercial products;
- ReFlow handles millions of transactions per second/day;
- specific exception distributions represent Razorpay production traffic;
- specific failure probabilities are real merchant distributions;
- AI adapter generation is safe until benchmarked;
- reconciliation automation always saves a fixed number of hours;
- our synthetic financial world represents all Indian payments.

The research motivates design. The benchmark establishes ReFlow's actual capability.
