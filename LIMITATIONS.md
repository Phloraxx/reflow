# ReFlow — Known Limitations and Non-Claims

This file must stay current as implementation progresses. A finance system should state what it cannot prove.

---

## Current state

ReFlow implementation scope now reaches **Gate 19**:

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
- a deterministic Gate 14 exception-case lifecycle with stable economic identity, immutable observations, append-only workflow dispositions, economic supersession and run-specific incident fingerprints/clusters;
- a Gate 15 journal-first Razorpay provider boundary for signed payment/settlement webhooks, Settlement Recon items and processed standard settlement API entities, with explicit evidence-origin labels and provider UTR preservation.
- a Gate 16 bounded exception investigator with immutable target binding, three read-only tools, content-addressed tool traces, deterministic proposal validation and an optional strict/stateless OpenAI Responses transport;
- a Gate 17 measured one-process scale path plus PostgreSQL 16 durability/application boundary for append-only raw evidence, immutable product/audit artifacts and optimistic operational current pointers.
- a Gate 18 scoped read-only FastAPI + React Operator Control Tower over immutable run/proof/case/source/evaluation state, including a deterministic synthetic demo path.
- a Gate 19 frozen held-out evaluation/failure-campaign layer with precommitted seeds/scorer hashes, preserved first-run evidence, generated final metrics and submission reproducibility checks.

Gate 19 now adds the first frozen held-out reconciliation result and a final representative failure campaign. Live-model adapter/investigation benchmarks, an authenticated real settlement/recon corpus, and a public authenticated production deployment are **not complete**.

The repository may publish only the checked-in final evidence with its exact denominators:

- automatic match coverage: **512/768 = 66.67%**;
- auto-match precision: **512/512 = 100%**;
- truth-reconciled recall: **512/624 = 82.05%**;
- silent false auto-match rate: **0/512 = 0%**;
- 256 explicit non-green decisions on the primary held-out corpus;
- Gate 17 proof-pipeline scale: **206.97 settlements/s** on the disclosed 10k Oracle workload.

These are synthetic/adversarial reference results. ReFlow still makes **no claim** of production SLO/capacity, 100k/1M scale, live-model quality, real Test Mode settlement accuracy, or production readiness.

---

## Current implementation limitations

### 1. Synthetic financial world

The main development/evaluation world is synthetic and adversarial. It is not presented as Razorpay production data.

The simulator checks arithmetic, identity references and temporal causality. Its standard-settlement bank truth now also requires one globally unique bank UTR per observed bank transaction. Its distributions still require later calibration against legitimate real integration evidence.

### 2. Current source formats are normalized fixture contracts

The current known-fixture adapters consume normalized test shapes. In particular, recon rows use fields such as `gross_amount_paise` and `settlement_effect_paise`.

They remain **normalized fixture adapters**, not the provider API boundary. Gate 15 now separately consumes provider-shaped Razorpay payment/settlement webhooks and Settlement Recon rows. It preserves raw provider evidence first and normalizes authoritative `debit`, `credit`, `amount`, `fee`, `tax`, settlement identity and UTR semantics without reusing synthetic arithmetic assumptions.

The connected merchant account did not expose settlement/recon rows during the Gate 15 check, so provider-document fixtures are not promoted to a real Test Mode settlement benchmark. An authenticated real settlement/recon corpus is still required before any live/Test Mode accuracy claim.

The neutral `ObservedBatch` / `RawRecord` transport contract remains the normalized fixture/bank path; Gate 15 is a distinct provider parsing boundary that emits the same canonical domain and `SourceLink` contracts rather than a second reconciliation engine.

### 3. Payment webhook and refund evidence remain separate

The normalized payment-event reducer accepts payment transition evidence used by the current fixture pipeline. Refunds remain first-class `Refund` / settlement-recon economic evidence rather than being synthesized as a `payment.refunded` webhook.

Razorpay documents payment entity status separately from the refund webhook lifecycle. A partial refund is represented by authoritative refund/payment fields rather than by inventing an unsupported generic payment webhook transition.

The later production adapter must preserve that distinction and must not infer a partial-refund amount from generic payment-event evidence.

### 4. Raw evidence provenance has a PostgreSQL durability reference, not a complete production ingestion service

Successful journal-first ingestion binds canonical source identities to immutable `SourceEnvelopeId`s. Canonicalization reads the journal’s retained immutable primary payloads; canonical facts and exact `SourceLink`s are then bound by a source-order-invariant compilation digest. Money Graph edges, Settlement Composition Proofs and Bank Receipt Proofs cite those raw envelopes, and each envelope validates its payload digest and deterministic identity.

The compilation digest is an integrity binding, not a digital signature. Gate 47 now provides a dedicated HTTP webhook server that verifies Razorpay HMAC over exact raw bytes and durably retains authenticated receipts before acknowledgement. Webhook secrets still come from deployment-managed environment files rather than a repository secret store. Gate 45 separately adds Cloudflare Access authentication and exact-scope authorization for the human Control Tower. For provider API reads, `RazorpayAccountContext` remains an explicit trusted connector/application boundary rather than cryptographic proof created by this library.

Gate 17 adds `PostgresApplicationStore`, which implements the structural journal contract with immutable PostgreSQL rows, exact duplicate replay, retained conflicting evidence, deterministic reads and restart/reconnect survival. The in-memory journal remains the fast deterministic test/evaluation implementation.

This is not a complete production ingestion service: there is still no connector scheduler, pooled/batched bulk loader, automated retention policy, tenant onboarding/provisioning, or authenticated operator write API. Gates 46–48 add restore-tested logical backup, durable webhook ingress, and a real physical PITR mechanics drill plus deployment templates, but no off-host WAL archive has been provisioned and no production RPO/RTO is claimed. The measured reference PostgreSQL path is intentionally fine-grained and much slower than the in-memory proof-scale benchmark.

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

Gate 15 validates the supported Razorpay recon identity families (`payment`, `refund`, `transfer`, `adjustment`) and fails closed on unsupported types/prefix mismatches. Any future provider entity type still requires an explicit identity contract before it can participate in this ownership rule.

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
- frozen held-out strategy and seed/scorer hashes;
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

### 24. Application persistence is implemented as immutable audit state; authenticated workflow is not

Gate 17 adds a PostgreSQL 16 application store for append-only raw evidence, immutable canonical JSON artifacts and optimistic current pointers, plus a minimal `ReflowApplicationService`. It can durably retain Gate 13 run/control artifacts, Gate 9 proofs, Gate 14 case/disposition/incident artifacts, approved adapters and Gate 16 result/trace artifacts. Real PostgreSQL tests cover reconnect survival, conflict retention, tamper detection, scope isolation and compare-and-swap behavior.

The existing `InMemoryProofLedger`, `InMemoryExceptionCaseLedger` and adapter lifecycle stores are still deterministic derivation/reference components; Gate 17 does not silently replace them with a new database-authoritative financial engine. Persisting an artifact does not bypass the originating domain object's self-validation. Authenticated operator identity, tenant authorization, RBAC/SSO and durable job/queue workflow remain unimplemented.


### 25. Gate 14 case lifecycle is deterministic but not durable/authenticated

Gate 14's `InMemoryExceptionCaseLedger` provides deterministic reference semantics, not PostgreSQL durability, crash recovery, distributed locking or an authenticated workflow service. Actor identifiers on dispositions are supplied audit fields; ReFlow does not yet prove who performed an action.

Gate 14 currently creates settlement cases from Gate 9 proof outcomes. It does not synthesize a case for every run-level Gate 13 close-readiness blocker when no settlement proof exists. Incident fingerprints group current failure patterns; they are operational grouping identities, not financial proof and not ML classifications.

Changed authoritative amount or UTR creates a new economic case and supersedes the old one. That deterministic behavior is tested with valid immutable artifacts and Gate 17 can persist the resulting history, but production source-correction semantics still depend on authenticated Razorpay connector context and operator workflow.

### 26. Gate 15 is a provider contract, not a complete production connector service

Gate 15 itself implements deterministic provider parsing and webhook HMAC verification rather than a complete connector service. Gate 47 later adds the dedicated durable HTTP webhook ingress and current/previous-secret rotation window, while Gate 48 provides a separated deployment template for that service. Settlement Recon polling, provider OAuth/onboarding, and authenticated account-context provisioning are still not implemented; `REAL_TEST_MODE` and `REAL_LIVE` remain explicit trust labels supplied by a trusted connector/application boundary.

Razorpay's documented standard settlement entity omits currency. Gate 15 therefore binds standard-settlement currency from explicit account context (currently INR) rather than inventing a provider field. A processed settlement API entity uses ReFlow observation time as canonical `processed_at`; provider `created_at` is retained/validated but is not reinterpreted as processing time or bank-credit time.

The connected account exposed no settlement or settlement-recon rows during the Gate 15 inspection. No private payment payload is checked into the repository, and no `REAL_TEST_MODE` settlement accuracy number is claimed. Standard Instant Settlement (`setlod_...` / `setlodp_...`) proof topology remains explicitly unsupported.

### 27. Gate 16 is a bounded advisory reference, not an autonomous finance operator

Gate 16 can investigate only one active case bound to one exact current Gate 9 proof. Its public capability set is limited to case snapshot, proof snapshot and proof-scoped source evidence. It cannot mutate proof state, case state, dispositions, adapters, evidence, refunds, payouts, transfers or settlement state. Accepted output is advisory only and limited to `WAIT`, `RECHECK`, `REQUEST_SOURCE`, `REQUEST_HUMAN_REVIEW` or `ABSTAIN`.

Gate 17 can durably retain validated Gate 16 investigation result/trace artifacts, but it does not provide a durable investigation queue, authenticated operators, tenant authorization, rate limiting, provider-cost budgets or production observability. Core bounds currently limit one investigation to 16 tool calls and 64 proof source envelopes; cases exceeding the source-evidence budget fail closed rather than being silently sampled.

The OpenAI Responses provider is protocol-tested with deterministic fake transports, not benchmarked for live investigation accuracy. No live-model Gate 16 success rate is claimed. It uses `store=false`, stateless output-item replay, strict function/final schemas and a minimized model-facing projection. External settlement IDs, UTRs and source-record IDs are omitted from model tool outputs, and source text gets heuristic redaction for obvious email, long-number, secret-token and transaction-ID patterns. This is data minimization, **not a DLP guarantee**; production policy must still decide whether particular merchant/customer evidence may be sent to an external model.

Provider refusal, timeout, malformed output, hallucinated citations, wrong financial numbers, unsupported actions or denied tool access cannot change deterministic financial truth. They produce abstention/rejection/provider-error artifacts only.

### 28. Gate 17 scale and PostgreSQL results are measured reference results, not a production capacity promise

Gate 17's checked-in scale artifacts were measured on one shared 4-vCPU aarch64 Oracle VM with Python 3.12.3 and one process. The largest completed clean tier is 10,000 settlements / 1,203,220 raw rows: 267.56 s end-to-end, 48.32 s in the proof pipeline, 206.97 proof settlements/s and about 3.18 GiB process RSS. Those numbers describe that exact deterministic benchmark shape only; they are not a production SLO or a statement that every merchant dataset has the same cardinality/memory behavior.

A 100k/1M run was not attempted. The 10k tier already satisfied the frozen Gate 17 requirement and used substantial memory on a VM hosting unrelated services. ReFlow makes no 100k/1M throughput or memory claim and does not extrapolate a headline number.

The isolated PostgreSQL 16.15 cold/warm benchmark measured roughly 76 source writes/s and 87–90 immutable-artifact writes/s for 1,000 fine-grained operations. This proves the reference persistence/idempotency path and also exposes its current bottleneck: it is not a bulk loader and has no connection pool/batched ingestion API. In-memory core throughput and PostgreSQL durability throughput must not be conflated.

Gate 17 itself does not provide HA/replication, recovery orchestration, retention/archival automation, authenticated tenant isolation, authenticated operator write APIs or a distributed queue. Later production-hardening gates add logical backup/restore verification, a physical PITR mechanics drill, Cloudflare Access read authorization, durable webhook ingress and single-host deployment templates; they still do not provide HA/failover, a provisioned off-host WAL archive, automated migrations, tenant onboarding or a distributed queue. None of Kafka, Kubernetes, Celery, Redis or sharding was introduced because the measured proof-core bottleneck was fixed algorithmically instead.
### 29. Gate 18 is a read-only reviewer/control-tower surface, not an authenticated production finance application

Gate 18 exposes scoped read models and a same-origin FastAPI/React application. It has no POST/PUT/PATCH/DELETE product routes and cannot mark a proof reconciled, issue money movement, execute Gate 16 recommendations or run generic SQL. That is an intentional authority boundary, not a claim that the web application is production-secure.

Gate 45 subsequently adds Cloudflare Access JWT authentication and exact-scope read authorization for the Control Tower, while preserving `scope_id` as a routing identifier rather than an authorization credential. The product still lacks tenant self-service/onboarding, authenticated operator write permissions, a production rate-limit/WAF policy, an external penetration test and a completed public real-data deployment. Real merchant evidence must not be exposed through a deployment that bypasses that authenticated application boundary.

Source Lab intentionally omits raw source payloads and exposes delivery/schema/adapter metadata only. Case File exposes bounded investigation summaries/citations and immutable artifact identities, but the default product surface is not a raw secret/data explorer. These reductions lower accidental exposure risk but are not a DLP/privacy guarantee.

The Gate 18 demo seeder is deterministic synthetic evidence generated through the existing proof/case/investigation pipeline. It is not Razorpay Test Mode/live merchant evidence and must not be used to claim real-data reconciliation accuracy. The demo PostgreSQL credentials shown in README are localhost-only disposable development credentials, not deployment secrets.

FastAPI can serve the built Vite application and `/api` on one origin. F-0082 fixed SPA history fallback so direct client navigation works while unknown `/api/*` paths stay 404. This packaging path was smoke-tested on Oracle, but there is no public deployment/SLO/availability claim yet.

The frontend formats exact API-supplied money values and performs presentation-only filtering. It must not become a second implementation of Gate 7/8/9 arithmetic or derive proof truth from displayed amounts.

### 30. Gate 19 final evidence is frozen synthetic evidence, not production validation

The final held-out v1 is intentionally synthetic/adversarial and its seeds/scorer/candidate hashes were committed before first execution. The first result is preserved unchanged. That makes the benchmark challengeable and reproducible; it does not make the synthetic distribution representative of every Razorpay merchant or bank.

`66.67%` is the automatic match rate over all 768 requested settlements, not an accuracy score. The relevant correctness number for automatic green decisions is 512/512 = 100% precision on this frozen corpus; truth-reconciled recall is 512/624 = 82.05%. The strong B1 grouped-exact baseline ties ReFlow's recall, and the repository explicitly reports that tie.

The final source-schema safety corpus and 12-check failure campaign test selected known safety boundaries. They do not constitute exhaustive security testing, penetration testing, formal verification or every possible financial/provider failure mode. The high-confidence secret-pattern scan is likewise not a substitute for platform-native secret scanning and repository-owner review.

No live-model final quality benchmark ran because no provider key was configured on the final Oracle host. No real Razorpay settlement/recon accuracy benchmark ran because no suitable real/Test Mode settlement corpus was available. Those absences must remain visible in any submission/pitch.

The repository is public, but a public authenticated ReFlow finance deployment is not claimed. A synthetic-only demo may be published separately. The read-only web app now has the Gate 45 Cloudflare Access/exact-scope authorization boundary and Gate 48 deployment templates, but no production host/tunnel has been provisioned as evidence and real merchant data must not be presented as publicly deployed.

### 31. Post-final audit hardening does not create a production application boundary

The post-final whole-codebase audit hardened the reference implementation substantially: public durable writes now require typed/self-validating artifacts, current pointers are identity-coherent, proof browsing is tied to scoped run/manifests rather than storage labels, the public journal is a narrow façade, final evidence verification is required in CI, Python/CI bootstrap dependencies are constrained/pinned, optional OpenAI transport is HTTPS-only/no-redirect with a 1 MiB response ceiling, and Gate 12 model-facing profiles have explicit finite bounds.

Those audit changes alone did not add an application security/deployment boundary. Subsequent gates now add Cloudflare Access authentication, exact-scope read authorization, current/previous Razorpay webhook-secret rotation, logical backup/restore verification, durable webhook ingress, and tested PITR/deployment templates. Remaining gaps include production connector identity/onboarding, authenticated operator write permissions, HA/failover, provisioned off-host WAL archival, production observability and a public real-data deployment. `scope_id` is still never treated as authorization by itself.

Independent branch-aware coverage is 79% on the repaired audit tree. Several proof/control validators remain intentionally complex and the Gate 13 control plane has the largest fail-closed branch-coverage debt at 73%. The generic reference artifact-list APIs also have finite query limits; production long-history operation needs pagination/indexed read models rather than assuming an unbounded in-process scan.

The 46.91 MiB Gate 19 first-run held-out artifact remains checked in unchanged because it is evidence. The Control Tower consumes a compact self-verifying derived summary instead of loading that raw artifact for every Evaluation Lab request.
