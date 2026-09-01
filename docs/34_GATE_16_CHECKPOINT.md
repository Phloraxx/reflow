# Gate 16 Checkpoint — Bounded Exception Investigation Agent

## Status

Gate 16 is implemented on `build/gate-16-bounded-exception-investigation` from final Gate 15 `main`:

`8d6b25bdab33a78e05c951f2bce4622639258909`

Implementation checkpoints:

- deterministic investigation core: `f4741ca2cf7fcc7859e3ee88306429962409b9f9`;
- bounded OpenAI Responses provider: `6ed1c8ac5983777a523eda9fd648b636c894fe95`;
- model-facing evidence minimization/privacy hardening: `d1325a99538e252248a7373e5deb4f0730df31c1`.

Oracle VM validation on 2026-09-01:

- Ruff: passed;
- strict mypy: passed across 54 source files;
- targeted Gate 16 suite: 46 collected cases and all passed;
- full repository suite: 356 collected cases and all passed;
- `git diff --check`: passed;
- provider scan: no financial-mutation calls, simulator truth, TODO, FIXME or `NotImplemented` marker.

PR #17 merged as `88acedf5c12eedd33fefada28c6677f76ebf4a39`; merge-triggered `main` CI run `33528694353` passed.

## Gate 16 thesis

> AI may inspect one immutable exception packet and propose one safe next step, but it cannot decide financial truth and its output is accepted only after deterministic citation, amount, action and lineage validation.

The model is an investigator, not an adjudicator.

## Exact target binding

Every investigation binds exactly one active Gate 14 case to:

- its current `ExceptionCaseState`;
- its latest immutable `ExceptionCaseObservation`;
- the exact Gate 9 `ReconciliationProofVersion` named by that observation;
- the raw source envelopes already cited by that proof;
- an explicit timezone-aware `as_of` timestamp.

Construction fails closed if the case, observation, proof, settlement amount, financial status, reason codes, UTR binding or retained source evidence disagree. Closed, superseded and financially reconciled cases are not investigation-active.

## Read-only capability surface

`ReadOnlyInvestigationTools` exposes only:

1. `CASE_SNAPSHOT`;
2. `PROOF_SNAPSHOT`;
3. `SOURCE_EVIDENCE` for one proof-cited `SourceEnvelopeId`.

There is no SQL tool, generic file/system access, adapter approval, case/disposition mutation, proof mutation, evidence attachment, refund, payout, transfer or mark-reconciled operation.

A source ID outside the bound Gate 9 proof is denied and recorded in the immutable tool trace.

## Typed output authority boundary

The provider returns an untrusted proposal containing:

- the exact case/observation/proof IDs;
- optional hypothesis prose;
- retrieved `SourceEnvelopeId` citations;
- optional typed exact-money claims;
- exactly one allowed next action;
- an optional source kind only for `REQUEST_SOURCE`.

Allowed actions are exactly:

```text
WAIT
RECHECK
REQUEST_SOURCE
REQUEST_HUMAN_REVIEW
ABSTAIN
```

There is no action capable of changing financial truth.

A non-abstain proposal is accepted only when deterministic code proves that:

- target IDs equal the bound packet;
- citations are canonical, proof-scoped and were actually retrieved;
- every money claim exactly equals the selected Gate 9 fact in integer paise/currency;
- free-form hypothesis prose contains no numeric claims;
- `WAIT` has an actual deterministic waiting/pending condition;
- `REQUEST_SOURCE` names a source in the current case packet;
- all counts/lengths remain inside Gate 16 bounds.

Invalid proposals become `REJECTED + ABSTAIN`. Provider/transport failure becomes `PROVIDER_ERROR + ABSTAIN`. Explicit model abstention is a valid `ABSTAINED` outcome.

## Bounded resource contract

The reference core enforces:

- at most 16 read-only tool calls per investigation;
- at most 64 proof source-envelope IDs in one investigation packet;
- hypothesis prose at most 600 characters;
- financial claims bounded by the finite `FinancialFactKind` set;
- source text extraction at most 16 strings, each at most 240 characters;
- OpenAI final output capped at 1200 output tokens;
- OpenAI function-call loop capped at at most 16 rounds.

Bounds fail closed rather than silently truncating authoritative financial facts.

## Independently evaluable tool trace

Every read or denied read produces a self-validating `ToolTraceEntry` containing:

- monotonic sequence;
- tool name;
- exact request reference;
- allowed/denied outcome;
- canonical returned references;
- SHA-256 digest of the returned view/denial packet;
- explicit denial code when applicable;
- deterministic content-addressed trace ID.

The final `InvestigationRunResult` binds the ordered trace IDs. Changing tool order changes result identity even when the final prose/action is otherwise identical.

## OpenAI Responses provider

`OpenAIInvestigationProvider` is optional and sits above the provider-independent core.

The current implementation follows the checked current Responses API contract:

- explicit model and API key;
- `store=false` on every request;
- strict JSON-schema function arguments;
- only the three read-only functions;
- `parallel_tool_calls=false`;
- strict final `text.format` JSON schema;
- stateless conversation replay rather than `previous_response_id`;
- `reasoning.encrypted_content` requested so reasoning-model state can be replayed in stateless/ZDR-style flows;
- repeated safety instructions on every turn;
- provider status/error/refusal/incomplete responses fail closed.

Reference documentation checked during implementation:

- `https://developers.openai.com/api/reference/resources/responses/methods/create`
- `https://developers.openai.com/api/docs/guides/latest-model`

No live-model Gate 16 quality number is claimed by this checkpoint. Fake transports exercise function-calling, stateless replay, refusal/error handling, tool budgets and strict final-output parsing deterministically without incurring provider cost or depending on network availability.

## Model-facing data minimization

The core source view is richer than the OpenAI-facing projection.

The OpenAI transport intentionally omits:

- external settlement IDs from case/proof tool output;
- settlement UTR from proof output;
- external source-record IDs from source output;
- raw source payloads.

Source text shown through `SOURCE_EVIDENCE` remains explicitly labelled `UNTRUSTED_SOURCE_DATA` and is heuristically redacted for:

- email addresses;
- long numeric identifiers;
- known secret-token patterns;
- transaction-like payment/settlement/UTR identifiers.

Internal content-addressed case/proof/source-envelope references and exact typed financial facts remain available because deterministic validation requires them.

This redaction is a data-minimization guard, not a DLP guarantee.

## Prompt-injection behavior

Prompt-like text inside bank narration/source payloads has no capability authority.

Tests prove that:

- the initial model request contains no source payload text;
- source text appears only after explicit `SOURCE_EVIDENCE` retrieval;
- source output is labelled untrusted;
- external/sensitive-looking identifiers are redacted before OpenAI transport;
- a model cannot use source text to create an unsupported action, citation or amount;
- `MARK_RECONCILED` is absent from the provider source/tool schema.

## Financial truth remains unchanged

Gate 16 does not alter:

- Gate 7 settlement composition;
- Gate 8 bank receipt proof;
- Gate 9 proof versions/status;
- Gate 13 close readiness or run truth;
- Gate 14 case observations, dispositions, workflow or resolution.

The investigation result is a separate immutable advisory artifact. Operators or later application services must perform any permitted operational follow-up through their own authenticated workflow.

## Genuine failures found during Gate 16

The failure log preserves:

- **F-0076** — case-snapshot trace returned refs were not canonical-sorted;
- **F-0077** — denied tool access was misclassified as provider outage;
- **F-0078** — `store=false` was initially combined with stateful `previous_response_id` chaining;
- **F-0079** — transport request snapshots shared a mutable conversation alias;
- **F-0080** — model-facing tool output initially exposed unnecessary external financial identifiers/unredacted source text.

All five have regression protection and are resolved at `d1325a9`.

## Explicit limitations / non-claims

Gate 16 does **not** provide:

- a live-model investigation accuracy benchmark;
- production DLP or PII classification;
- durable investigation-result persistence;
- authenticated operator identity/authorization;
- automatic case-disposition execution;
- arbitrary retrieval across unrelated cases/accounts;
- autonomous refund/payout/transfer actions;
- authority to reconcile money;
- a final held-out agent benchmark;
- production observability/cost controls for external model calls.

The OpenAI transport is implemented and protocol-tested, but model quality remains an evaluation question rather than a deterministic claim.

## Next gate

New Gate 17 is **Scale + Durability/Application Layer**.

Gate 16 PR/merge/main CI are green. Gate 17 may now start from the final Gate 16 `main` checkpoint. Its job is to make the deterministic/reference stores durable and exercise the scale/resilience shape without weakening Gates 7–16 invariants.
