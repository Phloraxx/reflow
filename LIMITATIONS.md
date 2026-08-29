# ReFlow — Known Limitations and Non-Claims

This file must stay current as implementation progresses. A finance system should state what it cannot prove.

---

## Current state

ReFlow has implemented and audited the deterministic foundation through **Gates 0–6** on the current build branch:

- engineering constitution and CI;
- typed financial contracts;
- hidden financial-world generator;
- adversarial observation corruption;
- normalized known-fixture adapters;
- journal-first raw evidence ingestion and temporal payment reduction;
- provenance-preserving Money Graph construction.

Settlement composition proofs, bank receipt proofs, proof versioning, the residual solver, final evaluation harness, AI layers, production Razorpay integration and operator UI are **not complete yet**.

We currently make **no published claims** about:

- reconciliation accuracy or match rate;
- throughput;
- maximum supported transaction volume;
- memory consumption;
- AI adapter success rate;
- false-positive rate on a final held-out benchmark;
- production readiness.

Any such number appearing before the checked-in final benchmark exists is a documentation bug.

---

## Current implementation limitations

### 1. Synthetic financial world

The main development/evaluation world is synthetic and adversarial. It is not presented as Razorpay production data.

The simulator now checks arithmetic, identity references and temporal causality, but its distributions still require later calibration against legitimate real integration evidence.

### 2. Phase 4 recon format is normalized synthetic evidence

The current known-fixture recon adapter consumes an already-normalized signed schema with fields such as `gross_amount_paise` and `settlement_effect_paise`.

It is **not** claimed to be the final production Razorpay Settlement Recon adapter. Razorpay's actual Recon API exposes authoritative `debit`, `credit`, `amount`, `fee` and `tax` fields. The later real adapter must normalize those semantics explicitly and fixture-test them against real Test Mode/API evidence rather than reuse synthetic arithmetic assumptions.

### 3. Journal persistence is in-memory

Raw evidence now enters the append-only journal before deterministic canonicalization, including malformed rows whose source timestamp cannot be parsed.

The current journal is still an in-memory reference implementation. Crash/restart persistence, database constraints, migrations and retention policy remain later work.

### 4. Bank adapter is a settlement-credit feed contract

The current bank adapter accepts positive settlement-credit rows. It is not a complete arbitrary bank-statement parser containing debits, balances, reversals and unrelated account traffic.

Unknown bank schemas remain fail-closed until the later adapter compiler/integration work.

### 5. Refund state modeling is intentionally conservative

Refunds are first-class economic entities. The generic `PaymentEventKind.REFUNDED` path represents a fully refunded payment; partial refund amount/status will require authoritative refund/payment fields from the real integration.

The proof engine must not infer partial-refund amount from a generic payment event alone.

### 6. INR first

The first contracts use INR and integer paise. Multi-currency settlement, FX conversion and cross-border accounting are outside initial Buildathon scope.

### 7. No accounting ERP mutation

ReFlow proves and explains payment-settlement-bank relationships. The Buildathon version will not automatically post accounting journal entries into Tally, QuickBooks or another ERP.

### 8. No autonomous money movement

The AI investigator will not initiate refunds, payouts, transfers or settlement operations.

### 9. No AML/fraud decisioning

Fraud detection, AML transaction monitoring, sanctions screening and credit underwriting are separate high-stakes domains and are not Buildathon scope.

### 10. Bank-format coverage is bounded

The Source Adapter Compiler will be benchmarked against an adversarial family of formats, not every Indian bank/accounting export in existence.

### 11. PDF/OCR is not the core

CSV/JSON are P0. XLSX/PDF/screenshot ingestion remains stretch functionality.

### 12. Split-credit semantics are constrained initially

The domain supports one settlement mapping to multiple bank entries. The first proof implementation may prove split credits only when explicit source evidence binds those rows to the settlement; it will not claim universal subset inference from amount alone.

### 13. Residual solving will be bounded

The solver will have strict candidate/time limits. If the solution space is large or ambiguous, the correct output is an exception.

### 14. AI providers are replaceable and fallible

No model is authoritative. Provider outage may degrade schema understanding or exception investigation, but deterministic financial truth must continue to function.

### 15. ReFlow cannot prove bank finality beyond supplied evidence

A bank statement/feed is itself a source. ReFlow can prove consistency with supplied bank evidence; it is not a participant in the banking settlement rail.

---

## Evaluation disclosures required before submission

The final README/pitch must disclose:

- how synthetic distributions were chosen;
- which failure types are represented and omitted;
- dataset seed/version;
- held-out strategy;
- model/provider/version used for AI evaluation;
- whether agent decisions are live or replayed;
- hardware/runtime used for throughput;
- every benchmark bug/fix that affected results;
- any source schema with poor adapter results;
- any exception class with weak accuracy;
- whether scale results are directly measured or extrapolated.

---

## Rule

When reality makes ReFlow look less impressive, update this file rather than weakening the test.
