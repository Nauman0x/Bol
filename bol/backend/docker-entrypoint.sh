#!/bin/sh
# Entrypoint for the API service only (backend/Dockerfile) — the worker
# (Dockerfile.worker) has its own CMD and never runs migrations, since only
# one process should race to apply them on a deploy with multiple replicas.
set -e

echo "Running database migrations..."
alembic upgrade head

# ":: " binds dual-stack (IPv4-mapped + IPv6) — Railway's private network
# resolves *.railway.internal to an IPv6-only address, so a plain 0.0.0.0
# bind means the worker service can never reach this one over
# API_BASE_URL. $PORT is what Railway (or any PaaS) actually routes traffic
# to; 8000 is only a fallback for plain `docker run` / local use.
exec uvicorn app.main:app --host :: --port "${PORT:-8000}"
