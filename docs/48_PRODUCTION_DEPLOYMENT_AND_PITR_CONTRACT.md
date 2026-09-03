# Production Deployment and PostgreSQL PITR Contract

**Started:** 2026-09-03
**Base `main`:** `66c616e620198409cd62b09c14025883cc845888`
**Branch:** `hardening/production-deployment-pitr`

## Goal

Turn the already-separated ReFlow HTTP boundaries into a reproducible single-host deployment shape and add a real PostgreSQL 16 point-in-time recovery drill without weakening any financial, authentication, or recovery boundary.

This gate does not replace the logical backup/restore contract in doc 46. Logical dumps and physical continuous-archive recovery solve different failure modes and remain complementary.

## Deployment boundary

The supported application layout has two independent unprivileged processes:

1. the human Control Tower on loopback port `8080`;
2. Razorpay webhook ingress on loopback port `8081`.

Both are launched from the exact release selected by `/opt/reflow/current`, use separate environment files, and bind no public socket. The systemd templates fail back to restart-on-failure behavior and apply conservative filesystem/kernel hardening that does not require elevated capabilities.

Cloudflare Tunnel maps two distinct public hostnames to the two loopback services. The final ingress rule is a `404` catch-all. The Control Tower hostname remains under Cloudflare Access; the Razorpay hostname cannot depend on human Access and instead uses the Gate 47 raw-body HMAC boundary.

A deployment is not healthy merely because a process exists. Each service must pass its dependency-aware readiness endpoint after restart.

## Release and rollback boundary

A release is an immutable directory named by reviewed Git SHA, containing its own Python virtual environment and built frontend. Deployments switch the `/opt/reflow/current` symlink only after the release has been built and validated.

Application rollback means switching that symlink to a previously built release and restarting the services. It does not roll database state backward. Any database rewind must use the explicit logical-recovery or PITR procedure and therefore remains an operator-controlled recovery action.

Secrets live outside the repository in root-controlled environment/credential files. The two application services do not share a combined secret file.

## PostgreSQL recovery layers

ReFlow now distinguishes:

- logical recovery: application-level `pg_dump` / `pg_restore`, integrity manifests and restored semantic verification from doc 46;
- physical PITR: a PostgreSQL base backup plus continuous WAL archive, restored at cluster level to an explicit recovery target.

PostgreSQL 16 documents continuous archiving as WAL archiving combined with a file-system/base backup, and `pg_basebackup` as a physical whole-cluster backup suitable as the starting point for PITR. Production WAL archival therefore requires `wal_level=replica` or higher, `archive_mode=on`, and a working archive command/library before taking the base backup.

Official references:

- https://www.postgresql.org/docs/16/continuous-archiving.html
- https://www.postgresql.org/docs/16/app-pgbasebackup.html
- https://www.postgresql.org/docs/16/runtime-config-wal.html

## Real PITR acceptance drill

The CI integration test launches a disposable digest-pinned PostgreSQL 16.15 cluster and performs the complete recovery sequence:

1. enable `wal_level=replica`, `archive_mode=on`, and a local test-only WAL archive;
2. create a baseline table/row;
3. take a physical `pg_basebackup` with streamed WAL;
4. create a named PostgreSQL restore point after the base backup;
5. force and verify archival of the WAL containing that restore point;
6. make a later database change;
7. force and verify archival of later WAL as well;
8. stop the primary cluster;
9. boot the physical base backup with `recovery.signal`, `restore_command`, and `recovery_target_name`;
10. promote at the named restore point;
11. prove the baseline row exists while the later row does not;
12. prove the recovered server has left recovery mode.

The local WAL volume is deliberately an acceptance-test fixture only. It demonstrates PostgreSQL recovery mechanics but is not a disaster-recovery storage recommendation.

## Production WAL archive contract

The real archive destination must be independently durable and off-host. Its implementation must:

- preserve WAL object names exactly;
- never silently replace different content under an existing WAL name;
- return non-zero on archival failure so PostgreSQL retains/retries the segment;
- retain all WAL required by every retained base backup;
- surface archival failure or lag to operations;
- keep archive credentials out of repository/config examples;
- support a restore command that returns non-zero for an unavailable requested file.

The storage vendor is intentionally not selected in source code. Choosing S3-compatible storage, Backblaze, OCI Object Storage, or another backend is an operational deployment decision, not financial application logic.

## Cloudflare routing contract

Cloudflare documents local tunnel ingress rules as ordered hostname/path matches requiring a terminal catch-all rule. ReFlow's example uses only hostname routing: one hostname for human traffic and one for Razorpay callbacks, followed by `http_status:404`.

Official reference:

- https://developers.cloudflare.com/tunnel/advanced/local-management/configuration-file/

## Acceptance criteria

1. Control Tower and webhook ingress use separate systemd services and separate env files.
2. Both app servers bind only to `127.0.0.1` and use different ports.
3. Tunnel configuration maps exactly two example hostnames and ends in a 404 catch-all.
4. Control Tower identity settings do not appear in the webhook env template and webhook secrets do not appear in the Control Tower env template.
5. Deployment templates preserve the existing Cloudflare Access versus Razorpay-HMAC split.
6. A real PostgreSQL 16.15 physical base-backup/WAL/named-target recovery drill runs in CI with no skip.
7. The PITR drill proves state after the restore point is excluded, rather than merely proving the recovered server starts.
8. The existing logical backup/restore drill continues to pass unchanged.
9. Full PostgreSQL reviewer tests, frontend checks and frozen evaluation evidence remain green.
10. No production off-host WAL archive or RPO/RTO claim is made until an actual archive backend, retention policy and operator restore exercise exist.

## Validation checkpoint

On the isolated Oracle VM branch worktree, the implementation passed the full submission gate with `REFLOW_RECOVERY_DOCKER_DRILL=1`:

- Ruff: passed;
- strict mypy: passed across **72 source files**;
- Python/PostgreSQL: **524 tests passed**;
- both the existing logical dump/restore drill and the new PostgreSQL 16.15 physical PITR drill executed with no skip;
- the PITR drill was also stress-run successfully five consecutive times after fixing F-0124;
- TypeScript project check: passed;
- React/Vitest: **5/5 tests passed**;
- Vite production build: passed;
- frozen Gate 17/Gate 19 artifacts and generated `EVALUATION.md`: verified unchanged;
- the Cloudflare tunnel example passed `cloudflared tunnel ingress validate` on the Oracle VM.

`systemd-analyze verify` parsed both unit templates without a unit-syntax error. Its only ReFlow-specific warning was expected on the unprovisioned validation host: `/opt/reflow/current/.venv/bin/python` does not exist until a release is installed.

PR #35 exact head `68c1d9e42856f959eb513efbda3cba4e9bbb4a29` passed CI run `33785178420` with **524 tests passed** and the frozen evaluation evidence green, then merged as `b5d88eef6d23f7e27b00850f367b2a74ef0f009e`. Merge-triggered `main` CI run `33785451379` exposed F-0125: the restored data was already exactly at the named recovery target, but the assertion queried `pg_is_in_recovery()` before asynchronous promotion completed. The follow-up fix explicitly waits for promotion completion. From that failed `main` plus the fix, the PITR drill passed **10 consecutive runs**, followed by the complete local submission gate with **524 tests passed**, frontend **5/5**, production build and all frozen evaluation checks green.

PR #36 exact fix head `776df9c5fb868cff090e2b50bbf4d3645b59c427` passed CI run `33786167402` with **524 tests passed**, strict mypy across 72 source files, frontend **5/5**, production build and all frozen evaluation checks green. It merged as `e047f8ae251857709a81309fe5f1c99465a83849`. Exact merge-triggered `main` CI run `33786427178` then passed the same required submission gate with **524 tests passed** and all frozen evidence verified.

**Gate status: closed and merged green.**

## Non-claims

This gate does not claim multi-region HA, automatic database failover, zero data loss, a particular RPO/RTO, an already-provisioned Cloudflare tunnel, or an already-provisioned off-host WAL archive. It provides a tested deployment shape and proves PITR mechanics; production credentials, host provisioning, archive retention and an external recovery exercise remain operator deployment work.
