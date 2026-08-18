# Backup and recovery

**Two things must be backed up together: the PostgreSQL database and the
dataset storage volume.** They are a matched pair — the database holds rows
whose `storage_key` points at files in the volume. Restore one without the
other and you get datasets that cannot be opened, or orphaned files nothing
references.

No backup service is bundled. What follows is the practical minimum, using
tools already present in the stack.

---

## What holds state

| State | Where | Lost if not backed up |
|---|---|---|
| Users, workspaces, projects, dataset metadata, versions, reports, insight runs, dashboards | PostgreSQL (`postgres_data` volume) | Everything |
| Uploaded dataset files, cleaned versions, rendered reports | `dataset_storage` volume (`/app/var/storage`) | Every file; rows survive but point nowhere |

Everything else — images, compiled frontend — is rebuildable from the
repository. Configuration lives in your secret manager or `.env.production`,
which should be backed up separately and **never** alongside data dumps.

---

## Database backup

```bash
# Compressed custom-format dump (supports selective restore)
docker compose -f docker-compose.prod.yml exec -T db \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc \
  > "backup-$(date +%F-%H%M).dump"
```

Plain SQL, if you prefer something readable:

```bash
docker compose -f docker-compose.prod.yml exec -T db \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" | gzip > "backup-$(date +%F).sql.gz"
```

`pg_dump` is consistent without stopping the database: it runs in a single
transaction and captures a snapshot from the moment it starts.

## Storage backup

```bash
docker run --rm \
  -v aibiplatform_dataset_storage:/data:ro \
  -v "$(pwd)":/backup \
  alpine tar czf "/backup/storage-$(date +%F-%H%M).tar.gz" -C /data .
```

Confirm the volume name first with `docker volume ls` — Compose prefixes it
with the project directory name.

## Taking both together

Files can be written while `pg_dump` runs, so take the storage snapshot
**after** the database dump. A file with no row is harmless clutter; a row with
no file is a broken dataset.

```bash
#!/usr/bin/env bash
# backup.sh - run from the compose directory
set -euo pipefail
STAMP=$(date +%F-%H%M)
DEST=${BACKUP_DIR:-/var/backups/aibi}
mkdir -p "$DEST"

docker compose -f docker-compose.prod.yml exec -T db \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$DEST/db-$STAMP.dump"

docker run --rm -v aibiplatform_dataset_storage:/data:ro -v "$DEST":/backup \
  alpine tar czf "/backup/storage-$STAMP.tar.gz" -C /data .

# Keep 30 days.
find "$DEST" -name 'db-*.dump' -mtime +30 -delete
find "$DEST" -name 'storage-*.tar.gz' -mtime +30 -delete
```

Schedule it (`cron`, systemd timer, or your platform's scheduler), then **copy
the output off the host**. A backup on the machine it protects is not a backup.
Encrypt it at rest — dumps contain password hashes and business data.

---

## Restore

Stop the application first so nothing writes mid-restore. Leave the database
running.

```bash
docker compose -f docker-compose.prod.yml stop backend frontend
```

**Database:**

```bash
# --clean --if-exists drops existing objects before recreating them.
docker compose -f docker-compose.prod.yml exec -T db \
  pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists \
  < backup-2026-08-15-0200.dump
```

From a plain SQL dump:

```bash
gunzip -c backup-2026-08-15.sql.gz | \
  docker compose -f docker-compose.prod.yml exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
```

**Storage:**

```bash
docker run --rm \
  -v aibiplatform_dataset_storage:/data \
  -v "$(pwd)":/backup \
  alpine sh -c "rm -rf /data/* && tar xzf /backup/storage-2026-08-15-0200.tar.gz -C /data"
```

**Restart and verify:**

```bash
docker compose -f docker-compose.prod.yml up -d
curl -fsS http://127.0.0.1:8000/api/v1/health/ready
docker compose -f docker-compose.prod.yml run --rm migrate alembic current
```

Then check in the UI that a dataset opens and a report downloads — that is what
proves the two halves match.

---

## Migration recovery

Production runs migrations as a one-shot service that must succeed before the
API starts, so a failed migration stops the deployment rather than leaving a
half-migrated database serving traffic.

**If a migration fails:**

1. Read the log: `docker compose -f docker-compose.prod.yml logs migrate`.
2. Check where the schema stopped: `... run --rm migrate alembic current`.
3. Alembic runs each migration in a transaction, so a failure usually leaves
   the schema at the previous revision. Fix the migration and re-run.
4. If the schema is genuinely inconsistent, **restore from backup** rather than
   hand-editing. `alembic downgrade` is available, but a downgrade that drops a
   column destroys data.

**Before every production migration:** take a backup, and review the SQL first:

```bash
docker compose -f docker-compose.prod.yml run --rm migrate alembic upgrade head --sql
```

Look for `drop_table`, `drop_column` and type narrowing. Those are the ones
that cannot be undone by running the migration backwards.

---

## Test the restore

An untested backup is a guess. At least once, and after any change to storage
or database configuration:

1. Restore the latest backup into a scratch stack.
2. Sign in, open a dataset, generate a report, open a dashboard.
3. Record how long the whole thing took — that number is your recovery time,
   and it is the one you will be asked for during an incident.
