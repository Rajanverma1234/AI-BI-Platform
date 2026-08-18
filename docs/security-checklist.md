# Production security checklist

Work through this before the first deployment and after any change to
authentication, storage or infrastructure. Each item says how to verify it, not
just what to want.

Legend: **[auto]** enforced by the application and verified by tests ·
**[ops]** your responsibility at deploy time.

---

## Authentication

- [auto] Passwords hashed with Argon2id; plaintext never stored or logged.
- [auto] Login timing is flat whether or not the account exists.
- [auto] Expired, malformed, wrongly-signed and wrong-type tokens are rejected.
- [auto] Authentication failures return identical wording (no account enumeration).
- [auto] `JWT_SECRET_KEY` ≥ 32 characters, required in production.
- [ops] Key generated with a CSPRNG, stored in a secret manager, never committed.
- [ops] `ACCESS_TOKEN_EXPIRE_MINUTES` matches your risk appetite (default 60).

```bash
curl -s -X POST $API/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"nobody@example.com","password":"whatever"}'   # expect 401
```

## Authorization

- [auto] Every resource resolved through User → Workspace → Project → Dataset → Version.
- [auto] Id-addressed routes (`/dashboards/{id}`, `/insights/{id}`) scoped by owner.
- [auto] Cross-tenant access returns 404, not 403 (no existence disclosure).
- [auto] Dashboards re-authorise their dataset on every read.
- [ops] Confirm with two accounts that neither can see the other's resources.

## Secrets

- [ops] `.env` / `.env.production` are **not** committed (`git ls-files | grep env`).
- [ops] No key, certificate or password in the repository history.
- [auto] AI keys are server-side only; never in a response, log or bundle.
- [auto] Only `VITE_*` values reach the browser, and they are public by nature.
- [ops] Rotation procedure agreed for `JWT_SECRET_KEY` and provider keys.

## CORS

- [auto] Wildcard origins rejected at startup in production.
- [auto] Plain `http://` non-localhost origins rejected in production.
- [ops] `CORS_ORIGINS` matches the frontend origin exactly (scheme, host, port).

## File uploads

- [auto] Client filename sanitised; storage keys server-generated.
- [auto] Extension allow-list enforced (`csv`, `xlsx` by default).
- [auto] Size ceiling enforced while streaming; no partial file left behind.
- [auto] Path traversal blocked at the storage provider.
- [ops] `MAX_UPLOAD_SIZE_MB` set for your data; storage volume has headroom.

```bash
# expect 415
curl -s -o /dev/null -w '%{http_code}\n' -X POST "$API/projects/$PID/datasets" \
  -H "Authorization: Bearer $TOKEN" -F 'file=@evil.sh'
```

## SQL and NLQ

- [auto] All queries built through SQLAlchemy; no string-concatenated SQL.
- [auto] NLQ produces a validated `QueryPlan`, never SQL.
- [auto] Plans validated against real columns before execution.
- [auto] No endpoint executes client-supplied SQL.

```bash
grep -rn "eval(\|exec(\|subprocess\|os.system\|pickle" backend/app   # expect nothing
```

## AI

- [auto] Provider selected via `AIProvider`; no vendor SDK in business logic.
- [auto] Only derived context sent to providers — never raw dataset rows.
- [auto] AI output validated; untraceable figures flagged or discarded.
- [auto] Timeout on every call; no retry loop.
- [ops] `RATE_LIMIT_AI_PER_MINUTE` set against your provider budget.
- [ops] Billing alerts configured at the provider.

## Rate limits

- [auto] Auth, AI and heavy endpoints throttled; 429 uses the standard envelope.
- [ops] `RATE_LIMIT_ENABLED=true` in production.
- [ops] **If running multiple API replicas**, limits are per replica — enforce
  globally at the ingress or move to a shared store. See
  [security.md](security.md#rate-limiting).

## Logging

- [auto] Structured JSON with `request_id`, status and duration.
- [auto] No passwords, tokens, keys, headers or dataset contents logged.
- [auto] `X-Request-ID` on every response.
- [ops] `LOG_JSON=true`; logs shipped off the host and retained.
- [ops] Log destination access-controlled — it contains operational detail.

## Errors

- [auto] One envelope for every failure.
- [auto] No stack trace, path or connection string in any response.
- [auto] `/docs`, `/redoc`, `/openapi.json` disabled in production.

```bash
curl -s -o /dev/null -w '%{http_code}\n' $API/openapi.json    # expect 404
```

## Database

- [auto] Timezone-aware timestamps.
- [auto] Schema changes only through Alembic; nothing created or dropped at boot.
- [auto] Production rejects a default `POSTGRES_PASSWORD`.
- [ops] Migrations run as the one-shot step before the API starts.
- [ops] Pool sized against `max_connections` ÷ workers.
- [ops] Database not reachable from the public network.
- [ops] Backups running **and a restore rehearsed**.

## Docker

- [auto] Production targets: no `--reload`, no dev dependencies, no dev server.
- [auto] Both images run as non-root (uid 1000 / nginx).
- [auto] Healthchecks defined.
- [ops] Database port not published.
- [ops] App ports bound to `127.0.0.1` behind a reverse proxy.
- [ops] Base images rebuilt periodically for OS patches.

## HTTPS

- [ops] TLS terminating in front of both services; valid certificate, auto-renewing.
- [ops] `HSTS_ENABLED=true` **only after** HTTPS is confirmed working.
- [ops] Proxy forwards `X-Forwarded-For` and `X-Forwarded-Proto`.

## Downloads

- [auto] Authorised through the full chain and scoped by owner.
- [auto] `Content-Disposition` filenames slugified; storage keys never exposed.
- [auto] Correct content type per format.

## Environment

- [auto] Production fails fast on missing or unsafe configuration.
- [ops] `ENVIRONMENT=production`, `DEBUG=false`.
- [ops] `.env.production.example` reviewed; every REQUIRED value set.

```bash
docker compose -f docker-compose.prod.yml logs backend | head -20
```

## Backups

- [ops] PostgreSQL dumps automated and stored off-host.
- [ops] `dataset_storage` volume backed up **with** the database.
- [ops] Restore tested end to end, not just assumed.
- [ops] Retention and encryption-at-rest decided for backup storage.

---

## Sign-off

| Area | Verified by | Date |
|---|---|---|
| Authentication & authorization | | |
| Secrets & environment | | |
| Network, TLS & CORS | | |
| Uploads, downloads & storage | | |
| AI & rate limits | | |
| Database & backups | | |
| Logging & monitoring | | |
