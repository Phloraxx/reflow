# Gate 49 — Production observability and operator audit contract

**Started:** 2026-09-03
**Base `main`:** `788258401bcbe948c014909ed7ee1f0524c0937c`
**Working branch:** `hardening/observability-operator-audit`
**Status:** merged and closed

## Purpose

Gate 48 proved a deployable single-host shape and PostgreSQL recovery mechanics. Gate 49 makes that shape operable without giving telemetry new financial authority.

The goal is deliberately narrow:

1. correlate every HTTP request across service logs and responses;
2. emit structured, bounded-cardinality request telemetry;
3. expose a local-only, authenticated Prometheus scrape surface;
4. durably record authenticated human authorization decisions before protected finance data is returned;
5. preserve that operator audit trail through the existing PostgreSQL logical backup/restore path;
6. keep tokens, emails, connection strings, payment/bank payloads and raw URLs out of generic telemetry.

This gate does **not** change reconciliation truth, proof computation, webhook HMAC verification, provider parsing or any money-moving authority.

## External guidance frozen for this gate

### OWASP application logging

OWASP's Logging Cheat Sheet recommends consistent application/security logging and explicitly warns against directly recording access/session tokens, passwords, database connection strings, encryption keys, bank/payment data and other sensitive material. It also recommends sanitization/pseudonymization when identity is useful but the raw identifier is not required.

Reference: https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html

ReFlow therefore logs route templates and generated correlation IDs, not concrete request URLs, query strings, request bodies, authorization headers or raw operator email addresses.

### OpenTelemetry HTTP semantic conventions

OpenTelemetry recommends the stable HTTP server request duration metric and bounded attributes such as HTTP method, route and response status. The documented request-duration advisory bucket boundaries are:

`0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1, 2.5, 5, 7.5, 10` seconds.

References:

- https://opentelemetry.io/docs/specs/semconv/http/
- https://opentelemetry.io/docs/specs/semconv/http/http-metrics/

ReFlow uses those route/method/status concepts and duration buckets while keeping the implementation dependency-free. Unknown/custom HTTP methods collapse to `_OTHER` instead of becoming new metric labels. This is an OTel-compatible shape, not a claim that an OpenTelemetry SDK/collector is deployed.

## Contract

### 1. Correlation identity

Every HTTP request receives a server-generated 32-character lowercase hex request ID. ReFlow does not trust or reuse a caller-supplied correlation header. The ID is returned as `X-Request-ID` and is the join key between generic request telemetry and durable operator-access audit records.

### 2. Generic HTTP telemetry

Both FastAPI services emit one-line JSON events with:

- schema version;
- stable service name;
- generated request ID;
- HTTP method;
- route template, or `unmatched`;
- response status;
- request duration in seconds;
- only a generic error type for an unhandled exception.

The generic event must not include raw path, query string, request/response body, JWT, webhook signature, provider event ID, email, IP address, DSN or exception message.

### 3. Bounded process-local metrics

Each process maintains bounded-cardinality counters/gauges/histograms for:

- active HTTP requests by method;
- completed requests by method + route template + status;
- request-duration histogram using the frozen boundaries above;
- accepted webhook processing outcomes using controlled disposition/outcome/code values;
- authenticated operator authorization decisions using controlled action/decision values.

No scope ID, proof ID, case ID, provider event ID, principal identifier or raw URL is a metric label.

### 4. Metrics exposure boundary

`/internal/metrics` is disabled when `REFLOW_METRICS_TOKEN` is unset/empty. If enabled, the token must be a trimmed 32–4096 byte value and the endpoint requires an exact Bearer token.

The deployment tunnel template rejects `^/internal/metrics$` before public hostname routing. This gives two independent controls:

1. the endpoint is bearer-gated in the application;
2. the supported Cloudflare Tunnel shape does not publish it at all.

### 5. Authenticated operator audit is mandatory in authenticated mode

A Control Tower app cannot be constructed with Cloudflare Access authentication enabled unless an operator audit recorder is present.

For each authenticated scope/evaluation authorization decision, ReFlow durably appends before protected data read:

- UTC timestamp;
- generated request ID;
- SHA-256 of the immutable Cloudflare subject;
- controlled operator action;
- exact reconciliation scope where applicable;
- `allowed` or `denied` decision.

The durable table does not contain operator email, JWT, IP address, query string, raw route, finance payload or session token.

### 6. Fail-closed audit persistence

If an authenticated authorization decision cannot be durably recorded, the Control Tower returns a generic HTTP 503 and does not continue to the protected reader call. Persistence errors and DSNs are not reflected to the client or telemetry.

Unauthenticated requests are not inserted into the durable operator table. This avoids turning public invalid-auth traffic into an unbounded PostgreSQL write-amplification path. Their HTTP 401/route/status remains visible in generic service telemetry.

### 7. Separate audit schema

Operator audit state uses independently versioned PostgreSQL tables:

- `reflow_operator_audit_schema_meta`;
- `reflow_operator_access_audit`.

The audit store exposes append, readiness, bounded recent-read and integrity-count operations only. It has no update/delete mutation API and no generic SQL surface.

### 8. Local inspection only

`python -m reflow.operator_audit_cli --limit 50` is the supported inspection surface for recent records. It is a local CLI, not a public HTTP route. Output remains pseudonymous and never includes the database DSN.

### 9. Backup/recovery inheritance

The operator tables are included naturally in PostgreSQL logical dumps. The existing destructive CI recovery drill is extended so one backup/restore round-trip must reopen both webhook and operator-audit subsystems with initialization disabled and verify retained state.

### 10. Readiness composition

When Cloudflare Access is enabled, Control Tower readiness requires both the application schema and operator-audit schema to be current/reachable. The public webhook readiness semantics remain unchanged.

## Acceptance criteria

1. request IDs are generated server-side and returned on normal responses;
2. HTTP telemetry contains route templates but not concrete identifiers/query values;
3. metrics use bounded route/method/status and controlled outcome labels only;
4. metrics token validation fails closed outside the 32–4096 byte contract;
5. metrics endpoint is 404 when disabled and 401 without the correct bearer token when enabled;
6. Cloudflare tunnel config blocks the metrics path before hostname forwarding;
7. authenticated Control Tower construction without an audit recorder fails;
8. allowed and denied authenticated authorization decisions are durably appended before data access;
9. audit failure returns generic 503 with no secret detail;
10. raw email/JWT/DSN is absent from durable audit rows, generic telemetry and audit CLI output;
11. PostgreSQL restart/readback verifies append-only audit records;
12. logical backup/restore CI verifies the audit table survives recovery;
13. full Python/PostgreSQL, frontend, build and frozen evaluation checks remain green.

## Local validation checkpoint

After the final F-0126/F-0127 review fixes, the exact working tree passed:

- Ruff across the whole repository;
- strict mypy across **75 source files**;
- **535 Python/PostgreSQL tests** with `REFLOW_RECOVERY_DOCKER_DRILL=1`, including logical backup/restore, webhook + operator-audit recovery, and physical PostgreSQL 16.15 PITR;
- TypeScript project checking;
- React/Vitest **5/5**;
- Vite production build;
- frozen Gate 17 scale/persistence verification;
- frozen Gate 19 held-out/failure/summary verification and `EVALUATION.md` regeneration check;
- Bandit medium/high: **0 findings**;
- `pip-audit`: **0 known vulnerabilities**;
- npm production/full audits: **0 vulnerabilities**;
- explicit `cloudflared tunnel --config ... ingress validate`: **OK**;
- ReFlow-specific systemd unit parsing with the intentionally unprovisioned executable path substituted: no unit diagnostics;
- high-confidence credential scan: no unexpected secret material beyond two documented loopback-only reviewer/demo PostgreSQL fixtures;
- source hygiene scan: no TODO/FIXME/HACK, `eval`, `exec`, or `shell=True`;
- optimized Python (`python -O`) non-PostgreSQL suite: exit **0** with the expected pytest warning that interpreter assertions are disabled.

One earlier optimized-mode attempt used a disposable local PostgreSQL listener on port 55433 that disappeared during the run, causing a broad connection-refusal cascade. That result was discarded as environment failure rather than treated as code evidence. The complete normal-mode PostgreSQL/recovery gate was then repeated against the still-running isolated test PostgreSQL on port 55434 and passed all 535 tests.

The local validation was followed by the required repository closure:

- implementation commit: `40cb8582308bf7a92a13e9ad7d71a7cf0f34a94e`;
- PR: **#38**;
- exact PR CI: **33795138071**, success with **535 tests**, strict mypy across **75 source files**, frontend **5/5**, production build and frozen Gate 17/19 verification;
- merge commit: `bd3efd7319af088943561d202ac3385eeb389c86`;
- exact merge-triggered `main` CI: **33795431092**, success with the same **535-test** recovery-enabled submission gate and frozen evidence checks.

No PR/main CI failure occurred in Gate 49. F-0126 and F-0127 were found during the pre-commit local review and fixed before the implementation commit.

## Non-claims

Gate 49 does not provision or claim:

- a Prometheus server, Grafana instance or OpenTelemetry collector;
- centralized/off-host log shipping or log-retention SLA;
- alert routing, paging, dashboards or measured alert latency;
- production SLI/SLO/error-budget values;
- distributed tracing across external services;
- client-IP attribution or forensic network identity;
- audit of operator write actions, because the product still exposes no authenticated operator write API;
- tenant self-service/provisioning;
- a public production deployment.

The process-local metrics reset on service restart by design. Durable operator access decisions do not.

## Merge rule — satisfied

The exact implementation head passed required PR CI, PR #38 merged without head movement, and the exact merge-triggered `main` CI passed. Gate 49 is closed.
