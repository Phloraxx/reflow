# Gate 18 Contract and Acceptance Plan — Operator Control Tower

## Status

Gate 18 starts from final verified Gate 17 `main`:

`95164be82a149419b936c529b57510eb17b6c317`

Final Gate 17 CI run `33535214302` passed on that exact SHA. This contract is frozen before Gate 18 implementation.

## Thesis

> Make ReFlow understandable and operable without turning the UI into a second reconciliation engine or a chatbot homepage.

The product surface is a finance-truth control tower over immutable Gate 13–17 state. It may summarize, filter, format and navigate evidence; it may not manufacture financial truth.

## 1. Product surfaces

Gate 18 must ship six coherent surfaces:

1. **Run / Close Overview** — current run identity, scope/period, close readiness, exact coverage/no-orphan state, balance residual, source completeness and proof-status value/count distribution.
2. **Settlement Proof** — authoritative settlement amount, Gate 7 composition equation/status, Gate 8 bank proof/status, Gate 9 combined status/reasons, provenance IDs and version timeline.
3. **Exception Queue** — one current row per economic case with age, materiality, affected amount, current financial status, workflow status/owner, fingerprint/incident and source blockers.
4. **Case File** — case chronology, proof link/current proof, source-state changes, residual/reason evidence, operator disposition chronology and bounded Gate 16 investigation result/trace when present.
5. **Source Lab** — source-delivery manifest completeness, late state, delivery mode, adapter/schema fingerprint and evidence counts. No raw-secret/payload browser in Gate 18.
6. **Evaluation Lab** — checked-in self-verifying benchmark artifacts and disclosed hardware/runtime; no hand-edited headline metric.

The investigation agent appears only inside Case File. There is no global chat surface.

## 2. Backend/API contract

Use a small FastAPI read API over Gate 17 persistence/application state. Financial endpoints require an explicit `scope_id`; cross-scope fallback is forbidden.

Minimum routes:

- `GET /api/v1/scopes/{scope_id}/overview`
- `GET /api/v1/scopes/{scope_id}/proofs`
- `GET /api/v1/scopes/{scope_id}/proofs/{proof_id}`
- `GET /api/v1/scopes/{scope_id}/exceptions`
- `GET /api/v1/scopes/{scope_id}/cases/{case_id}`
- `GET /api/v1/scopes/{scope_id}/sources`
- `GET /api/v1/evaluation`
- `GET /api/v1/health`

No endpoint may mark a proof green, alter a proof/case observation, execute arbitrary SQL, issue money movement or auto-execute Gate 16 suggestions.

Gate 18 may expose a bounded append-only operator-disposition endpoint only if it delegates to the existing Gate 14 disposition semantics with authenticated actor context. Authentication is not implemented yet, so Gate 18 v1 is read-only. Do not add a fake unauthenticated mutation path for demo convenience.

## 3. Read-model truth boundary

The API reads only immutable `StoredArtifact` records and Gate 17 current pointers/list queries. It never reconstructs hidden simulator truth.

Allowed derived presentation values:

- exact integer-paise sums grouped by already-established proof/case status;
- counts;
- age/duration from persisted timestamps;
- canonical sorting/filtering;
- formatted display strings.

Derived UI aggregates are presentation metadata, not new proof artifacts. They must be labeled as derived where ambiguity is possible.

Every proof/card must retain its underlying immutable artifact ID(s). No UI badge may change a Gate 7/8/9/13/14 status.

## 4. Scope isolation

Every finance read is anchored to one `ReconciliationScopeId` supplied in the route. A referenced artifact with a different scope must be treated as unavailable/integrity failure, not silently returned.

Evaluation artifacts are global repository evidence and therefore separate from merchant-scoped financial endpoints.

## 5. API money contract

Money in API responses uses:

- `amount_paise: int`;
- ISO-like currency enum string from the domain;
- backend-generated human display string.

The frontend does not recompute reconciliation equations or status. It may only format/navigation-render values supplied by the API.

Mixed-currency aggregation is rejected rather than silently converted.

## 6. Frontend contract

Use React + TypeScript + Vite. The UI should feel like an instrument panel / debugger / case file, not a generic admin dashboard.

Visual hierarchy:

- dark/neutral evidence workspace with high-contrast status semantics;
- compact source-health rail;
- proof equation as the hero object on proof detail;
- explicit residual marker and reason codes;
- timeline/version-diff language for case/proof history;
- monospace treatment for immutable IDs/hashes;
- tables only where density is useful, with strong drill-down hierarchy.

The app must support desktop first and remain usable at tablet/mobile widths. It must not rely on hover for essential content.

## 7. Frontend information architecture

Primary navigation:

- Overview
- Proofs
- Exceptions
- Sources
- Evaluation

Case File and Proof Detail are drill-down routes, not top-level nav.

The active scope is visible at all times. Gate 18 v1 accepts a scope ID through configuration/URL state rather than implementing tenant authentication.

## 8. Loading/error/empty-state contract

Each surface needs explicit:

- loading state;
- empty state;
- API/integrity error state;
- no-current-run state where relevant.

`NOT_READY`, `RESIDUAL`, `CONTRADICTED`, `WAITING` and `PROVEN` remain visually distinct. Unknown/missing state must never be rendered green.

## 9. Evaluation Lab contract

Evaluation Lab reads only checked-in artifacts under `data/eval/` through a bounded backend reader.

It shows artifact schema/digest, workload, hardware/runtime disclosure and measured metrics. It must verify each artifact before returning it. Gate 17 scale artifacts and persistence artifacts use their existing verifier functions.

The UI may not invent averages/extrapolate 100k/1M results from the measured 10k tier.

## 10. API/application packaging

FastAPI/Pydantic are optional `web` dependencies. PostgreSQL remains the deployment persistence target. The API can be instantiated against a structural read-store protocol so unit tests do not require PostgreSQL; real PostgreSQL integration remains in CI.

No ORM is introduced. No Redis/Kafka/Celery/Kubernetes is introduced.

## 11. Frontend build/CI

`web/` contains the React/TypeScript application with a committed lockfile.

CI must run:

- Python Ruff/mypy/pytest including API/read-model tests;
- PostgreSQL integration as in Gate 17;
- `npm ci`;
- TypeScript/static checks;
- frontend unit tests;
- production Vite build.

No secret/API key is required to build or test the UI.

## 12. Acceptance tests frozen before implementation

1. final Gate 17 SHA/CI are recorded as Gate 18 base;
2. overview returns the latest run for the requested scope only;
3. overview status/value counts equal persisted proof/case artifacts exactly;
4. mixed-currency overview aggregation fails closed;
5. close-readiness/coverage/balance IDs are retained in the overview;
6. no-current-run produces explicit empty state, not fake READY;
7. proof list is scope-filtered and canonical/recent ordered;
8. proof detail exposes exact Gate 7/8/9 statuses and source-envelope IDs;
9. proof detail cannot return a proof referenced by another scope;
10. exception queue emits one latest row per case;
11. exception ordering prioritizes materiality then age without changing truth;
12. latest operator owner/workflow is derived only from persisted dispositions/observations;
13. case file chronology is stable and timestamp ordered;
14. case file binds Gate 16 investigation only when target case/proof IDs match;
15. source lab exposes completeness/late/schema/adapter metadata without raw payload content;
16. source lab does not leak another scope's manifests;
17. evaluation endpoint verifies artifact digests before returning metrics;
18. tampered evaluation artifact is rejected;
19. every financial API endpoint requires an explicit scope path;
20. API has no route containing reconciliation-truth mutation verbs/capabilities;
21. read model imports no simulator truth;
22. frontend routes exist for Overview/Proofs/Exceptions/Sources/Evaluation plus Proof/Case detail;
23. frontend renders explicit loading/empty/error states;
24. frontend shows active scope and immutable artifact IDs;
25. frontend never derives proof status from monetary arithmetic;
26. proof page renders equation values supplied by API and visible residual/reason markers;
27. exception queue supports status/materiality/source-blocker filtering client-side without mutating data;
28. essential content is keyboard/touch reachable and not hover-only;
29. TypeScript check, frontend tests and production build pass in CI;
30. full Python repository regression suite remains green with PostgreSQL CI service.

## 13. Explicit non-goals

Gate 18 does not implement:

- authentication/SSO/RBAC;
- unauthenticated operator writes;
- refunds/payouts/transfers;
- full accounting/ERP posting;
- raw secret/payload explorer;
- generic SQL console;
- chatbot homepage;
- live notifications/websockets;
- multi-tenant onboarding;
- final held-out failure campaign/submission metrics.

These remain Gate 19 or post-Buildathon concerns.

## 14. Definition of done

Gate 18 is complete when a reviewer can open the control tower and understand, without a prompt:

1. whether the current run is close-ready and why;
2. exactly how a settlement was or was not proven;
3. what exceptions need attention and what evidence is blocking them;
4. what sources arrived/are late and under which adapter/schema;
5. what the bounded investigator proposed inside a case;
6. which measured benchmark artifacts support the scale claims.

Every displayed truth status must trace to immutable backend artifact IDs.
