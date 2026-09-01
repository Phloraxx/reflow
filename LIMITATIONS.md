# ReFlow — Known Limitations and Non-Claims

This file must stay current as implementation progresses. A finance system should state what it cannot prove.

---

## Current state

ReFlow implementation scope now reaches **Gate 14**:

- engineering constitution and CI;
- typed financial contracts;
- hidden financial-world generator;
- adversarial observation corruption;
- normalized known-fixture adapters;
- journal-first raw evidence ingestion and temporal payment reduction;
- journal-backed Money Graph construction with raw-envelope provenance;
- deterministic Settlement Composition Proofs with identity, provenance and temporal contradiction checks;
- conservative standard-settlement Bank Receipt Proofs using exact UTR identity, exact amount and causal bank timing;
- immutable versioned full-reconciliation proofs with knowledge cutoffs and reopening;
- bounded deterministic residual explanation hypotheses that never promote themselves to proof;
- a hidden-truth baseline evaluation harness with B0/B1/B2/ReFlow Core arms, semantic evidence scoring and independently verifiable benchmark artifacts;
- a journal-first AI-assisted Source Adapter Compiler with finite declarative transforms, explicit review/migration authorization, versioned schema routing and raw→canonical provenance;
- independently replayable Gate 12 proposal and automatic-migration development benchmarks;
- a deterministic Gate 13 reconciliation control plane with explicit scope, source-delivery/completeness state, versioned policy, proof-derived no-orphan coverage, exact balance control, close readiness and immutable run capsules;
- a deterministic Gate 14 exception-case lifecycle with stable economic identity, immutable observations, append-only workflow dispositions, economic supersession and run-specific incident fingerprints/clusters.

Gate 11 fixed development-seed results, Gate 12 development adapter/migration corpora and Gate 13/14 deterministic fixtures are regression evidence only. The final held-out reconciliation benchmark, live-model adapter benchmark, scale benchmark, durable application persistence, exception-investigation agent, production Razorpay integration and operator UI are **not complete yet**.

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

Unknown bank schemas now have a Gate 12 compiler path, but first-seen AI proposals remain review-only and are not production-authorized merely because they parse. The normalized bank contract is still not a universal production bank-statement parser.

### 12. INR first

The first contracts use INR and integer paise. Multi-currency settlement, FX conversion and cross-border accounting are outside initial Buildathon scope.

### 13. No accounting ERP mutation

ReFlow proves and explains payment-settlement-bank relationships. The Buildathon version will not automatically post accounting journal entries into Tally, QuickBooks or another ERP.

### 14. No autonomous money movement

The AI investigator will not initiate refunds, payouts, transfers or settlement operations.

### 15. No AML/fraud decisioning

Fraud detection, AML transaction monitoring, sanctions screening and credit underwriting are separate high-stakes domains and are not Buildathon scope.

### 16. Bank-format coverage is bounded

The Gate 12 development proposal/migration corpora exercise an adversarial family of formats, not every Indian bank/accounting export in existence. A separate live-model/provider benchmark is still required before any adapter-model quality claim.

### 17. PDF/OCR is not the core

CSV/JSON are P0. XLSX/PDF/screenshot ingestion remains stretch functionality.

### 18. Residual solving is bounded and intentionally incomplete

Gate 10 uses deterministic limits for candidate count, combination size, visited search nodes and returned solutions. It does **not** use wall-clock timeout as a correctness boundary.

The current candidate families are deliberately narrow: unmatched positive bank credits and recon components already blocked by upstream proof rules. Bank over-credit/negative residual explanations, provider-specific Instant Settlement payout explanations, richer fee/refund hypotheses and cross-source semantic hypotheses remain later work.

`candidate_space_truncated`, `search_budget_exhausted` and `solution_limit_reached` explicitly disclose incomplete search. An exact arithmetic explanation remains `HYPOTHESIS`; it cannot change Gate 7, Gate 8 or Gate 9 truth without new authoritative evidence.

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

### 22. Gate 12 is not a production connector platform

Gate 12 currently uses an in-memory adapter store and in-memory raw journal for the Buildathon reference implementation. Approval evidence is a typed, self-verifying record created by an explicit caller action; it is not an external identity/signature service and does not prove who performed a review. Production use still requires authenticated operator identity, durable persistence, access control and audit retention.

First-seen AI proposals never auto-activate. Financial control totals can reject wrong money semantics but do not prove identity/reference semantics. Automatic activation is currently limited to a migration whose old/new fixture replay produces identical canonical financial facts and whose approval evidence binds the exact adapter version/schema.

The OpenAI provider requires an explicit model and sends only bounded, heuristically redacted sample values with `store=false`. Redaction covers obvious address-like values, long numeric identifiers and known secret-token patterns, but it is not a DLP guarantee. Real customer/merchant data must not be used in the public benchmark.

No live-model Gate 12 quality number is claimed in the repository yet because no live provider benchmark has been frozen and run. The checked-in development reference/mutation corpus validates the compiler, safety boundaries and benchmark itself, not model intelligence.

### 23. Gate 13 control-plane proofs do not authenticate external source/account inputs

Gate 13 now implements first-class `ReconciliationScope`, `SourceDeliveryManifest`, `ReconciliationPolicyVersion`, `ReconciliationRun`, proof-derived `EvidenceCoverageCertificate`, exact `BalanceControlProof` and `CloseReadinessCertificate`. Those objects are deterministic, content-addressed and fail closed under direct tampering.

The source manifest binds retained envelope IDs to an explicit ReFlow scope/account, but the current reference implementation does not authenticate the external connector/session that supplied that account identity. Production ingestion must derive merchant/provider/bank account identity from an authenticated connector or trusted integration context rather than arbitrary operator text. The existing manifest/content hashes are integrity bindings, not digital signatures from Razorpay or a bank.

Likewise, the balance control proves the exact integer equation over supplied opening position, provider activity, bank-proven payout, adjustment and observed closing inputs. Gate 13 does not yet fetch or independently authenticate authoritative external opening/closing balances. It is a control proof, not a new product ledger.

Materiality bands are workflow metadata only and never weaken exact Gate 7/8/9 proof or Gate 13 balance residuals.

### 24. Application persistence and authenticated workflow are not implemented yet

Current stores are reference/in-memory implementations. Gate 13 run/certificate objects and Gate 14 case/disposition/incident objects exist, but durable run history, source manifests, proof/case history, adapter approvals, operator dispositions and authenticated ownership still require a minimal application/persistence layer. The planned Buildathon shape is a modular application service plus PostgreSQL, not a microservice/distributed-workflow architecture.


### 25. Gate 14 case lifecycle is deterministic but not durable/authenticated

Gate 14's `InMemoryExceptionCaseLedger` provides deterministic reference semantics, not PostgreSQL durability, crash recovery, distributed locking or an authenticated workflow service. Actor identifiers on dispositions are supplied audit fields; ReFlow does not yet prove who performed an action.

Gate 14 currently creates settlement cases from Gate 9 proof outcomes. It does not synthesize a case for every run-level Gate 13 close-readiness blocker when no settlement proof exists. Incident fingerprints group current failure patterns; they are operational grouping identities, not financial proof and not ML classifications.

Changed authoritative amount or UTR creates a new economic case and supersedes the old one. That deterministic behavior is tested with valid immutable artifacts, but production source-correction semantics still depend on the real Razorpay integration and later durable application layer.
