#!/usr/bin/env bash
# Run BOL on this machine (inside WSL) without Docker: API on :8000, frontend
# on :3000, worker if LiveKit is configured. Postgres and Redis run as WSL
# services; the Urdu voice server (:8030) has its own autostart task
# (urdu-tts/server/install_server_autostart.ps1).
#
#   bash scripts/start_local.sh          # start (or restart) everything
#   bash scripts/start_local.sh stop
#
# Needs: ~/bol-venv with `pip install -e 'backend[worker,dev]'`, Node 22, and
# a repo-root .env with DATABASE_URL/REDIS_URL pointing at localhost.
# Logs: ~/bol-api.log, ~/bol-worker.log, ~/bol-frontend.log
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${BOL_VENV:-$HOME/bol-venv}"

stop() {
    pkill -f 'uvicorn app.main:app' 2>/dev/null
    pkill -f 'worker.agent' 2>/dev/null
    pkill -f 'next dev' 2>/dev/null
    pkill -f 'next-server' 2>/dev/null
    sleep 1
}

stop
[ "${1:-}" = "stop" ] && { echo "stopped"; exit 0; }

# setsid: own session, so the processes survive the shell (and the WSL
# session) that started them.
cd "$ROOT/backend"
setsid nohup "$VENV/bin/uvicorn" app.main:app --host 0.0.0.0 --port 8000 > ~/bol-api.log 2>&1 < /dev/null &

if grep -qE '^LIVEKIT_URL=.+' "$ROOT/.env" && grep -qE '^LIVEKIT_API_KEY=.+' "$ROOT/.env"; then
    setsid nohup "$VENV/bin/python" -m worker.agent dev > ~/bol-worker.log 2>&1 < /dev/null &
    worker="started"
else
    worker="not started (set LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET in .env)"
fi

cd "$ROOT/frontend"
setsid nohup npm run dev -- --hostname 0.0.0.0 --port 3000 > ~/bol-frontend.log 2>&1 < /dev/null &

for _ in $(seq 1 90); do
    curl -s -o /dev/null localhost:8000/health/config && curl -s -o /dev/null localhost:3000/ && break
    sleep 2
done
echo "API      http://localhost:8000  $(curl -s localhost:8000/health/config)"
echo "Frontend http://localhost:3000  (HTTP $(curl -s -o /dev/null -w '%{http_code}' localhost:3000/))"
echo "Voices   http://localhost:8030  $(curl -s localhost:8030/health)"
echo "Worker   $worker"
