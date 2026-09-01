# Gate 17 Checkpoint — Scale + Durability/Application Layer

## Status

Gate 17 is implemented on `build/gate-17-scale-durability-application` from final Gate 16 `main`:

`c2b849da713beaa2ed55abc9e1776facca76817f`

Implementation checkpoints:

- frozen contract: `e098901c1b157a4e25ce6335e15893740932b666`;
- Gate 7 provenance-index performance fix + F-0081: `e8042e6ce34bf0b7ce4dfca773d408af97ed5b92`;
- PostgreSQL application store: `e30822443cac0582661729e4df93d6a5b09173a0`;
- reproducible scale/persistence benchmark evidence: `3fa4dd130f870ec88e1e967503bfe1f442a60197`.

Final pre-PR Oracle validation on 2026-09-01:

- Ruff: passed;
- strict mypy: passed across 57 source files;
- full repository suite: 375 passed with real PostgreSQL integration enabled;
- PostgreSQL integration suite: 12/12 passed against PostgreSQL 16;
- all checked-in Gate 17 benchmark artifacts independently verified;
- `git diff --check`: passed;
- production persistence/application modules have no simulator-truth import;
- no Kafka/Kubernetes/Celery/Redis/sharding/microservice infrastructure introduced.

PR/merge CI is pending at this checkpoint.

## Gate 17 thesis

> Measure the one-process proof engine, remove measured algorithmic waste, and add only the PostgreSQL durability/application boundary needed for replayable product state.

Gate 17 does not change financial semantics. Gate 7/8/9 proof truth, Gate 13 controls, Gate 14 case semantics, Gate 15 provider semantics and Gate 16 AI authority limits remain unchanged.

## F-0081 — measured Gate 7 provenance-scan bottleneck

Before optimization, `_required_provenance_edges()` rescanned the entire `MoneyGraph` for every recon row.

The first 50-settlement clean Oracle baseline contained 6,084 raw rows. It measured:

- ReFlow proof-core time: 2.733 s;
- proof-core throughput: 18.3 settlements/s;
- total wall time: 3.73 s;
- max RSS: ~34 MiB.

A cProfile run showed about 7.0 of 9.8 profiled seconds inside Gate 7 composition generation and approximately 13.8 million `EntityId.__str__` calls.

The pre-optimization 1,000-settlement clean run remained CPU-bound and had still not completed after **20m31s**. It was stopped at that point. No invented pre-optimization completion time exists.

### Fix

Gate 7 now constructs one provenance-edge index per immutable canonical batch, keyed by exact relationship/from/to identity. Every recon component still requires:

- the exact `entity_has_recon_entry` edge;
- the exact `recon_entry_contributes_to_settlement` edge;
- `PROVEN` state;
- authoritative strength;
- the exact raw `SourceEnvelopeId` evidence tuple;
- `EXACT_SOURCE_IDENTIFIER` reason evidence.

The index is local to one `prove_all_settlement_compositions()` call. A regression proves a new batch creates a new index; no cross-batch cache exists.

On the same 50-settlement clean shape, the final checked-in Gate 17 benchmark records a 0.150 s proof pipeline / 333.29 settlements/s. Against the original 2.733 s proof-core baseline this is roughly an 18x wall-time improvement while preserving the proof contract.

## Reproducible one-process scale evidence

Checked-in artifacts are under `data/eval/gate17/` and are self-verifying with SHA-256-bound payloads.

Oracle environment recorded in the artifacts:

- Linux aarch64;
- Python 3.12.3;
- 4 logical CPUs;
- one worker/process;
- deterministic in-memory core execution for the proof-scale benchmark.

| Workload | Raw rows | Total time | Proof pipeline | Proof throughput | Peak RSS | Outcome summary |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 50 clean | 6,084 | 1.125 s | 0.150 s | 333.29/s | 35.5 MiB | 40 proven, 5 waiting, 5 residual |
| 1,000 clean | 120,052 | 24.933 s | 3.949 s | 253.24/s | 353.4 MiB | 800 proven, 100 waiting, 100 residual |
| 10,000 clean | 1,203,220 | 267.560 s | 48.317 s | 206.97/s | 3.18 GiB | 8,000 proven, 1,000 waiting, 1,000 residual |
| 50 adversarial | 6,076 | 1.142 s | 0.160 s | 312.90/s | 35.9 MiB | 29 proven, 14 waiting, 6 residual, 1 contradicted |
| 1,000 adversarial | 119,873 | 27.199 s | 4.810 s | 207.88/s | 347.9 MiB | 638 proven, 280 waiting, 81 residual, 1 contradicted |

The 10k run completed under the explicit Oracle safety guard. A 100k run was **not attempted**: the required tier was already demonstrated, the 10k process reached about 3.18 GiB RSS on a shared VM, and Gate 17 has no reason to endanger unrelated services merely to claim a larger number. No 100k/1M throughput is extrapolated or claimed.

### Artifact identities

- `scale-50-clean.json`: `bc2ee30e165099d99e85f21e4f268b61fcf95f86a8cccb6f810f2005fcb9c6ed`
- `scale-1000-clean.json`: `13994daaa23b1f14c73552b59fd424799d8081c99e8d4db2a66e6f560e5313ad`
- `scale-10000-clean.json`: `46fd16aa6497aebf7d346ed85f07f462691c3e920bf760305d57fbbf30e9a08f`
- `scale-50-adversarial.json`: `19dbc7bd6bb151c4b6f32849b527932ac4e9a90ae6d2a21ab9495ac1f5f077ad`
- `scale-1000-adversarial.json`: `bb6287e2ca3458a5e782f4d27e93d8186fc8d72226638b60a1b52f6363f85ea2`

## PostgreSQL durability boundary

Gate 17 introduces `PostgresApplicationStore`, implementing the same structural `Journal` interface used by ingestion/proof/provider code rather than creating a second reconciliation path.

Raw evidence semantics preserved in PostgreSQL:

- deterministic `SourceEnvelope` validation before write;
- immutable envelope identity;
- stable source-kind/source-record primary identity;
- exact replay => `DUPLICATE`;
- conflicting payload is retained as evidence before raising `JournalConflictError`;
- deterministic `get`, `get_by_id`, `entries` and length behavior;
- reconnect/reconstruction survival;
- no public raw UPDATE/DELETE operation.

The PostgreSQL schema is explicit, versioned (`POSTGRES_SCHEMA_VERSION = 1`) and idempotently migrated.

## Immutable application artifacts

Instead of an ORM copy of every domain object, Gate 17 stores immutable canonical JSON audit artifacts with:

- artifact kind;
- artifact ID;
- optional reconciliation scope;
- canonical payload JSON;
- SHA-256 content digest;
- optional domain observation timestamp.

Supported artifact families cover scope/policy/manifests/controls/runs, Gate 9 proof versions, Gate 14 observations/dispositions/incidents, approved adapters, and Gate 16 result/trace records.

Same ID + same payload is idempotent. Same ID + different payload fails closed. Reads recompute the payload digest and reject direct database tampering.

## Optimistic current pointers

`reflow_current_pointers` provides an operational materialized pointer, not financial truth.

- generation starts at one;
- exact current replay is idempotent;
- stale compare-and-swap fails;
- pointer target must already exist as an immutable artifact;
- `publish_artifact_and_pointer()` writes the artifact and pointer in one database transaction;
- a failed pointer update cannot forge/delete immutable history.

## Minimal application service

`ReflowApplicationService` exposes only:

- append source evidence;
- read source evidence through the journal interface;
- persist/read/list immutable artifacts;
- read/publish current operational pointers;
- capability/health metadata.

It does **not** expose generic SQL, proof mutation, `MARK_RECONCILED`, adapter bypass, refund, payout, transfer, or Gate 16 action execution.

## PostgreSQL cold/warm measurement

The isolated Oracle benchmark used PostgreSQL 16.15 (`postgres:16-alpine`) and psycopg 3.3.5 with 1,000 deterministic source envelopes plus 1,000 immutable artifacts.

Checked-in artifact: `data/eval/gate17/postgres-1000-cold-warm.json`

SHA-256-bound artifact identity:

`a33416faee3e6fe5c5a3be934e42b8e9f9fdd527581ad4148a37d7bec6d363f4`

Measured reference-store rates:

| Operation | Time | Rate |
| --- | ---: | ---: |
| source first write | 13.141 s | 76.10 ops/s |
| source exact replay | 13.087 s | 76.41 ops/s |
| artifact first write | 11.086 s | 90.20 ops/s |
| artifact exact replay | 11.437 s | 87.43 ops/s |

This benchmark intentionally exposes a limitation: the reference store currently opens/commits at fine granularity and is not a bulk-ingestion loader. These numbers prove persistence/idempotency behavior, not high-throughput PostgreSQL ingestion. Batched/session ingestion is a future optimization if the product workload requires it; no distributed queue/database system is justified by this result.

## Crash/restart / integrity evidence

Real-PostgreSQL integration tests prove:

1. raw evidence survives store reconstruction;
2. immutable artifacts survive reconstruction;
3. current pointers survive reconstruction;
4. duplicate append after reconstruction remains idempotent;
5. conflicting raw evidence remains retained after the exception;
6. stale pointer CAS cannot move the pointer;
7. missing pointer targets are rejected;
8. artifact + pointer publication is atomic;
9. direct artifact payload tampering is detected on read;
10. scope-filtered artifact queries do not leak another scope;
11. schema migration is idempotent/version-checked;
12. public application capabilities expose no generic SQL/financial mutation.

CI now starts its own isolated `postgres:16-alpine` service and installs the optional `postgres` dependency, so these semantics are exercised on branch/PR/main validation rather than only on Oracle.

## What Gate 17 deliberately does not claim

Gate 17 does not provide:

- 100k or 1M measured scale;
- PostgreSQL bulk-ingestion throughput;
- connection pooling;
- HA/replication/backups/PITR;
- schema migration orchestration beyond the explicit v1 library migration;
- authenticated users, SSO or RBAC;
- durable distributed job queues;
- automatic persistence wiring for every in-memory derivation ledger;
- production HTTP APIs;
- production connector scheduling;
- final held-out reconciliation accuracy;
- live-model quality metrics;
- Gate 18 operator UI.

PostgreSQL stores durable evidence/audit/product state, but deterministic domain objects remain the authority for their own invariants and financial truth.

## Failure history

Gate 17 added one genuine failure:

- **F-0081** — Gate 7 provenance validation repeatedly scanned the full Money Graph, making the pre-optimization 1k run exceed 20m31s without completing.

It is fixed and regression-protected at `e8042e6`.

## Next gate

Gate 18 is **Operator Control Tower**.

It should begin only after Gate 17 PR CI, merge and merge-triggered `main` CI are green. Gate 18 should build read-oriented product surfaces over the immutable proof/run/case/evidence/application state; it must not introduce a second reconciliation engine or a chatbot-first product surface.
