# ReFlow — Known Limitations and Non-Claims

This file must stay current as implementation progresses.

A strong finance system should say what it cannot prove.

---

## Current state

ReFlow is currently in **research and architecture**. The implementation and final benchmark have not started.

Therefore we currently make **no claims** about:

- accuracy;
- throughput;
- maximum supported transaction volume;
- memory consumption;
- AI adapter success rate;
- reconciliation rate;
- false-positive rate;
- production readiness.

Any such number appearing elsewhere before the benchmark exists is a bug in the documentation.

---

## Scope limitations planned for the Buildathon

### 1. Synthetic financial world

Track 04 explicitly allows/requires synthetic batch data. The main measured reconciliation benchmark will therefore be synthetic and adversarial.

It will not be presented as a Razorpay production-data benchmark.

### 2. Real Razorpay Test Mode coverage

Razorpay Test Mode will be used where it provides legitimate integration evidence. Current connected account data does not provide a useful live settlement history, so settlement decomposition must not depend on live account settlements appearing before submission.

### 3. India / INR first

The first financial contracts are designed around INR and integer paise.

Multi-currency settlement, FX conversion and cross-border accounting are outside the initial scope.

### 4. Reconciliation, not accounting ERP

ReFlow proves/explains payment-settlement-bank relationships.

It will not automatically post journal entries into Tally/QuickBooks/ERP in the Buildathon version.

### 5. No autonomous money movement

The AI investigator will not initiate refunds, payouts, transfers or settlement operations.

### 6. No AML/fraud decisioning

Fraud detection, AML transaction monitoring, sanctions screening and credit underwriting are separate high-stakes domains and are not Buildathon scope.

### 7. Bank-format coverage

The Source Adapter Compiler will be benchmarked against an adversarial family of formats, not every Indian bank/accounting export in existence.

### 8. PDF/OCR is not the core

CSV/JSON are P0. XLSX/PDF/screenshot ingestion is stretch functionality.

### 9. Split-credit semantics may be constrained

The domain graph should support one settlement/request mapping to multiple bank entries. The first implementation may prove this only on explicitly modeled/synthetic settlement modes rather than claiming universal inference for arbitrary bank credits.

### 10. Residual solver is bounded

The solver will have strict candidate/time limits. When the solution space is too large or ambiguous, the correct output is an exception, not an exhaustive search that blocks the system.

### 11. AI providers are replaceable and fallible

No model is treated as authoritative. Provider outage should only degrade semantic adapter inference/investigation, not deterministic financial truth.

### 12. ReFlow does not prove bank finality beyond available evidence

A bank statement/feed is itself a source. ReFlow proves consistency with supplied bank evidence; it is not a direct participant in the banking settlement rail.

---

## Evaluation limitations that must be disclosed later

The final README/pitch should disclose:

- how synthetic distributions were chosen;
- which failure types are represented;
- which are not represented;
- dataset seed/version;
- held-out strategy;
- model/version used;
- whether agent decisions are live or replayed;
- hardware used for throughput;
- any benchmark bug/fix that affected results;
- any source schema with poor adapter results;
- any exception class with weak accuracy;
- whether large-scale results are extrapolated or directly measured.

---

## Rule

When reality makes ReFlow look less impressive, update this file rather than weakening the test.
