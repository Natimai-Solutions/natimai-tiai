#!/usr/bin/env bash
# Container entrypoint. Modes:
#   api      run migrations then serve the FastAPI app (default)
#   worker   run the worker loop (e-mail outbox + periodic tasks)
#   migrate  run Alembic migrations and exit
set -euo pipefail

mode="${1:-api}"

case "$mode" in
  api)
    alembic upgrade head
    python -m app.scripts.seed_admin || true
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000
    ;;
  worker)
    exec python -m app.core.worker
    ;;
  migrate)
    exec alembic upgrade head
    ;;
  *)
    echo "Unknown mode: $mode (expected api|worker|migrate)" >&2
    exit 1
    ;;
esac
