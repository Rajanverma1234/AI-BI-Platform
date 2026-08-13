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

## 4. AI provider abstraction

`app/ai/base.py` declares `AIProvider` (`is_configured`, `complete`, `stream`)
plus Pydantic request/response types. `app/ai/registry.py` maps a name to a
factory; `AI_PROVIDER` selects one at runtime.

- `null` (default) — offline stub, so the platform boots with no credentials
- `anthropic` — HTTP call to the Messages API, key read from the environment

Adding a provider means one new module and one `register_provider` line. No
application code imports a provider directly, and no credential is ever stored
in the repository.

## 5. Frontend structure

| Directory | Responsibility |
| --- | --- |
| `src/routes/` | Route table consumed by `createBrowserRouter` |
| `src/pages/` | Route-level screens |
| `src/features/` | Feature-scoped components (e.g. `health/BackendStatus`) |
| `src/components/` | Reusable UI (`ui/`) and the layout shell (`layout/`) |
| `src/lib/` | `apiClient` — the only module that calls `fetch` |
| `src/api/` | Typed endpoint wrappers built on `apiClient` |
| `src/hooks/` | `useAsync` — the loading/error/data state foundation |
| `src/config/` | Typed `import.meta.env` access |
| `src/types/` | Shared API types mirroring backend schemas |

`apiClient` centralises URL construction, timeouts, JSON parsing and error
normalisation, and turns every failure into an `ApiError`. `useAsync` gives each
screen `status`/`data`/`error`/`reload` with automatic request cancellation.
`ErrorBoundary` wraps the router so a render crash degrades to a message.

## 6. Testing strategy

Tests are part of the definition of done, not a follow-up task.

- **Backend** — pytest + pytest-asyncio, `httpx.ASGITransport` against the real
  app. The suite runs on in-memory SQLite and needs no external service.
  `tests/test_migrations.py` applies the Alembic chain to a throwaway database
  and asserts the resulting schema matches `Base.metadata`, so migrations cannot
  silently drift from the models.
- **Frontend** — Vitest + Testing Library in jsdom, with `fetch` stubbed. Tests
  cover the API client, the error boundary, routing and the health screen's
  loading/success/error/retry states.
- **Static analysis** — `mypy --strict` over `app/`, `ruff` for lint/imports,
  `tsc -b` for the frontend.

## 7. Conventions for future work

1. New endpoints: schema → service → route, registered on the v1 router.
2. Model changes always ship with an Alembic revision; `alembic check` must be clean.
3. Raise `AppError` subclasses rather than returning ad-hoc error payloads.
4. Frontend network access goes through `src/api/*` on top of `apiClient`.
5. Every change adds or updates tests, and the existing suites must stay green.
