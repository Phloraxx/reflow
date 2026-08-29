# Scale, Performance and Resilience Strategy

## Objective

ReFlow should have one correctness model that works for:

- a small merchant importing 30 rows from three files;
- a medium merchant processing tens of thousands of transactions;
- an enterprise/payment institution processing millions of events.

The implementation should **scale by changing execution strategy, not financial semantics**.

No benchmark number is claimed in this document. All targets must later be measured and published with hardware/runtime details.

---

## 1. Scale principles

1. Exact/indexed reconciliation should handle the majority of records.
2. Expensive algorithms operate only on a narrow unresolved frontier.
3. LLM usage must scale with exceptions/formats, not transaction count.
4. Raw evidence is append-only and replayable.
5. Reconciliation is partitionable.
6. Late evidence triggers local recomputation, not full-world recomputation.
7. Backpressure is safer than silent dropping.
8. Small-volume deployment must not require enterprise infrastructure.
9. The Buildathon implementation should prove the architecture without pretending to be a globally distributed payment processor.

---

## 2. Workload tiers

These are design tiers, not product pricing tiers.

### Tier S — local/small

Typical batch:

```text
10–5,000 source records
1–100 settlements
single merchant/account
CSV/JSON inputs
```

Desired execution:

- one process;
- SQLite or embedded local state acceptable;
- vectorized dataframe processing;
- synchronous “reconcile now” UX acceptable;
- AI only for unknown adapter/investigation.

### Tier M — operational

Typical batch:

```text
5,000–1,000,000 source records
multiple days/accounts
API/webhook + batch imports
```

Desired execution:

- PostgreSQL for authoritative application state;
- partitioned batch jobs;
- worker concurrency;
- async reconciliation runs;
- incremental updates;
- cached adapter versions;
- bounded AI exception queue.

### Tier L — enterprise architecture target

Potential workload:

```text
millions+ events/day
multiple gateways/accounts/business units
continuous source feeds
large historical backfills
```

Buildathon requirement is to **demonstrate that the core algorithm decomposes correctly for this shape**, not deploy a production-scale cluster.

Target architecture may use:

- durable event stream/object storage;
- horizontally partitioned workers;
- columnar analytical processing;
- materialized proof state;
- queue-based exception investigation.

Do not add this infrastructure before a measured bottleneck requires it.

---

## 3. Two execution paths, one domain core

### Batch path

For file imports/backfills:

```text
files
  ↓
vectorized canonicalization
  ↓
partition
  ↓
reconciliation engine
  ↓
proofs + exceptions
```

### Streaming/incremental path

For webhooks/API feeds:

```text
event
 ↓
idempotent journal append
 ↓
affected entity lookup
 ↓
local state reducer
 ↓
recompute affected proof fragment
 ↓
new proof version / no-op
```

Both invoke the same canonical reducers and proof functions.

---

## 4. Avoid global O(n²) matching

A naive bank-to-settlement matcher comparing every settlement with every bank row becomes unusable at scale.

ReFlow should use staged candidate generation.

### Stage 0 — native identity indexes

```text
settlement_id -> recon rows
payment_id -> payment/refunds/recon
UTR -> settlement/bank candidates
order_id -> payment candidates
```

Expected near-O(1) indexed lookup.

### Stage 1 — deterministic partition

Partition by:

- merchant/account;
- currency;
- bounded date/time window;
- settlement channel/type where known.

### Stage 2 — exact numeric/reference filters

Within partition:

- exact UTR;
- exact amount;
- exact payment/reference token.

### Stage 3 — local ambiguity analysis

Only small ambiguous groups use:

- narration token ranking;
- bipartite candidate analysis;
- bounded residual solver.

### Stage 4 — exception

If uniqueness cannot be proven within resource limits, fail closed.

This means expensive logic scales with exception density, not total volume.

---

## 5. Settlement-local computation

Settlement reconciliation is naturally partitioned by `settlement_id` once authoritative recon data is present.

For each settlement:

```text
R(settlement_id)
  -> normalize contributions
  -> aggregate exact totals
  -> compare settlement entity
  -> match bank receipt
  -> emit proof
```

Thousands of settlement partitions can be processed independently.

This is a useful scaling property and should be explicit in the implementation API.

---

## 6. Columnar/vectorized batch engine

Python is acceptable if the hot batch path avoids Python-row loops where practical.

Recommended benchmark candidates:

- Polars/Arrow for parsing, normalization and grouped aggregations;
- DuckDB for local analytical joins/grouping if it materially simplifies the implementation;
- PostgreSQL for durable deployed application state;
- pure Python/Pydantic at domain boundaries, not for every million-row arithmetic operation.

Do not lock to all of these simultaneously. Benchmark a simple combination and keep the domain functions portable.

Likely Buildathon shape:

```text
FastAPI
PostgreSQL (deployed state)
Polars (batch/eval pipeline)
React/TypeScript frontend
```

SQLite remains a valid local test/dev option.

---

## 7. Incremental recomputation

When new evidence arrives, do not rerun the entire month.

Maintain dependency relationships:

```text
payment event
  affects payment P
  affects recon/settlement S?
  affects proof S
```

A new payment event should recompute:

- payment P state;
- graph edges touching P;
- settlement proof(s) depending on P;
- exception cases depending on those proofs.

A bank row should recompute only bank candidates/proofs within its partition.

---

## 8. Late and backfilled events

High-volume systems routinely receive:

- webhook retries;
- delayed source exports;
- historical backfills;
- corrected rows.

Each import/event should be idempotently appended with both `occurred_at` and `received_at`.

The reducer determines whether it changes derived truth.

Possible outcomes:

```text
NO_EFFECT_DUPLICATE
NEW_EVIDENCE_NO_STATE_CHANGE
STATE_ADVANCED
PROOF_REOPENED
EXCEPTION_RESOLVED
NEW_EXCEPTION
```

This prevents “every new event = full job rerun.”

---

## 9. Hot path vs cold path

### Hot path

Must be cheap:

- signature/source validation;
- deduplication;
- journal append;
- indexed state update;
- deterministic proof fragment recompute;
- queue exception if necessary.

### Cold path

Can be more expensive:

- adapter inference;
- residual constraint solving;
- exception clustering;
- AI investigation;
- historical batch replay;
- deep audit export.

The AI must never be required for hot-path ingestion.

---

## 10. Exception frontier economics

Suppose only a small percentage of records need investigation. This is consistent with the general payment-operations pattern described by Swift, where a minority of payments generate enquiries but still create substantial operational work.

ReFlow should exploit that asymmetry.

If total transactions are `N` and unresolved exceptions are `E`, with `E << N`, expensive AI/tool workflows should trend with `E`, not `N`.

Metrics should therefore include:

```text
AI calls / 1,000,000 input records
AI tokens / exception
% records resolved without AI
% settlements proven without fuzzy/solver path
```

This will make the scale story much more credible.

---

## 11. Exception clustering at scale

Instead of launching 2,000 independent investigations for the same root cause:

1. compute deterministic fingerprint features;
2. group similar exceptions;
3. detect sudden cluster growth;
4. investigate representative cases;
5. propose one systemic remediation.

Fingerprint dimensions can include:

```text
primary reason code
source instance
adapter version
bank/provider
amount residual bucket
reference availability
hour/day
schema fingerprint
settlement channel
```

A cluster can have a representative proof diff and affected-value sum.

---

## 12. Concurrency and idempotency

Concurrency cannot allow two workers to “prove” incompatible outcomes.

Approach:

- immutable source journal;
- unique source event constraints;
- deterministic proof version input hash;
- optimistic concurrency or transaction lock around current materialized proof pointer;
- recomputation itself side-effect-free until commit;
- duplicate job execution produces same proof hash/no-op.

The exact database strategy should be decided during implementation after tests, not over-engineered now.

---

## 13. Backpressure

When ingestion exceeds processing capacity:

Allowed behaviour:

- accept to durable queue/journal, process later;
- expose lag metric;
- throttle source importer;
- reject new batch before partial processing if durability is unavailable.

Not allowed:

- silently discard events;
- mark a batch reconciled while required source partitions are unprocessed;
- invoke unlimited model calls to catch up.

---

## 14. Source outage behaviour

Each source has health/completeness state.

Example:

```text
RAZORPAY_EVENTS: HEALTHY
RECON_EXPORT:    COMPLETE_THROUGH 2026-08-29T12:00
BANK_FEED:       DEGRADED / 47m behind
```

Proof logic incorporates completeness.

If bank evidence is delayed, the settlement should be `WAITING_FOR_BANK`, not `BANK_MISSING` immediately.

This distinction reduces false exceptions during ordinary source lag.

---

## 15. AI-provider outage behaviour

If the model API is unavailable:

- ingestion continues;
- deterministic reconciliation continues;
- proof generation continues;
- exceptions remain queued;
- operator can inspect proofs manually;
- adapter inference for *new* unknown formats pauses/quarantines rather than guessing.

The dashboard should visibly distinguish:

```text
financial engine: healthy
AI investigator: unavailable
```

The demo should intentionally show that the core survives this failure.

---

## 16. Data retention and replay

For the Buildathon simulator:

- retain all generated raw observations;
- retain hidden truth separately;
- retain adapter versions;
- retain proof versions;
- retain evaluation run manifests;
- retain model/tool decision records where allowed.

A reviewer should be able to rerun a benchmark from seed and reproduce deterministic metrics.

---

## 17. Performance benchmark matrix

Do not report one throughput number.

Benchmark dimensions:

### Dataset sizes

```text
50 records      # Buildathon minimum smoke test
1,000
10,000
100,000
1,000,000       # target stress benchmark if feasible on available hardware
```

### Exception densities

```text
0.1%
1%
5%
20% adversarial
```

### Input quality

```text
clean
messy but parseable
schema drift
high duplicate rate
high late-event rate
```

### Modes

```text
cold full batch
warm repeated batch/idempotency
incremental late event
single settlement recompute
```

Report:

- rows/sec ingestion;
- transactions/sec normalization;
- settlements/sec proof generation;
- end-to-end wall time;
- peak memory;
- proof accuracy;
- exception accuracy;
- false auto-match count;
- AI calls;
- residual-solver invocation count;
- p50/p95 per-settlement latency where meaningful.

---

## 18. Hardware disclosure

Every published performance number must include:

- CPU/device;
- memory;
- Python/runtime version;
- database mode;
- process/worker count;
- dataset seed/version;
- whether AI calls are included or replayed.

No “handles millions” claim without a reproducible run.

---

## 19. Small-volume UX must not suffer because of scale architecture

Avoid an enterprise-only product that requires users to understand partitions, streams or source cursors.

Small mode should feel like:

```text
Drop files
→ map once
→ reconcile
→ inspect 3 exceptions
→ export proof
```

The sophisticated architecture remains invisible.

---

## 20. High-volume UX must not become a giant table

Enterprise mode should surface:

- value proven;
- value awaiting evidence;
- value contradicted;
- proof aging;
- source lag;
- top exception clusters;
- newly detected schema drift;
- reconciliation SLO;
- queue depth;
- high-value unresolved cases.

Operators drill into a graph/proof only when necessary.

---

## 21. Buildathon implementation boundary

For the submission, prioritize proving:

1. correctness at 50+ and 1,000+ records;
2. a larger stress run if feasible;
3. indexed/partitioned design rather than global fuzzy matching;
4. incremental replay correctness;
5. exception density driving AI cost;
6. clean failure under model/source outage.

Do **not** build Kafka, Kubernetes, sharded databases or a microservice fleet merely to look scalable.

A small implementation with measured algorithmic behaviour is stronger than an untested distributed diagram.
