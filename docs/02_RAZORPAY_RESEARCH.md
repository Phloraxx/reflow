# Razorpay Domain Research

> Research-phase document. Last verified: 2026-08-29. Prefer official Razorpay documentation over assumptions.

## 1. Settlement semantics

Razorpay defines settlement as transferring captured customer-payment funds to the merchant's registered bank account after applicable deductions. The standard domestic cycle is generally T+2 working days, but the actual cycle can vary by business/risk configuration.

Sources:

- https://razorpay.com/docs/payments/settlements/
- https://razorpay.com/docs/payments/settlements/faqs/

A settlement has a settlement ID, amount, status, UTR, fees, tax and creation timestamp. The settlement states exposed by the API include `created`, `processed`, and `failed`.

- https://razorpay.com/docs/api/settlements/entity/
- https://razorpay.com/docs/api/settlements/fetch-with-id/

### Important timing distinction

`settlement.processed` means Razorpay has successfully initiated/transferred the funds through the bank rail; it does **not** prove the merchant's bank account has already been credited. Razorpay's docs note that the bank credit can follow after the normal NEFT/RTGS/IMPS timeline and may take up to roughly three hours.

Therefore ReFlow must not collapse:

`Razorpay says processed`

into:

`bank credit proven`.

Those are two separate pieces of evidence and two separate states.

Source: https://razorpay.com/docs/webhooks/settlements/

## 2. What is actually inside a settlement

The dashboard settlement break-up includes payment amount, adjustments, tax, fees, transfers and refunds depending on the merchant/product context. Razorpay describes the settlement as a net of the underlying movements rather than a one-payment/one-bank-credit mapping.

Source: https://razorpay.com/docs/payments/settlements/dashboard/

The combined Settlement Recon endpoint is particularly important:

`GET /v1/settlements/recon/combined?year=YYYY&month=MM[&day=DD]`

It returns transaction-level entries that can include:

- `payment`
- `refund`
- `transfer`
- `adjustment`

and fields including:

- entity ID;
- debit / credit / amount;
- fee;
- tax;
- settled flag;
- creation and settlement timestamps;
- settlement ID;
- settlement UTR;
- payment ID;
- order ID / receipt;
- payment method;
- dispute ID.

This is the canonical model for our synthetic settlement ledger.

Source: https://razorpay.com/docs/api/settlements/fetch-recon/

## 3. Bank reconciliation key

Razorpay explicitly recommends using the settlement **UTR** to reconcile the settlement against the merchant bank statement.

Sources:

- https://razorpay.com/docs/webhooks/settlements/
- https://razorpay.com/docs/payments/settlements/faqs/

ReFlow therefore uses UTR as strong evidence when present, but it must still handle:

- a processed settlement whose bank credit has not arrived yet;
- missing/garbled bank narration;
- duplicate bank rows;
- same-amount settlements;
- amount discrepancy;
- unknown bank credit;
- a UTR collision in corrupt synthetic data.

A UTR match is evidence, not permission to ignore an impossible amount or duplicate record.

## 4. Payment event semantics

Razorpay webhooks are not a totally ordered, exactly-once log. Implementations must expect duplicate delivery and ordering differences, verify webhook signatures against the raw request body, and deduplicate using `x-razorpay-event-id` where available.

Sources:

- https://razorpay.com/docs/webhooks/validate-test/
- https://razorpay.com/docs/webhooks/best-practices/

### Critical state-transition case

A payment can first emit `payment.failed` and later become `payment.captured`, including late-authorisation / UPI retry scenarios. Reconciliation must therefore derive current financial state from an idempotent state model rather than treating the first failure event as permanent truth.

Sources:

- https://razorpay.com/docs/webhooks/payments/
- https://razorpay.com/docs/payments/payments/late-authorisation/

This gives ReFlow a valuable adversarial case: feed the journal a failed event, then a later captured event for the same payment, optionally delivered out of order, and prove that the final ledger contains one captured payment rather than a duplicate or a false exception.

## 5. Reports and reconciliation

Razorpay already provides settlement reconciliation reports and custom reports across payments, refunds and settlements. Therefore ReFlow should not position itself as “Razorpay does not have reconciliation.” That would be inaccurate.

Razorpay's own 2026 Agentic Platform also advertises Intelligent Reconciliation that can extract UTR/amount information from a bank-statement screenshot and compare it with Razorpay records.

Sources:

- https://razorpay.com/docs/payments/dashboard/reports/
- https://razorpay.com/docs/payments/dashboard/reports/custom-reports/
- https://razorpay.com/blog/razorpay-agentic-platform/

### Product gap ReFlow targets

ReFlow targets the **verification and exception-investigation layer** around multi-source reconciliation:

1. ingest event history without being fooled by duplicates/order;
2. reconstruct transaction truth;
3. decompose grouped settlements into underlying financial movements;
4. prove the expected net amount;
5. tie settlement to bank-credit evidence;
6. classify the mismatch when any invariant fails;
7. let a bounded agent gather more evidence and propose the next safe step;
8. preserve unresolved uncertainty rather than inventing a match.

## 6. Razorpay's current AI philosophy

Razorpay's 2026 Agent Studio material repeatedly emphasizes merchant-controlled scopes, verified first-party data, deterministic/platform validation before execution, human approval for sensitive actions and full audit trails.

Source: https://razorpay.com/blog/razorpay-agent-studio-principles-guardrails-and-merchant-control/

Razorpay engineering's August 2026 eval write-up is also highly relevant: evaluate the **whole agentic system**, use a representative corpus, run candidates under the same conditions, make item selection deterministic, fail safely, preserve raw results, and report uncertainty rather than relying on a single flattering benchmark.

Source: https://razorpay.com/blog/?p=27428

ReFlow should visibly mirror these engineering values without copying Razorpay internals.

## 7. Test-mode constraint discovered for this project

The connected Razorpay merchant account currently exposes a small amount of test payment data but **no settlement records**. Consequently:

- the benchmark must be synthetic-first;
- the product must not require a real settlement to arrive during judging;
- any live Razorpay integration should demonstrate payment/API/webhook correctness, while settlement-reconciliation correctness is measured against the checked-in synthetic corpus.

This is consistent with the Track 04 requirement, which explicitly asks for a 50+ record synthetic batch.

## 8. Data model implications

Use integer paise for all monetary truth. Avoid floating point.

Keep these concepts distinct:

- merchant order;
- Razorpay payment attempt;
- current payment state;
- refund;
- adjustment;
- recon ledger entry;
- settlement batch;
- settlement webhook state;
- bank transaction;
- evidence link;
- reconciliation decision;
- exception;
- agent investigation;
- proposed resolution;
- approval/audit record.

Do not overload a single `status` column to represent all of them.
