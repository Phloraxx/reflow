# Production Readiness Phase 1

**Started:** 2026-09-03
**Base `main`:** `55e490936119ee2769343ec01001f6d392fa0ace`
**Branch:** `hardening/production-readiness-phase1`

## Purpose

The third whole-codebase audit is closed. This phase does not extend or retune that evidence.

Phase 1 establishes the minimum operational boundaries needed before ReFlow is exposed to real merchant evidence:

1. liveness and dependency-aware readiness are separate;
2. Razorpay API access is bounded, HTTPS-only and non-redirecting;
3. real Test Mode settlement/recon acquisition is paginated and replayable;
4. raw private Razorpay payloads are never emitted into checked-in acceptance reports;
5. real-data claims remain impossible when the source corpus is empty;
6. public webhook ingress is not admitted until its acknowledgement/error policy is explicit and regression-tested;
7. tenant authentication/RBAC is designed separately rather than approximated with `scope_id`.

## Current external facts re-verified

Official Razorpay documentation currently confirms:

- Settlement Recon: `GET /v1/settlements/recon/combined`, with `year`/`month`, optional `day`, `count` up to 1000 and `skip` pagination.
- Standard settlements: `GET /v1/settlements/`, with `count` up to 100 and `skip` pagination.
- API authentication uses separate Test/Live API keys.
- Webhook HMAC verification must use the exact raw request bytes before parsing.
- Webhooks are at-least-once and can arrive out of order; `x-razorpay-event-id` is the documented duplicate identity.
- Non-2xx webhook responses are retried with exponential backoff for up to 24 hours and persistent failure can disable the webhook.

References:

- https://razorpay.com/docs/api/settlements/fetch-recon/
- https://razorpay.com/docs/api/settlements/fetch-all/
- https://razorpay.com/docs/webhooks/validate-test/
- https://razorpay.com/docs/webhooks/best-practices/
- https://razorpay.com/docs/payments/dashboard/test-live-modes/

## Phase 1 acceptance criteria

### A. Readiness

1. `/api/v1/health` remains a side-effect-free liveness signal.
2. `/api/v1/ready` verifies the durable PostgreSQL dependency on every request.
3. readiness returns 503 with a non-sensitive error body when the dependency probe fails.
4. the production environment factory wires readiness to the same PostgreSQL store used by the Control Tower.
5. schema-version disagreement fails readiness instead of presenting the process as healthy-for-traffic.

### B. Razorpay API acceptance client

6. the client uses only the fixed `https://api.razorpay.com/v1` origin by default;
7. redirects are rejected so Basic credentials cannot move to another origin;
8. request timeout and response bytes are bounded;
9. settlements paginate with `count=100` and monotonic `skip`;
10. Settlement Recon paginates with `count=1000` and monotonic `skip`;
11. malformed collection responses fail closed;
12. page count and total retained records have explicit safety caps;
13. Test and Live evidence origins remain explicit and cannot be inferred from payload shape.

### C. Real-data acceptance report

14. an acceptance run refuses to claim success when settlement or recon corpus is empty;
15. provider entities are compiled through the existing Gate 15 journal-first functions rather than a second parser;
16. the report contains only counts, IDs/digests and aggregate diagnostics required for verification;
17. raw Razorpay payloads, API key material and Authorization headers are never serialized into the report;
18. every compiled settlement/recon fact is backed by a retained `SourceEnvelope`;
19. settlement/recon overlap and orphan counts are explicit;
20. the report states `REAL_TEST_MODE` or `REAL_LIVE` only from configured execution context.

## Deliberately deferred

- public webhook HTTP ingress, until acknowledgement/retry semantics have a durable operator-visible failure record;
- multi-tenant authentication and RBAC;
- SSO/OIDC provider choice;
- bank connector credentials and production bank ingestion;
- HA, backup/PITR automation and deployment orchestration;
- Instant Settlement `setlod_` / `setlodp_` proof topology;
- live-model quality claims.

A `scope_id` is never authorization. Real merchant data must not be exposed through the current unauthenticated Control Tower.

## Current connected-account observation

On 2026-09-03, authenticated Test Mode acceptance was executed with privately supplied credentials. The account returned zero orders, zero payments, zero standard settlements, and zero Settlement Recon rows for every month January through September 2026. The harness correctly failed closed and wrote no acceptance report. The connected Razorpay account independently returned zero settlements/recon rows. This is authenticated empty-corpus evidence, not a real-settlement accuracy corpus.

## Implemented checkpoint

Phase 1 now adds:

- `PostgresApplicationStore.check_ready()`, which verifies database reachability and the exact supported schema version without mutating state;
- `/api/v1/ready`, separate from the existing side-effect-free `/api/v1/health`;
- fail-closed 503 readiness when no probe is configured or the dependency probe fails, without returning DSN/exception details;
- `reflow.razorpay_acceptance`, a bounded read-only client for standard settlements and Settlement Recon;
- fixed Razorpay API origin, redirect refusal, Basic-auth header isolation, finite timeout and response-size caps;
- documented `count`/`skip` pagination for settlements and recon with page/record safety limits;
- Test/Live evidence-origin binding to `rzp_test_` / `rzp_live_` key modes;
- a privacy-preserving acceptance report containing aggregate counts and SHA-256 bindings rather than raw provider payloads;
- explicit refusal to produce a successful acceptance report from an empty settlement or recon corpus;
- `data/generated/` as the documented private report destination, which is already ignored by Git.

## Validation checkpoint

On the exact Phase 1 worktree:

- `make submission-check`: passed;
- Ruff: passed;
- strict mypy: passed across 67 source modules;
- Python/PostgreSQL: 480 tests passed;
- TypeScript project check: passed;
- React/Vitest: 5/5 tests passed;
- Vite production build: passed;
- frozen Gate 19 held-out/failure/summary evidence: verified unchanged;
- Gate 17 scale/PostgreSQL artifacts and generated `EVALUATION.md`: verified unchanged;
- the full PostgreSQL-enabled suite also passed under `PYTHONOPTIMIZE=1`;
- Bandit medium/high: 0 findings;
- `pip-audit`: 0 known vulnerabilities;
- npm production/full audits: 0 vulnerabilities;
- high-confidence production-tree secret scan: no matches;
- TODO/FIXME/HACK and unsafe dynamic execution scan: no matches;
- `git diff --check`: passed.

## Merge closure

Phase 1 is closed. PR #29 merged as `c4922b8c466656bea3c9ee9016818e1fd7235ea7`; exact merge-triggered `main` CI run `33763965048` completed successfully. Real Razorpay acceptance remains pending until the account supplies a non-empty settlement/recon corpus; this merge does not change that non-claim.
