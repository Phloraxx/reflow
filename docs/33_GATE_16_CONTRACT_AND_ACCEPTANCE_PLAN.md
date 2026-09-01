# Gate 16 Contract and Acceptance Plan — Bounded Exception Investigation Agent

## Status

Frozen pre-implementation acceptance contract. Implemented by Gate 16 checkpoints `f4741ca`, `6ed1c8a` and `d1325a9`; see `34_GATE_16_CHECKPOINT.md` for the validated implementation state and privacy hardening discovered during execution.

Gate 16 starts from verified Gate 15 `main`:

`8d6b25bdab33a78e05c951f2bce4622639258909`

Gate 15 provider integration and merge-triggered CI are green. No Gate 16 code may change Gate 7/8/9 financial truth, Gate 13 close readiness, Gate 14 case observations, or operator dispositions.

## Thesis

> AI may investigate one immutable exception packet with read-only evidence tools, but deterministic ReFlow code validates every citation, amount and allowed next action before the result is accepted.

The model is an investigator, never an adjudicator.

## Exact investigation target

One investigation binds exactly:

- active Gate 14 `ExceptionCaseState`;
- latest immutable `ExceptionCaseObservation`;
- exact Gate 9 `ReconciliationProofVersion` named by that observation;
- retained raw source envelopes cited by that proof;
- explicit `as_of` time for case age.

The target is rejected if case/observation/proof IDs, settlement identity, amount, status, reasons or source evidence do not agree.

Resolved, superseded or financially green cases are not eligible for a new investigation run.

## Read-only tool catalog

Gate 16 exposes only:

1. `CASE_SNAPSHOT`
   - case identity, workflow, materiality, age, current source states and immutable latest IDs.
2. `PROOF_SNAPSHOT`
   - exact proof status, reason codes, Gate 7/8 amounts/residuals, knowledge cutoff and source envelope IDs.
3. `SOURCE_EVIDENCE`
   - one retained proof-cited envelope by exact `SourceEnvelopeId`.

There is no generic SQL, arbitrary file access, ledger write, disposition write, adapter approval, evidence attachment, refund, payout, transfer or `MARK_RECONCILED` tool.

A source-evidence request for an ID outside the bound proof is denied and recorded in the tool trace.

## Prompt/data boundary

The initial provider context contains structured case/proof metadata and the list of available source envelope IDs, but not raw payload contents.

Raw source strings become visible only through the bounded `SOURCE_EVIDENCE` tool and are explicitly labelled untrusted source data. They may contain prompt-like text. Such text has no authority over tool permissions, citations, financial facts or next actions.

## Allowed next actions

Exactly:

- `WAIT`
- `RECHECK`
- `REQUEST_SOURCE`
- `REQUEST_HUMAN_REVIEW`
- `ABSTAIN`

`WAIT` is accepted only when deterministic state shows pending bank credit or an incomplete/waiting/late source.

`REQUEST_SOURCE` must name one source kind present in the case source-state packet.

## Financial-number rule

Free-form hypothesis prose may not contain digits. Every financial number must be emitted through a typed financial fact claim.

Allowed fact references are derived from the exact case/proof packet, including:

- affected amount;
- settlement amount;
- composition observed amount;
- composition residual;
- expected bank amount;
- observed bank credit;
- bank residual.

The validator recomputes the expected `Money` value for the named fact and rejects any mismatch. The model cannot introduce an unsupported amount by prose or by a typed claim.

## Citation rule

A non-abstaining investigation must cite at least one exact `SourceEnvelopeId`.

Every citation must:

- belong to the bound proof;
- still exist in the supplied journal;
- have been actually retrieved through `SOURCE_EVIDENCE` during this investigation.

The model cannot cite guessed, stale, hidden-truth or merely available-but-unread evidence.

## Tool trace

Every tool call creates an immutable trace entry containing:

- monotonic sequence;
- tool name;
- request reference;
- allowed/denied outcome;
- returned immutable references;
- deterministic digest of the returned view when allowed;
- deterministic content-addressed trace-entry ID.

The final investigation result binds the exact ordered trace. A reviewer can recompute whether the model actually inspected every cited envelope.

## Provider contract

The provider receives:

- immutable `InvestigationContext`;
- a `ReadOnlyInvestigationTools` capability.

It returns an untrusted JSON-like mapping. Deterministic parsing and validation occur after provider execution.

Provider timeout/error/outage produces a `PROVIDER_ERROR` investigation result with action `ABSTAIN`. It never mutates financial or workflow state.

An explicit model abstention is a valid `ABSTAINED` result.

Malformed/hallucinated provider output produces `REJECTED` + `ABSTAIN`, preserving the rejection reason and tool trace for evaluation.

## Result authority

A `VALIDATED` Gate 16 result is still a hypothesis/recommended next safe action only.

It cannot:

- change Gate 9 status;
- change Gate 13 close readiness;
- append Gate 14 dispositions;
- attach evidence to a proof;
- approve an adapter;
- initiate money movement.

## Acceptance tests — freeze before model provider

1. exact latest case/observation/proof packet is accepted;
2. mismatched proof version fails closed;
3. resolved/green case cannot be investigated;
4. case tool returns bounded immutable snapshot;
5. proof tool returns exact deterministic financial facts;
6. source tool returns only proof-cited retained evidence;
7. source tool rejects a hallucinated/out-of-scope envelope ID;
8. denied tool calls remain visible in trace;
9. source payload is labelled untrusted and absent from initial context;
10. valid non-abstain proposal requires an actually retrieved citation;
11. hallucinated citation is rejected;
12. proof-cited but unread citation is rejected;
13. exact typed monetary claim is accepted;
14. wrong typed monetary amount is rejected;
15. free-form digits in hypothesis text are rejected;
16. duplicate/noncanonical citations or claims are rejected;
17. unsupported action such as `MARK_RECONCILED` is rejected by parser;
18. `WAIT` is accepted for pending bank credit;
19. `WAIT` is rejected when deterministic state gives no waiting condition;
20. `REQUEST_SOURCE` requires one current source kind;
21. `RECHECK` can be validated without pretending truth changed;
22. `REQUEST_HUMAN_REVIEW` can be validated;
23. explicit model `ABSTAIN` is accepted;
24. provider outage returns `PROVIDER_ERROR` / `ABSTAIN`;
25. provider outage leaves case/proof histories unchanged;
26. prompt-like source text cannot authorize unsupported evidence/number/action;
27. same provider output and same tool sequence produce same result identity;
28. tool sequence is bound into result identity;
29. direct trace/result tampering fails self-validation;
30. production Gate 16 core imports no simulator truth;
31. public Gate 16 tool surface contains no mutator;
32. tool traces are independently recomputable from returned views.

## Deferred

- production persistence for investigation results/traces;
- authenticated human actor identity;
- live model benchmark and model-quality numbers;
- UI;
- asynchronous investigation workers;
- automatic dispositions;
- autonomous remediation;
- arbitrary SQL/data warehouse tools;
- Gate 17 scale/durability work.

## Admission rule for Gate 17

Gate 16 is complete only when provider-independent safety/validation tests are green, a bounded model provider can fail/abstain harmlessly, hallucinated citations/numbers/actions are rejected, prompt-like source content remains inert, and tool traces are independently evaluable.
