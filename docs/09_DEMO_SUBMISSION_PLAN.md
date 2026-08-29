# ReFlow Demo and Submission Plan

## Story to communicate

The demo is not “look, AI can talk to a CSV.”

It is:

> A payment processor can tell you a settlement was processed, but a finance operator still has to prove which underlying movements produced that amount, whether the bank actually received it, and what to do when the sources disagree. ReFlow builds that proof deterministically and uses AI only where human investigation normally begins.

## Five-minute pitch structure

### 0:00–0:25 — Hook

Show one bank credit, for example ₹1,52,430. Ask:

**“Can you prove exactly why this number is correct?”**

Immediately expand it into dozens of payments/refunds/adjustments flowing into a settlement.

Message: matching one row to one row is easy; proving a grouped settlement across systems is the actual control problem.

### 0:25–0:55 — What ReFlow does

Show the overview with three numbers:

- proven reconciled amount;
- pending amount;
- exception amount.

Then state the boundary:

**“The LLM never decides whether money reconciles.”**

That should be one of the most memorable lines in the video.

### 0:55–1:50 — Clean many-to-one proof

Open a settlement containing many transactions.

Show:

- payments/refunds/adjustments;
- exact signed arithmetic;
- settlement ID and UTR;
- one bank credit;
- evidence graph;
- `PROVEN_RECONCILED` state.

Click an edge and expose the source evidence. This demonstrates that the product is not a black box.

### 1:50–2:35 — Hard failure scenario

Use a scenario that genuinely demonstrates production reasoning. Preferred:

**late payment state + duplicate/out-of-order event**

Sequence:

1. payment has a failure event;
2. later capture exists;
3. duplicate events are present;
4. events are shuffled;
5. ReFlow reconstructs one final captured payment;
6. settlement math stays exact.

Mention that Razorpay documents late failed→captured cases and webhook duplicate/order concerns.

Alternative/additional scenario if visually clearer:

**settlement.processed but bank credit not observed yet**

Show ReFlow choosing `PENDING_BANK_CREDIT` rather than falsely calling it reconciled or missing.

### 2:35–3:20 — Exception + bounded AI investigation

Open `BANK_AMOUNT_MISMATCH` or `SETTLEMENT_COMPOSITION_MISMATCH`.

Show deterministic evidence first:

- expected;
- observed;
- residual;
- reason codes;
- missing evidence.

Then click **Investigate**.

The model calls only read-only tools, finds a relevant refund/adjustment/missing component or concludes evidence is insufficient, and proposes a typed next step.

Show the policy gate:

`AI proposal → deterministic validator → resolve only if proof passes / otherwise review`

If possible, deliberately inject a hallucinated evidence ID into a test/replay and show it being rejected. This is stronger than saying “we use guardrails.”

### 3:20–4:15 — Evaluation

Switch to the Evaluation page.

Do not narrate ten metrics. Emphasize four:

1. size/composition of the held-out batch;
2. settlement/edge correctness;
3. silent false auto-match rate;
4. unresolved exception rate and what those exceptions are.

Then show throughput.

If the AI arm improves exception resolution, show the delta against deterministic core. If it does not, say so and explain what AI still contributes. Never force a fake “AI wins” result.

### 4:15–4:45 — What broke

Show one real development failure from `FAILURE_LOG.md`.

Good candidates:

- evaluator accidentally rewarded a false match;
- generated ground truth violated its own settlement equation;
- event-order assumption caused a late capture to disappear;
- ambiguous same-amount settlements cross-linked;
- LLM output contained unsupported numeric claim and validator rejected it.

Show failing regression → fix → passing test.

This communicates engineering maturity much better than claiming everything worked immediately.

### 4:45–5:00 — Close

Return to the settlement proof and say the result in one sentence:

**“ReFlow turns reconciliation from a best-effort match into an auditable proof: every rupee is either explained, pending for a specific reason, or explicitly unresolved.”**

End on the actual final benchmark numbers once measured.

## Visual priorities

The demo should have three signature screens.

### 1. Money Flow / Settlement Proof

A clean visual chain:

`Orders → Payments → Refunds/Adjustments → Settlement → Bank`

Avoid a generic node graph with dozens of crossing lines. Use grouped columns/lanes and animate only the selected settlement's flow.

### 2. Exception Investigator

Split view:

- left: deterministic evidence and arithmetic;
- right: investigation timeline/tool calls/proposed next step.

The AI explanation is subordinate to evidence, not the hero element.

### 3. Evaluation Lab

Show metrics plus a scenario matrix. Let the reviewer filter to anomalies and inspect failures.

## README visual assets

Final README should include:

- hero product screenshot/GIF;
- one architecture image;
- one settlement-proof screenshot;
- one benchmark chart;
- concise reproducibility command.

Do not fill README with badges before the product has meaningful tests/results.

## Architecture slide

Use six boxes maximum:

```text
Sources
  ↓
Immutable Journal
  ↓
Payment State + Evidence Graph
  ↓
Settlement Proof + Bank Match
  ↓
Typed Exceptions
  ↓
Bounded AI Investigator + Validator
```

Add Eval/Audit as a horizontal layer underneath.

## Questions we should expect from a Razorpay panel

### “Why AI? Couldn't deterministic code do this?”

Correct answer: the financial matching core **should** be deterministic when the rules/evidence are sufficient. AI is useful in the long tail of exception investigation: deciding which evidence/tool to inspect, interpreting incomplete cross-system context and presenting a bounded next step. We benchmark the AI layer separately so we can prove whether it adds value.

### “Is your data real?”

No. The official track asks for synthetic data. The corpus is synthetic and deliberately adversarial; its generator and probabilities/rules are public. Real Razorpay Test Mode objects/events are used only where available to validate adapter semantics. We never imply synthetic settlements are production data.

### “Why not just use Razorpay's reconciliation reports?”

Those reports are one source in the loop. ReFlow's job is to verify grouped money movement across merchant, gateway/settlement and bank sources and investigate contradictions. Razorpay itself highlights reconciliation as a manual operational problem even with reports available.

### “Why not let the LLM match rows?”

Because a plausible wrong match is worse than an explicit exception. Stable IDs, UTRs and exact arithmetic are stronger evidence than language-model similarity. AI operates after deterministic controls have identified uncertainty.

### “What happens if the model is down?”

The batch still reconciles deterministically and unresolved cases remain explicit. Only optional investigation is unavailable.

### “What is your biggest limitation?”

Answer whatever the final system genuinely cannot do. Likely candidates: synthetic bank/settlement corpus, limited bank-format diversity, no accounting-system writeback, or incomplete Route/transfer support. Do not hide it.

### “What would you build next inside Razorpay?”

High-value extensions:

- first-party access to real merchant reconciliation corpora for learned exception ranking;
- Tally/QuickBooks connectors;
- bank connectors instead of uploads;
- controlled accounting journal proposals;
- Route/linked-account reconciliation;
- continuous evals on de-identified real exception classes;
- model routing based on measured per-exception performance.

## Submission checklist

Before submission:

- repo public;
- final branch clean;
- README numbers generated from final artifacts;
- fresh-clone setup verified;
- no API keys/secrets/history leaks;
- demo deployment public and stable;
- offline synthetic demo works if external services fail;
- 5-minute video publicly accessible;
- architecture readable on mobile/laptop;
- `FAILURE_LOG.md` honest and current;
- `EVALUATION.md` includes denominator and exceptions;
- license selected;
- source attribution is clear;
- AI-generated assistance is not misrepresented as manually authored work if the application asks about it.

## Quality bar

The submission should leave a reviewer with four beliefs:

1. this builder understands payment-system correctness beyond API happy paths;
2. this builder knows where AI is useful and where it should be structurally constrained;
3. this builder knows how to create an eval whose numbers can be challenged and reproduced;
4. this looks like a small product that could plausibly become a real Razorpay finance-control surface, not a weekend chatbot.
