#!/bin/sh
# Production container entrypoint.
#
# The development stack runs `alembic upgrade head` from its compose command,
# so the schema is always present locally. A managed platform (Render, Fly,
# Cloud Run) starts the image directly and never sees that command, which left
# production connected to an empty database: /health passed because it only
# issues SELECT 1, while every real query failed with `database_error`.
# Migrating here keeps the two paths honest - the schema is applied by the
# image itself, wherever it runs.
#
# Set RUN_MIGRATIONS=false when a separate release/job step owns migrations, or
# when several instances start at once and you do not want each one racing for
# Alembic's lock.
set -eu

# An explicit command wins outright, so the image stays usable as a plain
# runner: `docker compose run backend alembic downgrade -1`, and the one-shot
# `migrate` service in docker-compose.prod.yml, both go straight through.
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    echo "entrypoint: applying database migrations (alembic upgrade head)"
    alembic upgrade head
    echo "entrypoint: migrations up to date"
else
    echo "entrypoint: RUN_MIGRATIONS=false, skipping migrations"
fi

# PORT is injected by most managed platforms; 8000 keeps docker-compose and
# local `docker run` unchanged. exec so uvicorn is PID 1 and receives SIGTERM
# directly, giving it a clean shutdown instead of being killed by the runtime.
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --workers "${UVICORN_WORKERS:-4}" \
    --proxy-headers \
    --forwarded-allow-ips "*"
