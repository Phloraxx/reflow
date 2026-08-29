# ReFlow Failure Log

## Why this file exists

The Razorpay AI Builder Internship submission form explicitly asks:

> **Build Challenges & Technical Obstacles** — What issues did you face while building, and how did you solve them?

This log records genuine implementation/evaluation failures as they occur.

It is **not** a marketing page. Do not invent failures, hide regressions, or rewrite history after a fix.

Research-stage strategic decisions and the Track 03 → Track 04 pivot are documented separately in `docs/03_COMPETITIVE_ANALYSIS.md`.

---

## Rules

For every meaningful failure:

1. record it before or while fixing it;
2. preserve the test/fixture that exposed it;
3. state whether the bug was in the engine, generator, benchmark, model, connector, UI or assumption;
4. add a regression test where technically appropriate;
5. record benchmark impact if the fix changes published metrics;
6. retain embarrassing findings if they are true;
7. do not call a limitation “fixed” until the reproducer passes.

---

## Entry template

```markdown
## F-XXXX — Short title

**Date:** YYYY-MM-DD  
**Area:** engine | ingestion | simulator | evaluation | agent | UI | performance | infrastructure  
**Severity:** low | medium | high | safety-critical

### Symptom

What happened?

### Initial assumption

What did we believe before the failure?

### Reproducer

Exact test, fixture, seed or command that exposes it.

### Root cause

What was actually wrong?

### Why it matters

Financial/safety/evaluation/product consequence.

### Fix

What changed?

### Regression protection

Test/invariant/monitor added.

### Metric impact

What numbers changed, if any?

### Remaining limitation

What is still not solved?
```

---

# Active failures

None yet. Implementation has not begun.

---

# Resolved failures

None yet. Implementation has not begun.

---

# Failure categories we expect to attack deliberately

These are **test targets, not claimed failures**:

- duplicate webhook double counting;
- out-of-order reducer errors;
- `payment.failed → payment.captured` mishandling;
- settlement debit/credit sign mistakes;
- rupee/paise conversion mistakes;
- repeated recon row counting;
- same-amount bank ambiguity;
- exact UTR with wrong amount;
- split bank-credit handling;
- late source evidence reopening a proof;
- schema drift;
- AI adapter inferring the wrong amount unit;
- AI adapter inferring the wrong debit/credit sign;
- prompt-like text inside bank narration;
- hallucinated evidence IDs;
- AI provider outage;
- unfair baseline construction;
- hidden-truth leakage into candidate pipeline;
- benchmark scorer bug;
- residual solver combinatorial explosion;
- high-memory batch behaviour;
- crash/restart idempotency.

When one becomes a real observed failure, create a numbered entry above with evidence.
