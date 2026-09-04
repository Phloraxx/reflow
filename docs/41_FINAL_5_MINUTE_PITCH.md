# ReFlow — Final Five-Minute Pitch and Recording Runbook

## What the video must prove

Do not make this feel like a presentation about a reconciliation system. Show the system doing reconciliation.

The judge should remember four things:

1. ReFlow can process a meaningful batch, not one hand-picked transaction.
2. It only auto-reconciles what the evidence can prove.
3. DeepSeek helps with messy finance operations, but cannot change reconciliation truth.
4. The result is scored against hidden ground truth after the run.

Target duration: **4:45–4:58**.

Record the product full-screen. Avoid terminal footage unless something genuinely cannot be shown in the UI.

## Before recording

Run `~/Developer/ReFlow Demo.command` and open:

`http://127.0.0.1:8000/demo?scope=scope_demo`

Confirm the page starts with no generated batch and DeepSeek shows as configured.

For the main take use:

- Settlements: **500**
- Profile: **Adversarial close**
- World seed: **402**
- Observation seed: **1402**

Expected generated workload on the current build:

- **500 settlements**
- **60,227 observed source records**
- dataset SHA-256 beginning `1753fd1d0cdc…`
- truth commitment beginning `508e7ee6ab2e…`

The exact run time will vary by machine. Do not rehearse a fake duration.

Keep browser zoom around 100–110% and close unrelated tabs, bookmarks and extensions that could expose private information.

Razorpay Test Mode credentials are configured locally. The current sandbox authenticates successfully but contains no test payments, settlements or recon rows. That is acceptable for the connector check: the UI now shows all three endpoints as reachable and labels the sandbox as empty instead of treating zero rows as a failure.

Optional before the final take: complete one Razorpay mock Checkout in Test Mode if you want a genuine test payment count above zero. Do not delay the scored demo waiting for sandbox settlement/recon rows.

## 0:00–0:20 — Start with the problem

### Screen

Start on the clean Live Run page before generating anything.

### Say

> Razorpay can tell a merchant that a settlement was processed. Finance still has to answer a different question: which payments and refunds produced that settlement, and did that money actually reach the bank?

> I built ReFlow to close that loop without turning approximate matches into accounting facts.

Do not introduce architecture yet. Do not say a slogan.

## 0:20–0:50 — Generate the workload live

### Screen

Select the 500-settlement adversarial profile and click **Generate batch**.

Point briefly to the record count, source counts, dataset hash and locked truth commitment.

### Say

> This is a synthetic month-end close generated now: 500 settlements and just over 60,000 observed records across merchant, Razorpay payment, settlement-recon and bank sources.

> The seeds and dataset hash are visible. The simulator knows the real answer, but ReFlow does not get that ground truth until after the reconciliation run.

This is the answer to “is the data premade?” It is synthetic by design, reproducible and scored later—not four hand-written examples.

## 0:50–1:15 — Run ReFlow

### Screen

Click **Run reconciliation** and let the real progress stream play.

Do not talk over every stage. Let the counters be visible.

### Say

> It is actually processing the batch now. Evidence is journaled and normalized, the Money Graph is built, settlement composition is proved, and bank receipt is checked independently by identity and amount.

On the current Mac this run is roughly four to five seconds. The UI reports the actual measured duration; there is no artificial stage delay.

Expected result for the fixed seeds:

- **317 proven reconciled**
- **140 pending bank credit**
- **42 residual**
- **1 contradicted**
- **183 explicit exceptions**

## 1:15–1:55 — Open something ReFlow refused to reconcile

### Screen

Filter to **pending bank credit** and open `setl_000004` or the first pending result.

For the current seed this settlement is about **₹3,158.62**. Its composition is exact, but the bank credit is not observed.

### Say

> This is the part I care about. ReFlow can fully explain the settlement amount, but there is no authoritative bank receipt yet. So it stays pending instead of treating “processed” as “received.”

Point to:

- settlement amount;
- observed composition;
- zero bank credit;
- bank residual;
- `BANK_RECEIPT_NOT_OBSERVED`.

Do not call this an “AI decision.” The proof engine created this state before DeepSeek is involved.

## 1:55–2:30 — Use DeepSeek on the real exception

### Screen

Click **Ask DeepSeek to investigate**.

The currently validated path takes about 2–3 seconds and records the bounded evidence accesses.

### Say

> Now the model can help with the operational question, not the accounting answer.

> ReFlow gives DeepSeek only this exception, its proof and the source envelopes already cited by that proof. In this case it recommends requesting the bank source. It cannot mark the settlement reconciled.

Point to the trace:

- `CASE_SNAPSHOT`
- `PROOF_SNAPSHOT`
- `SOURCE_EVIDENCE`

The final proposal is still validated by ReFlow. If the model invents an evidence ID, amount or unsupported action, the result is rejected or becomes `ABSTAIN`.

## 2:30–3:05 — Show where AI is genuinely useful: schema drift

### Screen

Scroll to **Bank export changed** and click **Ask DeepSeek to map columns**.

The sample export deliberately uses vendor-style columns such as `Txn`, `Credit`, `Date`, `Reference` and an explicit `Asia/Kolkata` timezone.

### Say

> A second place models are useful is when a finance source changes shape. Instead of asking an engineer to hard-code another parser, DeepSeek proposes a constrained mapping.

> Here it identifies the rupee amount, transaction reference, Indian date format and timezone. ReFlow then parses the sample rows itself and verifies the exact control total before the adapter can even reach review.

Point to:

- `Credit → amount_paise` with `rupees_to_paise`;
- `Date → occurred_at` with `%d/%m/%Y`;
- timezone offset `+330` minutes;
- the verified **₹4,666.64** financial control;
- the final `needs_review` state.

Say plainly:

> The model suggests the adapter. It does not activate it.

## 3:05–3:45 — Unlock the answer only after ReFlow finishes

### Screen

Click **Unlock hidden ground truth**.

For the fixed 500-settlement adversarial batch the current expected comparison is:

- ReFlow: **317 automatic, 317 correct, 0 wrong**;
- fuzzy matcher: **323 automatic, 317 correct, 6 wrong**;
- ReFlow precision: **100%** on its automatic decisions;
- ReFlow truth-reconciled recall: **79.25%**.

### Say

> Only now do I reveal the simulator truth and score the decisions.

> ReFlow automatically closed 317 settlements and all 317 were correct. A fuzzy matcher closed six more. Every one of those extra six was wrong.

Then add:

> I am not optimizing for the smallest exception queue. I am optimizing for the smallest number of incorrect financial decisions.

Do not call 63.4% coverage “accuracy.” If asked, it is 317 automatic decisions out of 500 requested settlements.

## 3:45–4:10 — Prove the Razorpay integration is real

### Screen

Use **Check Razorpay API** only when Test Mode credentials are configured.

Show aggregate counts from:

- `/v1/payments`
- `/v1/settlements`
- `/v1/settlements/recon/combined`

### Say

> The scored workload is synthetic so I can know the answer and measure it. Separately, this is the actual Razorpay API connector in Test Mode. The credentials authenticate and all three endpoints are reachable. This sandbox is empty right now, so I am not pretending its zero rows are an accuracy benchmark.

If you completed a mock Checkout before recording, mention the genuine test payment count briefly. Either way, keep the distinction explicit: the 500-settlement benchmark did not come from the connected Razorpay account.

## 4:10–4:40 — Show the checked-in evidence briefly

### Screen

Open the Evaluation page or checked-in evaluation artifact for only long enough to establish that the live demo is not the only test.

### Say

> I also kept a separate frozen held-out evaluation in the repository: 768 settlements and 87,364 observed records. ReFlow made 512 automatic decisions, all 512 were correct, and the fuzzy baseline made nine false automatic matches.

If there is time, mention the disclosed scale benchmark:

> On a separate 10,000-settlement clean benchmark, the proof pipeline sustained 206.97 settlement proofs per second on a four-vCPU ARM VM. That is a proof-pipeline measurement, not a production SLO.

Do not spend time scrolling through README tables.

## 4:40–4:58 — Close

### Screen

Return to the settlement results or the pending proof.

### Say

> The point is not to automate every settlement. It is to automate the ones we can actually prove, and make the rest impossible to hide.

> ReFlow uses AI where finance data is messy, and deterministic evidence where the answer affects money.

Stop recording.

## If a live model call fails during recording

Retake the shot. Do not replace a rejected/abstained result with a hard-coded success state.

Current local repeatability checks before this runbook was written:

- pending-settlement investigation: **3/3 validated**, 2.39–2.95 seconds;
- bank-schema mapping after prompt hardening: **5/5 passed deterministic financial controls**, 2.18–2.70 seconds.

A provider outage is safe: ReFlow reconciliation is already complete and the investigation result fails closed to abstention/provider error.

## Claims to keep precise

Say:

- “synthetic adversarial workload,” not “real merchant month”;
- “automatic coverage” or “automatic decisions,” not “accuracy,” for the fraction automatically reconciled;
- “100% precision on automatic decisions” only with its denominator;
- “proof-pipeline throughput” for the 206.97/s scale metric;
- “Razorpay Test Mode API connector” when showing the live connector.

Do not say:

- ReFlow beats the grouped-exact baseline on recall;
- the synthetic 500-settlement run came from Razorpay;
- DeepSeek decides whether a settlement reconciles;
- the schema adapter is automatically activated;
- the system is fully production-ready.

## Judge Q&A

### Why synthetic data?

> Because I need ground truth to measure false reconciliation decisions. The workload is generated from fixed seeds, hashed before the run, and the truth is withheld until scoring. The live Razorpay connector is shown separately.

### Why use AI if reconciliation is deterministic?

> The hard part is not only arithmetic. Real finance exports change shape and exceptions need investigation. DeepSeek handles those ambiguous interfaces; ReFlow still validates the adapter and the financial evidence deterministically.

### Why not fuzzy-match more settlements?

> On this 500-settlement run it closes six more, but all six additional decisions are wrong. On the separate frozen 768-settlement benchmark it makes nine false automatic matches.

### What happens when DeepSeek is wrong or unavailable?

> The model result is rejected or abstains. The reconciliation proof does not change.

## Final checklist

- demo reset to `phase=ready` before recording;
- 500 / adversarial / seeds 402 and 1402;
- DeepSeek configured;
- Razorpay **Test Mode** connector configured before the final take;
- no API keys, terminals, private payer data or `.env` files visible;
- actual run counters visible;
- one pending proof opened;
- one live DeepSeek investigation shown;
- one live schema mapping shown;
- hidden truth unlocked only after the run;
- under five minutes;
- test the final video link logged out before submitting.
