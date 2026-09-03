# Gate 50 — Control Tower long-history pagination contract

**Started:** 2026-09-04
**Base `main`:** `dfd8c943aae80ffb2184f1c9df718d1922175ad9`
**Working branch:** `hardening/control-tower-pagination`
**Status:** merged and closed

## Purpose

Gate 49 made the single-host Control Tower observable and auditable. Gate 50 removes a separate scalability boundary in the read path without changing deterministic financial truth.

Before this gate:

- `ControlTowerReader._list()` asked for at most 10,000 artifacts and failed closed above that count;
- the persistence list primitive exposed only `LIMIT`, not a continuation key;
- Proofs, Exceptions and Sources returned one complete JSON array;
- the React Control Tower fetched those complete arrays in one request.

That behavior was safe against silent truncation, but a legitimate long-lived scope could become unreadable and browser/network payloads grew with history.

## External guidance frozen for this gate

PostgreSQL 16 documents that rows skipped by a large `OFFSET` still have to be computed, so large-offset pagination can be inefficient. It also requires a deterministic `ORDER BY` when selecting subsets with `LIMIT`.

Reference: https://www.postgresql.org/docs/16/queries-limit.html

PostgreSQL 16 also documents that a B-tree matching `ORDER BY` can satisfy `ORDER BY ... LIMIT n` directly without scanning the remainder just to identify the first `n` rows.

Reference: https://www.postgresql.org/docs/16/indexes-ordering.html

ReFlow therefore uses continuation/keyset predicates over its existing B-tree order instead of offset pagination.

## Persistence contract

### 1. Stable artifact keyset

Scoped artifact history keeps the existing deterministic order:

`observed_at ASC NULLS LAST, artifact_id ASC`

The existing PostgreSQL index is:

`(artifact_kind, scope_id, observed_at, artifact_id)`

`ArtifactPageCursor` contains only the last artifact's `observed_at` and `artifact_id`. Equal timestamps are disambiguated by artifact ID. Once the non-null timestamp range is exhausted, the cursor continues through the `NULLS LAST` tail by artifact ID.

### 2. Bounded database pages

`PostgresApplicationStore.list_artifact_page()` accepts a continuation cursor and reads at most `limit + 1` rows to determine whether another page exists. The supported persistence limit remains bounded to 1–10,000; Control Tower integrity traversal uses pages of 1,000.

No `OFFSET` is used.

### 3. Complete-history integrity scans remain fail closed

Control Tower projections that genuinely require historical state still scan every required artifact, but they do so in fixed pages rather than one 10,000-row request.

For each internal scan ReFlow:

1. counts matching history before traversal;
2. validates every returned artifact kind, storage scope and payload identity;
3. requires every continuation cursor to match the last item actually returned;
4. counts matching history again at the end;
5. requires both counts to equal the number traversed.

A concurrent history change, malformed page chain or prematurely terminated store page therefore fails closed rather than returning a partial projection.

## Product collection contract

### 4. Legacy collection routes remain compatible

The existing routes remain available and preserve their array response shape:

- `/api/v1/scopes/{scope_id}/proofs`
- `/api/v1/scopes/{scope_id}/exceptions`
- `/api/v1/scopes/{scope_id}/sources`

Gate 50 does not silently change existing API consumers.

### 5. New bounded page routes

The Control Tower UI uses:

- `/api/v1/scopes/{scope_id}/proofs/page`
- `/api/v1/scopes/{scope_id}/exceptions/page`
- `/api/v1/scopes/{scope_id}/sources/page`

Each response is:

```json
{"items": [], "next_cursor": null}
```

Page size defaults to 50 and must be between 1 and 100.

### 6. Opaque cursor envelope

The product cursor is a versioned base64url JSON envelope containing only:

- schema version;
- collection name;
- reconciliation scope ID;
- last projection item ID.

The encoded cursor is limited to 1 KiB. Decoding requires the exact key set and exact JSON types. The cursor is bound to the requested collection and scope; a Proofs cursor cannot be reused for Sources or another scope.

The cursor is an opaque navigation token, **not** an authentication credential, authorization claim or confidentiality mechanism.

### 7. Authorization precedes cursor validation

Existing Cloudflare Access scope authorization is reused for paged routes. ReFlow authorizes the requested scope before asking the reader to decode/resolve the cursor. A viewer probing a forbidden scope with a malformed cursor therefore receives the same forbidden result rather than cursor-state information.

### 8. UI paging

Proofs, Exceptions and Sources use a shared `usePagedApi` hook. Initial network payload is at most 50 projected items; each explicit `Load more` action appends at most another 50.

A scope/path change aborts both the initial request and any in-flight continuation request, resets the cursor chain and prevents stale results from being appended into the new scope.

Client-side exception filters continue to apply only to the rows currently loaded. Gate 50 does not silently reinterpret those filters as server-side financial logic.

## Consistency boundary

Internal complete-history projections use the before/after count invariant above and fail closed if the backing history changes while being scanned.

Cross-request UI pagination is a **live navigation view**, not a database snapshot transaction spanning multiple HTTP requests. ReFlow artifacts are immutable, but new artifacts can be appended between page requests and projection order can evolve. A cursor whose referenced item is no longer available in the current projection fails with HTTP 400 rather than guessing a continuation point.

A snapshot-pinned read model would be a separate feature if product requirements demand repeatable cross-request pages under concurrent ingestion.

## Acceptance criteria

1. real PostgreSQL keyset paging handles equal timestamps and `NULLS LAST` history correctly;
2. no artifact keyset query uses `OFFSET`;
3. actual PostgreSQL-backed Control Tower traversal succeeds with more than 10,000 scoped artifacts;
4. a store that terminates a page chain early is detected by count mismatch and fails closed;
5. Proof, Exception and Source page sizes are bounded to 1–100;
6. malformed cursors return HTTP 400;
7. cursor JSON `true` cannot be accepted as schema version integer `1`;
8. cursors are bound to exact scope and collection;
9. scope authorization occurs before cursor resolution;
10. `/proofs/page` cannot be captured by the dynamic proof-detail route;
11. existing non-paged API routes remain green;
12. React collection screens fetch bounded pages and can append the next page;
13. scope changes cannot append stale in-flight continuation data;
14. full Python/PostgreSQL, frontend, build and frozen evaluation checks remain green.

## Local validation checkpoint

The exact pre-commit working tree passed:

- Ruff across the whole repository;
- strict mypy across **75 source files**;
- **539 Python/PostgreSQL tests** with `REFLOW_RECOVERY_DOCKER_DRILL=1`;
- a real PostgreSQL-backed Control Tower traversal of **10,001** scoped immutable artifacts through `ReflowApplicationService`;
- logical backup/restore, webhook + operator-audit restore verification, and physical PostgreSQL 16.15 PITR;
- TypeScript project checking;
- React/Vitest **6/6**, including explicit `Load more` continuation;
- Vite production build;
- frozen Gate 17 scale/persistence verification;
- frozen Gate 19 held-out/failure/summary verification and `EVALUATION.md` check;
- Bandit medium/high: **0 findings**;
- `pip-audit`: **0 known vulnerabilities**;
- npm production/full audits: **0 vulnerabilities**;
- production runtime scan: no `OFFSET` query;
- high-confidence credential scan: no unexpected secret material;
- source hygiene scan: no TODO/FIXME/HACK, `eval`, `exec`, or `shell=True`;
- optimized Python (`python -O`) non-PostgreSQL suite: exit **0** with only the expected pytest assertion warning.

The local validation was followed by required repository closure:

- implementation commit: `d08d028c6830ba5badeee2d6f15cb3ab674b65ce`;
- PR: **#40**;
- exact PR CI: **33800278792**, success with **539 tests**, strict mypy across **75 source files**, frontend **6/6**, production build, recovery drills and frozen Gate 17/19 verification;
- merge commit: `8330a12f2bd170de4897ab483834d94943e603bd`;
- exact merge-triggered `main` CI: **33800798991**, success with the same **539-test** recovery-enabled submission gate and frozen evidence checks.

No PR/main CI failure occurred in Gate 50.

## Non-claims

Gate 50 does not claim:

- O(1) exception-queue reconstruction;
- that first-page projection work is proportional only to page size;
- a materialized exception/proof/source read model;
- snapshot-consistent pagination across independent HTTP requests;
- server-side filtering/search over long exception history;
- reduced deterministic validation of historical case/proof/source dependencies;
- any change to reconciliation, proof, close-readiness or money semantics.

The primary guarantees are removal of the hard 10,000-history ceiling, bounded database query batches, bounded browser collection payloads, and continued fail-closed historical integrity.

## Merge rule — satisfied

The exact implementation head passed required PR CI, PR #40 merged without head movement, and the exact merge-triggered `main` CI passed. Gate 50 is closed.
