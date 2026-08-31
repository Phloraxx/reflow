# Gate 12 Checkpoint — AI-Assisted Source Adapter Compiler

## Status

Gate 12 is implemented, checkpointed, merged through PR #9, and verified on `main` at `a7bf0d134dcd524a370591b023986a42c72bcae6`.

Final Gate 12 checkpoint evidence:

- branch code checkpoint: `7495ed1c93ee4ae764deb2e09b45ea76d9532bb9`
- merged `main`: `a7bf0d134dcd524a370591b023986a42c72bcae6`
- Ruff: passed
- strict mypy: passed across 49 source files
- pytest: 221 passed

This checkpoint introduces ReFlow's first model-capable path. The model has **zero reconciliation authority**. It may only propose a constrained declarative source mapping.

## Gate 12 thesis

> Let AI interpret an unfamiliar schema once, but make activation a deterministic, versioned and auditable decision that remains tied to immutable raw evidence.

Gate 12 does not create another reconciliation engine. Approved adapters compile unfamiliar data into the same canonical domain contracts consumed by the Money Graph and Gates 7–10.

## Supported canonical targets

- merchant order
- payment event
- settlement recon entry
- settlement
- bank entry

## Operational trust chain

```text
unknown raw rows
    ↓
append-only SourceEnvelope journal
    ↓
profile retained journal payloads
    ↓
optional bounded model proposal
    ↓
strict AdapterSpec parser
    ↓
finite deterministic transforms
    ↓
existing Gate 4 canonical adapters
    ↓
validation + optional financial controls
    ↓
NEEDS_REVIEW / REJECTED
    ↓
explicit operator review OR migration equivalence
    ↓
approved adapter version
    ↓
compile retained journal envelopes
    ↓
CanonicalBatch + SourceLinks
    ↓
Money Graph / Gates 7–10
```

The supported operational proposal path is journal-first. The pure row-level proposer is a private benchmark/unit-test seam.

## Declarative compiler

`AdapterSpec` uses a finite transform vocabulary:

- `TEXT`
- `OPTIONAL_TEXT`
- `INTEGER_PAISE`
- `RUPEES_TO_PAISE`
- `ISO_DATETIME`
- `DATE_TO_ISO_DATETIME`
- `CONSTANT`

Generated Python, `eval`, SQL, shell commands and arbitrary expressions are not part of the contract.

The compiler enforces the source-kind → record-kind pairing and restricts constants to narrow categorical targets. Money, IDs and timestamps cannot be invented with `CONSTANT`.

Money conversion uses exact decimal arithmetic and ends in integer paise. The existing canonical adapters remain the final validation boundary for money signs, required IDs, currencies and timestamps.

## First-seen schema authorization

Parse success is not authorization. Financial control totals are useful rejection evidence, but they do not prove identity/reference semantics.

Therefore every first-seen model proposal that otherwise validates ends as `NEEDS_REVIEW`. A verified control total may prove its money total but does not change that review requirement.

An operator-reviewed proposal can be promoted only through an explicit approval action that creates typed approval evidence bound to the exact adapter ID, version and schema fingerprint.

## Automatic migration authorization

Automatic activation exists only for a deterministic migration from an already approved adapter.

The old and proposed adapters replay paired old/new fixture rows into canonical financial facts. `MIGRATION_EQUIVALENCE` approval evidence can be created only when the canonical diff is identical.

The adapter store preserves historical versions and fingerprints. A newer version does not erase the older adapter needed to reproduce historical ingestion.

The store also prevents one adapter identity from changing its source kind or canonical record kind across versions.

## Schema fingerprints and drift

The structural fingerprint binds exact column names, normalized column names and primitive type families. Exact names matter because the deterministic compiler uses exact key lookup.

Current drift states are:

- `KNOWN_SCHEMA`
- `BENIGN_DRIFT`
- `REQUIRES_MIGRATION`
- `BREAKING_DRIFT`
- `UNRECOGNIZED_SOURCE`

Whitespace/case-like source-key changes that would break exact lookup cannot masquerade as a known schema merely because their normalized names are equal.

## Raw-to-canonical lineage

Gate 12 exposed an assumption that was acceptable for normalized Gate 4 fixtures but not for unknown exports: the raw source identity is not necessarily the canonical financial identity.

`SourceLink` now preserves both:

```text
raw identity       = adapter-batch:<batch>:row:<n>
canonical identity = bank_... / order_... / recon_... / ...
envelope ID        = immutable src_... evidence identity
```

The downstream `source_index()` remains keyed by canonical identity for compatibility with the Money Graph and proof engines. A separate raw-source index preserves the original journal identity.

The canonical compilation digest includes this lineage contract, so changing the raw/canonical binding changes compilation identity.

## Approved adapter runtime

An approved version may only process retained envelopes whose exact structural schema matches its approved fingerprint. Runtime compilation reads those payloads back from the immutable journal, not from a caller-supplied replacement row.

The resulting canonical fragment can be merged with other source fragments into a normal `CanonicalBatch`. An end-to-end regression sends merchant, payment, recon, settlement and bank batches through Gate 12 and then uses the existing Money Graph, Gate 7 and Gate 8 APIs without any Gate-12-specific reconciliation path.

## Optional OpenAI proposal provider

The provider uses the Responses API with strict JSON-schema output and `store=false`. The model name is mandatory; there is no hidden default model.

Only bounded structural profiles and bounded sample rows are sent. Obvious address-like values, long numeric identifiers and known secret-token patterns are deterministically redacted before transport. Free-text prompt-like narration remains visible as untrusted data so prompt-injection behavior is still tested.

The caller fixes adapter identity, version, source kind and canonical record kind. A model response that changes that contract is rejected before deterministic compilation.

Structured output constrains syntax only. It does not authorize a mapping or establish financial truth.

## Development proposal benchmark

The checked-in proposal corpus has 11 synthetic cases covering all five record kinds plus unit ambiguity, prompt-like text, duplicate identities, negative credits, missing columns and malformed dates.

Reference-provider regression at the code checkpoint:

- 11 cases
- 7 correct canonical previews requiring review
- 4 correct rejections
- 0 unsafe activations

A known-wrong rupee→paise mutation is also exercised. It is rejected/reviewed safely and still counted as an incorrect semantic preview, so safety cannot hide poor proposal quality.

These are compiler/benchmark regression results, **not live-model accuracy claims**.

## Development migration benchmark

The migration corpus exercises the real automatic-activation path:

- 3 cases total
- 1 canonical-equivalent header migration that must activate
- 2 unsafe migrations that must not activate
- 1 safe activation
- 2 correct rejections
- 0 unsafe activations
- 0 false rejections
- 0 routing failures

The unsafe cases include a wrong-unit/value migration and an identity/reference-field mutation that preserves money arithmetic but changes canonical meaning.

Both the proposal benchmark and migration benchmark have JSON artifact generators plus deterministic verifier CLIs. The verifier reconstructs the stored proposals/migrations and recomputes the report instead of trusting stored counts.

## Model benchmark non-claim

No live OpenAI model benchmark is claimed at this checkpoint. The development machine did not have a live provider credential configured, and ReFlow does not invent a model result.

A future live run must record the explicit provider/model name and use the already-frozen artifact/verifier contract. Model proposal quality and unsafe activation rate must be reported separately.

## Gate 12 failures discovered during implementation

The permanent details live in `FAILURE_LOG.md`. Gate 12 materially changed because of these findings:

- parse success alone could not prove rupee/paise semantics;
- a money control total could pass while identity/reference mappings were wrong;
- validation state was initially too close to activation authority;
- a zero-unsafe-activation benchmark could become vacuous if nothing was activatable;
- an implicit model default could silently change/stale the live benchmark contract;
- descriptive benchmark adapter IDs could leak scenario intent to a model;
- normalized-only schema fingerprints conflicted with exact source-key lookup;
- the compiler needed stricter source/record contracts and constant restrictions;
- the first proposal path bypassed journal-first raw retention;
- raw source identity was incorrectly assumed to equal canonical identity;
- first-seen reviewed proposals lacked an explicit activation/runtime bridge;
- validation and approval records were not initially bound to an exact adapter version/schema;
- the migration artifact had a JSON list/tuple replay mismatch;
- model-bound samples initially lacked deterministic sensitive-value redaction.

These are not erased from the history merely because the final design is safe.

## Gate 12 non-goals / remaining work

- no live-model accuracy claim yet;
- no production Razorpay Settlement Recon API adapter yet;
- no XLSX/PDF/OCR ingestion path;
- no durable database-backed adapter registry yet;
- no authenticated human-review identity/signature system yet;
- sample redaction is heuristic, not a DLP guarantee;
- no autonomous finance action is added;
- no exception-investigation agent is added in this gate.

## Reproducible commands

Development proposal artifact:

```bash
python -m reflow.adapter_compiler.benchmark_runner \
  --provider development \
  --output /tmp/reflow-gate12-adapters.json
python -m reflow.adapter_compiler.benchmark_verify_cli \
  /tmp/reflow-gate12-adapters.json
```

Development migration artifact:

```bash
python -m reflow.adapter_compiler.migration_benchmark_runner \
  --output /tmp/reflow-gate12-migration.json
python -m reflow.adapter_compiler.migration_benchmark_verify_cli \
  /tmp/reflow-gate12-migration.json
```

Live provider runs require both `OPENAI_API_KEY` and an explicit `--model`; their results must not be conflated with the deterministic development corpus.

## Gate verdict

Gate 12 passed branch exact-head CI, independent PR-triggered CI, merge, and the resulting `main` CI with Ruff, strict mypy and 221 tests.

The post-Gate-12 strategic review in `27_STRATEGIC_PAUSE_CURRENT_STATE_AND_REVISED_PLAN.md` deliberately postpones the exception-investigation agent until a deterministic reconciliation control plane and exception-case lifecycle exist. Any later agent must preserve Gate 12 boundaries: it cannot approve first-seen adapters, bypass the journal, manufacture canonical facts or promote hypotheses to financial proof.
