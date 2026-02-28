#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python}"
PORT="${PORT:-8000}"
GUNICORN_TIMEOUT="${GUNICORN_TIMEOUT:-120}"

"$PYTHON_BIN" manage.py migrate
"$PYTHON_BIN" manage.py collectstatic --noinput
exec gunicorn pracsite.wsgi:application --bind "0.0.0.0:${PORT}" --timeout "${GUNICORN_TIMEOUT}"
