# Production deployment

Provider-agnostic. Everything below runs on any host that can run Docker, and
each step is equally valid on a managed platform if you prefer to run the
images there.

Companion documents: [security.md](security.md) for the threat model and
controls, [security-checklist.md](security-checklist.md) for the pre-launch
sign-off, [backup-recovery.md](backup-recovery.md) for backups and restores.

---

## 1. Required environment variables

Start from `.env.production.example`:

```bash
cp .env.production.example .env.production
```

Five values have no safe default and **the API refuses to start without
them** in production:

| Variable | Why it is required |
|---|---|
| `JWT_SECRET_KEY` | Signs access tokens. Minimum 32 characters. Anyone with it can mint a token for any account. |
| `POSTGRES_PASSWORD` | Rejected if left at a known default (`aibi`, `postgres`, `password`, …). |
| `CORS_ORIGINS` | Exact frontend origin(s). `*` is rejected; so is plain `http://` for a non-localhost host. |
| `VITE_API_BASE_URL` | Compiled into the frontend bundle at build time. |
| `ENVIRONMENT=production` | Turns on every check in this table, and disables `/docs`. |

Generate the signing key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

A misconfigured deployment fails at startup with every problem listed at once:

```
Invalid production configuration:
  - JWT_SECRET_KEY must be at least 32 characters.
  - CORS_ORIGINS must not contain '*' in production.
  - POSTGRES_PASSWORD must not be a default value in production.
```

That is deliberate. A deployment that stops with a clear message costs minutes;
one that silently starts insecure costs much more.

### Prefer a secret manager

Every value in `.env.production` can be injected as an ordinary environment
variable instead. If your platform has a secret store, use it and skip the file
— then `JWT_SECRET_KEY` and the AI keys never touch disk.

---

## 2. Database setup

The compose stack runs PostgreSQL 17 with a named volume. For a managed
database instead, drop the `db` service and set `DATABASE_URL`:

```
DATABASE_URL=postgresql+asyncpg://user:password@db-host:5432/aibi
```

Note the `+asyncpg` driver — the application is async throughout.

Tune the pool against your database's `max_connections`. The ceiling is
`(DB_POOL_SIZE + DB_MAX_OVERFLOW) × workers`, which with the defaults
(10 + 20, four workers) is 120 connections.

---

## 3. Migrations

```bash
# development
cd backend && alembic upgrade head
```

In production migrations run as a **separate one-shot service** that must
complete before the API starts:

```yaml
migrate:
  command: ["alembic", "upgrade", "head"]
backend:
  depends_on:
    migrate:
      condition: service_completed_successfully
```

A failed migration therefore stops the deployment rather than leaving a
half-migrated database serving traffic. The API never creates or drops tables
at startup — schema changes only ever happen through Alembic.

Before migrating production:

1. **Back up first** (see [backup-recovery.md](backup-recovery.md)).
2. Review the SQL: `alembic upgrade head --sql > migration.sql`.
3. Check for destructive operations (`drop_table`, `drop_column`, type narrowing).
4. Apply, then verify: `alembic current`.

Rollback is `alembic downgrade -1`, but a downgrade that drops a column
destroys data. Restore from backup instead when data is at stake.

---

## 4–6. Starting the stack

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

This builds the `production` target of both images:

- **Backend** — runtime dependencies only, no dev tooling, no `--reload`,
  four uvicorn workers, `--proxy-headers` so client IPs survive the proxy.
- **Frontend** — `npm ci` + `vite build`, served by nginx. No dev server and no
  Node runtime in the shipped image.
- **Database** — named volume, no published port.

Verify:

```bash
docker compose -f docker-compose.prod.yml ps
curl -fsS http://127.0.0.1:8000/api/v1/health
curl -fsS http://127.0.0.1:8000/api/v1/health/ready
```

To run the backend without Docker:

```bash
cd backend
pip install .
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 --proxy-headers
```

Frontend without Docker: `npm ci && npm run build`, then serve `dist/` from any
static host with the headers in `frontend/nginx.conf`.

---

## 7. HTTPS

**Both services bind to `127.0.0.1` in the production compose file.** They are
not reachable from outside the host until you put a TLS-terminating reverse
proxy in front of them. That is intentional — it makes serving the app over
plain HTTP an explicit act rather than the default.

Terminate TLS at nginx, Caddy, Traefik or your platform's load balancer, then:

```
https://app.example.com  ->  127.0.0.1:8080   (frontend)
https://api.example.com  ->  127.0.0.1:8000   (backend)
```

The proxy must forward `X-Forwarded-For` and `X-Forwarded-Proto`; uvicorn runs
with `--proxy-headers` so client addresses reach the rate limiter intact.

Once HTTPS is confirmed working, set `HSTS_ENABLED=true`. Not before: sending
HSTS from a host that is not yet TLS-terminated locks browsers out of it.

---

## 8–9. Domains and CORS

The frontend calls the API directly from the browser, so the API must permit
the frontend's origin:

```
CORS_ORIGINS=https://app.example.com
VITE_API_BASE_URL=https://api.example.com
```

`VITE_API_BASE_URL` is inlined by Vite at build time — changing it requires a
**rebuild**, not a restart. Serving both from one domain via a path prefix also
works; then `CORS_ORIGINS` is that single origin.

---

## 10. Secret management

- Never commit `.env`, `.env.production`, keys or certificates. `.gitignore`
  already excludes them; only the `.example` files are tracked.
- Rotate `JWT_SECRET_KEY` by replacing it and restarting. Every existing token
  becomes invalid, so users sign in again — schedule accordingly.
- AI provider keys are read server-side only and are never returned by an API
  response, never logged, and never reach the browser.
- If a key leaks, revoke it at the provider first, then rotate here.

---

## 11. Backups

See [backup-recovery.md](backup-recovery.md). Two things must be backed up
together: the **PostgreSQL database** and the **`dataset_storage` volume** that
holds uploaded datasets and generated reports. A database restored without its
storage volume leaves rows pointing at files that no longer exist.

---

## 12. Health endpoints

| Endpoint | Purpose | Behaviour |
|---|---|---|
| `GET /api/v1/health` | Liveness | Process-level only; touches no dependency. Use for container restarts. |
| `GET /api/v1/health/ready` | Readiness | Checks the database and AI provider configuration. `503` when a dependency is down. Use to gate traffic. |

Readiness reports dependency *names and states* only — never a connection
string, host or credential. Point the orchestrator's liveness probe at
`/health` and its readiness probe at `/health/ready`; using readiness for
liveness would restart a healthy container during a brief database blip.

---

## 13. Troubleshooting

**API exits immediately with "Invalid production configuration"**
Working as designed. Set the variables it lists.

**Browser console: blocked by CORS policy**
The frontend origin is not in `CORS_ORIGINS`. It must match scheme, host and
port exactly — `https://app.example.com` does not match `https://www.app.example.com`.

**Frontend loads but every request fails**
`VITE_API_BASE_URL` was wrong at build time. Rebuild the frontend image; a
restart will not pick it up.

**`429 rate_limited`**
Expected under load. Tune `RATE_LIMIT_*`; see the multi-replica note in
[security.md](security.md#rate-limiting).

**`413 payload_too_large`**
Raise `MAX_REQUEST_BODY_MB`, or `MAX_UPLOAD_SIZE_MB` for dataset uploads.

**Readiness is `degraded`**
Normal with `AI_PROVIDER=null` or no key set. The platform runs fully; AI
features fall back to deterministic output.

**Migration fails and the API never starts**
Correct behaviour. Read `docker compose -f docker-compose.prod.yml logs migrate`,
fix the cause, re-run. Restore from backup if the schema is inconsistent.

---

## 14. Monitoring recommendations

Nothing here requires a monitoring platform, and none is bundled. What the
application already emits:

- **Structured JSON logs** (`LOG_JSON=true`) with timestamp, level, logger,
  message and `request_id`; access lines add status and duration in
  milliseconds. Ship stdout to your log aggregator.
- **`X-Request-ID`** on every response, echoed from the request when supplied,
  so a user-reported failure can be traced to its log lines.

Worth alerting on: `/health/ready` returning 503; a rising 5xx rate; repeated
`Rate limit exceeded` from one source; `AI provider failed`; and container
restarts. Add an APM agent (OpenTelemetry, Sentry) at the ASGI layer if you
need traces — the middleware stack is the natural insertion point.
