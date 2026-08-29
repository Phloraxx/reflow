# ReFlow Novel Product Thesis

## Thesis

ReFlow should not be positioned as “an AI that decides whether transactions match.” That is neither novel enough nor safe enough.

ReFlow should be positioned as a **financial truth compiler**.

It takes messy, heterogeneous financial evidence and compiles it into:

1. a canonical event journal;
2. a temporal Money Graph;
3. deterministic reconciliation proofs;
4. explicit unresolved residuals;
5. bounded AI-assisted investigations;
6. versioned, auditable close states.

The core product promise is:

> **Every rupee should have a path, a proof, or an exception. Never a guess.**

---

## 1. Why “AI makes decisions” is not enough

The public Buildathon field already contains several implementations where an LLM proposes an action and deterministic rules approve or reject it. That pattern is useful but increasingly common.

Razorpay's own Agent Studio also already emphasizes agents that reason over verified data and operate within guardrails.

Therefore ReFlow needs a novel systems primitive, not merely a better prompt.

The novel primitives proposed here are:

- **Money Graph**
- **Reconciliation Proof**
- **Residual Solver**
- **Temporal Truth / versioned close**
- **Source Adapter Compiler**
- **Exception Fingerprints**
- **Proof-carrying AI investigation**

These are meaningful even with the LLM turned off.

---

## 2. ReFlow as a “finance compiler”

A compiler takes messy human-authored source code and turns it into a strict intermediate representation that can be validated and executed.

ReFlow applies the same idea to finance operations:

```text
Messy financial sources
        │
        ▼
Semantic adapter / parser
        │
        ▼
Canonical Financial IR
        │
        ▼
Temporal reducer
        │
        ▼
Money Graph
        │
        ▼
Invariant + equation engine
        │
        ├── PROOF
        │
        └── RESIDUAL / EXCEPTION
```

The “IR” is a canonical, typed representation of orders, payment events, refunds, settlement components and bank movements.

This framing is useful because it separates:

- syntax/format problems;
- semantic mapping problems;
- financial truth problems.

An LLM may help with the first two. It must not own the third.

---

## 3. Novel primitive #1 — Money Graph

Traditional reconciliation tends to think in rows.

ReFlow thinks in **economic movements and evidence relationships**.

Example:

```text
Order O1 ₹1,000
   │
   └─ Payment P1 captured ₹1,000
         │
         ├─ fee ₹20
         ├─ tax ₹3.60
         └─ contributes ₹976.40
                  │
                  ▼
             Settlement S7
                  │
                  └─ UTR U7
                        │
                        ▼
                 Bank Credit B7
```

Refunds, disputes, transfers and adjustments become new nodes/edges rather than destructive mutations.

Benefits:

- many-to-one settlement decomposition is natural;
- cross-period movements remain traceable;
- evidence can be weak, candidate, rejected or proven;
- the UI can explain *why* a match exists;
- graph fragments can be re-evaluated when late evidence appears.

No graph database is required. The graph is a domain abstraction.

---

## 4. Novel primitive #2 — Reconciliation Proofs

A reconciliation result should be a **proof object**, not a boolean.

For a settlement, the proof must answer:

- Which source rows were included?
- Why do they belong to this settlement?
- What arithmetic explains the net amount?
- Which fees/tax/refunds/adjustments changed the amount?
- What UTR links it to the bank side?
- Which bank rows prove receipt?
- What source/version produced every fact?
- Are there any residuals?

A proof can be independently rechecked without an LLM.

Conceptually:

```text
Settlement S7
Expected Net = Σ credits - Σ debits - fees - tax ± adjustments
Expected Net = ₹152,430.00
Settlement Entity = ₹152,430.00
Bank Evidence = ₹152,430.00
UTR = MATCH
Residual = ₹0.00

=> PROVEN_RECONCILED
```

This creates a much stronger demo than a table saying `MATCHED`.

---

## 5. Novel primitive #3 — Residual-first reconciliation

Most systems ask:

> Which rows match?

ReFlow should also ask:

> **What amount is still unexplained, and what is the smallest plausible evidence set that can explain it?**

This leads to a Residual Solver.

Example:

```text
Settlement expected: ₹86,427.00
Bank observed:       ₹86,127.00
Residual:               ₹300.00
```

The system then searches deterministic candidate explanations:

- missing fee row;
- omitted refund;
- adjustment;
- duplicate contribution;
- split bank credit;
- wrong bank candidate;
- missing source row.

The solver should rank **explanations**, not silently mutate the settlement.

At low volume it may perform a more exhaustive constrained search. At high volume it first partitions the candidate space and only invokes expensive solving on local residual groups.

This is substantially more useful than generic fuzzy matching.

---

## 6. Novel primitive #4 — Temporal Truth

Financial systems have two clocks:

- **occurred time** — when the economic event happened;
- **observed time** — when ReFlow learned about it.

This matters because:

- webhooks arrive out of order;
- payments can move from apparently failed to captured;
- bank credits can appear after settlement processing;
- refunds and disputes arrive later;
- source corrections can change what was known at a prior close.

ReFlow should support a bitemporal-style question:

> “What did we believe at 09:00, and what do we know now?”

Instead of overwriting yesterday's result, a late event produces a new proof version.

Example:

```text
09:00  S7 = WAITING_FOR_BANK
11:12  bank credit arrives
11:12  S7 proof v2 = PROVEN_RECONCILED
```

This is both operationally realistic and visually compelling.

---

## 7. Novel primitive #5 — Source Adapter Compiler

Messy data is one of the main reasons reconciliation becomes bespoke services work.

Rather than hard-code each CSV format, ReFlow should support an AI-assisted adapter compilation flow:

```text
Unknown file
  ↓
LLM proposes semantic mapping
  ↓
Typed Adapter Spec
  ↓
Deterministic compiler
  ↓
Validation against sample rows
  ↓
Financial invariants
  ↓
Human approval if needed
  ↓
Versioned deterministic adapter
```

Example input headers:

```text
Txn Ref | Amt Cr | Value Dt | Narration
```

AI might infer:

```text
transaction_reference ← Txn Ref
credit_paise          ← parse_rupees(Amt Cr)
occurred_at           ← parse_date(Value Dt)
narration             ← Narration
```

But the mapping is **not activated because the model sounded confident**.

The compiler must verify:

- amounts parse consistently;
- no sign ambiguity;
- dates parse safely;
- IDs have expected uniqueness/cardinality;
- required fields exist;
- totals reconcile to source control totals where available;
- sample rows satisfy range/unit checks.

Once approved, the LLM leaves the runtime path. Every future row uses deterministic code.

This is meaningful AI use that actually addresses messy financial operations.

---

## 8. Novel primitive #6 — Schema drift watchdog

A connector can work for months and then fail because a bank changes:

- a header;
- a date format;
- a narration pattern;
- sign conventions;
- blank/null behaviour;
- a column's meaning.

Silent drift is dangerous.

ReFlow should fingerprint each source schema and detect changes before reconciliation.

On drift:

1. quarantine the new batch;
2. show exactly what changed;
3. ask the Source Adapter Synthesizer for a proposed migration;
4. replay old and new fixtures against the new adapter;
5. only activate after deterministic tests pass.

This turns “AI connector generation” into a safe lifecycle rather than a one-off demo trick.

---

## 9. Novel primitive #7 — Exception Fingerprints

At high scale, individual exception handling is not enough.

If 2,000 exceptions all share:

- the same bank;
- the same hour;
- the same narration change;
- the same ₹2.36 discrepancy;
- the same missing fee pattern;

they are probably one systemic incident, not 2,000 unrelated problems.

ReFlow should create an **exception fingerprint** from deterministic features and cluster recurring exception families.

Possible output:

```text
INCIDENT CLUSTER #14
1,842 affected settlements
₹3.7 Cr affected value
First seen 14:03
Common feature: BANK_X narration format changed
Likely root cause: parser/schema drift
```

The AI investigator can summarize the cluster, but detection can be deterministic/statistical.

This is where high-volume operations become dramatically better than simply scaling a row matcher.

---

## 10. Novel primitive #8 — Reconciliation confidence as evidence state, not a magic score

Avoid an opaque `confidence = 0.93` number.

Use explicit evidence tiers:

```text
PROVEN
  exact authoritative identifiers + exact financial invariants

SUPPORTED
  strong but non-authoritative evidence; safe for candidate display

AMBIGUOUS
  more than one admissible explanation

CONTRADICTED
  authoritative sources disagree

INSUFFICIENT
  required evidence has not arrived
```

The UI can display what evidence would promote a case to the next state.

This is much more useful to finance teams than a generic probability.

---

## 11. Novel primitive #9 — Close is reversible, history is not

Traditional month-end workflows often treat close as a final checkbox.

For asynchronous payments, a more honest model is:

- **provisional close** — all currently available evidence reconciles;
- **finalized close** — all required source windows have elapsed and evidence is complete;
- **reopened** — new authoritative evidence invalidated a previous proof.

ReFlow should preserve prior proof versions rather than rewrite them.

This makes late authorizations, delayed credits and retroactive adjustments understandable instead of mysterious.

---

## 12. Novel primitive #10 — Proof-carrying AI

The AI investigator must not return:

> “I think the bank settlement is probably correct.”

It must return something structurally closer to:

```json
{
  "hypothesis": "missing_refund_recon_row",
  "evidence_ids": ["ev_17", "rfnd_9", "setl_2"],
  "missing_evidence": ["settlement_recon_refresh"],
  "proposed_next_step": "REFETCH_RECON",
  "cannot_resolve_without": ["authoritative_recon_row"]
}
```

The proposal is then checked against the graph and proof engine.

The AI therefore carries evidence references with every claim. If it cannot cite evidence, the claim cannot change financial state.

---

## 13. Product experience

The UI should be organized around **money questions**, not database tables.

Home:

```text
₹12.84 Cr observed
₹12.79 Cr proven
₹4.8 L awaiting evidence
₹37,400 contradicted
18 exception families
```

Click a settlement:

```text
₹152,430.00
PROVEN

317 payments          +₹181,320.00
12 refunds             -₹21,500.00
fees                   -₹6,262.71
tax                    -₹1,127.29
adjustments                 ₹0.00
--------------------------------
expected settlement   ₹152,430.00
Razorpay settlement   ₹152,430.00
bank credit           ₹152,430.00
UTR                     matched
residual                    ₹0.00
```

Click an exception:

```text
₹300 unexplained

Known:
✓ settlement composition proves ₹86,427
✓ exact UTR found
✕ bank credit is ₹86,127

Possible explanations:
1. bank-side deduction not represented in source data
2. wrong bank record despite UTR collision [contradicted by uniqueness]
3. settlement source correction pending

Needed evidence:
→ refreshed settlement/recon source
```

This is a fundamentally different experience from “AI chat with your settlements.”

---

## 14. Why this is well aligned with Razorpay

Razorpay's stated current direction emphasizes:

- verified first-party data;
- bounded AI;
- independent validation;
- audit trails;
- system-level evaluations;
- reconciliation as an important post-payment workflow.

ReFlow follows those principles but contributes a distinctive systems idea:

> **financial answers are compiled into proofs before they are narrated by AI.**

That should be the core story in the repo, architecture review and five-minute pitch.
