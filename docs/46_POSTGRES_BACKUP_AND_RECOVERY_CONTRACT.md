# PostgreSQL Logical Backup and Recovery Contract

**Started:** 2026-09-03
**Base `main`:** `7a5ebe7c17606aa7a171f3d43e62405dc095e48c`
**Branch:** `hardening/postgres-recovery-v2`

## Goal

Add a restore-tested PostgreSQL logical-backup path for ReFlow without weakening application integrity checks or implying that a logical dump provides point-in-time recovery.

This gate uses PostgreSQL custom-format `pg_dump` archives and `pg_restore`. WAL archiving/PITR remains a separate production capability and is not claimed by this gate.

## Backup contract

A backup is accepted only when all of the following hold:

1. the source ReFlow database passes exact schema/readiness validation before dumping;
2. PostgreSQL connection information is parsed with libpq/psycopg semantics;
3. inherited `PG*` variables are removed before the client process is launched;
4. credentials, hosts and full DSNs never appear in `pg_dump`/`pg_restore` argv;
5. the partial archive exists with private permissions before `pg_dump` writes data;
6. the custom archive is non-empty and `pg_restore --list` can parse it;
7. the archive is fsynced and published without replacing an existing backup;
8. a private JSON manifest binds archive name, byte length, SHA-256, UTC creation time and `pg_dump` version;
9. the manifest is published only after the archive is complete and verified;
10. partial/orphan output is removed if publication fails.

Backup archives and manifests contain finance evidence and must remain private. The reference implementation requires no group/world permissions on files and uses a private output directory.

## Restore-verification contract

`restore-verify` is intentionally not an in-place production restore command.

It requires both the source DSN and a separately configured restore DSN. The restore target must:

- identify a different database from the source under normalized host/port/database identity;
- be reachable;
- contain zero user tables before `pg_restore` begins.

The tool never creates, drops or overwrites databases. A human/deployment system must provision a disposable empty target first.

Before restore, the archive filename, size, SHA-256, private permissions and `pg_restore --list` result are revalidated. `pg_restore` runs with `--exit-on-error`, no owner replay and no privilege replay.

## Application integrity after restore

A successful PostgreSQL process exit is insufficient. ReFlow then opens the restored database with migrations disabled and requires the exact supported schema version.

The verifier exhaustively checks:

- every retained source envelope through journal hash/readback validation;
- every unique source identity resolves to a retained envelope;
- source-identity inventory count matches the validated identity set;
- every immutable application artifact can be read through its payload-hash validation path;
- every current pointer can be read exactly and references an existing artifact of the required kind.

Any mismatch fails the drill closed.

## CI recovery drill

CI provisions two dedicated PostgreSQL 16 databases after the normal submission suite: one seeded source and one empty restore target. Pinned PostgreSQL 16 client binaries create a real custom-format dump and restore it into the fresh target. ReFlow's integrity verifier must then pass.

The normal `reflow_ci` database is not used as the restore target.

## Acceptance criteria

1. secret/DSN material never appears in subprocess argv or manifest content;
2. inherited PostgreSQL environment variables cannot redirect a configured DSN;
3. dump failure leaves no published or partial backup;
4. a same-target restore is rejected before restore execution;
5. a non-empty restore target is rejected before restore execution;
6. archive or manifest tampering is rejected before restore;
7. output-name collisions never overwrite an existing backup;
8. restored source/artifact/pointer integrity is exhaustively revalidated;
9. real PostgreSQL 16 dump -> fresh database -> restore -> ReFlow verification passes in CI;
10. the entire existing submission suite and frozen evaluation evidence remain unchanged and green.

## Validation checkpoint

The exact recovery implementation commit `c3de59e7cac1e0ffae68b41ced99875ef718b60f` passed PR #31 CI run `33775739678`. The required `Submission check` completed with **503 Python/PostgreSQL tests passed and no skips**, so the CI-only real recovery integration test executed rather than being skipped. TypeScript, 5/5 React tests, the Vite production build, frozen Gate 17/Gate 19 artifacts and generated `EVALUATION.md` also passed/verified unchanged.

Before push, the rebuilt branch also passed Ruff, strict mypy across 69 source modules, 458 local tests with only deployment/PostgreSQL-gated skips, the same local suite under `python -O`, `pip check`, Bandit medium/high with zero findings, `pip-audit` with no known vulnerabilities, npm production/full audits with zero vulnerabilities, a high-confidence working-tree credential scan with zero hits, and `git diff --check`.

The recovery integration uses a digest-pinned PostgreSQL 16.15 Alpine client image, two disposable databases distinct from the normal `reflow_ci` database, a real custom-format `pg_dump`, archive verification, restore into the empty target, and ReFlow source/artifact/pointer integrity readback. The test drops both disposable databases in `finally`.

PR #31 merged as `fda3cbd43b3a8ea055f0d5934d0b2ab5de22f0f3`; exact merge-triggered `main` CI run `33776336580` completed successfully. This logical backup/recovery gate is closed. WAL archiving/PITR remains a separate non-claim.

## Non-claims / next layer

This gate does not provide WAL archiving, PITR, cross-region copies, backup retention policy, encrypted object-storage replication, automated production database creation/drop, HA failover, or an RPO/RTO SLA. Those require deployment-specific infrastructure and an actual recovery exercise before being claimed.
