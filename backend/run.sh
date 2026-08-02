#!/usr/bin/env bash
# Boots the whole stack: Redis, MCP server, Celery worker, Flask.
# Elastic is Cloud-hosted, so nothing starts a database here.
set -euo pipefail

cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
PORT="${PORT:-5000}"
HOST="${HOST:-127.0.0.1}"
PY="./venv/bin/python"

if [ ! -d venv ]; then
  echo "==> creating venv"
  python3 -m venv venv
  ./venv/bin/pip install --quiet --upgrade pip
  ./venv/bin/pip install --quiet -r requirements.txt
fi

PIDS=()
cleanup() {
  echo ""
  echo "==> shutting down"
  for pid in "${PIDS[@]:-}"; do kill "$pid" 2>/dev/null || true; done
}
trap cleanup EXIT INT TERM

# --- Redis ------------------------------------------------------------------
# Homebrew's default config loads modules that may not be present, so we start
# a bare instance rather than using `brew services`.
if ! redis-cli ping >/dev/null 2>&1; then
  echo "==> starting redis"
  mkdir -p .redis
  redis-server --port 6379 --daemonize yes --save "" --appendonly no --dir "$(pwd)/.redis"
  sleep 1
fi
redis-cli ping >/dev/null 2>&1 && echo "    redis      ok" || { echo "!! redis failed"; exit 1; }

# --- MCP server -------------------------------------------------------------
if ! curl -sf "http://127.0.0.1:8000/mcp/health" >/dev/null 2>&1; then
  echo "==> starting mcp server"
  (cd "$ROOT/mcp" && "$ROOT/backend/venv/bin/python" server.py --http > "$ROOT/backend/.mcp.log" 2>&1) &
  PIDS+=($!)
  for _ in $(seq 1 20); do
    curl -sf "http://127.0.0.1:8000/mcp/health" >/dev/null 2>&1 && break
    sleep 0.5
  done
fi
curl -sf "http://127.0.0.1:8000/mcp/health" >/dev/null 2>&1 \
  && echo "    mcp        ok" || echo "    mcp        DOWN (see backend/.mcp.log)"

# --- Celery worker ----------------------------------------------------------
echo "==> starting celery worker"
./venv/bin/celery -A tasks worker --loglevel=info --concurrency="${CELERY_CONCURRENCY:-4}" \
  > .celery.log 2>&1 &
PIDS+=($!)
sleep 3
./venv/bin/celery -A tasks inspect ping --timeout 3 >/dev/null 2>&1 \
  && echo "    worker     ok" || echo "    worker     DOWN (see backend/.celery.log)"

# --- Flask ------------------------------------------------------------------
echo "==> starting flask on http://${HOST}:${PORT}"
$PY app.py &
PIDS+=($!)

for _ in $(seq 1 30); do
  if curl -sf "http://${HOST}:${PORT}/api/health" >/dev/null 2>&1; then
    echo ""
    curl -s "http://${HOST}:${PORT}/api/health" | $PY -c "
import json, sys
h = json.load(sys.stdin)
for name, s in h['subsystems'].items():
    mark = 'ok  ' if s['status'] in ('ok', 'configured') else 'DOWN'
    print(f'    [{mark}] {name:<9} {s[\"status\"]}')
print()
print(f'    ready={h[\"ready\"]}  llm={h[\"subsystems\"][\"llm\"][\"provider\"]}')
"
    echo ""
    echo "    http://${HOST}:${PORT}/api/health"
    wait
    exit 0
  fi
  sleep 0.5
done

echo "!! flask did not come up within 15s" >&2
exit 1
