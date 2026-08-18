# AI BI Platform

A production-oriented platform for AI-assisted business intelligence: connect
data, ask questions in natural language, and turn the answers into shareable
analysis.

This repository currently contains the **foundation plus authentication and
multi-tenant workspaces** — a working, tested end-to-end slice: JWT auth,
per-user workspaces and projects, database migrations, a React app with login /
register / protected routes, an AI provider abstraction, Docker, and test
suites. The BI and AI features are built on top of it in subsequent tasks.

## Tech stack

| Area | Choice |
| --- | --- |
| Frontend | React 19, TypeScript 5.7, Vite 6, React Router 7 |
| Backend | Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic |
| Auth | JWT (PyJWT, HS256) with Argon2id password hashing (argon2-cffi) |
| Database | PostgreSQL 17 (`asyncpg`) |
| Infrastructure | Docker, Docker Compose |
| Tests | pytest + pytest-asyncio + httpx, Vitest + Testing Library |
| Static analysis | mypy (strict), ruff, `tsc -b` |

## Repository layout

```
.
├── backend/              FastAPI service
│   ├── app/
│   │   ├── api/v1/       Versioned routes + typed dependencies (CurrentUser)
│   │   ├── core/         Config, logging, middleware, errors, security (hash/JWT)
│   │   ├── db/           Engine, session, declarative base + mixins
│   │   ├── models/       SQLAlchemy models (users, workspaces, projects)
│   │   ├── schemas/      Pydantic request/response contracts
│   │   ├── services/     Business logic
│   │   ├── ai/           Provider-agnostic AI layer + registry
│   │   └── utils/        Framework-free helpers
│   ├── alembic/          Migration environment and versions
│   └── tests/            pytest suite
├── frontend/             React + TypeScript app
│   └── src/
│       ├── api/          Typed endpoint wrappers
│       ├── auth/         AuthProvider, useAuth, route guards
│       ├── components/   Reusable UI + layout shells
│       ├── config/       Typed environment access
│       ├── features/     Feature-scoped components
│       ├── hooks/        useAsync (loading/error foundation)
│       ├── lib/          Centralised API client
│       ├── pages/        Route-level screens
│       └── routes/       Route table
├── docs/architecture.md  Architecture reference
├── docker-compose.yml    db + backend + frontend
└── .env.example          Every supported variable
```

## Architecture in one paragraph

The browser talks only to `/api/v1/*` on the backend through a single API client.
FastAPI keeps routes thin and delegates to services; services use SQLAlchemy
models over an async PostgreSQL session; Alembic owns the schema. Every failure
is rendered as one JSON error envelope and every request carries an
`X-Request-ID` that appears in the logs. AI providers sit behind an interface
so no provider is hard-wired into the application. Full detail lives in
[docs/architecture.md](docs/architecture.md).

## Setup

Prerequisites: Python 3.11+, Node.js 20+, and Docker (for PostgreSQL).

```bash
cp .env.example .env      # then edit as needed; .env is git-ignored
```

### Environment variables

Defined in [.env.example](.env.example). The important ones:

| Variable | Default | Purpose |
| --- | --- | --- |
| `ENVIRONMENT` | `development` | `development` / `test` / `staging` / `production`; production hides `/docs` |
| `DEBUG` | `false` | FastAPI debug mode |
| `LOG_LEVEL` | `INFO` | Root log level |
| `LOG_JSON` | `false` | `true` emits single-line JSON logs |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `aibi` | Database credentials |
| `POSTGRES_HOST` / `POSTGRES_PORT` | `localhost` / `5432` | Use `db` as host under Docker Compose |
| `DATABASE_URL` | — | Full SQLAlchemy URL; overrides the discrete values above |
| `POSTGRES_HOST_PORT` | `5432` | Host port mapped to the database container |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated or JSON list of allowed origins |
| `JWT_SECRET_KEY` | — | **Required in production**; elsewhere a clearly-marked insecure placeholder is used |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | Access token lifetime |
| `PASSWORD_HASH_TIME_COST` / `_MEMORY_COST` / `_PARALLELISM` | `3` / `65536` / `4` | Argon2id cost parameters |
| `AI_PROVIDER` | `null` | `null` (offline stub) or `anthropic` |
| `AI_MODEL` | — | Optional model override |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | — | Read from the environment only; never commit them |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Backend origin used by the browser |
| `VITE_API_VERSION_PREFIX` | `/api/v1` | API prefix used by the frontend |

Generate a signing key with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Secrets are never committed: `.env*` is git-ignored (except `.env.example`), and
no credential is hard-coded anywhere in the source. Starting the app with
`ENVIRONMENT=production` and no `JWT_SECRET_KEY` fails immediately rather than
signing tokens with a known key.

## API

| Method | Endpoint | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/v1/health` | — | Liveness |
| GET | `/api/v1/health/ready` | — | Readiness (database + AI provider) |
| POST | `/api/v1/auth/register` | — | Create an account → `201` `UserResponse` |
| POST | `/api/v1/auth/login` | — | Exchange credentials → `TokenResponse` |
| GET | `/api/v1/auth/me` | Bearer | The authenticated user |
| POST | `/api/v1/workspaces` | Bearer | Create a workspace (caller becomes owner) |
| GET | `/api/v1/workspaces` | Bearer | List the caller's workspaces |
| GET | `/api/v1/workspaces/{id}` | Bearer | Get one workspace |
| PATCH | `/api/v1/workspaces/{id}` | Bearer | Update name / slug / description |
| DELETE | `/api/v1/workspaces/{id}` | Bearer | Delete a workspace and its projects |
| POST | `/api/v1/workspaces/{ws}/projects` | Bearer | Create a project |
| GET | `/api/v1/workspaces/{ws}/projects` | Bearer | List projects |
| GET | `/api/v1/workspaces/{ws}/projects/{id}` | Bearer | Get one project |
| PATCH | `/api/v1/workspaces/{ws}/projects/{id}` | Bearer | Update a project |
| DELETE | `/api/v1/workspaces/{ws}/projects/{id}` | Bearer | Delete a project |

Authenticate with `Authorization: Bearer <access_token>`.

```bash
curl -X POST localhost:8000/api/v1/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"a-strong-password","display_name":"You"}'

TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"a-strong-password"}' | jq -r .access_token)

curl localhost:8000/api/v1/auth/me -H "Authorization: Bearer $TOKEN"
curl -X POST localhost:8000/api/v1/workspaces -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"name":"Revenue Analytics"}'
```

### Authorization model

A workspace has one owner; a project belongs to one workspace. A workspace or
project that the caller does not own returns **404, not 403** — a 403 would
confirm the id exists and allow tenant enumeration. Slugs are globally unique
for workspaces and unique per workspace for projects; a clash returns `409`.
See [docs/architecture.md](docs/architecture.md#4-authentication-and-authorization).

## Running locally

Start PostgreSQL (easiest via Compose):

```bash
docker compose up -d db
```

**Backend**

```bash
cd backend
python -m venv .venv
source .venv/Scripts/activate        # Windows;  source .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"

alembic upgrade head                 # apply migrations
uvicorn app.main:app --reload        # http://localhost:8000
```

- Health: <http://localhost:8000/api/v1/health>
- Readiness (checks the database): <http://localhost:8000/api/v1/health/ready>
- API docs: <http://localhost:8000/docs>

**Frontend**

```bash
cd frontend
npm install
npm run dev                          # http://localhost:5173
```

Open <http://localhost:5173>, register an account, and you land in the app. The
overview screen calls `/api/v1/health` to confirm connectivity; **Workspaces**
lets you create a workspace and add projects to it. Signing out clears the
token and returns you to the login screen.

## Running with Docker

```bash
cp .env.example .env
docker compose up --build
```

| Service | URL |
| --- | --- |
| Frontend | <http://localhost:5173> |
| Backend | <http://localhost:8000> |
| PostgreSQL | `localhost:5432` |

The backend container waits for the database healthcheck, runs
`alembic upgrade head`, then starts uvicorn with reload. Source directories are
bind-mounted, so edits on the host reload inside the containers.

```bash
docker compose ps            # status and health
docker compose logs -f backend
docker compose down          # stop;  add -v to also drop the database volume
```

> **After changing dependencies, rebuild the image.** Source is bind-mounted,
> but installed packages live in the image, so a new entry in `pyproject.toml`
> or `package.json` is not picked up by a plain restart — the container will
> crash with `ModuleNotFoundError` (or its JS equivalent) while the frontend
> shows "Could not reach the API".
>
> ```bash
> docker compose up -d --build backend
> ```

> **This compose file is for development only.** It bind-mounts source, runs
> uvicorn with `--reload` and publishes the database port. For production use
> `docker-compose.prod.yml` — see [Production deployment](#production-deployment).

## Production deployment

```bash
cp .env.production.example .env.production   # fill in every REQUIRED value
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

The production stack differs from development in every way that matters:
release image targets (no reload, no dev dependencies, no dev server), no
source bind-mounts, no published database port, migrations as a one-shot step
that must succeed before the API starts, and both services bound to
`127.0.0.1` behind a TLS-terminating reverse proxy.

Production **refuses to start** without `JWT_SECRET_KEY` (≥ 32 chars), a
non-default `POSTGRES_PASSWORD`, and explicit HTTPS `CORS_ORIGINS`. It lists
every problem at once rather than failing on the first.

| Document | Covers |
| --- | --- |
| [docs/deployment.md](docs/deployment.md) | Environment variables, migrations, HTTPS, domains, troubleshooting, monitoring |
| [docs/security.md](docs/security.md) | Authentication, authorization, secrets, uploads, AI/NLQ, CORS, headers, rate limits, logging |
| [docs/security-checklist.md](docs/security-checklist.md) | Pre-launch sign-off, with verification commands |
| [docs/backup-recovery.md](docs/backup-recovery.md) | Database and storage backup, restore, migration recovery |

## Running tests

**Backend** — no external services required; the suite runs on in-memory SQLite.

```bash
cd backend
pytest                    # tests
pytest --cov=app          # with coverage
mypy                      # strict type checking
ruff check .              # lint + import order
```

**Frontend**

```bash
cd frontend
npm test                  # Vitest
npm run typecheck         # tsc -b
npm run build             # production build
```

**Optional live checks** — run the real API modules against a running backend
(register → login → `/auth/me` → workspace → project):

```bash
cd frontend
RUN_API_INTEGRATION=1 VITE_API_BASE_URL=http://127.0.0.1:8000 \
  npx vitest run src/api/health.integration.test.ts src/api/auth.integration.test.ts
```

## Database migrations

```bash
cd backend
alembic upgrade head                          # apply
alembic revision --autogenerate -m "message"  # create from model changes
alembic check                                 # fail if models and migrations drift
alembic downgrade -1                          # roll back one revision
```

Schema: `users` → `workspaces` → `projects`, with UUID primary keys,
timezone-aware timestamps, cascading foreign keys, and a per-workspace unique
project slug.

| Revision | Change |
| --- | --- |
| `0001_initial` | `users`, `workspaces`, `projects` |
| `0002_auth_user_fields` | Renames `hashed_password` → `password_hash` (now `NOT NULL`) and `full_name` → `display_name` |
| `0003_datasets` | `datasets` |
| `0004_dataset_versions` | `dataset_versions` |
| `0005_nlq_queries` | `nlq_queries` |
| `0006_reports` | `reports` |
| `0007_insight_runs` | `insight_runs` |
| `0008_dashboards` | `dashboards`, `dashboard_widgets` |

In production, migrations run as a **separate one-shot service** that must
complete before the API starts, so a failed migration stops the deployment
rather than leaving a half-migrated database serving traffic. The application
never creates or drops tables at startup. Back up before migrating — see
[docs/backup-recovery.md](docs/backup-recovery.md#migration-recovery).

## Working on this codebase

Tests are a permanent part of the project. Every change should keep
`pytest`, `npm test`, `mypy`, `ruff` and `npm run build` green, and new
functionality ships with tests alongside it. See
[docs/architecture.md](docs/architecture.md#8-conventions-for-future-work) for
the conventions new features are expected to follow.
