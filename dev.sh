#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
[ -f .env ] && set -a && . ./.env && set +a

if ! command -v node &>/dev/null; then
  echo "node not found — install node 20+ to run the UI dev server"
  echo "or use ./start.sh to serve the pre-built UI"
  exit 1
fi

[ ! -d frontend/node_modules ] && (cd frontend && npm install --silent)

cleanup() { kill 0; }
trap cleanup SIGINT SIGTERM

HOST="${HOST:-127.0.0.1}"
echo ""
echo "  yomeru dev"
echo "  ui      →  http://localhost:3000/ui  (vite HMR)"
echo "  backend →  http://localhost:7788     (uvicorn --reload)"
echo "  api     →  http://localhost:7788/api/docs"
echo "  ctrl+c to stop"
echo ""

(cd backend && uv run --no-sync uvicorn yomeru.app:app --host "$HOST" --port 7788 \
  --reload --reload-dir yomeru) &
(cd frontend && npm run dev -- --host "$HOST") &
wait
