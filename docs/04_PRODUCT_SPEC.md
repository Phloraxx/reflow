# ReFlow Product Specification

## One-line product

**ReFlow is an evidence-first AI finance controller that reconciles grouped payment settlements to merchant orders and bank credits, then investigates the exceptions it cannot deterministically prove.**

Tagline candidate: **Every rupee, explained.**

## User

The primary user is a finance/operator person at an Indian internet business who needs to answer questions such as:

- Did the money Razorpay says it settled actually reach the bank?
- Which payments and refunds make up this settlement?
- Why is this bank credit ₹X different from the expected settlement?
- Is the difference a fee/tax/refund/adjustment, missing row, duplicate, timing issue or unknown exception?
- Which cases can be resolved automatically and which require a person?
- Can I prove the answer from source records rather than trusting generated prose?

## The one loop we close

```text
SOURCE INGESTION
merchant ledger + Razorpay journal/recon + bank ledger
        ↓
NORMALISE
canonical IDs, times, integer money, source provenance
        ↓
RECONSTRUCT PAYMENT TRUTH
idempotent state reduction over duplicated/out-of-order events
        ↓
BUILD SETTLEMENT COMPOSITION
payments/refunds/adjustments → settlement ID → expected net
        ↓
MATCH BANK CREDIT
UTR + amount + time-window evidence
        ↓
VERIFY INVARIANTS
money conservation, uniqueness, source consistency
        ↓
CLASSIFY EXCEPTION
or produce PROVEN_RECONCILED
        ↓
INVESTIGATE
bounded AI chooses read-only evidence tools
        ↓
RESOLVE / WAIT / HUMAN REVIEW
all actions and evidence audited
```

The product is complete when an input batch ends with **every item** in a typed terminal or pending state. Nothing disappears from the denominator.

## Core entities

### MerchantOrder
Merchant-side sales intent / ledger entry.

Key fields: `order_id`, `receipt`, `gross_amount_paise`, `currency`, `created_at`, merchant metadata.

### PaymentEvent
Immutable event-journal record. Includes source event ID, payment ID, event type, observed payload state, occurrence/receipt timestamps and payload hash.

### PaymentCurrentState
Derived state after reducing the event journal. This is not directly mutated by AI.

### Refund
Refund evidence linked to a payment and, when applicable, a settlement movement.

### ReconEntry
Canonical representation of a Razorpay settlement-recon row. Types initially: payment, refund, adjustment. `transfer` is supported by schema but can be excluded from the benchmark unless we can model it faithfully.

### Settlement
Settlement-level record: ID, amount, status, UTR, timestamps.

### BankEntry
A bank-side transaction. For the benchmark, settlement credits are synthesized separately from Razorpay recon data so the matching system does not get its answer by construction.

### EvidenceEdge
A typed relationship between two records with strength and reason. Examples:

- `ORDER_HAS_PAYMENT`
- `PAYMENT_HAS_RECON_ENTRY`
- `REFUND_OF_PAYMENT`
- `ENTRY_IN_SETTLEMENT`
- `SETTLEMENT_MATCHES_BANK_UTR`
- `SETTLEMENT_MATCHES_BANK_AMOUNT_TIME`

### ReconciliationDecision
The deterministic output for a settlement/bank-credit scope, including:

- status;
- expected amount;
- observed amount;
- residual;
- evidence IDs;
- reason codes;
- confidence class derived from rules, not an LLM token probability;
- whether auto-resolution is permitted.

### ExceptionCase
First-class finance-control object containing unresolved evidence, impact amount and investigation state.

### InvestigationRun
A bounded AI run: question, tools offered, tool calls, observations, proposed root cause, proposed next step, validation result, model/provider metadata, latency and cost.

## Primary statuses

Exact names may change during implementation, but the semantics should remain explicit.

### Reconciliation statuses

- `PROVEN_RECONCILED` — all required invariants satisfied.
- `PENDING_BANK_CREDIT` — settlement processed, but bank proof has not arrived inside the expected observation state/window.
- `BANK_AMOUNT_MISMATCH` — strong identity evidence but observed credit differs.
- `MISSING_BANK_CREDIT` — observation window elapsed without a corresponding bank entry.
- `AMBIGUOUS_BANK_MATCH` — multiple bank entries remain plausible.
- `UNKNOWN_BANK_CREDIT` — bank credit cannot be tied to a settlement.
- `SETTLEMENT_COMPOSITION_MISMATCH` — component arithmetic cannot reproduce settlement amount.
- `MISSING_RECON_COMPONENT` — expected source movement is absent.
- `DUPLICATE_SOURCE_EVENT` — retained/audited duplicate, not double-counted.
- `CONFLICTING_PAYMENT_STATE` — event history cannot be safely reduced without more evidence.
- `SOURCE_INTEGRITY_ERROR` — invalid amount/currency/ID/timestamp/schema.
- `REQUIRES_REVIEW` — bounded controller cannot prove a safe resolution.

Duplicates that are safely deduplicated can be represented as evidence warnings rather than making an otherwise valid settlement terminally failed. The benchmark should score both correctness of final financial state and correctness of anomaly detection.

## Deterministic reconciliation invariants

### Money

All INR amounts are signed integer paise. No float crosses the domain boundary.

For each settlement `S`, ReFlow calculates expected net from its recon entries according to the explicit sign/credit/debit model. The computed amount must exactly equal the settlement amount before the bank link can be marked proven.

A rough conceptual identity is:

```text
expected settlement
  = Σ transaction credits
  - Σ transaction debits
```

The precise implementation uses the recon row's documented `credit` and `debit` fields rather than hard-coding assumptions by row type.

### Uniqueness

A source entity cannot contribute twice merely because its webhook was delivered twice. A bank entry cannot prove two settlements unless the synthetic scenario explicitly models a valid aggregate bank transfer and the policy permits it.

### Temporal validity

Evidence must be plausible in time. A bank entry cannot prove a settlement created after the bank entry. A stale event cannot resurrect or duplicate money movement.

### Identity strength

Use strongest available evidence first:

1. exact settlement UTR;
2. exact stable entity relationships / IDs;
3. amount plus bounded time window only as candidate-generation evidence;
4. fuzzy text similarity can suggest candidates but cannot alone authorize a financial match.

### Source truth boundaries

Merchant ledger says what was sold/expected.
Razorpay event/recon data says what happened in the gateway/settlement ledger.
Bank data says what actually appeared at the bank.

No one source is allowed to impersonate another.

## AI responsibilities

The AI agent is allowed to:

- choose which read-only investigation tool to call;
- request evidence by entity/settlement/payment/order ID;
- compare deterministic summaries already computed by tools;
- choose among a finite root-cause taxonomy or `UNKNOWN`;
- propose `WAIT`, `RECHECK_SOURCE`, `REQUEST_HUMAN_REVIEW`, or a typed low-risk resolution that must pass deterministic validation;
- explain the evidence to a finance operator in concise language.

The AI agent is forbidden to:

- create or change an amount;
- modify a source record;
- mark a settlement reconciled directly;
- fabricate IDs or evidence;
- suppress an unresolved exception;
- make an irreversible financial action;
- infer that a bank credit exists when the bank source lacks it.

## Agent tool surface — initial

Read-only tools:

- `get_settlement(settlement_id)`
- `get_settlement_components(settlement_id)`
- `get_bank_candidates(settlement_id)`
- `get_payment_history(payment_id)`
- `get_order(order_id)`
- `get_refund(refund_id)`
- `get_recon_math(settlement_id)`
- `get_exception_evidence(case_id)`
- `search_source_by_exact_id(kind, id)`

Controller actions:

- `wait_until(timestamp, reason)` — simulated in benchmark / scheduled in runtime;
- `recompute(case_id)` — deterministic;
- `resolve_if_proven(case_id)` — deterministic gate, no model override;
- `escalate(case_id, reason)`;

Potential write actions such as posting accounting adjustments are **out of MVP scope**.

## Merchant UI

The interface should optimize for decisions, not table density.

### Overview

Top-level numbers:

- total amount expected;
- proven reconciled amount;
- pending amount;
- exception amount;
- silent-error test result / confidence indicator from evaluation, not runtime self-congratulation;
- settlements reconciled / total.

### Reconciliation river

A visual flow for a selected settlement:

`orders/payments → refunds/adjustments → settlement → UTR → bank credit`

Each edge is clickable and shows evidence.

### Exceptions inbox

Prioritized by monetary impact and age, not by arbitrary severity colors.

Each exception card answers:

- what failed;
- amount at risk/unexplained;
- deterministic reason codes;
- evidence available/missing;
- AI investigation summary;
- next safe action;
- whether human approval is required.

### Audit view

Chronological immutable log of ingestion, dedupe, state reduction, reconciliation decisions, agent tool calls and resolution events.

## Demo scenarios that must exist

1. **Clean grouped settlement** — many payments + refund/adjustment reconcile to one bank credit.
2. **Processed but not yet credited** — correctly waits; does not call it missing immediately.
3. **Late `failed → captured` payment** — no double counting / stale failure truth.
4. **Duplicate webhook** — evidence retained, amount counted once.
5. **Out-of-order webhook** — final state still correct.
6. **Refund shifts net amount** — correct settlement arithmetic.
7. **Adjustment explains residual** — system resolves from source evidence.
8. **Same-amount settlement collision** — UTR prevents wrong bank match.
9. **Wrong bank amount with right UTR** — exception, never auto-match.
10. **Ambiguous/malformed evidence** — explicit human review.

## Scope cuts

MVP will not attempt:

- full double-entry accounting package integration;
- general GST/TDS filing advice;
- OCR as a core dependency;
- production bank login automation;
- arbitrary bank-specific narration parsing;
- chargeback/dispute automation;
- payout/Route reconciliation unless the basic settlement loop is finished and measured;
- autonomous book mutation.

These cuts preserve enough time for evaluation, failure testing and demo quality.
