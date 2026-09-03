# Production Authentication and Scope Authorization Contract

**Started:** 2026-09-03
**Base `main`:** `c4922b8c466656bea3c9ee9016818e1fd7235ea7`
**Branch:** `hardening/auth-scope-boundary`

## Goal

Add a production-safe human identity boundary to the read-only Control Tower without changing financial truth, persistence semantics, or the frozen evaluation artifacts.

The browser must not hold Razorpay credentials or a reusable ReFlow API secret. Authentication is delegated to Cloudflare Access; ReFlow verifies the signed Access application JWT at the origin and performs its own authorization for reconciliation scopes.

## Current guidance

This gate is aligned with:

- OWASP ASVS 5.0 authentication/session/authorization requirements;
- Cloudflare Access origin JWT validation guidance;
- RFC 9700 OAuth 2.0 Security Best Current Practice;
- RFC 10017 OAuth 2.0 for Browser-Based Applications.

## Authentication contract

Production mode consumes `Cf-Access-Jwt-Assertion` only. The origin does not trust caller-supplied email, user, role, scope, or proxy identity headers.

The verifier must:

1. require an exact HTTPS Cloudflare Access issuer under `cloudflareaccess.com`;
2. derive JWKS only from that issuer's `/cdn-cgi/access/certs` endpoint;
3. reject redirects, oversized JWKS responses, invalid JSON, and unbounded waits;
4. accept only RS256 application tokens with a non-empty key ID;
5. verify signature, expiry/not-before, exact issuer, and configured application audience;
6. require token `type=app` and a non-empty human `sub` plus email;
7. refresh bounded JWKS cache once when a signing key rotates;
8. return generic authentication failures without token/claim/JWKS detail leakage.

Service-token-only identities are not admitted to the human Control Tower in this gate.

## Authorization contract

Authorization is server-side and independent of the browser `scope` query parameter.

A versioned local policy file maps an exact verified email to:

- one or more fixed roles;
- an explicit list of permitted `ReconciliationScopeId` values.

Initial roles are intentionally narrow:

- `scope_viewer` — may read finance data only for explicitly granted scopes;
- `evaluation_reviewer` — may read the global frozen evaluation surface.

There is no wildcard email/domain matching and no implicit scope inheritance. Unknown principals, unknown roles, duplicate principal entries, malformed scope IDs, and empty grants fail policy loading or authorization closed.

## HTTP behavior

Infrastructure endpoints remain unauthenticated:

- `GET /api/v1/health`;
- `GET /api/v1/ready`.

Every `/api/v1/scopes/{scope_id}/...` route requires an authenticated principal with `scope_viewer` and an exact matching scope grant. `GET /api/v1/evaluation` requires `evaluation_reviewer`.

Missing or invalid identity returns generic `401`. A valid identity without permission returns generic `403`. Cross-scope probing must not fall through to another scope or disclose whether a denied artifact exists.

The SPA shell/static assets may still be served by the origin; finance data remains inaccessible without the authenticated API boundary. Cloudflare Access should protect the whole public hostname as the outer control.

## Deployment modes

`REFLOW_AUTH_MODE` is mandatory for environment-based serving. There is no implicit unauthenticated default.

`REFLOW_AUTH_MODE=disabled` is an explicit synthetic/local-reviewer opt-in. It is not authorized for public real-merchant data.

`REFLOW_AUTH_MODE=cloudflare_access` requires issuer, AUD and authorization-policy path at startup. Missing or malformed production auth configuration prevents application creation.

## Acceptance criteria

1. verified Access JWT + granted scope can read that scope;
2. missing/invalid token returns 401 without claim leakage;
3. wrong issuer, audience, algorithm, token type, expired/not-yet-valid token are rejected;
4. unknown signing key triggers at most one bounded JWKS refresh;
5. redirects and oversized JWKS responses fail closed;
6. verified identity without scope grant returns 403;
7. a grant for scope A cannot read scope B even when B exists;
8. evaluation requires its dedicated role;
9. health/readiness remain available without user authentication;
10. disabled mode preserves the existing synthetic reviewer behavior;
11. production auth startup fails closed on missing/invalid configuration;
12. policy parser rejects duplicate principals, unknown roles and malformed scopes;
13. auth errors never serialize JWTs, emails from invalid tokens, JWKS bodies, or configuration secrets;
14. no authentication code can mutate financial truth or operator workflow;
15. the entire existing PostgreSQL/frontend/submission suite remains green.

## Deferred

This gate does not add user provisioning UI, SCIM, OAuth client implementation, password storage, refresh tokens, authenticated operator writes, or tenant onboarding. Cloudflare Access/IdP owns interactive authentication and session lifecycle; later write endpoints will require a separate authorization/step-up review.

## Implemented checkpoint

The gate now adds a dedicated `reflow.access_auth` boundary under the optional web surface. It verifies Cloudflare Access application JWTs against bounded, no-redirect JWKS retrieval and maps verified human identities to immutable in-process authorization grants loaded from a versioned local JSON policy.

The FastAPI Control Tower now applies authentication before scope parsing in authenticated mode, then requires exact `scope_viewer` authorization for every finance scope route. The global evaluation route independently requires `evaluation_reviewer`. Health/readiness remain infrastructure endpoints and no route gains financial mutation authority.

Environment-based serving now requires an explicit `REFLOW_AUTH_MODE`; missing mode fails startup. The synthetic reviewer demo must explicitly choose `disabled`, while real merchant serving uses `cloudflare_access` with issuer, AUD and policy path.
## Validation checkpoint

On the exact auth-gate worktree after the explicit-mode hardening:

- `make submission-check`: passed;
- Ruff: passed;
- strict mypy: passed across 68 source modules;
- Python/PostgreSQL: 492 tests passed;
- TypeScript and Vite production build: passed;
- React/Vitest: 5/5 tests passed;
- frozen Gate 17/Gate 19 artifacts and `EVALUATION.md`: verified unchanged;
- the full PostgreSQL-enabled suite passes under `python -O`;
- Bandit medium/high: 0 findings;
- `pip-audit`: 0 known vulnerabilities;
- `pip check`: no broken requirements;
- npm production/full audits: 0 vulnerabilities;
- `git diff --check`: passed.