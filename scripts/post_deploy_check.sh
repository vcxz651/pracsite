#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BASE_URL="${BASE_URL:-https://pracsite-production.up.railway.app}"
LOG_LINES="${LOG_LINES:-200}"
RUN_PREWARM=1

if [[ "${PYTHON_BIN:-}" == "" ]]; then
  if [[ -x "./.venv/bin/python" ]]; then
    PYTHON_BIN="./.venv/bin/python"
  else
    PYTHON_BIN="python"
  fi
fi

for arg in "$@"; do
  case "$arg" in
    --skip-prewarm)
      RUN_PREWARM=0
      ;;
    -h|--help)
      cat <<'EOF'
Usage: bash scripts/post_deploy_check.sh [--skip-prewarm]

Runs the standard post-deploy verification flow:
1. railway status
2. railway logs --lines N
3. Verify collectstatic marker and staticfiles warning absence
4. curl home and demo pages
5. railway run manage.py check
6. railway run prewarm_demo (unless --skip-prewarm)
EOF
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 1
      ;;
  esac
done

echo "[1/6] Railway status"
railway status

echo
echo "[2/6] Recent deploy logs"
LOG_OUTPUT="$(railway logs --lines "$LOG_LINES")"
printf '%s\n' "$LOG_OUTPUT"

echo
echo "[3/6] Deploy log assertions"
if [[ "$LOG_OUTPUT" != *"static files copied to '/app/staticfiles'"* ]]; then
  echo "collectstatic marker not found in recent logs" >&2
  exit 1
fi
if [[ "$LOG_OUTPUT" == *"No directory at: /app/staticfiles/"* ]]; then
  echo "staticfiles warning still present in recent logs" >&2
  exit 1
fi
echo "collectstatic marker found and staticfiles warning absent"

echo
echo "[4/6] HTTP checks"
curl -I -L --max-time 20 "$BASE_URL/"
curl -I -L --max-time 20 "$BASE_URL/demo/"

echo
echo "[5/6] Django check with Railway environment"
railway run "$PYTHON_BIN" manage.py check

if [[ "$RUN_PREWARM" -eq 1 ]]; then
  echo
  echo "[6/6] Demo prewarm"
  PYTHON_BIN="$PYTHON_BIN" railway run bash scripts/prewarm_demo.sh
else
  echo
  echo "[6/6] Demo prewarm skipped"
fi
