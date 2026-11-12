#!/usr/bin/env bash
# Container entrypoint. Modes:
#   api      run migrations then serve the FastAPI app (default)
#   worker   run the worker loop (e-mail outbox + periodic tasks)
#   migrate  run Alembic migrations and exit
set -euo pipefail

# Started as root (the image's default): give the packages volume to the
# service account, then run everything below as that account, without any
# capability left (audit S32). A container started with `user:` skips this.
if [ "$(id -u)" = "0" ] && id tiai >/dev/null 2>&1; then
  packages="${PACKAGES_DIR:-/data/packages}"
  if [ -d "$packages" ] && [ "$(stat -c %u "$packages")" != "$(id -u tiai)" ]; then
    chown -R tiai:tiai "$packages"
  fi
  exec setpriv --reuid=tiai --regid=tiai --init-groups --inh-caps=-all bash "$0" "$@"
fi

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
