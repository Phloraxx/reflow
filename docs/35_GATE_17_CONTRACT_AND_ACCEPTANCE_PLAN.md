# Gate 17 Contract and Acceptance Plan — Scale + Durability/Application Layer

## Status

Gate 17 starts from final verified Gate 16 `main`:

`c2b849da713beaa2ed55abc9e1776facca76817f`

Gate 16 implementation, post-merge metadata, and merge-triggered `main` CI are green. Gate 17 may change execution strategy and persistence, but it must not weaken or redefine any Gate 7–16 financial, provenance, case, workflow, or AI-safety invariant.

## Thesis

> Measure the existing one-process engine first, remove proven algorithmic waste, then add only the durable PostgreSQL-backed product state and application boundary required for replayable operation.

No Kafka, Kubernetes, distributed workflow engine, sharding, or microservice split is admitted unless benchmark evidence proves one-process/PostgreSQL insufficient.

## Pre-implementation benchmark finding

The first clean Oracle baseline at 50 settlements expanded to 6,084 raw rows because the simulator includes high-cardinality settlement cases. It measured approximately 6.6k raw rows/s ingestion, 18.3 settlements/s in the ReFlow proof core, 3.73 s total wall time, and 34 MiB maximum RSS.

A cProfile run on the same 50-settlement workload attributed about 7.0 of 9.8 profiled seconds to Gate 7 composition proof generation, specifically repeated `_required_provenance_edges()` scans. That function scanned the entire Money Graph for every recon row, producing roughly 13.8 million `EntityId.__str__` calls in the small workload. This is measured algorithmic waste and must be fixed before larger scale claims are attempted.

The pre-optimization 1,000-settlement baseline was intentionally allowed to continue separately to capture an honest comparison point; 10k+ runs are deferred until the measured O(rows × edges) provenance scan is removed.

## 1. Scale contract

Gate 17 must provide a reproducible scale runner that reports, at minimum:

- settlement count;
- raw input row count;
- journal entry count;
- exception/failure profile;
- ingestion wall time and rows/s;
- Money Graph/proof wall time and settlements/s;
- end-to-end wall time;
- maximum resident memory;
- deterministic status counts;
- benchmark seed/profile;
- Python/runtime version;
- CPU count and host description;
- database mode and worker/process count.

Required measured tiers are 50, 1,000 and 10,000 settlements after optimization. 100,000 is a stress target if the preceding tier is safe on the available Oracle VM. 1,000,000 is explicitly optional and must not be claimed unless actually run.

The benchmark must distinguish clean and adversarial/exception-heavy input. It must not import hidden truth into production reconciliation code. Hidden truth may remain isolated inside evaluation tooling for accuracy scoring.

## 2. Gate 7 performance invariant

The provenance optimization must preserve exact Gate 7 outputs. A graph-edge index may replace repeated whole-graph scans, but the accepted proof must still require both authoritative source-backed edges per recon component with exact source envelope identity and `EXACT_SOURCE_IDENTIFIER` reason evidence.

Acceptance requires byte-equivalent/content-equivalent proof fields versus the pre-optimization semantics across existing fixtures, permutations, duplicate/conflict cases and provider-shaped Gate 15 evidence.

No cache may cross a canonical batch boundary or allow stale evidence from another scope/run.

## 3. Durable raw-evidence journal

Gate 17 adds a PostgreSQL implementation of the existing append-only journal contract.

Required semantics:

- exact `SourceEnvelope` self-validation before persistence;
- immutable envelope row keyed by `SourceEnvelopeId`;
- stable `(source_kind, source_record_id)` primary identity;
- exact replay returns `DUPLICATE` and the original primary envelope;
- conflicting payload under the same stable source identity is retained as a separate immutable envelope before the call fails closed;
- `get`, `get_by_id`, `entries`, and length semantics match `InMemoryJournal`;
- entries remain deterministically ordered;
- restart/reconnect preserves all retained evidence;
- no UPDATE/DELETE API for raw evidence.

A transaction must never turn a retained conflict into accidental absence.

## 4. Immutable product artifact store

Gate 17 persists product artifacts as immutable canonical JSON records rather than duplicating the domain model into an ORM hierarchy.

The minimum artifact kinds are:

- reconciliation run;
- Gate 9 proof version;
- Gate 13 source manifest/control certificate;
- Gate 14 case observation;
- Gate 14 operator disposition;
- Gate 14 incident cluster;
- approved adapter version/approval evidence;
- Gate 16 investigation result/tool trace.

Each stored artifact binds:

- artifact kind;
- immutable artifact ID;
- optional explicit reconciliation scope ID;
- canonical payload JSON;
- SHA-256 of canonical payload;
- creation/observation timestamp supplied by the domain artifact where available.

Same ID + same payload is idempotent. Same ID + different payload fails closed. Reads recompute the digest and reject tampered rows.

Gate 17 does not make persisted JSON authoritative over the self-validating domain objects that produced it; it is durable application/audit state.

## 5. Current-pointer / optimistic concurrency contract

A small materialized pointer table may identify the current artifact for an operational stream (for example latest proof/case/run view). It is not financial truth.

Pointer advancement requires compare-and-swap semantics using an expected generation/version. Concurrent stale writers fail; they may not overwrite a newer pointer. Replaying the exact already-current artifact is idempotent.

Immutable artifacts must be persisted before a pointer can reference them. Pointer failure must not delete or rewrite immutable history.

## 6. Minimal application service boundary

Gate 17 adds a dependency-light application service that composes the durable journal/artifact/pointer stores and exposes product operations needed by Gate 18 read models.

It may:

- append/read raw evidence;
- store/read immutable product artifacts;
- list artifacts by kind/scope;
- read/advance operational current pointers;
- expose a health/capability summary.

It may not:

- manufacture Gate 7/8/9 proof outcomes;
- mark money reconciled;
- mutate historical proof/case evidence;
- auto-execute Gate 16 suggestions;
- approve adapters without existing deterministic approval evidence;
- issue refunds, payouts, transfers, or arbitrary SQL.

No public generic SQL execution surface is permitted.

## 7. PostgreSQL boundary

PostgreSQL is the deployment persistence target. The Python driver must remain a small optional/deployment dependency rather than forcing a heavy ORM. Schema creation/migration must be explicit and versioned.

Integration tests must run against a real PostgreSQL instance on Oracle via an isolated test container. Tests must use their own database/container and must not touch Dokploy or any existing application database.

The test database/container is disposable and must be removed after validation.

## 8. Crash/restart and transaction acceptance

Gate 17 must prove:

1. raw evidence survives connection/service reconstruction;
2. immutable artifacts survive reconstruction;
3. current pointers survive reconstruction;
4. duplicate append after restart remains idempotent;
5. conflicting raw source evidence remains retained after the conflict exception;
6. stale pointer CAS fails without moving the pointer;
7. artifact/pointer atomic helper cannot leave a pointer to a missing artifact;
8. failed multi-record transaction does not partially publish application state;
9. direct database payload tampering is detected on read;
10. scope-filtered artifact queries cannot return another scope accidentally.

## 9. Benchmark acceptance

After the Gate 7 optimization, rerun the same Oracle baseline used before the change and preserve both numbers. The checkpoint must report the observed speedup rather than a theoretical complexity claim alone.

Then run 50, 1k and 10k clean workloads. Run an adversarial/exception-heavy tier at least at 50 and 1k; extend farther only if safe. Warm replay/idempotency must be measured for the durable journal/artifact store separately from cold first-write throughput.

If 100k is not feasible within available memory/time, record the limitation; do not extrapolate a throughput claim.

## 10. Acceptance tests frozen before implementation

1. indexed Gate 7 proof output equals existing semantics on clean fixture;
2. indexed proof output equals existing semantics on duplicate/conflict/late/UTR cases;
3. proof result remains input-permutation invariant;
4. no cross-batch provenance cache leakage;
5. PostgreSQL journal exact append/replay matches in-memory behavior;
6. PostgreSQL conflicting source identity retains conflict envelope then raises;
7. PostgreSQL journal survives reconnect/restart;
8. journal entries ordering matches in-memory ordering;
9. immutable artifact same-ID/same-payload replay is idempotent;
10. immutable artifact same-ID/different-payload fails closed;
11. persisted artifact digest is verified on read;
12. artifact queries are scope-filtered and canonical-ordered;
13. current pointer first publish succeeds at generation one;
14. exact pointer replay is idempotent;
15. stale pointer compare-and-swap fails;
16. pointer cannot reference a missing artifact;
17. artifact+pointer transactional publish is atomic;
18. application service exposes no financial mutation/generic SQL capability;
19. service reconstruction sees prior journal/artifact/pointer state;
20. schema migration is idempotent and version-checked;
21. real PostgreSQL integration suite passes in isolated container;
22. scale runner records hardware/runtime/seed/database mode;
23. benchmark result serialization is deterministic;
24. 50-settlement post-optimization run is materially faster than the captured pre-optimization baseline without output drift;
25. 1k post-optimization run completes and preserves deterministic output counts;
26. 10k post-optimization run completes if VM safety bounds permit;
27. warm duplicate journal/artifact ingestion produces no duplicate economic/product state;
28. production persistence/application modules do not import simulator truth;
29. no distributed infrastructure is introduced;
30. full repository regression suite remains green.

## 11. Explicit non-goals

Gate 17 does not implement:

- Gate 18 operator UI;
- authentication/SSO/RBAC beyond explicit scope keys in persistence APIs;
- a full accounting/general ledger;
- event streaming infrastructure;
- multi-region/high-availability PostgreSQL;
- Redis/Kafka/Celery workflow orchestration;
- Instant Settlement topology;
- final held-out submission benchmark;
- live-model quality claims.

Those remain separate concerns. Gate 17 is successful when one process plus PostgreSQL is measured, restart-safe, idempotent and sufficient for the product state needed by Gate 18.
