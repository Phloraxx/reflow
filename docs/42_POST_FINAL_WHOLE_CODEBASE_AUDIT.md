# Post-Final Whole-Codebase Audit

**Date:** 2026-09-02
**Base `main`:** `4300f3493fcabb1b1fe4de732c9ce194c7adc1d7`
**Audit branch:** `audit/post-final-whole-codebase`
**Status:** merged green via PR #25 as `71ae9ad039a99b5cf06c1e71d513f99be3231687`; exact merge-triggered `main` CI run `33657418624` passed.

## 1. Why this audit exists

Gates 1–19 had already merged green when the repository was deliberately audited again as a whole system rather than treated as complete because CI passed.

The audit objective was to find disagreements between the stated architecture and the actual runtime capability surface: financial authority, persistence/currentness, scope isolation, evidence reproducibility, optional model transport, UI authority, CI supply chain, resource bounds and reviewer setup.

The frozen Gate 19 seeds, scorer, candidate hashes and first held-out v1 were not changed or rerun in response to audit findings.

## 2. Method

The audit combined:

- line-by-line review of persistence, Control Tower, provider and evaluation boundaries;
- direct adversarial reproducers before fixes;
- branch-aware full-suite coverage;
- full tests under normal Python and optimized `python -O`;
- real PostgreSQL 16.15 integration tests;
- Ruff and strict mypy;
- Bandit medium/high security scan;
- `pip-audit` against the exact reviewer constraints;
- npm production and development audits;
- AST import-cycle and layer-boundary analysis;
- high-confidence current-tree and Git-patch-history secret scans;
- tracked-file/build/cache and local Markdown-link hygiene checks;
- Radon complexity and Vulture high-confidence dead-code review.

A finding was classified as a defect only after a concrete reproducer or a direct contract/runtime contradiction was established.

## 3. Reproduced findings

### F-0085 — durable application artifact forgery / timestamp currentness — high

The public application service accepted arbitrary JSON for typed finance artifact kinds, while the Control Tower inferred the current run from timestamps. A forged run payload could therefore reach the operator-facing read model without changing Gate 7/8/9 proof truth.

**Fix:** typed self-validating application writes, intrinsic ID/scope checks, explicit `LATEST_RUN` CAS currentness and regressions for forged/unpointed runs.

### F-0086 — final Evaluation Lab one gate behind — medium

The finished UI displayed Gate 17 scale/persistence evidence but not Gate 19 final held-out evidence.

**Fix:** `gate19-final-summary-v1`, a compact verified artifact derived from the unchanged held-out and failure-campaign artifacts. The UI reads this compact artifact rather than reparsing the 46.91 MiB raw held-out result per request.

### F-0087 — frozen evidence not required by CI — high

Normal CI could pass while final held-out/report artifacts drifted.

**Fix:** CI now runs the same `make submission-check` reviewer path, including all frozen evidence/report verifiers.

### F-0088 — vulnerable/drifting Python test/bootstrap toolchain — medium

The old `<9` pytest range resolved to an affected pytest 8.4.2 and Python CI resolved ranges afresh.

**Fix:** pytest floor 9.0.3, exact reviewer/CI constraints (currently pytest 9.1.1), pip 26.2.1, pinned PEP 517 build tools, and constrained installation in CI/reviewer commands.

### F-0089 — submission check could skip PostgreSQL — medium

A reviewer could receive success while durability tests were skipped because no DSN was configured.

**Fix:** `submission-preflight` fails clearly unless `REFLOW_TEST_POSTGRES_DSN` is supplied.

### F-0090 — current-pointer semantic stream keys not bound — medium

A valid typed artifact could be published as the current artifact for an unrelated logical stream.

**Fix:** public current-pointer writes bind policy/run to scope, proof to settlement, case observation/investigation to case, and adapter to adapter identity. The lower-level store remains a generic CAS primitive.

### F-0091 — mutable CI bootstrap references — medium

CI used mutable GitHub Action major tags and a mutable PostgreSQL image tag.

**Fix:** exact GitHub Action commit SHAs and PostgreSQL 16.15 OCI digest are pinned.

### F-0092 — frontend retained hidden evaluation denominators — low

The first final-evaluation card hardcoded the denominators `4` and `12`.

**Fix:** numerators and denominators are both stored/verified in the compact summary and rendered from API data.

### F-0093 — model credentials could cross insecure endpoint/redirect boundaries — medium

Optional OpenAI providers accepted arbitrary base URLs. Python's standard redirect behavior can also preserve authorization headers for redirected POST requests.

**Fix:** absolute HTTPS-only endpoints, no embedded URL credentials/fragments, and redirect refusal in the default transport.

### F-0094 — `service.journal` leaked the generic PostgreSQL store — high

A property typed as `Journal` returned the concrete store at runtime, exposing generic artifact/current-pointer mutation methods.

**Fix:** a concrete narrow journal façade exposes only append/read raw-evidence operations.

### F-0095 — direct proof browsing trusted storage scope metadata — high

Gate 9 proofs intentionally have no intrinsic scope. A valid proof could be stored under a caller-selected scope and appear in proof browsing without any run in that scope referencing it.

**Fix:** proof persistence requires its cited raw evidence to be covered by typed manifests in the supplied scope; Control Tower proof browsing independently requires membership in a reconciliation run for that scope.

### F-0096 — unbounded default model HTTP response body — medium

Both default model transports could read an arbitrarily large response before JSON validation.

**Fix:** shared 1 MiB response ceiling with fail-closed oversized-body handling.

### F-0097 — documented bounded adapter-model profile was not actually bounded — medium

Gate 12 documented bounded model samples, but callers could request arbitrary sample counts/schema width/header length.

**Fix:** at most 10 model-facing sample rows, 128 columns and 256 characters per column name.

All findings remain preserved in `FAILURE_LOG.md` with their regression evidence.

## 4. Final behavioral evidence on the repaired tree

Branch-aware full-suite run after F-0097:

- **419/419 Python tests passed** with PostgreSQL enabled;
- overall branch-aware coverage: **79%**;
- Money Graph: **95%**;
- settlement composition proof: **89%**;
- bank receipt proof: **88%**;
- full reconciliation proof: **83%**;
- Control Tower: **87%**;
- persistence: **76%**;
- control plane: **73%**.

The control plane remains the largest meaningful fail-closed branch-coverage debt. The audit did not inflate coverage by adding low-value tests solely to improve the percentage.

The exact repaired working tree also passed `make submission-check` with PostgreSQL 16.15 enabled: Ruff, strict mypy across 66 source files, 419 Python tests, 5 React tests, TypeScript, the Vite production build, the frozen Gate 19 held-out verifier, the 12-check failure campaign, the compact Gate 19 summary, Gate 17 scale/persistence verifiers and generated `EVALUATION.md`.

The final repaired tree also passed **419/419 tests under `python -O`** with PostgreSQL enabled. Pytest emitted only its expected warning that test-module assertions themselves are disabled under optimized Python. This confirms production `assert` statements are not carrying hidden financial/integrity authority.

## 5. Independent security / supply-chain results

On the repaired tree:

- Bandit medium/high: **0 findings**;
- `pip-audit` against `requirements/ci-constraints.txt`: **0 known vulnerabilities**;
- npm production audit: **0 vulnerabilities**;
- npm full/dev audit: **0 vulnerabilities**;
- import cycles across 66 source modules: **0**;
- production imports from `reflow.simulator`: **0**;
- core financial modules importing persistence/UI/OpenAI layers: **0**.

High-confidence credential-pattern scans found no non-synthetic matches in the tracked tree or Git patch history. A synthetic `sk-test_...` fixture remains intentionally present to regression-test redaction.

## 6. Repository hygiene

- no tracked runtime caches, build outputs or Python bytecode;
- no broken local Markdown links;
- no TODO/FIXME/HACK/XXX debt found in the audited production tree;
- no `eval`, `exec` or `shell=True` execution path found;
- frontend remains GET-only and does not use browser persistence for finance state;
- the only tracked file >=1 MiB is the intentionally frozen first-run Gate 19 result (`46.91 MiB`).

The large held-out JSON compresses well in Git and is retained because replacing it would destroy the first-run evidence property. Product UI requests use the compact verified summary instead.

## 7. Complexity / maintainability observations

Independent complexity analysis still identifies large validation/proof functions, especially:

- `settlement_proof._prove_settlement_composition`;
- `control_plane.build_reconciliation_run`;
- `control_plane.EvidenceCoverageCertificate.__post_init__`;
- `investigation._validate_proposal`;
- `control_tower.ControlTowerReader._case_queue`.

These functions are candidates for semantics-preserving decomposition, but no correctness defect was inferred merely from cyclomatic complexity. They are intentionally not refactored during a submission-critical audit without a failing invariant.

Vulture's 100%-confidence findings were only protocol method parameter names required by DB cursor/context-manager signatures, not dead executable code.

## 8. Remaining explicit non-claims / residual debt

This audit does **not** turn ReFlow into a production multi-tenant finance service. Remaining boundaries include:

- no authentication, SSO, RBAC or tenant/session authorization;
- no production connector scheduler/onboarding/secret-rotation service;
- no HA, backups/PITR, retention orchestration or distributed job system;
- fine-grained reference PostgreSQL writes rather than a pooled/batched bulk loader;
- generic artifact-list queries have finite limits and need pagination/indexed read models for very long histories;
- heuristic AI-data redaction is not a DLP system;
- no live-model quality benchmark;
- no authenticated real Razorpay Test Mode settlement/recon accuracy corpus;
- Instant Settlement payout topology remains unsupported;
- the public/read-only demo must remain synthetic until an authenticated boundary exists.

These are product/production limitations, not hidden reconciliation-truth shortcuts.

## 9. Frozen-evidence integrity

The audit did not modify or rerun the Gate 19 held-out seeds, scorer or first-run v1 in response to findings.

The compact final summary is a derived convenience artifact. Its verifier recomputes it from the frozen sources and CI rejects drift. `EVALUATION.md` remains generated from verified evidence.

## 10. Merge rule

This audit branch must not be merged until all of the following pass on the exact branch head:

1. fresh constrained Python installation;
2. PostgreSQL-enabled `make submission-check`;
3. frontend type tests + production build;
4. frozen evidence/report verification;
5. optimized-Python regression run;
6. independent security scans;
7. PR CI on the exact head.

After merge, the exact `main` merge-triggered CI run must also be green before this post-final audit is considered closed.
## 11. Merge evidence

- audit PR: **#25**;
- merge commit: `71ae9ad039a99b5cf06c1e71d513f99be3231687`;
- exact merge-triggered `main` CI: **33657418624**, passed;
- frozen Gate 19 held-out v1/seeds/scorer remained unchanged.

The post-final audit is closed at this merge checkpoint.
