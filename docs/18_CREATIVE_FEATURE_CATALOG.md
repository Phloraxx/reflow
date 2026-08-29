# Creative Feature Catalog

## Purpose

ReFlow needs to feel novel, but novelty is not the same as feature count.

This document records creative product/system ideas and ranks them so that strong ideas do not become uncontrolled scope creep.

Scoring: 1 (low) → 5 (high).

| Idea | Merchant value | Novelty | Technical signal | Demo value | Build risk | Priority |
|---|---:|---:|---:|---:|---:|---|
| Reconciliation Proof | 5 | 5 | 5 | 5 | 2 | **P0** |
| Money Graph | 5 | 4 | 5 | 5 | 3 | **P0** |
| Source Adapter Compiler | 5 | 5 | 5 | 5 | 3 | **P0** |
| Temporal proof timeline | 4 | 5 | 5 | 5 | 3 | **P1** |
| Residual-first solver | 5 | 5 | 5 | 5 | 4 | **P1** |
| Financial Diff / “Git for money” | 4 | 5 | 4 | 5 | 2 | **P1** |
| Close Readiness Certificate | 4 | 4 | 4 | 4 | 2 | **P1** |
| Schema Drift Watchdog | 5 | 4 | 5 | 4 | 3 | **P1** |
| Exception Fingerprints | 5 | 5 | 4 | 5 | 3 | **P1/P2** |
| Recon Chaos Lab | 4 | 5 | 5 | 5 | 3 | **P1** |
| Source Trust Map | 4 | 4 | 3 | 5 | 2 | P2 |
| Counterfactual close / cash view | 4 | 4 | 4 | 4 | 3 | P2 |
| Tamper-evident proof chain | 3 | 4 | 4 | 3 | 3 | P2 |
| Multi-gateway universal adapter | 5 | 3 | 4 | 4 | 5 | future |

---

# 1. Reconciliation Proof — P0

## Idea

Replace a binary `MATCHED` badge with a proof packet that contains:

- component movements;
- exact arithmetic;
- evidence relationships;
- settlement identity;
- bank receipt evidence;
- residual;
- rule versions;
- provenance.

## Why it is creative

Most reconciliation UX is optimized around lists and statuses. A proof object turns reconciliation into something independently verifiable and inspectable.

## Demo moment

Click `PROVEN` and the settlement visually unfolds into the exact movements and equation that created the bank amount.

## Build rule

Must be machine-readable first, beautiful second.

---

# 2. Money Graph — P0

## Idea

Visualize money as connected economic movements rather than matching rows.

```text
order
  → payment
      → settlement contribution
      → refund
      → dispute
settlement
  → UTR
      → bank credit
```

## Why it matters

Many-to-one and cross-period relationships become natural rather than special cases.

## Demo moment

Select one bank credit and trace backward to every payment/refund/fee that explains it.

---

# 3. Source Adapter Compiler — P0

## Idea

Give ReFlow a previously unseen export. AI proposes a declarative mapping. Deterministic compilation and tests prove whether it is safe.

## Why it is better than “AI parses CSV”

The AI does semantic work once. Reconciliation never depends on probabilistic row-by-row model output.

## Demo moment

Upload a file with deliberately weird headings such as:

```text
Txn Ref | Amt Cr | Val Dt | Details
```

Then show:

```text
AI proposal
→ unit/sign checks
→ compiled adapter
→ deterministic parse
```

For extra signal, include one unsafe proposal/fixture that the compiler rejects.

---

# 4. Temporal Proof Timeline — P1

## Idea

Show the financial truth as it evolved.

```text
09:01 PAYMENT_FAILED observed
09:02 proof: waiting
09:04 PAYMENT_CAPTURED arrives late
09:04 payment state corrected
10:31 settlement processed
10:31 proof: waiting for bank
11:12 bank UTR appears
11:12 PROVEN
```

## Why it is novel

It makes asynchronous payment semantics understandable without overwriting history.

## Demo moment

Scrub a timeline and watch the proof state change as evidence arrives.

---

# 5. Residual-First Solver — P1

## Idea

When amounts do not close, show the exact unexplained residual and search for bounded explanation candidates.

Instead of:

> mismatch

show:

> `₹1,180` remains unexplained. Candidate explanation set: missing refund ₹1,000 + fee correction ₹180.

## Safety

Candidate explanation ≠ proof.

No candidate becomes truth without sufficient evidence.

---

# 6. Financial Diff — “Git for money” — P1

## Idea

A first-class `diff` between proof versions.

Example:

```diff
 Settlement setl_A

 state
- WAITING_FOR_BANK
+ PROVEN_RECONCILED

 bank evidence
+ bank_184: ₹152,430.00
+ UTR: AXIS...

 residual
- ₹152,430.00 missing
+ ₹0.00
```

Or:

```diff
 proof v4 → v5
+ refund rfnd_91 -₹2,499
- expected settlement ₹44,381
+ expected settlement ₹41,882
```

## Why it matters

Finance operators constantly ask “what changed?” A version diff answers directly.

## Implementation

Proof objects are immutable, so structural diff is straightforward after versioning exists.

---

# 7. Close Readiness Certificate — P1

## Idea

At the end of a batch/day, ReFlow emits a deterministic **Close Artifact**.

Not a blockchain certificate. A normal machine-readable signed/hashed report.

Example:

```text
Close: 2026-08-29 / Merchant M1

Sources
✓ merchant ledger complete through 23:59
✓ Razorpay recon complete through 23:59
✓ bank feed complete through 23:59

Financial state
₹9,482,103 proven
₹18,220 waiting for bank SLA
₹4,310 unresolved
3 contradictions

Status: NOT READY TO FINALIZE
Reason: unresolved contradicted value > configured threshold
```

## Why useful

Reconciliation becomes an explicit close gate rather than a pile of green rows.

---

# 8. Schema Drift Watchdog — P1

Already specified in the connector compiler.

Creative UX:

```diff
 BANK HDFC EXPORT v7 → v8

- Settlement UTR
+ Bank Ref No

 Date format
- DD/MM/YYYY
+ DD-MMM-YY

 New column
+ Branch
```

Then show whether the existing adapter remains safe.

---

# 9. Exception Fingerprints — P1/P2

## Idea

Group cases by operational root signature.

Example:

```text
Cluster: SOURCE_DRIFT/HDFC/V8
1,842 cases
₹3.7 Cr affected
started 14:03

98.7% share:
  missing UTR after column rename
```

## Why it matters

At enterprise scale, the job is not solving case #1,842; it is recognizing there is one broken pipeline.

## AI role

AI can write a human summary after deterministic clustering.

---

# 10. Recon Chaos Lab — P1

## Idea

Turn the evaluation harness into an interactive product/demo feature.

Controls:

```text
[✓] duplicate webhooks 10%
[✓] reorder events
[✓] late captures 5%
[✓] drop UTRs 3%
[✓] same-amount collisions
[✓] schema drift halfway through
[ ] AI outage
[ ] bank feed delayed 2h

Records: 100,000
Seed: 94217
```

Click **Run**.

Compare:

```text
Naive 1:1
Grouped baseline
Fuzzy baseline
ReFlow Core
ReFlow + AI
```

## Why it is powerful

A judge can actively try to break the product instead of watching a canned demo.

It converts evaluation from a README table into an interactive engineering artifact.

---

# 11. Source Trust Map — P2

## Idea

Show which source feeds are strong or degraded without turning it into an opaque overall confidence score.

```text
Merchant ERP      healthy
Razorpay events   healthy / lag 1.2s
Recon API         complete through 18:00
Bank HDFC         delayed 42m
Bank ICICI        schema drift
AI provider       unavailable
```

Click a source to see:

- schema version;
- parse error rate;
- identifier completeness;
- freshness;
- last drift;
- affected proofs.

---

# 12. Counterfactual close / cash view — P2

## Idea

Without changing truth, answer:

> “If all currently processed settlements arrive within SLA, what will available cash be?”

Use deterministic pending settlement amounts and evidence state.

Important distinction:

```text
PROVEN CASH
EXPECTED WITHIN SLA
UNRESOLVED / DO NOT FORECAST
```

This lightly touches Razorpay's “cash position” Track 04 language without turning ReFlow into a forecasting project.

---

# 13. Tamper-evident proof chain — P2

## Idea

Hash canonical evidence/proof versions so exported audit packets can be checked for modification.

This is **not blockchain** and should never be marketed as decentralized finance.

Potential structure:

```text
proof_hash = SHA256(
  canonical_input_hashes +
  rule_versions +
  proof_payload
)
```

Useful for demo/audit signal only after core correctness is complete.

---

# 14. Human questions the product should answer instantly

The UI/agent should be designed around questions like:

- Why is this settlement ₹300 short?
- Which payments created this ₹1.52L bank credit?
- What changed since this settlement was marked waiting?
- Which source is blocking today's close?
- Are these 800 exceptions actually one incident?
- Did this refund affect the original settlement or a later one?
- Why didn't ReFlow auto-match these same-amount rows?
- What evidence would be required to prove this case?
- Which proofs were reopened by yesterday's backfill?
- How much money is proven vs merely expected?

If a proposed feature does not improve one of these questions, it probably does not belong in the Buildathon version.

---

# 15. Visual product language

Avoid the aesthetics of:

- generic SaaS admin tables;
- neon “AI” gradients everywhere;
- chatbot-first layouts;
- dozens of cards with no hierarchy.

Prefer a visual language inspired by:

- an instrument panel;
- a ledger;
- a debugger;
- a version-control diff;
- an evidence case file.

Core visual objects:

- money-flow rail;
- proof equation;
- evidence badges;
- residual marker;
- source-health strip;
- temporal proof diff;
- exception cluster.

The product should feel like **developer tooling for finance truth**, not a conventional accounting dashboard.

---

# 16. Final selection rule

Before implementing a creative feature, ask:

1. Does it directly improve Track 04 evidence?
2. Does it demonstrate something competitors are unlikely to show?
3. Does it help prove correctness rather than hide uncertainty?
4. Can it be demonstrated in under 20 seconds?
5. Can we evaluate it?
6. Does it preserve AI boundaries?
7. Does it displace a more important P0 task?

If #7 is yes, defer it.
