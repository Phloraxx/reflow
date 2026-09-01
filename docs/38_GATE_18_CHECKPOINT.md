# Gate 18 Checkpoint — Operator Control Tower

## Status

Gate 18 starts from final verified Gate 17 `main`:

`95164be82a149419b936c529b57510eb17b6c317`

Final Gate 17 CI run `33535214302` passed on that exact SHA.

Gate 18 implementation checkpoints on `build/gate-18-operator-control-tower`:

- contract: `9c17065b8d94b04fad65fb6619cb0a8e22b0af73`;
- read model + FastAPI: `84fc18a5a16243f93b6e0f273b9d23d7b783cdf2`;
- React control tower + CI: `788c914d850708b9cc04603b2b15509670b73be9`;
- reproducible demo + same-origin serving/F-0082 fix: `2f8f6b143fb571c5ff35eed0265d456c1818cf2a`.
- reviewer workflow / env / `make check` hardening: `df08a770195d1475829b31ab4b131e85a7af1525`.

PR/merge CI is pending at this checkpoint.

## 1. Product result

Gate 18 turns ReFlow from a reference finance engine into a reviewable operator product without creating a second reconciliation engine.

The primary product surface is now a **read-only finance-truth control tower**, not a chatbot.

A reviewer can inspect:

1. current run / Close Readiness;
2. exact settlement proofs;
3. exception queue and case files;
4. source completeness/schema state;
5. bounded Gate 16 investigation inside the case;
6. checked-in Gate 17 benchmark evidence.

The UI never decides whether money reconciles.

## 2. Backend read model

`src/reflow/control_tower.py` projects immutable Gate 13–17 artifacts into bounded product read models.

Every finance read requires an explicit `ReconciliationScopeId`.

The reader fails closed on:

- cross-scope artifact references;
- wrong artifact kinds;
- malformed/missing financial values;
- mixed-currency aggregation;
- invalid case/disposition chronology;
- investigation records bound to another case/proof;
- tampered evaluation artifacts.

It does not expose SQL, proof mutation or money movement.

## 3. API surface

`src/reflow/control_tower_api.py` exposes:

- `GET /api/v1/health`;
- `GET /api/v1/scopes/{scope_id}/overview`;
- `GET /api/v1/scopes/{scope_id}/proofs`;
- `GET /api/v1/scopes/{scope_id}/proofs/{proof_id}`;
- `GET /api/v1/scopes/{scope_id}/exceptions`;
- `GET /api/v1/scopes/{scope_id}/cases/{case_id}`;
- `GET /api/v1/scopes/{scope_id}/sources`;
- `GET /api/v1/evaluation`.

There are no POST/PUT/PATCH/DELETE product routes in Gate 18.

`/api/v1/health` explicitly reports:

- `mode = read_only`;
- `financial_truth_mutation = false`;
- `generic_sql = false`.

## 4. Run / Close Overview

The overview is derived from the current persisted run and its exact referenced artifacts.

It includes:

- run ID, period, cutoff and build SHA;
- Close Readiness status/reasons;
- coverage/no-orphan state;
- balance-control status/residual;
- proof-status counts and exact values;
- source delivery states;
- exception counts/materiality.

A scope with no current run renders an explicit empty state. It does not fabricate `READY`.

## 5. Settlement Proof surface

Proof detail shows API-supplied Gate 7/8/9 facts:

- authoritative settlement amount;
- composition observed value and exact residual;
- bank expected amount, observed credit and exact residual;
- composition/bank/full proof statuses;
- reason codes;
- UTR when present;
- source-envelope provenance IDs;
- proof version lineage.

The frontend formats those numbers but does not recompute proof status.

## 6. Exception Queue and Case File

The queue emits one current row per persisted economic case.

It exposes:

- financial status;
- affected amount;
- age;
- materiality;
- workflow status;
- owner;
- incident fingerprint/cluster;
- source blockers.

Client-side filters affect presentation only.

Case File adds:

- observation chronology;
- operator disposition chronology;
- current proof link;
- source-state changes;
- exact residual/reason context;
- latest matching Gate 16 investigation result and trace.

A Gate 16 investigation bound to a different case/observation/proof is rejected by the read model.

## 7. Source Lab

Source Lab intentionally exposes metadata rather than raw payload content:

- source kind;
- delivery manifest ID;
- completeness;
- late state;
- delivery mode;
- expected/received/watermark times;
- adapter version;
- schema fingerprint;
- delivered/effective evidence counts.

This keeps raw merchant/customer evidence out of the default operator UI.

## 8. Evaluation Lab

Gate 18 needed benchmark verification without importing hidden simulator truth into the product backend.

Verification-only Gate 17 artifact logic was therefore moved to:

`src/reflow/evaluation/benchmark_artifacts.py`

The scale/persistence runners use the same verifier functions, while the control tower can validate checked-in artifacts without importing `reflow.simulator`.

Evaluation Lab exposes only verified checked-in evidence and does not extrapolate an unmeasured 100k/1M result.

## 9. React control tower

`web/` is a React 19 / TypeScript / Vite application.

The visual language is intentionally closer to a debugger/ledger/instrument panel than a generic SaaS dashboard.

Primary routes:

- `/` — Overview;
- `/proofs`;
- `/proofs/:proofId`;
- `/exceptions`;
- `/cases/:caseId`;
- `/sources`;
- `/evaluation`.

The shell keeps reconciliation scope visible and labels the product `READ ONLY`.

Essential information is not hover-only and the layout is responsive for desktop/tablet/mobile widths.

## 10. Frontend/toolchain checkpoint

Oracle validation used:

- React `19.2.8`;
- React Router `7.18.3`;
- Vite `8.2.2`;
- TypeScript `7.0.2`;
- Vitest `4.1.11`;
- Node `20.20.2`.

Node-22-only test utilities were not forced onto the Oracle runtime. `jsdom`/`jest-dom` are pinned to Node-20-compatible versions.

Final production build at the checkpoint:

- HTML: ~0.46 kB;
- CSS: ~18.43 kB (~4.46 kB gzip);
- JS: ~266.06 kB (~82.61 kB gzip).

These are bundle sizes, not performance/SLO claims.

## 11. Same-origin application serving

FastAPI can serve the built `web/dist` application and `/api` from one origin.

Environment variables:

- `REFLOW_POSTGRES_DSN` — required application PostgreSQL DSN;
- `REFLOW_EVALUATION_ROOT` — optional verified evaluation-artifact directory;
- `REFLOW_WEB_DIST` — optional explicit built frontend directory.

If `REFLOW_WEB_DIST` is not set and `web/dist` exists in the current working directory, it is used automatically.

Unknown `/api/*` routes remain API 404s. Non-API client routes use the SPA index fallback.

## 12. F-0082 — SPA history fallback

The real Uvicorn smoke test found that the first same-origin implementation used Starlette `StaticFiles(..., html=True)` at `/`.

`/` worked, but direct navigation to `/exceptions?scope=...` returned 404.

The fix:

- mounts only `/assets` as static files;
- serves `/` explicitly;
- returns `index.html` for non-API client routes;
- preserves 404 for unknown `/api/*` paths.

Regression tests and a real Uvicorn/curl smoke test now cover this boundary.

Financial truth impact: none. This was UI deployment routing only.

## 13. F-0083 — reviewer command Python executable assumption

The final documented-state validation then found that `make check` still hard-coded `python`. Oracle has Python 3.12 as `python3` and a valid `.venv/bin/python`, but no global `python` alias.

The Makefile now prefers `.venv/bin/python` when the project venv exists and otherwise falls back to `python3`. README explicitly creates and activates the venv before install/check commands. The exact `make check` path then completed Ruff, mypy, all 396 Python/PostgreSQL tests, all 5 frontend tests and the production Vite build; only a documentation EOF whitespace check remained and was cleaned afterward.

Financial truth impact: none. This was repository packaging/reviewer reproducibility only.

## 14. Deterministic synthetic demo

`src/reflow/evaluation/control_tower_demo.py` creates a clearly synthetic demonstration corpus by running the existing deterministic ReFlow pipeline rather than writing hand-authored dashboard JSON.

It creates a non-green standard-settlement scenario with a late/missing bank source and persists:

- source evidence;
- scope/policy/manifests;
- Gate 9 proof;
- coverage/balance/close artifacts;
- Gate 13 run;
- Gate 14 case observation/disposition/incident cluster;
- validated deterministic Gate 16 investigation result/trace.

Oracle demo scope at the checkpoint:

`scope_191d74319bb8632a190c5b77`

The resulting story was:

- Close Readiness: `not_ready`;
- proof: `pending_bank_credit`;
- materiality: `critical`;
- case workflow: `awaiting_source`;
- source blocker: `bank:late`;
- investigation action: `REQUEST_SOURCE`.

This is demo/regression evidence only, not a real Razorpay merchant accuracy claim.

## 15. Final Oracle validation

On the exact post-F-0082 implementation tree:

```text
Ruff: passed
strict mypy: passed across 61 source files
pytest with PostgreSQL 16: 396 passed
frontend TypeScript check: passed
frontend Vitest: 5 passed
frontend production Vite build: passed
git diff --check: passed after EOF hygiene cleanup
control-tower simulator-truth / MARK_RECONCILED / TODO / FIXME scan: clean
```

The full test run used a disposable PostgreSQL 16 container configured with the same user/database shape as CI. The container was removed after validation.

## 16. Real service smoke evidence

Against the seeded PostgreSQL demo and built Vite output, Uvicorn returned:

```text
GET /                                           -> 200
GET /exceptions?scope=<demo-scope>              -> 200 (SPA shell)
GET /api/v1/not-a-route                         -> 404
GET /api/v1/scopes/<demo-scope>/overview        -> not_ready, one non-green proof
```

This verifies the same-origin packaging path, not a public deployment.

## 17. CI changes

Gate 18 CI now validates both product halves in one job:

1. PostgreSQL 16 service;
2. Python install with dev/postgres/web extras;
3. Ruff;
4. strict mypy;
5. Python/PostgreSQL pytest;
6. Node 20.20.2 + `npm ci`;
7. TypeScript check;
8. Vitest;
9. Vite production build.

No Razorpay key, OpenAI key or other external secret is required for CI.

## 18. Non-claims / remaining limitations

Gate 18 is not a production multi-tenant finance application.

It does **not** provide:

- authentication/SSO;
- RBAC/tenant authorization;
- a secure merchant scope-discovery/session layer;
- operator write APIs;
- production webhook ingress;
- secret management;
- rate limiting/WAF/security-header policy;
- backups/PITR/HA;
- websocket/live notification infrastructure;
- public deployment evidence;
- a final held-out accuracy claim.

The `scope` query/path value is a routing identifier, **not an authorization control**.

The read-only API reduces risk but does not remove the need for authentication before exposing real merchant evidence publicly.

## 19. Gate 19 next

Gate 19 is the final failure campaign + held-out evidence + submission hardening phase.

It begins only after Gate 18 PR CI, merge and merge-triggered `main` CI are green.

Gate 19 should attack the finished product end to end, freeze final scorers/policies before held-out runs, produce reproducible submission evidence, and prepare the five-minute demo without hand-edited headline metrics.
