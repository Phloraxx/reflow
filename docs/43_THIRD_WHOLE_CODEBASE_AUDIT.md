# Third Whole-Codebase Audit

**Date:** 2026-09-03
**Base `main`:** `61d8b305e1cf2b31fd68c5a3a332634a977938ff`
**Audit branch:** `audit/third-whole-codebase-pass`
**Status:** complete and merged green. Audit PR #27 merged as `e2c8a2f33bbf7506257a9a8cfda4349d838a60ac`; exact merge-triggered `main` CI run `33744722448` passed.

## 1. Purpose

After the first post-final audit had already merged green, ReFlow was audited again from the repaired `main` rather than assuming the previous audit had exhausted the defect surface.

This pass focused on discrepancies between immutable domain truth and what can survive persistence, migration, HTTP serialization, operator projection and optional model context.

The frozen Gate 19 seeds, scorer, candidate hashes and first-run v1 were not changed or rerun in response to this audit.

## 2. Reproduced failures

The third pass reproduced and fixed F-0098 through F-0123. Full descriptions and regression evidence remain in `FAILURE_LOG.md`.

- **F-0098:** PostgreSQL duplicate raw-evidence replay diverged from the in-memory journal.
- **F-0099:** exact int64 paise could lose precision after JSON entered JavaScript.
- **F-0100:** malformed `//api/...` paths could fall through to the SPA shell.
- **F-0101:** model transports accepted NaN/infinite/unreasonably large timeouts.
- **F-0102:** `LATEST_PROOF` current-pointer keys were not scope-qualified; PostgreSQL schema v2 now migrates legacy pointers and fails closed on unmigratable legacy state.
- **F-0103:** durable artifact scope/time/adapter identity could still be caller-controlled despite typed payloads.
- **F-0104:** a run could become operationally current before its complete immutable dependency graph existed.
- **F-0105:** fixed 10k scans could silently truncate Control Tower history or make proof-scope validation incorrect.
- **F-0106:** case observations were not fully rebound to their proof, policy, manifests, chronology and economic identity at read time.
- **F-0107:** disposition replay accepted impossible/orphaned Gate 14 workflow history.
- **F-0108:** incident clusters could be orphaned or ordered by caller-controlled storage time.
- **F-0109:** Gate 16 investigation packets allowed temporal or citation inconsistency with their bound evidence.
- **F-0110:** durable manifests/proofs could exist even when cited raw envelopes were absent from PostgreSQL.
- **F-0111:** Gate 16 bounded source values but not model-facing field paths/depth.
- **F-0112:** Gate 12 could transmit sensitive identifiers embedded in source column names.
- **F-0113:** schema-v1 proof-pointer migration could silently repair a contradictory legacy key instead of failing closed.
- **F-0114:** schema-v2 canonical timestamp semantics disagreed with its own migration, breaking replay/reseed of a real v1 database.
- **F-0115:** v1 approved-adapter caller identities survived migration, forking canonical identity/currentness on replay.
- **F-0116:** a populated database with missing schema metadata was silently stamped v2 instead of failing closed.
- **F-0117:** v1 adapter migration could accept a `LATEST_ADAPTER` pointer targeting a non-adapter artifact and still stamp schema v2.
- **F-0118:** v1 proof-pointer migration could trust proof payload content whose retained SHA-256 no longer matched.
- **F-0119:** Gate 12 sample redaction leaked long identifier-like numeric values when source profiling represented them as floats.
- **F-0120:** Gate 12/Gate 16 numeric-string redaction stopped at 19 digits and leaked longer identifiers.
- **F-0121:** Gate 16 value bounding could cut through a credential before redaction and expose a secret-like fragment.
- **F-0122:** the root environment example advertised dead/misnamed variables instead of the actual Python runtime/OpenAI configuration contract.
- **F-0123:** test-only `httpx2` was included in the production web dependency extra, unnecessarily expanding runtime dependency surface.

## 3. Durable schema v2

This pass upgrades `POSTGRES_SCHEMA_VERSION` from 1 to 2 because several fixes change durable metadata/currentness semantics rather than only application code.

The v1→v2 migration:

- removes caller convenience timestamps from artifact families with no intrinsic domain time;
- stores reusable policy/approved-adapter definitions globally;
- canonicalizes legacy approved-adapter artifact IDs to deterministic content identities while preserving current-pointer generation;
- rewrites legacy latest-proof pointer keys to `scope_id:settlement_id`;
- preserves scoped proof artifacts;
- preflights legacy latest-proof payload digest/identity plus approved-adapter identity and pointer target kind, aborting rather than stamping v2 when retained content, currentness or canonical identity is contradictory/unmigratable;
- refuses to infer a schema version when the metadata row is missing from a populated ReFlow database.

Normal migration, repeated initialization/reopen, legacy metadata/timestamp semantics, pointer-generation preservation, real base-code v1 run and approved-adapter seed → current v2 replay compatibility, missing-metadata refusal, and contradictory/unmigratable legacy fail-closed behavior are regression-tested on disposable PostgreSQL databases.
## 4. Persistence and operator-surface hardening

The public application service remains the typed/self-validating write boundary while the lower PostgreSQL store remains an intentionally generic infrastructure primitive.

New durable guarantees include:

- source manifests and proof versions cannot be retained unless every cited raw envelope exists;
- scoped proof evidence is checked with targeted manifest-coverage queries rather than a finite list scan;
- current-run publication requires the complete policy/manifest/proof/coverage/balance/close graph;
- typed intrinsic timestamps override convenience storage metadata and conflicting overrides fail closed;
- approved adapter artifacts use deterministic content identity;
- proof current-pointer namespaces include reconciliation scope.

Control Tower now independently rejects incomplete or inconsistent persisted packets. It also detects when a finite history query is truncated instead of presenting that partial data as complete finance state.

Case projection revalidates proof facts, source states, policy materiality, run chronology and economic identity. Workflow replay enforces Gate 14 chronology/REOPEN semantics, and incident clusters are tied to real run observations and immutable run completion time.

## 5. Exact-money and HTTP boundary

`MoneyView.amount_paise` is now a decimal string across the API boundary. Python/domain arithmetic remains signed-int64 integer paise; React only formats verified values and never converts exact raw paise to an unsafe JavaScript number.

SPA fallback routing normalizes the captured path before checking the `/api` boundary, so malformed double-slash API-like paths remain API 404s rather than receiving the web shell.
## 6. Bounded model-context hardening

The shared OpenAI transport now requires a finite positive timeout no greater than 300 seconds in addition to the existing HTTPS-only, no-redirect and bounded-response rules.

Gate 16 source-evidence projection now bounds field count, collection fan-out, recursion depth, path length and value length. Both paths and values pass through model-facing sensitive-data redaction.

Gate 12 still preserves exact source column names because adapters must reference real columns. If a column name itself looks like a credential, email/UPI-like identifier or long account/phone number, the OpenAI proposal provider now refuses transport rather than redacting the schema into unusable semantics.
Long numeric identifiers are also redacted consistently when source profiling represents them as integers or floats; non-finite float samples are normalized before model serialization.

Gate 16 also rejects an investigation timestamp before its latest bound case observation/proof generation. Case File rejects persisted investigation citations outside the exact proof evidence packet.

## 6A. Configuration contract cleanup

The root `.env.example` now documents only environment variables actually consumed by the Python runtime. Optional OpenAI paths use the exact `OPENAI_API_KEY`, `REFLOW_ADAPTER_MODEL` and `REFLOW_INVESTIGATION_MODEL` names required by their constructors; frontend-only scope configuration remains in `web/.env.example`. Dead generic AI, Razorpay credential and unused environment/seed placeholders were removed.


Packaging/hygiene review also moved Starlette TestClient's `httpx2` dependency to the dev extra; a clean web-only resolution now contains only serving dependencies. Coverage.py parallel shards (`.coverage.*`) are ignored so reviewer instrumentation no longer dirties the worktree.

## 7. Exact-current-tree validation

After F-0122/F-0123 and repository-hygiene cleanup, the complete PostgreSQL-enabled reviewer path was rerun without further source changes:

- `make submission-check`: **passed**;
- Ruff: **passed**;
- strict mypy: **passed across 66 source files**;
- Python/PostgreSQL: **469 tests passed**;
- TypeScript project check: **passed**;
- React/Vitest: **5/5 tests passed**;
- Vite production build: **passed**;
- frozen Gate 19 held-out artifact: **verified**;
- Gate 19 failure campaign: **verified**;
- compact Gate 19 final summary: **verified**;
- Gate 17 scale and PostgreSQL artifacts: **verified**;
- generated `EVALUATION.md`: **verified**.

The same PostgreSQL-enabled Python suite also passed under `PYTHONOPTIMIZE=1`; correctness does not depend on removable `assert` statements. Independent checks on the same code/config tree found:

- Bandit medium/high: **0 findings**;
- `pip-audit` over the pinned constraint set: **0 known vulnerabilities**;
- npm production audit: **0 vulnerabilities**;
- npm full/dev audit: **0 vulnerabilities**;
- concrete non-package source-module import cycles: **0**;
- core-layer forbidden dependency violations: **0**;
- production simulator leakage: **0**;
- high-confidence tracked-tree secret patterns: **0**;
- tracked cache/build/coverage outputs: **0**;
- TODO/FIXME/HACK markers in source/UI: **0**;
- unsafe dynamic execution/deserialization patterns: **0**.

Branch-instrumented PostgreSQL tests also passed all **469 tests**. Coverage is **80% across `src/reflow` including branches** and **85% across source + tests**. The lower source percentages are concentrated in defensive malformed-state branches, CLI/bootstrap wiring and injected live-network transport paths; the Razorpay integration test module is 100%, PostgreSQL persistence tests are 99%, and both model-provider test modules are 99%. No uncovered branch was promoted into a fix without a reproducible violated invariant.

Packaging validation confirms `.[web]` no longer resolves `httpx2`, `httpcore2` or `truststore`; the combined reviewer install `.[dev,postgres,web]` still resolves under the checked-in constraints. `git diff --check` is clean.

## 8. Complexity / residual maintainability debt

The audit deliberately did not refactor correct financial validators merely to reduce cyclomatic complexity. Radon still identifies several large validation/proof functions, especially `ControlTowerReader._case_queue`, `settlement_proof._prove_settlement_composition`, `control_plane.build_reconciliation_run`, and `investigation._validate_proposal`.

The Control Tower case projection is now especially dense because it independently fail-closes corrupted low-level persistence. A future semantics-preserving decomposition is desirable, but changing that code during the audit without a failing invariant would increase submission risk rather than reduce it.

Vulture's 100%-confidence output remains limited to protocol parameter names required by cursor/context-manager interfaces, not dead executable behavior.

## 9. Explicit non-claims unchanged

This audit still does not add authentication, tenant authorization, SSO/RBAC, production connector identity, HA/backups/PITR, a distributed queue, a live-model quality benchmark, or a real authenticated Razorpay settlement/recon accuracy corpus.

Long histories now fail closed when the reference read window is insufficient; they still require pagination/indexed read models for production operation. Heuristic model redaction is still not a DLP system.

The 46.91 MiB first-run held-out artifact remains unchanged and intentionally retained. Product evaluation reads the compact self-verifying summary instead.

## 10. Merge evidence

Audit commit `baa26b9` passed PR validation and PR #27 merged to `main` as `e2c8a2f33bbf7506257a9a8cfda4349d838a60ac`. The exact merge-triggered `main` CI run `33744722448` completed successfully. The third whole-codebase audit is therefore closed; any future changes require a new validation boundary rather than extending this evidence retroactively.
