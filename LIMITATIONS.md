# ReFlow — Known Limitations and Non-Claims

This file must stay current as implementation progresses. A finance system should state what it cannot prove.

---

## Current state

ReFlow has implemented the deterministic foundation through **Gate 8**. A pre-Gate-9 independent audit is hardening that merged foundation before full proof/versioning begins:

- engineering constitution and CI;
- typed financial contracts;
- hidden financial-world generator;
- adversarial observation corruption;
- normalized known-fixture adapters;
- journal-first raw evidence ingestion and temporal payment reduction;
- journal-backed Money Graph construction with raw-envelope provenance;
- deterministic Settlement Composition Proofs with identity, provenance and temporal contradiction checks;
- conservative standard-settlement Bank Receipt Proofs using exact UTR identity, exact amount and causal bank timing.

Gate 9 full proof/versioning is implemented on its checkpoint branch. The residual solver, final evaluation harness, AI layers, production Razorpay integration and operator UI are **not complete yet**.

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

The simulator checks arithmetic, identity references and temporal causality. Its standard-settlement bank truth now also requires one globally unique bank UTR per observed bank transaction. Its distributions still require later calibration against legitimate real integration evidence.

### 2. Current source formats are normalized fixture contracts

The current known-fixture adapters consume normalized test shapes. In particular, recon rows use fields such as `gross_amount_paise` and `settlement_effect_paise`.

They are **not** claimed to be final production Razorpay API/webhook adapters. Razorpay's actual Settlement Recon API exposes authoritative `debit`, `credit`, `amount`, `fee` and `tax` fields. The later real adapter must normalize those semantics explicitly and fixture-test them against actual Test Mode/API evidence rather than reuse synthetic arithmetic assumptions.

The neutral `ObservedBatch` / `RawRecord` transport contract now lives under `reflow.ingestion.records`; the simulator depends on that contract rather than ingestion depending on the simulator. Real provider integrations still require source-specific DTO/parsing layers before these normalized records.

### 3. Payment webhook and refund evidence remain separate

The normalized payment-event reducer accepts payment transition evidence used by the current fixture pipeline. Refunds remain first-class `Refund` / settlement-recon economic evidence rather than being synthesized as a `payment.refunded` webhook.

Razorpay documents payment entity status separately from the refund webhook lifecycle. A partial refund is represented by authoritative refund/payment fields rather than by inventing an unsupported generic payment webhook transition.

The later production adapter must preserve that distinction and must not infer a partial-refund amount from generic payment-event evidence.

### 4. Raw evidence provenance is journal-backed, but persistence is in-memory

Successful journal-first ingestion binds canonical source identities to immutable `SourceEnvelopeId`s. Canonicalization reads the journal’s retained immutable primary payloads; canonical facts and exact `SourceLink`s are then bound by a source-order-invariant compilation digest. Money Graph edges, Settlement Composition Proofs and Bank Receipt Proofs cite those raw envelopes, and each envelope validates its payload digest and deterministic identity.

The compilation digest is an integrity binding, not a digital signature or proof that an external source was authentic. Production webhook/API authenticity remains a separate integration boundary.

The journal is still an in-memory reference implementation. Crash/restart persistence, database constraints, migrations and retention policy remain later work.

### 5. Settlement Composition Proof is not full reconciliation

Gate 7 proves settlement composition only. A `COMPOSITION_PROVEN` result means the supplied authoritative recon components consistently and uniquely explain the settlement amount under the current normalized contract.

It does **not** prove that money reached the bank.

### 6. Bank Receipt Proof is still only one proof fragment

Gate 8 proves consistency between a **standard Razorpay settlement** and supplied bank-credit evidence.

For the current standard-settlement contract, automatic proof requires:

- settlement UTR present;
- exactly one distinct bank transaction carrying that UTR;
- exact amount and currency;
- bank timestamp not before settlement processing;
- no settlement-UTR reuse in the batch;
- complete raw source provenance.

A `BANK_RECEIPT_PROVEN` result alone does not mean the settlement is fully reconciled. Gate 9 combines it with the independent composition fragment and only emits `PROVEN_RECONCILED` when both required fragments are proven.

### 7. Same amount and nearby time are never bank identity

If UTR is missing or corrupted, Gate 8 does not substitute:

- same amount;
- nearby date/time;
- narration similarity.

Such rows may be preserved as investigation evidence, but they do not establish identity. This is intentionally conservative to avoid silent same-amount false matches.

### 8. Standard settlements and Instant Settlements are not conflated

The current Gate 8 implementation supports the standard `setl_...` settlement shape.

Razorpay Instant Settlements use a different topology: a `settlement.ondemand` parent (`setlod_...`) can contain explicit `settlement.ondemand_payout` children (`setlodp_...`) with payout-level evidence and UTRs.

ReFlow does **not** yet implement that topology. It therefore does not claim support for proving multi-credit Instant Settlements. Multiple distinct bank transactions reusing one standard settlement UTR are treated as a contradiction rather than guessed as a split settlement.

A later Instant Settlement adapter/proof must model the parent and payout identities explicitly before multi-credit proof is allowed.

### 9. No arbitrary maximum bank-delay cutoff

Razorpay documents that a processed settlement may only become visible in the bank account after the bank-transfer timeline. Gate 8 therefore enforces a causal lower bound but no fixed upper delay bound.

A very late exact-UTR bank observation may still become admissible evidence. Gate 9 creates a new immutable proof version rather than rewriting what was known earlier.

### 10. Current economic-identity ownership is conservative

For the normalized fixture contract, one payment/refund/transfer/adjustment identity cannot silently be claimed by multiple settlements. Such evidence is contradicted rather than guessed.

The production Razorpay adapter must verify the exact identity semantics of every real recon entity type before this rule is generalized beyond the supported source contract.

### 11. Bank adapter is a settlement-credit feed contract

The current bank adapter accepts positive settlement-credit rows. It is not a complete arbitrary bank-statement parser containing debits, balances, reversals and unrelated account traffic.

Unknown bank schemas remain fail-closed until later adapter-compiler/integration work.

### 12. INR first

The first contracts use INR and integer paise. Multi-currency settlement, FX conversion and cross-border accounting are outside initial Buildathon scope.

### 13. No accounting ERP mutation

ReFlow proves and explains payment-settlement-bank relationships. The Buildathon version will not automatically post accounting journal entries into Tally, QuickBooks or another ERP.

### 14. No autonomous money movement

The AI investigator will not initiate refunds, payouts, transfers or settlement operations.

### 15. No AML/fraud decisioning

Fraud detection, AML transaction monitoring, sanctions screening and credit underwriting are separate high-stakes domains and are not Buildathon scope.

### 16. Bank-format coverage is bounded

The Source Adapter Compiler will be benchmarked against an adversarial family of formats, not every Indian bank/accounting export in existence.

### 17. PDF/OCR is not the core

CSV/JSON are P0. XLSX/PDF/screenshot ingestion remains stretch functionality.

### 18. Residual solving will be bounded

The solver will have strict candidate/time limits. If the solution space is large or ambiguous, the correct output is an exception.

### 19. AI providers are replaceable and fallible

No model is authoritative. Provider outage may degrade schema understanding or exception investigation, but deterministic financial truth must continue to function.

### 20. ReFlow cannot prove bank finality beyond supplied evidence

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
