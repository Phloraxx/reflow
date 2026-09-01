# ReFlow — Final Five-Minute Pitch Script and Recording Runbook

## Recording rule

The video should demonstrate evidence, not narrate architecture for five minutes.

Target duration: **4:45–4:58** so upload/player timing does not push the submission over five minutes.

Use only synthetic/demo data. Do not expose local environment files, API keys, terminal history containing secrets or private merchant data.

## Pre-recording setup

1. Start the synthetic Gate 18 demo PostgreSQL instance from README.
2. Seed the deterministic demo and capture the printed `scope_id`.
3. Build the frontend and run the same-origin FastAPI application.
4. Open the app with the synthetic scope.
5. Keep `EVALUATION.md`, `FAILURE_LOG.md` and the architecture diagram/README available in separate tabs.
6. Pre-open one non-green Case File and Evaluation Lab to avoid dead time.
7. Browser zoom should make proof arithmetic readable in the recording.
8. Do not rely on a live OpenAI call. The final evaluation host had no model key and the submission makes no live-model quality claim.

## 0:00–0:25 — Hook

### Screen

Start on the ReFlow overview or a settlement proof, not a terminal.

### Script

> A payment processor can say a settlement was processed. Finance still has to prove exactly which payments, refunds and adjustments produced that amount, whether the bank actually received it, and what to do when the sources disagree. ReFlow turns that reconciliation into evidence you can audit.

Then say:

> Every rupee gets a path, a proof, or an exception.

## 0:25–0:50 — Product and safety boundary

### Screen

Show Run / Close Overview and the `READ ONLY` product authority.

### Script

> ReFlow compiles merchant, Razorpay-shaped and bank evidence into deterministic money proofs. The LLM never decides whether money reconciles. AI is limited to understanding unfamiliar source schemas and investigating an already-created exception through bounded read-only tools.

Point briefly to proven/pending/exception state.

## 0:50–1:35 — Exact settlement proof

### Screen

Open Settlement Proof.

### Script

> This is the core loop. ReFlow first proves settlement composition: the signed underlying movements must equal the authoritative settlement amount. Bank receipt is a separate proof: a processed settlement alone is never treated as bank credit. The full reconciliation proof becomes green only when both exact fragments agree.

Point to:

- settlement amount;
- composition equation;
- bank-proof state;
- proof/reason IDs;
- evidence/provenance references.

Then say:

> Same amount and approximate date are not enough. Stable identity and exact arithmetic outrank fuzzy similarity.

## 1:35–2:15 — Exception and bounded investigation

### Screen

Open the deterministic synthetic case with pending bank evidence.

### Script

> When evidence is missing or contradictory, ReFlow does not force a match. It creates a stable exception case that survives across runs, tracks workflow separately from financial truth, and keeps every historical proof version.

Show the case chronology and source blocker.

> The investigation agent can inspect only the case, its exact proof and proof-cited source evidence. It can propose actions like request source or human review. A hallucinated evidence ID, unsupported financial number or unsafe action is rejected by deterministic validation.

If the demo case contains the deterministic investigation result, show it. Do **not** imply it is a live model response.

## 2:15–2:50 — Product surface / operations loop

### Screen

Move quickly through Exception Queue, Source Lab and back to overview.

### Script

> The UI is a control tower over immutable finance state, not another reconciliation engine. Source Lab shows whether required feeds are complete or late without exposing raw source payloads. The exception queue ranks what remains non-green. Scope is explicit on every finance read.

Mention that the current public/reference UI is read-only and not an authenticated production finance app.

## 2:50–3:45 — Frozen held-out evaluation

### Screen

Open `EVALUATION.md` or Evaluation Lab with the final metrics visible.

### Script

> Before the final run, I committed the held-out seeds and hashes of the scorer and candidate systems. Then I ran the first v1 result once and preserved it unchanged.

> The primary corpus has 768 settlements and 87,364 observed records. ReFlow auto-reconciled 512 of 768 settlements. All 512 automatic matches were correct: 100 percent auto-match precision, zero silent false auto-matches. Against the 624 settlements that are reconciled in hidden truth, recall is 82.05 percent.

Pause before the nuance:

> The 66.67 percent number is coverage, not accuracy. I deliberately keep those terms separate.

Then compare the baseline:

> A strong grouped-exact baseline ties ReFlow's auto-match recall. I do not claim otherwise. A fuzzy baseline made nine more automatic decisions, but nine of its matches were wrong. ReFlow left those cases unresolved instead of buying coverage with false financial truth.

## 3:45–4:15 — Honest exceptions + failure campaign

### Screen

Show exception section of `EVALUATION.md`, then `FAILURE_LOG.md` around F-0081 or F-0084.

### Script

> The same held-out run leaves 256 explicit non-green decisions: 170 unresolved, 78 residual and 8 contradicted. The full machine-readable exception list is checked in; none were manually removed.

> I also ran a separate final failure campaign: 12 of 12 representative safety regressions passed, including late-source semantics, case supersession, model outage, prompt injection, hallucinated citations, PostgreSQL restart/idempotency and SPA/API routing.

For the development challenge, prefer F-0081:

> One real failure was performance: Gate 7 repeatedly rescanned provenance edges. The old 1,000-settlement benchmark was still running after more than 20 minutes. Profiling showed the exact hotspot; a batch-local provenance index fixed the algorithm without weakening proof semantics.

## 4:15–4:35 — Scale

### Screen

Show the verified Gate 17 10k metric in EVALUATION/README.

### Script

> On the disclosed four-vCPU ARM Oracle VM, the verified 10,000-settlement clean benchmark processed 1.2 million raw rows and sustained 206.97 settlement proofs per second in the proof pipeline. I do not extrapolate that to a production SLO or a 100k/1M claim.

## 4:35–4:55 — Close

### Screen

Return to the proof/case product view.

### Script

> ReFlow turns reconciliation from a plausible match into an auditable control: every amount is either proven, pending for a specific evidence reason, or explicitly unresolved. AI helps with the messy edges, but deterministic evidence remains the authority.

> Every rupee gets a path, a proof, or an exception.

Stop recording.

## What not to say

Do not say:

- “66.67% accuracy.” It is the all-requested-settlement automatic match rate.
- “AI achieved X% investigation accuracy.” No live-model Gate 16 benchmark was run.
- “Validated on real Razorpay settlements.” No real settlement/recon corpus was available for the final benchmark.
- “Production ready.” Authentication, RBAC, HA, secret management and production connector service are not implemented.
- “ReFlow beats all baselines.” B1 grouped-exact ties ReFlow's held-out auto-match recall.
- “206.97 settlements/s end to end.” That is the measured Gate 17 **proof-pipeline** rate; total 10k runtime was 267.56 seconds.

## Judge Q&A short answers

### Why use AI at all if the finance core is deterministic?

> Because financial truth should be deterministic when evidence is sufficient. AI is useful before and after that core: mapping unfamiliar source schemas into a constrained adapter, and deciding which read-only evidence to inspect for an exception. The model has no authority to mark money reconciled.

### Why does the grouped-exact baseline tie your recall?

> Because exact grouping and exact UTR matching already solve a large part of this synthetic corpus. I kept that baseline intentionally strong. ReFlow's contribution is the audited evidence/provenance layer, conservative contradiction handling, immutable proof lifecycle, run/close controls, persistent cases, bounded investigation and operator workflow around that exact matching core.

### Why not use fuzzy matching to increase match rate?

> On the frozen held-out corpus it increased automatic decisions from 512 to 521, but all nine extra automatic decisions were wrong. In finance, an explicit exception is safer than a confident false match.

### Is the data real?

> The final measured corpus is synthetic and adversarial, matching the Track 04 requirement. Provider-shaped Razorpay fixtures validate integration semantics, but I do not claim a real Test Mode settlement accuracy number because no settlement/recon corpus was available in the connected account.

### What happens if the model is unavailable?

> Reconciliation, proofs, close controls and exception creation still run deterministically. Investigation falls back to abstention; financial truth is unchanged.

### Biggest current limitation?

> The reference product is not an authenticated multi-tenant production finance application. It still needs first-party connector authentication, RBAC/SSO, production secret management and real de-identified settlement/bank corpora for production calibration.

## Final recording checklist

- under five minutes;
- no private data or keys visible;
- synthetic/demo label visible where useful;
- exact 512/768, 512/512 and 512/624 denominators spoken correctly;
- mention the strong B1 tie honestly;
- mention nine false fuzzy matches;
- show at least one real development failure/fix;
- show the read-only safety boundary;
- end on the one-sentence product thesis;
- upload the video publicly/unlisted as required and test the link in a logged-out browser before submitting.
