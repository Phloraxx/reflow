# Money Graph and Reconciliation Proof Protocol

## Objective

This document defines the core deterministic abstraction ReFlow should build before any AI layer.

The central idea is:

> A reconciliation result is not a label. It is a verifiable proof over financial evidence.

The Money Graph is the model used to represent those relationships. The Reconciliation Proof is the artifact used to prove, explain and audit a financial conclusion.

---

## 1. Canonical financial objects

ReFlow should use a small canonical vocabulary.

### Commercial objects

- `MerchantOrder`
- `MerchantInvoice` (optional in Buildathon scope)

### Gateway/economic objects

- `Payment`
- `PaymentEvent`
- `Refund`
- `Transfer`
- `Adjustment`
- `Dispute` (initially modeled as an optional linked negative movement)

### Settlement objects

- `SettlementReconEntry`
- `Settlement`
- `InstantSettlement` (stretch/constrained support)

### Bank objects

- `BankEntry`

### ReFlow objects

Implemented through Gate 9:

- `SourceEnvelope`
- `EvidenceEdge`
- `SettlementCompositionProof`
- `BankReceiptProof`
- `ReconciliationProofVersion`
- `ProofVersionDiff`

Gate 9 now defines the combined immutable reconciliation-proof/version contract from those audited fragments. Earlier placeholder `ReconciliationProof`, `ProofVersion`, `Residual` and `ExceptionCase` domain classes were intentionally removed during the pre-Gate-9 audit; the implemented contract was then introduced only after Gate 7 and Gate 8 were audited. Residual explanation/exception workflow remains Phase 10+ work.

---

## 2. Money representation

All financial quantities use signed integer subunits.

```text
Money {
  currency: "INR"
  amount_paise: int64
}
```

Rules:

- no float in domain arithmetic;
- no implicit rupee/paise conversion;
- source units must be declared by adapter;
- currency mismatch is an exception, not a coercion;
- integer overflow/range bounds are validated at ingestion.

---

## 3. Economic movement model

Every canonical row that changes money produces an `EconomicMovement`.

Conceptually:

```text
EconomicMovement {
  movement_id
  movement_type
  amount_paise_signed
  currency
  occurred_at
  source_evidence_ids[]
  related_entity_ids[]
}
```

Positive and negative signs are defined once in canonical semantics.

Example canonical convention:

- payment contribution to merchant balance: positive;
- refund debit: negative;
- transfer debit: negative if it leaves merchant settlement balance;
- adjustment: signed according to Razorpay recon row semantics;
- fee: negative;
- tax: negative.

The adapter may ingest `debit` and `credit` separately, but the canonical movement must have one unambiguous sign.

---

## 4. Evidence edges

The Money Graph consists of typed relationships.

Examples:

```text
ORDER_HAS_PAYMENT
PAYMENT_HAS_EVENT
PAYMENT_HAS_REFUND
PAYMENT_LINKED_TO_RECON_ENTRY
RECON_ENTRY_CONTRIBUTES_TO_SETTLEMENT
SETTLEMENT_HAS_UTR
SETTLEMENT_CANDIDATE_BANK_ENTRY
SETTLEMENT_PROVEN_BANK_ENTRY
DISPUTE_LINKED_TO_PAYMENT
ADJUSTMENT_AFFECTS_SETTLEMENT
```

Each edge contains evidence metadata:

```text
EvidenceEdge {
  from_id
  to_id
  relation
  state: CANDIDATE | PROVEN | REJECTED
  reason_codes[]
  evidence_ids[]
  rule_version
  created_at
}
```

No edge is “proven” because an embedding similarity is high.

---

## 5. Evidence hierarchy

Evidence strength must be explicit.

Suggested hierarchy for bank-side settlement matching:

### Tier A — authoritative exact evidence

- exact settlement UTR;
- exact settlement id in an authoritative source;
- exact provider-native transaction identifier where semantics establish identity.

### Tier B — deterministic consistency evidence

- exact amount;
- valid currency;
- timing inside an expected settlement window;
- unique candidate within an already constrained partition.

### Tier C — supporting semantic evidence

- bank narration tokens;
- merchant/account labels;
- source-specific prefixes;
- description similarity.

Tier C can reduce search space or rank candidates. It should not independently authorize a financial match.

---

## 6. Settlement composition proof

For each settlement `S`, let `R(S)` be all authoritative recon entries claiming `settlement_id = S.id`.

Each row is normalized into signed economic contribution `c(r)`.

Then:

```text
recon_net(S) = Σ c(r) for r ∈ R(S)
```

The precise conversion from Razorpay recon fields must be fixture-tested against the API semantics for `debit`, `credit`, `amount`, `fee` and `tax` rather than assumed from prose.

The proof must establish:

1. all rows are structurally valid;
2. duplicate economic rows have not been counted twice;
3. every row's sign is known;
4. all rows use the expected currency;
5. `recon_net(S)` equals the authoritative settlement amount under the defined formula;
6. any discrepancy is retained as an exact residual.

Possible state:

```text
COMPOSITION_PROVEN
COMPOSITION_MISMATCH
COMPOSITION_INCOMPLETE
COMPOSITION_CONTRADICTED
```

---

## 7. Bank receipt proof

Settlement processing and bank receipt are separate facts.

A bank proof must answer:

- has a valid bank-side candidate appeared?
- does UTR match?
- does the amount reconcile?
- is the candidate unique?
- is timing plausible?
- is the settlement expected to be split into multiple credits?

### Simple normal settlement

Strong proof:

```text
exact settlement UTR
AND exact net amount
AND one admissible bank candidate
```

### Split-credit settlement

Razorpay documents that some instant settlement paths can result in multiple IMPS credits.

For a supported split case:

```text
Σ bank_credit_i = expected bank receipt
```

with source-specific evidence binding those bank rows to the settlement/request.

For the currently supported **standard Razorpay settlement** contract, Gate 8 requires one unambiguous bank transaction for the settlement UTR. Genuine multi-credit Instant Settlements are a different provider topology (`setlod` parent + `setlodp` payout children) and must be modeled explicitly rather than inferred by grouping arbitrary bank rows.

---

## 8. Full reconciliation proof

The planned Gate 9 full reconciliation proof requires two independent **batch-safe** proofs:

```text
SettlementCompositionProof
AND
BankReceiptProof
```

Conceptual schema:

```json
{
  "settlement_id": "setl_123",
  "proof_state": "PROVEN_RECONCILED",
  "composition": {
    "entries": ["recon_1", "recon_2"],
    "gross_credit_paise": 18132000,
    "refund_debit_paise": 2150000,
    "fees_paise": 626271,
    "tax_paise": 112729,
    "adjustments_paise": 0,
    "expected_net_paise": 15243000,
    "settlement_amount_paise": 15243000,
    "residual_paise": 0
  },
  "bank_receipt": {
    "utr": "AXIS...",
    "bank_entry_ids": ["bank_8"],
    "observed_paise": 15243000,
    "residual_paise": 0
  },
  "evidence_ids": ["..."],
  "rule_versions": ["composition:v1", "bank-match:v1"],
  "proof_version": 3
}
```

The exact schema can change during implementation, but these semantics should remain.

---

## 9. Proof states

Use states that explain *why* a settlement is not yet reconciled.

Recommended top-level states:

```text
PROVEN_RECONCILED
WAITING_FOR_SETTLEMENT
WAITING_FOR_RECON
WAITING_FOR_BANK
COMPOSITION_MISMATCH
BANK_AMOUNT_MISMATCH
BANK_REFERENCE_CONTRADICTION
AMBIGUOUS_BANK_MATCH
SOURCE_INVALID
SOURCE_DRIFT
REOPENED
HUMAN_REVIEW
```

Do not compress all uncertainty into `FAILED`.

---

## 10. Residuals as first-class objects

A residual is exact unexplained value.

```text
Residual {
  residual_id
  scope_type
  scope_id
  amount_paise_signed
  created_from_proof_version
  candidate_explanations[]
  state
}
```

Examples:

- settlement composition residual;
- bank receipt residual;
- Instant Settlement payout residual (future provider-specific proof);
- unmatched merchant-order residual.

A residual of zero is necessary for some proof types but not sufficient if identity evidence is ambiguous.

This is important: two unrelated ₹10,000 transactions do not reconcile merely because the amount difference is zero.

---

## 11. Residual Solver

The solver operates only after exact/indexed matching has exhausted obvious paths.

### Goal

Find admissible explanation sets for an exact residual under bounded constraints.

Example:

```text
residual = -₹1,180
candidate movements:
  refund A = -₹1,000
  fee correction = -₹180
  adjustment B = +₹400
  duplicate C = -₹1,180
```

The solver can discover possible combinations but must not immediately convert them into proven edges.

### Candidate search strategy

1. partition by merchant/account/currency/time window;
2. filter by movement type permitted for the exception;
3. use exact amount/index lookups;
4. run bounded subset/constraint search only within the small candidate set;
5. return zero, one or multiple admissible explanations;
6. require authoritative evidence before promotion to `PROVEN` where necessary.

Potential implementation options:

- bounded dynamic programming for small residual candidate sets;
- CP-SAT / integer constraint solver as a stretch feature;
- deterministic branch-and-bound with strict node/time caps.

The solver should have a deterministic timeout/fallback path.

---

## 12. Temporal proof versions

Gate 9 implements immutable `ReconciliationProofVersion` records. A version binds the complete Gate 7 and Gate 8 proof fragments for one settlement without performing any new matching.

```text
ReconciliationProofVersion {
  proofv_id
  settlement_id
  version
  status
  composition_proof
  bank_proof
  source_envelope_ids[]
  scoped_input_sha256
  batch_compilation_sha256
  composition_ruleset_version
  bank_ruleset_version
  combiner_ruleset_version
  knowledge_cutoff
  generated_at
  prior_version_id?
  reopened
  reason_codes[]
}
```

`scoped_input_sha256` decides whether that settlement's authoritative financial truth changed. `batch_compilation_sha256` records the exact reproducible canonical batch context but does not, by itself, force a new version. Both source delivery order and non-authoritative same-amount diagnostics are excluded from version identity.

If late authoritative evidence arrives, ReFlow computes a new version.

Example:

```text
v1 10:00 PENDING_BANK_CREDIT
v2 11:12 PROVEN_RECONCILED
```

If a later authoritative correction invalidates a prior proof:

```text
v3 16:20 REOPENED -> COMPOSITION_MISMATCH
```

The system never rewrites v1/v2.

---

## 13. Two clocks

Every raw source record should distinguish:

```text
occurred_at   # source says event happened
received_at   # ReFlow learned about it
```

Where the source lacks a trustworthy event timestamp, mark provenance accordingly rather than fabricating certainty.

This enables:

- out-of-order replay tests;
- as-of queries;
- proof history;
- latency measurement;
- late-event exception analysis.

---

## 14. Conservation invariants

Examples of invariants to property-test:

### Payment state

- repeated identical events never duplicate value;
- event permutation does not change final state when semantics are equivalent;
- late captured evidence supersedes earlier failed observation where Razorpay permits the sequence;
- captured value cannot exceed valid modeled amount without an explicit exceptional event.

### Settlement composition

- each authoritative recon entity contributes at most once to one settlement proof version;
- currency cannot be silently converted;
- arithmetic is exact integer arithmetic;
- residual is reproducible from proof inputs.

### Bank proof

- a proven standard-settlement bank entry cannot be silently reused by another settlement;
- exact UTR with wrong amount is a non-reconciled residual (`BANK_AMOUNT_MISMATCH`), not success;
- same amount/time/narration without authoritative identity remains non-identity evidence;
- multi-credit Instant Settlement support requires explicit payout identities rather than a generic split relationship.

---

## 15. AI access to proofs

The AI layer receives proof objects and can call read-only tools such as:

```text
get_proof(settlement_id)
get_evidence(evidence_id)
list_residual_candidates(residual_id)
get_payment_timeline(payment_id)
get_source_health(source_id)
compare_proof_versions(settlement_id, v1, v2)
```

The model cannot call:

```text
mark_reconciled(...)
edit_amount(...)
change_utr(...)
attach_bank_row(...)
```

Instead it returns an investigation proposal with evidence references.

---

## 16. Why this architecture matters for the Buildathon

Razorpay asks for throughput, measured accuracy and honest exceptions.

A proof system makes all three defensible:

- **accuracy** can be scored against hidden ground-truth graph relationships;
- **throughput** can measure proof generation per second, not just CSV parsing;
- **exceptions** have exact missing/contradictory evidence instead of vague “low confidence” labels;
- **AI faithfulness** can be tested by verifying that every cited claim maps to proof/evidence objects.

The demo should visually inspect at least one proof and one residual case. That is much stronger evidence than showing a green KPI dashboard alone.
