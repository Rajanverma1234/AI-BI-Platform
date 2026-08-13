# Architecture

Concise, living description of how the platform is put together. Update this
file whenever a structural decision changes.

## 1. System shape

```
Browser
  │  HTTP (JSON), CORS-restricted
  ▼
Frontend  (React + TypeScript + Vite)          :5173
  │  centralised API client → /api/v1/*
  ▼
Backend   (FastAPI + Pydantic + SQLAlchemy)    :8000
  ├─ AI provider abstraction ──► external AI providers (optional)
  ▼
PostgreSQL (SQLAlchemy async + Alembic)        :5432
```

Each tier is a separate container in `docker-compose.yml` on one bridge
network; the browser reaches backend and frontend through published host ports,
while the backend reaches the database by the compose service name `db`.

## 2. Backend layering

Dependencies point strictly downward. A layer never imports from the layer above.

| Layer | Location | Responsibility |
| --- | --- | --- |
| API | `app/api/v1/endpoints/` | HTTP shape only: routing, status codes, response models |
| Dependencies | `app/api/deps.py` | Typed FastAPI dependencies (`DbSession`, `AppSettings`, `Provider`) |
| Schemas | `app/schemas/` | Pydantic request/response contracts |
| Services | `app/services/` | Business logic; no FastAPI imports |
| Models | `app/models/` | SQLAlchemy ORM entities |
| Database | `app/db/` | Engine, session factory, declarative base, mixins |
| Core | `app/core/` | Config, logging, middleware, error handling, exceptions |
| AI | `app/ai/` | Provider-agnostic AI interface and registry |
| Utils | `app/utils/` | Pure helpers with no framework dependency |

Routes stay thin: they translate HTTP to a service call and back. Anything a
second endpoint might need belongs in `app/services/`.

### API versioning

Every route is mounted under `settings.API_V1_PREFIX` (`/api/v1`) through a
single aggregating router (`app/api/v1/router.py`). A future `v2` adds a
sibling package and a second `include_router` call in `app/main.py`; `v1` keeps
working untouched.

### Configuration

`app/core/config.py` defines one `Settings` model (pydantic-settings) read from
the environment, cached with `lru_cache`. Nothing else reads `os.environ`.
`CORS_ORIGINS` accepts either JSON or a comma-separated list; it is annotated
`NoDecode` so the field validator, not the settings source, does the parsing.

### Error handling

All handled failures subclass `AppError` (`app/core/exceptions.py`). Handlers
registered in `app/core/errors.py` render one envelope for every failure:

```json
{ "error": { "code": "not_found", "message": "...", "details": null },
  "request_id": "0f3c…" }
```

Unhandled exceptions are logged with a traceback and returned as a generic
`internal_error` so internal details never reach the client. The frontend
mirrors this shape in `ApiError`.

### Logging

`app/core/logging.py` configures the root logger: human-readable in
development, single-line JSON when `LOG_JSON=true`. `RequestContextMiddleware`
assigns each request a `X-Request-ID` (honouring an inbound one), stores it in a
`ContextVar`, and every log record emitted during that request carries it.

### Database

SQLAlchemy 2.0 async (`asyncpg`) with `AsyncSession`. `get_db` yields a
request-scoped session that commits on success and rolls back on error. Models
inherit `UUIDPrimaryKeyMixin` and `TimestampMixin`; a metadata naming convention
keeps constraint names deterministic so migrations stay reviewable.

## 3. Data model

Initial entities only — BI/AI tables arrive with the features that need them.

```
users ──1:N──► workspaces ──1:N──► projects
```

- `users` — `email` unique + indexed, `hashed_password` nullable until auth lands
- `workspaces` — globally unique `slug`, `owner_id` → `users.id` (ON DELETE CASCADE, indexed)
- `projects` — `workspace_id` → `workspaces.id` (ON DELETE CASCADE, indexed),
  `slug` unique **per workspace** via `uq_projects_workspace_id_slug`

All three carry UUID primary keys and timezone-aware `created_at` / `updated_at`.

## 4. Authentication and authorization

### Flow

```
register ──► Argon2id hash stored ──► login ──► signed JWT ──► Authorization: Bearer <token>
                                                                      │
                                            get_current_user dependency resolves the user
```

`POST /auth/register` creates the account; `POST /auth/login` returns an access
token; every protected route resolves the caller through one dependency.

### Where the pieces live

| Concern | Module |
| --- | --- |
| Password hashing, token sign/verify | `app/core/security.py` |
| Register / authenticate / issue token | `app/services/auth_service.py` |
| `CurrentUser` dependency | `app/api/deps.py` |
| Routes | `app/api/v1/endpoints/auth.py` |
| Request/response contracts | `app/schemas/auth.py`, `app/schemas/user.py` |

`app/core/security.py` imports neither FastAPI nor SQLAlchemy, so the crypto is
testable on its own.

### Passwords

Argon2id via `argon2-cffi`, cost parameters configurable
(`PASSWORD_HASH_TIME_COST`, `_MEMORY_COST`, `_PARALLELISM`). Login rehashes
transparently when those parameters change. `verify_password` always runs one
hash comparison — even for an unknown email — so response timing does not
reveal whether an account exists.

### Tokens

HS256 JWT carrying `sub` (user id), `iat`, `exp` and `type: "access"`. The
`type` claim means a future refresh token cannot be replayed as an access
token. `JWT_SECRET_KEY` comes from the environment; **production refuses to
start without it**, and other environments fall back to a value explicitly
named `insecure-development-only-…`. Any missing, malformed, expired,
wrongly-signed or wrong-type token yields a 401 in the standard error envelope.

### What is deliberately not leaked

- Login returns one message — `Incorrect email or password.` — for unknown
  email, wrong password and disabled account alike.
- `password_hash` appears in no schema, so it cannot escape through a response.
- Cross-tenant reads return **404, not 403**. A 403 would confirm that an id
  exists, letting an attacker enumerate other tenants' resources. The trade-off
  is that a user who genuinely lost access sees "not found"; the check lives in
  `workspace_service.get_workspace_for_user`, so it is a one-line change if a
  future membership model needs a real 403.

### Authorization model

Membership is ownership: a workspace has exactly one `owner_id`, and a project
belongs to exactly one workspace.

```
GET /workspaces/{ws}/projects/{p}
  │
  ├─ get_current_user            → 401 if the token is bad
  ├─ get_workspace_for_user      → 404 unless the caller owns {ws}
  └─ project scoped to {ws}.id   → 404 if {p} lives in another workspace
```

Every project query is filtered by the already-authorised workspace id, so a
valid project id addressed through the wrong workspace cannot resolve. When
richer roles arrive (a `workspace_members` table), only
`get_workspace_for_user` changes — callers keep working.

## 5. AI provider abstraction

`app/ai/base.py` declares `AIProvider` (`is_configured`, `complete`, `stream`)
plus Pydantic request/response types. `app/ai/registry.py` maps a name to a
factory; `AI_PROVIDER` selects one at runtime.

- `null` (default) — offline stub, so the platform boots with no credentials
- `anthropic` — HTTP call to the Messages API, key read from the environment

Adding a provider means one new module and one `register_provider` line. No
application code imports a provider directly, and no credential is ever stored
in the repository.

## 6. Frontend structure

| Directory | Responsibility |
| --- | --- |
| `src/routes/` | Route table consumed by `createBrowserRouter` |
| `src/pages/` | Route-level screens |
| `src/auth/` | `AuthProvider`, `useAuth`, `ProtectedRoute` / `GuestOnlyRoute` |
| `src/features/` | Feature-scoped components (e.g. `health/BackendStatus`) |
| `src/components/` | Reusable UI (`ui/`) and the layout shells (`layout/`) |
| `src/lib/` | `apiClient` — the only module that calls `fetch`; `authToken` storage |
| `src/api/` | Typed endpoint wrappers built on `apiClient` |
| `src/hooks/` | `useAsync` — the loading/error/data state foundation |
| `src/config/` | Typed `import.meta.env` access |
| `src/types/` | Shared API types mirroring backend schemas |

`apiClient` centralises URL construction, timeouts, JSON parsing and error
normalisation, and turns every failure into an `ApiError`. `useAsync` gives each
screen `status`/`data`/`error`/`reload` with automatic request cancellation.
`ErrorBoundary` wraps the router so a render crash degrades to a message.

### Auth state

`AuthProvider` (React context — no extra state library) holds
`status | user | login | register | logout`. On load, a stored token is treated
as unproven until `/auth/me` confirms it; a rejected token is discarded. The
route table splits into a `GuestOnlyRoute` branch (login, register) and a
`ProtectedRoute` branch (everything else), and both render a spinner while
`status === 'loading'` so a valid session is never bounced to the login screen.

`apiClient` attaches `Authorization: Bearer <token>` automatically; `withAuth:
false` opts out for login and register.

**Token storage.** The token lives in a module variable mirrored into
`localStorage`, so a reload keeps the session. localStorage is reachable by any
script on the origin, so this accepts some XSS exposure in exchange for a
stateless backend; the stronger option (an httpOnly refresh cookie) needs
session endpoints that do not exist yet. Every read and write goes through
`src/lib/authToken.ts`, so that change touches one file.

## 7. Testing strategy

Tests are part of the definition of done, not a follow-up task.

- **Backend** — pytest + pytest-asyncio, `httpx.ASGITransport` against the real
  app. The suite runs on in-memory SQLite and needs no external service.
  `tests/test_migrations.py` applies the Alembic chain to a throwaway database
  and asserts the resulting schema matches `Base.metadata`, so migrations cannot
  silently drift from the models.
  Auth, workspace and project suites cover the happy paths plus the tenancy
  boundary (cross-user and cross-workspace access).
- **Frontend** — Vitest + Testing Library in jsdom. `src/test/mockApi.ts`
  provides a route-aware `fetch` stub keyed by `"METHOD /path"`, and
  `renderWithProviders` mounts the real route table inside `AuthProvider`. Tests
  cover the API client, error boundary, routing, login/register forms, auth
  state, protected routes, logout, and workspace/project loading and creation.
- **Live integration (opt-in)** — `src/api/*.integration.test.ts` drive the real
  API modules against a running backend; skipped unless `RUN_API_INTEGRATION=1`.
- **Static analysis** — `mypy --strict` over `app/`, `ruff` for lint/imports,
  `tsc -b` for the frontend.

## 8. Conventions for future work

1. New endpoints: schema → service → route, registered on the v1 router.
2. Model changes always ship with an Alembic revision; `alembic check` must be clean.
3. Raise `AppError` subclasses rather than returning ad-hoc error payloads.
4. Frontend network access goes through `src/api/*` on top of `apiClient`.
5. Protected routes take `CurrentUser`; tenant-scoped reads go through
   `get_workspace_for_user` rather than querying by id directly.
6. Every change adds or updates tests, and the existing suites must stay green.
