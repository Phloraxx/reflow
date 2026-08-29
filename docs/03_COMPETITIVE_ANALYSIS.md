# Competitive Analysis and Track Decision

> Point-in-time research conducted 2026-08-29 against publicly discoverable GitHub repositories. This document is for product positioning, not for copying competitors.

## Decision

**Build for Track 04 — AI Finance Controller.**

Track 03 (AI Revenue Recovery) was the initial direction, because it aligns strongly with our payment-system experience. The decision changed after inspecting the actual public field and Razorpay's own 2026 product launches.

## Why we moved away from Track 03

Track 03 is visibly crowded on public GitHub. Several projects already implement variants of:

`failure detection → LLM/heuristic decision → deterministic guardrail → retry/payment-link/message → synthetic evaluation`

Two particularly strong public examples found during research were:

- `dheraingoud/RRI-Razorpay` — expected-value recovery logic, deterministic guardrails, Razorpay test-mode integration and Monte Carlo evaluation.
- `Ovais-Maker/razorpay-buildathon-recoup` — common-random-number benchmark, multiple baselines, incremental rather than gross recovery measurement, stopping rules, deterministic compliance guardrails, hash-chained audit ledger, and an unusually honest live-model comparison where the heuristic beat the LLM.

Those projects materially raise the novelty threshold for a generic revenue-recovery agent.

There is a second issue: Razorpay itself already ships/announces adjacent capabilities. Its Agentic Platform includes Active Revenue Recovery; Agent Studio includes recovery agents; Razorpay has also offered Failed Payment Recovery that sends payment links after failures. A submission that merely detects a failure and produces a payment link risks demonstrating an inferior duplicate of Razorpay's existing direction.

Relevant Razorpay sources:

- https://razorpay.com/blog/razorpay-agentic-platform/
- https://razorpay.com/blog/razorpay-agent-studio-principles-guardrails-and-merchant-control/
- https://razorpay.com/blog/razorpay-failed-payment-recovery/

Track 03 remains a good challenge. It is simply no longer the highest-probability choice for **this** submission.

## Why Track 04 is better for ReFlow

Track 04 explicitly rewards multi-source reconciliation, measured accuracy, throughput and honest unresolved exceptions. That maps directly to the strongest engineering experience available to this project: payment state machines, idempotent event ingestion, evidence correlation, audit records, late events and reconciliation logic.

The public Track 04 field is smaller in obvious GitHub search results than Track 03. More importantly, the strongest Finance Controller submission inspected exposes a concrete gap we can attack instead of competing feature-for-feature.

### Strong public benchmark: `SuryaSK-dev/razorpay-ai-finance-controller`

This is a serious submission, not a straw man. It includes:

- deterministic reconciliation;
- a bounded read-only AI layer;
- synthetic adversarial data;
- tax validation;
- hundreds of tests;
- explicit exception states;
- failure logs and honest limitations.

The useful part of its own limitations section is that its settlement model is **1:1**: one PG transaction to one bank credit. It explicitly notes that real settlements are batched and that decomposing them is the harder reconciliation problem. It also notes that its invented bank-reference format makes matching easier and that its fuzzy matching tier is not exercised end to end.

That gap is our opportunity.

## ReFlow's differentiation

ReFlow will not try to win by having more dashboard widgets or a larger prompt. It will solve a structurally harder reconciliation problem:

### 1. Many-to-one settlement decomposition

A settlement contains multiple financial movements. ReFlow reconstructs the expected net settlement from transaction-level payment/refund/adjustment entries and connects that grouped result to one bank credit.

### 2. Temporal/event correctness

Before reconciliation, ReFlow must reconstruct reliable payment state from a journal that may contain duplicate events, out-of-order events and late transitions such as `failed → captured`.

### 3. Evidence graph, not opaque match score

Every decision stores the exact evidence edges that support it. A reviewer can answer:

- which merchant order generated this payment?
- which payment/refund/adjustment contributed to this settlement?
- how did the amount reconcile mathematically?
- which UTR supports the bank-credit link?
- what evidence is missing?
- why did the system refuse to auto-match?

### 4. Agent closes the exception-investigation loop

The AI layer receives a typed exception and can call only pre-approved read-only tools. It can gather missing context, identify the most likely root cause, explain the discrepancy and produce a proposed resolution. It cannot change source records or declare a match.

For low-risk deterministic resolutions, the controller may automatically resolve after re-running all invariants. For ambiguous or book-changing actions, it must route to human review.

### 5. Silent false matches are treated as the catastrophic metric

A reconciliation engine that reports 99% match rate by confidently attaching the wrong transaction is worse than one that reports 90% and escalates the ambiguous 10%.

Therefore we optimize in this order:

1. zero/near-zero silent false auto-matches;
2. exact money conservation;
3. high correct auto-resolution;
4. high exception-classification quality;
5. throughput;
6. UI convenience.

## Competitive anti-patterns to avoid

- Inventing success probabilities and then claiming business uplift from the same assumptions.
- Giving the model hidden ground truth.
- Comparing an intelligent agent to an artificially weak baseline.
- Calling self-generated labels an independent real-world validation set.
- Reporting only records that matched.
- Building a chat UI before the deterministic finance core is correct.
- Claiming tax/legal correctness beyond the exact rules and assumptions encoded.
- Using `float` for money.
- Treating a test-mode mock as if it were a production settlement.
- Copying public competitor architecture, wording, datasets or code.

## Strategic positioning sentence

> **ReFlow does not ask an LLM whether the books reconcile. It builds a proof of where every rupee went, then gives AI the unresolved evidence to investigate.**

That is the sentence every architecture and demo choice should reinforce.
