# Security model

What the platform defends against, how, and where the limits are. Companion to
[deployment.md](deployment.md) and [security-checklist.md](security-checklist.md).

---

## Authentication

**Passwords** are hashed with **Argon2id** (`argon2-cffi`), the current
recommendation for password storage. Cost parameters are configurable
(`PASSWORD_HASH_*`) and default to the library's own guidance. A plaintext
password is never stored, never logged and never returned by any endpoint.

`app/core/security.py` handles two subtleties:

- **Timing.** A login for an account that does not exist still performs a real
  Argon2 verification against a dummy hash, so response time cannot be used to
  enumerate registered email addresses.
- **Rehashing.** `needs_rehash` detects hashes made with older parameters, so
  raising the cost later can upgrade stored hashes on next login.

**Tokens** are JWTs signed with `JWT_SECRET_KEY` (HS256 by default), carrying
`sub`, `iat`, `exp` and a `type` claim. The type claim means a future refresh
token could never be replayed as an access token. Decoding requires `exp` and
`sub` to be present; expired, malformed, wrongly-signed and wrong-type tokens
are all rejected with the same message — a caller cannot tell a bad signature
from a disabled account.

Production refuses to start without a `JWT_SECRET_KEY` of at least 32
characters. Outside production a deliberately obvious placeholder is used,
named so it is unmistakable in a config dump.

**No refresh tokens yet.** Sessions last `ACCESS_TOKEN_EXPIRE_MINUTES`
(default 60) and then require a fresh sign-in. Adding refresh tokens later
means adding a token type and a revocation store; the `type` claim already
exists for it.

---

## Authorization

Every protected resource is resolved through its full ownership chain, on the
**backend**, on every request:

```
User → Workspace → Project → Dataset → Dataset Version → Report / Dashboard / Insight
```

Two functions carry almost all of it:

- `dataset_service.get_project_for_user` — resolves a project through its
  owning workspace.
- `dataset_access.load_for_user` — the single entry point for every read-only
  feature. It resolves user → workspace → project → dataset → version *before*
  any file is opened. Profiling, cleaning, visualisation, analytics, NLQ,
  insights, reports and dashboards all go through it, so there is one gate to
  audit rather than a dozen.

**Against IDOR.** Ids from a client are never trusted. Queries are scoped by
owner rather than filtered afterwards, so a guessed id belonging to another
tenant simply is not found — and a 404 (not a 403) means the response does not
even confirm that the resource exists.

Resources addressed by id alone — `/insights/{run_id}`, `/dashboards/{id}` —
are scoped by `user_id` in the query itself. Dashboards go further: owning the
dashboard is not enough, because the dataset it points at is re-authorised on
every read. Revoking access to a dataset therefore revokes the dashboards
built on it.

Frontend route guards exist for user experience only. They are not a security
control and the backend assumes nothing about them.

---

## Secret management

| Secret | Source | Exposure |
|---|---|---|
| `JWT_SECRET_KEY` | env | Never leaves the server |
| `POSTGRES_PASSWORD` / `DATABASE_URL` | env | Never in a response or log |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | env | Server-side only; never sent to the browser |

Nothing is hard-coded. `.gitignore` excludes `.env` and `.env.*` except the
`.example` templates, which contain placeholders only.

Secrets are never logged: startup logs the *names* of the selected storage and
AI providers, never their credentials. Rate-limit keys hash the Authorization
header rather than storing it, so a token cannot appear even in in-memory
state. Error responses carry a safe message and a request id; details stay in
the server log.

Only `VITE_*` variables reach the browser, and they hold the API URL and app
name — values that are public by nature.

---

## File upload security

Handled in `dataset_service` and the storage provider:

- **The client filename is never trusted.** `sanitise_filename` strips
  directory components (both separators), leaving a bare display name.
- **Storage keys are server-generated**: `datasets/{uuid}/data.{ext}`. No part
  of a client string becomes a path. The same applies to reports:
  `reports/{uuid}/{slug}.{ext}`, where the slug is reduced to lowercase
  alphanumerics and hyphens.
- **Defence in depth on paths.** `LocalStorageProvider._resolve` resolves every
  key and refuses anything landing outside the storage root, so a traversal bug
  upstream still cannot reach the filesystem.
- **Extensions are allow-listed** (`ALLOWED_DATASET_EXTENSIONS`, default
  `csv,xlsx`). Anything else is rejected with 415.
- **Size is enforced while streaming.** The upload is written in chunks and
  aborted the moment it exceeds `MAX_UPLOAD_SIZE_MB`, leaving no partial file.
  The file is never buffered whole in memory.
- **Uploads are data, never code.** They are written under the storage root,
  which contains no application code, and are only ever read by pandas
  parsers. Nothing uploaded is executed, and no upload can overwrite an
  application file.

---

## Dataset processing

The codebase contains no `eval`, `exec`, `subprocess`, `os.system` or
`pickle` — verifiable with a grep, and worth keeping that way.

Spreadsheet formulas are read as values by `openpyxl`; they are never
evaluated. Cleaning operations are a fixed enum of named transformations, not
user-supplied expressions.

---

## SQL and NLQ

**SQL.** Every query is built with SQLAlchemy expressions, so values are always
bound parameters. There is no string-concatenated SQL anywhere and no endpoint
that executes client-supplied SQL. The only raw fragment in the codebase is
`SELECT 1` in the health check.

**NLQ never generates SQL.** The pipeline is:

```
question → plan (AI or deterministic rules) → validate against real columns → execute on the DataFrame
```

The model emits a **`QueryPlan`** — a typed structure naming columns,
aggregations, filters and a limit. It is validated against the loaded frame
before execution: a column that does not exist is rejected, not attempted. The
executor then runs pandas operations, so even a malicious plan can only ask
for an aggregation over a column that exists.

The LLM never touches the database, never sees a connection string, and cannot
express anything the plan schema does not model.

---

## AI security

- **Keys stay server-side.** Providers read them from settings; no key crosses
  the API boundary.
- **Provider-agnostic.** Business logic depends on the `AIProvider` interface;
  concrete providers live in `app/ai/providers` and are chosen by
  `AI_PROVIDER`. No module imports a vendor SDK directly.
- **Raw data is never sent.** Every AI call receives a compact, already-computed
  context — KPIs, trend results, aggregate findings. The AI Analyst, NLQ,
  Insights and dashboard AI widgets all send derived figures, never dataset
  rows. A verbatim customer record cannot reach a provider through normal use.
- **Output is untrusted input.** Narrative is parsed as JSON with failures
  handled; NLQ plans are validated before execution; and
  `find_untraceable_numbers` cross-checks every figure the model writes against
  the context it was given, flagging anything that cannot be traced. In NLQ,
  unverifiable wording is discarded in favour of the deterministic answer.
- **Absence degrades, never breaks.** With `AI_PROVIDER=null` — the default —
  every AI feature falls back to deterministic output and says so.

### Cost protection

| Control | Setting |
|---|---|
| Request rate on AI endpoints | `RATE_LIMIT_AI_PER_MINUTE` (default 20/min) |
| Per-call timeout | `AI_REQUEST_TIMEOUT` (default 60s) |
| Output ceiling | `max_tokens` set per call site |
| Input ceiling | Context is derived and bounded by construction, not raw rows |

There is no code path that calls a provider in a loop: each request makes at
most one call, and a failure returns rather than retrying.

---

## CORS

Explicit origins only, from `CORS_ORIGINS`. Methods and headers are enumerated
rather than wildcarded, and `Content-Disposition` is exposed so the browser can
read download filenames.

Because the API is credentialed, `allow_origins=["*"]` would be a serious
mistake — production configuration **rejects a wildcard outright**, and also
rejects a plain `http://` origin for a non-localhost host.

---

## Security headers

Applied by `SecurityHeadersMiddleware` to every response, including errors:

| Header | Value | Why |
|---|---|---|
| `X-Content-Type-Options` | `nosniff` | Stops a response being reinterpreted as script |
| `X-Frame-Options` | `DENY` | Clickjacking |
| `Content-Security-Policy` | `default-src 'none'; frame-ancestors 'none'; …` | The API returns JSON; it needs nothing |
| `Referrer-Policy` | `no-referrer` | Keeps URLs out of third-party referer logs |
| `Permissions-Policy` | camera, geolocation, microphone… all `()` | Shrinks what an injection could reach |
| `Strict-Transport-Security` | opt-in via `HSTS_ENABLED` | Off by default: asserting HTTPS-only from a plain-HTTP host locks browsers out |

The frontend is served by nginx with its own policy (`frontend/nginx.conf`)
suited to a document rather than an API.

---

## Rate limiting

Fixed-window counters keyed by authenticated user, falling back to client
address. Four budgets:

| Scope | Default | Applies to |
|---|---|---|
| `auth` | 10/min | Login, registration |
| `ai` | 20/min | AI analyst, NLQ, insight generation and refresh |
| `heavy` | 30/min | Uploads, report preview/generate, dashboard refresh/export, clustering, forecasting |
| `default` | 120/min | Ordinary authenticated traffic |

Keying on identity means one tenant behind a shared NAT cannot exhaust
another's budget.

**The honest limitation.** Counters live in the API *process*, not the
container. The production image runs `UVICORN_WORKERS` uvicorn workers
(default 4), each a separate process with its own counters, so the effective
ceiling is up to `workers × replicas ×` the configured value — with the shipped
defaults a 10/min auth budget admits up to 40/min. Worse than the multiplier,
it is *unpredictable*: the kernel decides which worker accepts each connection,
so an identical burst may be throttled on one run and not the next.

This is a deliberate trade, not an oversight. It needs no Redis, and it still
does the job these limits exist for: a runaway client loop and a
credential-stuffing script both exceed any per-worker budget by orders of
magnitude. It is a backstop, not a precise quota — do not rely on it for
billing control or hard per-tenant quotas.

Two ways to get exact limits:

1. **`UVICORN_WORKERS=1`**, scaling out with replicas behind a load balancer
   that enforces the quota.
2. **Enforce at the ingress/gateway** — usually the better place, because it
   sheds load before it reaches the application at all.

Replacing `FixedWindowLimiter` with a shared-store implementation would not
change the dependency surface if a future deployment needs it.

---

## Logging

Structured JSON in production (`LOG_JSON=true`), with timestamp, level, logger,
message and `request_id`; access lines add status and duration.

**Never logged:** passwords, password hashes, tokens, Authorization headers,
API keys, database URLs, or dataset contents. Access logs record
`request.url.path` — never the query string, so a value in a URL cannot leak
into logs. Rate-limit warnings record the path and scope, never the key.

Exceptions are logged with full detail server-side; the client receives only a
safe message and the request id needed to correlate the two.

---

## Error handling

One envelope for every failure:

```json
{"error": {"code": "not_found", "message": "…", "details": null},
 "request_id": "…"}
```

Production responses never contain a stack trace, file path, connection string
or internal identifier. The catch-all handler returns "An unexpected error
occurred." and logs the rest. `/docs`, `/redoc` and `/openapi.json` are
disabled in production, and the root endpoint omits the docs link there.

---

## Downloads

Report downloads (`GET .../reports/{id}/download`) are authorised through the
full chain and additionally scoped by owning user, so another tenant's report
id returns 404. The storage key is never exposed in any response.

`Content-Disposition` filenames are rebuilt from a slugified report name —
lowercase alphanumerics and hyphens only, never the stored key or a client
string. Content types are set per format from a fixed mapping.

---

## Data protection

- Dataset files live in the storage provider, never in PostgreSQL.
- The original upload is immutable; cleaning writes a new version, so the
  lineage is always reconstructible.
- Deleting a dataset removes its stored file; deleting a report removes the row
  first and the file second, because an orphaned file is recoverable and a row
  pointing at a deleted file is not.
- Timestamps are timezone-aware (`TIMESTAMPTZ`) throughout.
- Insight runs and NLQ history store derived results and validated plans — no
  credentials, no prompts, no raw rows.

---

## Dependencies

Kept deliberately small, because every dependency is attack surface. The
backend ships 15 runtime packages; the frontend ships four (`react`,
`react-dom`, `react-router-dom`, `recharts`).

Reviewed for this release:

- `npm audit --omit=dev` reports **0 vulnerabilities**.
- No unused or duplicated packages. There is one charting library, one HTTP
  client, one PDF renderer, one PPTX renderer, and XLSX reuses the `openpyxl`
  already needed to read uploads.
- Outstanding updates are **major versions only** (pandas 3, mypy 2, pytest 9,
  reportlab 5). These are not applied here: each is a breaking change, and a
  hardening release is the wrong place to absorb one. Schedule them separately,
  behind the test suite.
- The production image installs `pip install .` — runtime dependencies only, so
  pytest, mypy and ruff are not present in the shipped artefact.

Recommended in CI: `pip-audit` for the backend and `npm audit` for the
frontend, plus a periodic base-image rebuild for OS-level patches. Neither
tool is added as a project dependency — they belong in the pipeline, not the
runtime.

---

## Deployment recommendations

1. Terminate TLS in front of both services; they bind to `127.0.0.1` by default.
2. Enable `HSTS_ENABLED=true` once HTTPS is confirmed.
3. Keep the database off the public network — the production compose file
   publishes no port for it.
4. Inject secrets from a secret manager rather than a file where possible.
5. Run migrations as the one-shot step, before the API starts.
6. Back up the database **and** the dataset storage volume together.
7. Rotate `JWT_SECRET_KEY` on any suspicion of compromise; it invalidates every
   existing session.
8. Keep `ENVIRONMENT=production` — it is what enables the startup checks and
   disables the docs.
