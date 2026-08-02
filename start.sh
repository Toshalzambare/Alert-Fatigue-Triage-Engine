#!/usr/bin/env bash
# Boots the whole stack: Redis, MCP, Celery, Flask, Vite.
#
#   ./start.sh          start everything, stream logs, Ctrl-C to stop
#   ./start.sh --stop   stop everything and exit
#   ./start.sh --status report what is running and exit
#
# Elastic is Cloud-hosted, so nothing here starts a database.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
MCP="$ROOT/mcp"
PY="$BACKEND/venv/bin/python"
LOGS="$ROOT/.logs"

FLASK_PORT="${PORT:-5000}"
UI_PORT="${UI_PORT:-5173}"
MCP_PORT=8000

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
ok()   { printf '  \033[32mok\033[0m    %s\n' "$1"; }
bad()  { printf '  \033[31mDOWN\033[0m  %s\n' "$1"; }
info() { printf '  \033[2m%s\033[0m\n' "$1"; }

stop_all() {
  pkill -f "celery -A tasks" 2>/dev/null
  pkill -f "$BACKEND/venv/bin/python app.py" 2>/dev/null
  pkill -f "server.py --http" 2>/dev/null
  pkill -f "vite" 2>/dev/null
  sleep 2
  for p in "$FLASK_PORT" "$UI_PORT" "$MCP_PORT"; do
    lsof -ti:"$p" 2>/dev/null | xargs kill -9 2>/dev/null
  done
}

status_all() {
  bold "status"
  redis-cli ping >/dev/null 2>&1 && ok "redis   :6379" || bad "redis"
  curl -sf "http://127.0.0.1:$MCP_PORT/mcp/health" >/dev/null 2>&1 \
    && ok "mcp     :$MCP_PORT" || bad "mcp"
  (cd "$BACKEND" && ./venv/bin/celery -A tasks inspect ping --timeout 3 >/dev/null 2>&1) \
    && ok "celery" || bad "celery"
  curl -sf "http://127.0.0.1:$FLASK_PORT/api/health" >/dev/null 2>&1 \
    && ok "flask   :$FLASK_PORT" || bad "flask"
  curl -sf "http://127.0.0.1:$UI_PORT/" >/dev/null 2>&1 \
    && ok "vite    :$UI_PORT" || bad "vite"
}

case "${1:-}" in
  --stop)   bold "stopping"; stop_all; echo "  stopped"; exit 0 ;;
  --status) status_all; exit 0 ;;
esac

# --- preflight --------------------------------------------------------------
[ -f "$ROOT/.env" ] || { echo "!! no .env at repo root"; exit 1; }
[ -x "$PY" ] || { echo "!! no venv. run: cd backend && python3 -m venv venv && ./venv/bin/pip install -r requirements.txt"; exit 1; }
[ -d "$FRONTEND/node_modules" ] || { echo "!! frontend deps missing. run: cd frontend && npm install"; exit 1; }

mkdir -p "$LOGS"
bold "cleaning up"
stop_all
echo ""

# --- redis ------------------------------------------------------------------
# Homebrew's default config loads modules that may not be installed, so start a
# bare instance rather than using `brew services`.
bold "starting services"
if ! redis-cli ping >/dev/null 2>&1; then
  mkdir -p "$LOGS/redis"
  redis-server --port 6379 --daemonize yes --save "" --appendonly no \
    --dir "$LOGS/redis" >/dev/null 2>&1
  sleep 1
fi
redis-cli ping >/dev/null 2>&1 && ok "redis" || { bad "redis"; exit 1; }

# --- mcp --------------------------------------------------------------------
# --http is required: without it mcp.run() takes stdin, hits EOF when
# backgrounded, and the HTTP bridge dies with the interpreter.
(cd "$MCP" && nohup "$PY" server.py --http > "$LOGS/mcp.log" 2>&1 &)
for _ in $(seq 1 30); do
  curl -sf "http://127.0.0.1:$MCP_PORT/mcp/health" >/dev/null 2>&1 && break
  sleep 0.5
done
curl -sf "http://127.0.0.1:$MCP_PORT/mcp/health" >/dev/null 2>&1 \
  && ok "mcp" || bad "mcp — see .logs/mcp.log"

# --- celery -----------------------------------------------------------------
# Workers import the agent at startup, so this must restart after Agent/ edits.
(cd "$BACKEND" && nohup ./venv/bin/celery -A tasks worker \
  --loglevel=info --concurrency="${CELERY_CONCURRENCY:-4}" \
  > "$LOGS/celery.log" 2>&1 &)
for _ in $(seq 1 40); do
  (cd "$BACKEND" && ./venv/bin/celery -A tasks inspect ping --timeout 2 >/dev/null 2>&1) && break
  sleep 0.5
done
(cd "$BACKEND" && ./venv/bin/celery -A tasks inspect ping --timeout 3 >/dev/null 2>&1) \
  && ok "celery" || bad "celery — see .logs/celery.log"

# --- flask ------------------------------------------------------------------
(cd "$BACKEND" && nohup "$PY" app.py > "$LOGS/flask.log" 2>&1 &)
for _ in $(seq 1 30); do
  curl -sf "http://127.0.0.1:$FLASK_PORT/api/health" >/dev/null 2>&1 && break
  sleep 0.5
done
curl -sf "http://127.0.0.1:$FLASK_PORT/api/health" >/dev/null 2>&1 \
  && ok "flask" || bad "flask — see .logs/flask.log"

# --- vite -------------------------------------------------------------------
(cd "$FRONTEND" && nohup npm run dev > "$LOGS/vite.log" 2>&1 &)
for _ in $(seq 1 40); do
  curl -sf "http://127.0.0.1:$UI_PORT/" >/dev/null 2>&1 && break
  sleep 0.5
done
curl -sf "http://127.0.0.1:$UI_PORT/" >/dev/null 2>&1 \
  && ok "vite" || bad "vite — see .logs/vite.log"

# --- subsystem report -------------------------------------------------------
echo ""
bold "subsystems"
curl -s "http://127.0.0.1:$FLASK_PORT/api/health" | "$PY" -c "
import json, sys
try:
    h = json.load(sys.stdin)
except Exception:
    print('  could not read /api/health'); raise SystemExit
G, R, D = '\033[32m', '\033[31m', '\033[0m'
for name, s in sorted(h['subsystems'].items()):
    good = s['status'] in ('ok', 'configured')
    mark = f'{G}ok{D}   ' if good else f'{R}DOWN{D} '
    detail = s.get('detail') or ''
    print(f'  {mark} {name:<9} {s[\"status\"]:<15} {detail}')
print()
if h['ready']:
    print(f'  {G}all systems ready{D}')
else:
    print(f'  {R}degraded: ' + ', '.join(h['degraded']) + D)
" 2>/dev/null

echo ""
bold "open"
info "http://localhost:$UI_PORT"
info "http://localhost:$FLASK_PORT/api/health"
echo ""
info "logs in .logs/  ·  ./start.sh --stop to shut down"
echo ""

# --- follow logs ------------------------------------------------------------
trap 'echo ""; bold "stopping"; stop_all; echo "  stopped"; exit 0' INT TERM
bold "streaming logs — Ctrl-C to stop everything"
echo ""
tail -f "$LOGS/flask.log" "$LOGS/celery.log" "$LOGS/mcp.log" 2>/dev/null
