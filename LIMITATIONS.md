# ReFlow — Known Limitations and Non-Claims

This file must stay current as implementation progresses. A finance system should state what it cannot prove.

---

## Current state

ReFlow has implemented and independently re-audited the deterministic foundation through **Gate 7** on `build/phase-7-9-proof-engine`:

- engineering constitution and CI;
- typed financial contracts;
- hidden financial-world generator;
- adversarial observation corruption;
- normalized known-fixture adapters;
- journal-first raw evidence ingestion and temporal payment reduction;
- journal-backed Money Graph construction with raw-envelope provenance;
- deterministic Settlement Composition Proofs with identity, provenance and temporal contradiction checks.

Gate 8 bank receipt proofs, Gate 9 full proof/versioning, the residual solver, final evaluation harness, AI layers, production Razorpay integration and operator UI are **not complete yet**.

We currently make **no published claims** about:

- final reconciliation accuracy or match rate;
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

The simulator checks arithmetic, identity references and temporal causality, but its distributions still require later calibration against legitimate real integration evidence.

### 2. Current source formats are normalized fixture contracts

The current known-fixture adapters consume normalized test shapes. In particular, recon rows use fields such as `gross_amount_paise` and `settlement_effect_paise`.

They are **not** claimed to be final production Razorpay API/webhook adapters. Razorpay's actual Settlement Recon API exposes authoritative `debit`, `credit`, `amount`, `fee` and `tax` fields. The later real adapter must normalize those semantics explicitly and fixture-test them against actual Test Mode/API evidence rather than reuse synthetic arithmetic assumptions.

The current `ObservedBatch` / `RawRecord` container also lives under the simulator package because it is the evaluation fixture transport. This does not expose hidden truth to the engine, but production ingestion should eventually use integration-specific DTOs rather than present the simulator container as a public production API.

### 3. Payment webhook and refund evidence remain separate

The normalized payment-event reducer accepts payment transition evidence used by the current fixture pipeline. Refunds remain first-class `Refund` / settlement-recon economic evidence rather than being synthesized as a `payment.refunded` webhook.

Razorpay documents `created`, `authorized`, `captured`, `refunded` and `failed` as payment entity statuses, while refund webhooks are a separate lifecycle. A partial refund leaves the payment status `captured` and is represented by authoritative refund fields such as `refund_status` and `amount_refunded` in the real payment entity.

The later production adapter must preserve that distinction and must not infer a partial-refund amount from generic payment-event evidence.

### 4. Raw evidence provenance is journal-backed, but persistence is in-memory

Successful journal-first ingestion now binds canonical source identities to immutable `SourceEnvelopeId`s. Money Graph edges and Settlement Composition Proofs cite those raw envelopes, and each envelope validates its payload digest and deterministic identity.

The journal is still an in-memory reference implementation. Crash/restart persistence, database constraints, migrations and retention policy remain later work.

### 5. Settlement Composition Proof is not full reconciliation

Gate 7 proves settlement composition only. A `COMPOSITION_PROVEN` result means the supplied authoritative recon components consistently and uniquely explain the settlement amount under the current normalized contract.

It does **not** prove that money reached the bank. Gate 8 must independently prove bank receipt before Gate 9 can emit a full reconciled proof.

### 6. Current economic-identity ownership is conservative

For the normalized fixture contract, one payment/refund/transfer/adjustment identity cannot silently be claimed by multiple settlements. Such evidence is contradicted rather than guessed.

The production Razorpay adapter must verify the exact identity semantics of every real recon entity type before this rule is generalized beyond the supported source contract.

### 7. Bank adapter is a settlement-credit feed contract

The current bank adapter accepts positive settlement-credit rows. It is not a complete arbitrary bank-statement parser containing debits, balances, reversals and unrelated account traffic.

Unknown bank schemas remain fail-closed until later adapter-compiler/integration work.

### 8. INR first

The first contracts use INR and integer paise. Multi-currency settlement, FX conversion and cross-border accounting are outside initial Buildathon scope.

### 9. No accounting ERP mutation

ReFlow proves and explains payment-settlement-bank relationships. The Buildathon version will not automatically post accounting journal entries into Tally, QuickBooks or another ERP.

### 10. No autonomous money movement

The AI investigator will not initiate refunds, payouts, transfers or settlement operations.

### 11. No AML/fraud decisioning

Fraud detection, AML transaction monitoring, sanctions screening and credit underwriting are separate high-stakes domains and are not Buildathon scope.

### 12. Bank-format coverage is bounded

The Source Adapter Compiler will be benchmarked against an adversarial family of formats, not every Indian bank/accounting export in existence.

### 13. PDF/OCR is not the core

CSV/JSON are P0. XLSX/PDF/screenshot ingestion remains stretch functionality.

### 14. Split-credit semantics are constrained initially

The domain supports one settlement mapping to multiple bank entries. Gate 8 may prove split credits only when explicit source evidence binds those rows to the settlement; it will not claim universal subset inference from amount alone.

### 15. Residual solving will be bounded

The solver will have strict candidate/time limits. If the solution space is large or ambiguous, the correct output is an exception.

### 16. AI providers are replaceable and fallible

No model is authoritative. Provider outage may degrade schema understanding or exception investigation, but deterministic financial truth must continue to function.

### 17. ReFlow cannot prove bank finality beyond supplied evidence

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
