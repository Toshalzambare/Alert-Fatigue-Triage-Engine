#!/usr/bin/env bash
# One-command startup (plan 05 Phase 4). Test this from a clean shell -
# "it works on my machine" is the classic hour-4 failure.
#
# Elastic is Cloud-hosted, so this script never starts a database. It sets up
# the venv, optionally waits for MCP, launches Flask, and polls health.
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-5001}"
HOST="${HOST:-127.0.0.1}"

if [ ! -d venv ]; then
  echo "==> creating venv"
  python3 -m venv venv
  ./venv/bin/pip install --quiet --upgrade pip
  ./venv/bin/pip install --quiet -r requirements.txt
else
  ./venv/bin/pip install --quiet -q -r requirements.txt 2>/dev/null || true
fi

if [ -f .env ]; then
  echo "==> using .env"
else
  echo "==> no .env (running in mock mode; copy .env.example to configure)"
fi

echo "==> starting backend on http://${HOST}:${PORT}"
./venv/bin/python app.py &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT INT TERM

# Poll health until it answers, then print the status line.
for _ in $(seq 1 30); do
  if curl -sf "http://${HOST}:${PORT}/api/health" >/dev/null 2>&1; then
    echo "==> up. subsystem status:"
    curl -s "http://${HOST}:${PORT}/api/health" \
      | ./venv/bin/python -c 'import sys,json
h=json.load(sys.stdin)
for name, s in h["subsystems"].items():
    mark = "OK  " if s["status"] in ("ok","configured") else "STUB"
    print(f"    [{mark}] {name:9s} {s[\"status\"]}")
print(f"    mode={h[\"config\"][\"mode\"]}  ready={h[\"ready\"]}")'
    echo ""
    echo "    health:  http://${HOST}:${PORT}/api/health"
    echo "    ask:     POST http://${HOST}:${PORT}/api/ask"
    echo ""
    wait $SERVER_PID
    exit 0
  fi
  sleep 0.5
done

echo "!! backend did not come up within 15s" >&2
exit 1
