# AI BI Platform

A production-oriented platform for AI-assisted business intelligence: connect
data, ask questions in natural language, and turn the answers into shareable
analysis.

This repository currently contains the **foundation** — a working, tested
end-to-end skeleton (API, database, migrations, frontend shell, AI provider
abstraction, Docker, test suites). The BI and AI features are built on top of it
in subsequent tasks.

## Tech stack

| Area | Choice |
| --- | --- |
| Frontend | React 19, TypeScript 5.7, Vite 6, React Router 7 |
| Backend | Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic |
| Database | PostgreSQL 17 (`asyncpg`) |
| Infrastructure | Docker, Docker Compose |
| Tests | pytest + pytest-asyncio + httpx, Vitest + Testing Library |
| Static analysis | mypy (strict), ruff, `tsc -b` |

## Repository layout

```
.
├── backend/              FastAPI service
│   ├── app/
│   │   ├── api/v1/       Versioned routes + typed dependencies
│   │   ├── core/         Config, logging, middleware, error handling
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
│       ├── components/   Reusable UI + layout shell
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
| `AI_PROVIDER` | `null` | `null` (offline stub) or `anthropic` |
| `AI_MODEL` | — | Optional model override |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | — | Read from the environment only; never commit them |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Backend origin used by the browser |
| `VITE_API_VERSION_PREFIX` | `/api/v1` | API prefix used by the frontend |

Secrets are never committed: `.env*` is git-ignored (except `.env.example`), and
no credential is hard-coded anywhere in the source.

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

The home screen calls `/api/v1/health` and shows whether the backend is
reachable — the quickest way to confirm the stack is wired up.

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

**Optional live check** — runs the real API client against a running backend:

```bash
cd frontend
RUN_API_INTEGRATION=1 VITE_API_BASE_URL=http://127.0.0.1:8000 \
  npx vitest run src/api/health.integration.test.ts
```

## Database migrations

```bash
cd backend
alembic upgrade head                          # apply
alembic revision --autogenerate -m "message"  # create from model changes
alembic check                                 # fail if models and migrations drift
alembic downgrade -1                          # roll back one revision
```

Initial schema: `users` → `workspaces` → `projects`, with UUID primary keys,
timezone-aware timestamps, cascading foreign keys, and a per-workspace unique
project slug.

## Working on this codebase

Tests are a permanent part of the project. Every change should keep
`pytest`, `npm test`, `mypy`, `ruff` and `npm run build` green, and new
functionality ships with tests alongside it. See
[docs/architecture.md](docs/architecture.md#7-conventions-for-future-work) for
the conventions new features are expected to follow.
