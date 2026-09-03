# ReFlow production deployment templates

These files describe the supported single-host application layout. They are templates, not evidence that a public production deployment already exists.

## Process layout

- `reflow-control-tower.service` binds only to `127.0.0.1:8080` and serves the human Control Tower.
- `reflow-webhook.service` binds only to `127.0.0.1:8081` and serves Razorpay callbacks.
- `cloudflared` publishes two different hostnames to those loopback services.
- Cloudflare Access protects the Control Tower hostname. Do not put human Access in front of the Razorpay callback hostname; ReFlow authenticates that route with Razorpay's raw-body HMAC signature.

The two application services use different environment files. Provider webhook secrets never belong in the Control Tower environment.

## Host layout

```text
/opt/reflow/releases/<git-sha>/    immutable application release + .venv + web/dist
/opt/reflow/current                symlink to one release
/etc/reflow/control-tower.env      mode 0600
/etc/reflow/webhook.env            mode 0600
/etc/reflow/authz.json              operator authorization policy
/etc/cloudflared/config.yml         tunnel routing
```

Run both application services as an unprivileged `reflow` system user. Install the unit files in `/etc/systemd/system/`, copy the example environment files into `/etc/reflow/`, populate secrets out of band, and set the environment files to mode `0600`.

## Release procedure

1. Materialize one exact reviewed Git commit under `/opt/reflow/releases/<git-sha>`.
2. Create that release's `.venv` and install with `requirements/ci-constraints.txt` and the `postgres,web` extras.
3. Build `web/dist` inside the release.
4. Run the repository submission check against the intended PostgreSQL target or an equivalent pre-production database.
5. Atomically repoint `/opt/reflow/current` to the new release.
6. Restart `reflow-control-tower.service` and `reflow-webhook.service`.
7. Require local readiness to return 200 before considering the release healthy.
8. Verify the Control Tower through its Access-protected hostname and verify webhook routing without sending production financial mutations.

Rollback is the inverse: repoint `current` to the previous already-built release, restart both services, and re-run readiness checks. Database rollback is not implied by an application rollback; schema/data recovery follows the PostgreSQL recovery contracts.

## Cloudflare Tunnel

Copy `cloudflared/config.example.yml` to the host's Cloudflare Tunnel configuration and replace only the documented placeholders/hostnames. Keep the final catch-all `http_status:404` rule. The app ports stay loopback-only; they are not firewall-exposed public listeners.

## PostgreSQL recovery layers

Logical `pg_dump`/`pg_restore` recovery remains the portable application-data recovery path in `docs/46_POSTGRES_BACKUP_AND_RECOVERY_CONTRACT.md`.

Point-in-time recovery is a separate cluster-level layer. Production PITR requires:

- `wal_level = replica` or higher;
- `archive_mode = on`;
- an `archive_command` or archive library that stores WAL in independently durable, off-host storage;
- physical base backups retained together with every WAL segment needed from the backup start onward;
- a tested `restore_command` and recovery-target procedure.

The archive command must fail non-zero when archival fails and must not silently overwrite a different object under an existing WAL name. Do not treat a directory on the same VM as disaster recovery.

A production archive backend is intentionally not hard-coded here. Select it operationally, bind its credentials outside the repository, and monitor archival failures/lag. The CI test uses a local Docker volume only to prove PostgreSQL 16 base-backup + WAL replay + named-target recovery mechanics.

See `docs/48_PRODUCTION_DEPLOYMENT_AND_PITR_CONTRACT.md` for acceptance evidence and non-claims.
