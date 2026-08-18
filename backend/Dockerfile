# Backend image. Two targets share one dependency layer:
#
#   development  editable install with dev extras, uvicorn --reload
#   production   runtime dependencies only, no reload, multiple workers
#
# Build the production target explicitly:
#   docker build --target production -t aibi-backend:prod ./backend
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependency layer first so source edits do not invalidate the install cache.
COPY pyproject.toml README.md ./
COPY app/__init__.py ./app/__init__.py


# --- Development -------------------------------------------------------------
FROM base AS development

RUN pip install --upgrade pip && pip install -e ".[dev]"

COPY . .

# Non-root by default.
RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/v1/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]


# --- Production --------------------------------------------------------------
FROM base AS production

# Runtime dependencies only: no pytest, mypy or ruff in the shipped image.
RUN pip install --upgrade pip && pip install .

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x ./docker-entrypoint.sh

# The storage root is created up front and owned by the runtime user, so a
# bind-mounted volume does not land root-owned and unwritable.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/var/storage \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Liveness only - readiness is checked by the orchestrator, which can tolerate
# a dependency being briefly unavailable without killing the container.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/v1/health', timeout=4).status == 200 else 1)"

# No --reload. The worker count is an environment variable rather than a
# baked-in constant: it must follow the CPU allocation, and it also determines
# how the in-process rate limiter behaves, because each worker keeps its own
# counters. Set UVICORN_WORKERS=1 when the configured RATE_LIMIT_* budgets need
# to be exact - see docs/security.md#rate-limiting.
ENV UVICORN_WORKERS=4

# The entrypoint applies pending migrations before starting uvicorn, so an
# image deployed straight to a managed platform brings its own schema rather
# than relying on a compose command that platform never runs. It reads
# UVICORN_WORKERS and PORT at start-up and execs uvicorn as PID 1.
ENTRYPOINT ["/app/docker-entrypoint.sh"]
