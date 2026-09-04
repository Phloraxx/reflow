# Gate 52 — Authenticated operator case-workflow contract

**Started:** 2026-09-04
**Base `main`:** `e423b383f5e90c30a3b6d4aa2378ae6890e18182`
**Working branch:** `hardening/operator-case-workflow`
**Status:** implementation locally validated; repository closure pending

## Purpose

Gate 52 adds the smallest authenticated operator write surface needed to work an existing deterministic exception case. It does not create a general mutation API and does not grant operators authority over reconciliation proof truth, source evidence, money movement, adapter activation, payouts, refunds, transfers or arbitrary SQL.

The only new product write is an append-only case disposition:

```text
Cloudflare Access subject
        + exact scope
        + case_operator role
        + Idempotency-Key
        + expected generation
              ↓
validated Gate 14 next disposition
              ↓
immutable CASE_DISPOSITION artifact
        + optimistic latest pointer
        + bounded command record
```

Writes remain opt-in. The Control Tower continues in read-only mode unless `REFLOW_CASE_WORKFLOW_WRITES=enabled` and Cloudflare Access authentication is configured.

## Authorization boundary

Gate 52 adds `case_operator` as a scoped role. A write is accepted only when the authenticated principal has that role for the exact `ReconciliationScopeId` in the route.

The route performs authentication and scope/role authorization before parsing the request body. A viewer without `case_operator`, an operator granted another scope, or an unauthenticated caller cannot use malformed-body behavior as an authorization oracle.

`scope_id` remains a routing identifier and never becomes a credential.

Every allowed or denied write authorization is recorded through the existing durable operator-audit boundary using the SHA-256 pseudonym of the immutable Access subject. Raw subject and email values are not persisted in the workflow artifact or audit row.

## HTTP command surface

When write mode is enabled, the only new route is:

`POST /api/v1/scopes/{scope_id}/cases/{case_id}/dispositions`

The command requires:

- authenticated exact-scope `case_operator` authorization;
- `Idempotency-Key` with a bounded 256-byte contract;
- `Content-Type: application/json`;
- a request body no larger than 8192 bytes;
- exact JSON keys: required `expected_generation` and `kind`, optional `owner` and `note`;
- non-negative integer `expected_generation`;
- a valid Gate 14 `DispositionKind`;
- bounded, trimmed optional owner/note values.

Unknown keys, malformed JSON, invalid content type, invalid idempotency keys and over-sized inputs fail closed. The route is absent when writes are disabled.

## Gate 14 transition reuse

Gate 52 does not fork or reimplement the exception-case state machine. `build_exception_case_disposition()` is the shared next-transition constructor used by both the original in-memory Gate 14 reference ledger and the authenticated durable workflow.

The shared boundary preserves:

- contiguous monotonic disposition sequence;
- no disposition before case creation;
- no backward disposition timestamp;
- existing owner/kind validation;
- no new workflow mutation after a financially reconciled or economically superseded case;
- explicit `REOPEN` before another status-changing action on a closed workflow.

The resulting `ExceptionCaseDisposition` remains content-addressed under the frozen Gate 14 ruleset.

## Durable command and idempotency contract

Gate 52 introduces PostgreSQL schema version 3 with:

- `LATEST_CASE_DISPOSITION` optimistic current pointers, one stream per case;
- `reflow_case_workflow_commands`, keyed by `(principal_subject_sha256, command_key_sha256)`.

A command record binds:

- pseudonymous authenticated subject digest;
- SHA-256 digest of the caller's idempotency key;
- canonical request-content digest;
- request correlation ID;
- exact scope and case;
- immutable disposition artifact ID;
- expected and committed generations.

Idempotent retry is intentionally bound to principal + idempotency key + canonical command content, not to the transport request ID. A later retry may have a new correlation ID and still returns the originally committed immutable disposition. Reusing one key with different scope/case/content/generation fails with conflict.

The disposition artifact insertion, latest-pointer compare-and-swap and command-row insertion occur in one PostgreSQL transaction. A stale expected generation rolls back the candidate artifact rather than leaving an orphan write.

## Migration and recovery

The schema v2 -> v3 migration validates existing CASE_DISPOSITION artifacts before backfilling each case's `LATEST_CASE_DISPOSITION` pointer. Migration fails closed on invalid payload digests, duplicated/non-contiguous sequences, changing scope within one case, or an inconsistent pre-existing pointer.

Logical restore verification now inventories case-workflow command rows and validates:

- all three SHA-256 digests;
- the stored 32-hex request correlation ID;
- scope/case/disposition binding;
- `committed_generation == expected_generation + 1`;
- disposition artifact kind, scope, case, sequence and pseudonymous actor binding;
- normal pointer-to-artifact integrity.

The PostgreSQL 16 logical dump/restore acceptance drill contains a real workflow command so backup evidence covers the new durable state rather than only table existence.

## Financial authority boundary

Gate 52 changes workflow metadata only. It cannot:

- create or rewrite raw source evidence;
- alter a Gate 7/8/9 proof result;
- mark an unsupported settlement reconciled;
- mutate reconciliation runs or close controls;
- activate an adapter;
- execute Gate 16 advisory recommendations automatically;
- issue or alter a payment, payout, refund, transfer or bank fact;
- execute generic SQL.

The health response continues to report `financial_truth_mutation: false` even when case workflow writes are enabled.

## Reproduced implementation findings

Gate 52 preserves the following pre-merge findings in `FAILURE_LOG.md`:

- **F-0135** — committed-command replay binding accidentally compared tuples with different shapes, so an otherwise valid persisted retry would conflict;
- **F-0136** — the first PostgreSQL command INSERT omitted the required `request_id` value despite declaring its column/placeholder;
- **F-0137** — the first HTTP route required an extra undocumented workflow-intent header that was not part of the minimal command contract and prevented valid clients/tests from reaching body validation;
- **F-0138** — logical restore verification initially omitted the durable workflow `request_id` integrity check.

Each production finding has a focused regression or is exercised by the real PostgreSQL/recovery suite.

## Local validation checkpoint

The exact pre-commit Gate 52 tree passed:

- whole-repository Ruff;
- strict mypy across **78 source files**;
- **560 Python/PostgreSQL tests** with `REFLOW_RECOVERY_DOCKER_DRILL=1`;
- real PostgreSQL Gate 52 command/idempotency/CAS tests;
- PostgreSQL 16 logical dump/restore integrity drill containing workflow command state;
- TypeScript checking;
- React/Vitest **6/6**;
- Vite production build;
- frozen Gate 17 scale/persistence verification;
- frozen Gate 19 held-out/failure/summary verification and `EVALUATION.md` check;
- optimized Python (`python -O`) non-PostgreSQL suite: **501 passed, 59 expected environment-gated skips**, with only pytest's expected optimized-assertion warning;
- Bandit medium/high: **0 findings**;
- `pip-audit`: **0 known Python vulnerabilities**;
- high-confidence tracked-tree and Git patch-history credential scan: **0 matches**;
- production source hygiene: no TODO/FIXME/HACK/XXX or `eval`, `exec`, `shell=True` patterns;
- `git diff --check`: clean.

The npm advisory endpoint did not return within repeated bounded production-audit attempts on the Oracle VM. `web/package.json` and `web/package-lock.json` are unchanged from the exact green Gate 51 base, and the locked frontend still passes TypeScript, Vitest 6/6 and the production build. This registry-availability limitation is recorded rather than converted into a clean audit claim.

## Explicit non-claims

Gate 52 does not claim:

- a general authenticated financial mutation API;
- tenant self-service or role administration;
- distributed workflow locking beyond PostgreSQL optimistic compare-and-swap for one case stream;
- a job queue, escalation scheduler or SLA engine;
- bulk case mutation;
- approval/signature semantics beyond Cloudflare Access authentication plus the configured authorization policy;
- external penetration testing, WAF/rate-limit policy or managed SIEM coverage;
- that pseudonymous SHA-256 subject digests are anonymous against an attacker who already knows candidate subjects.

## Merge rule

Gate 52 is not closed until the exact implementation head passes required PR CI, merges without head movement, the exact merge-triggered `main` CI passes, and the follow-up documentation record captures those immutable commit/PR/run identities.
