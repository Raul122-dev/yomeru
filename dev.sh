#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if ! command -v node &>/dev/null; then
  echo "node not found — install node 18+ to run the frontend dev server"
  echo "or use ./start.sh to serve the pre-built frontend"
  exit 1
fi

[ ! -d frontend/node_modules ] && cd frontend && npm install --silent && cd ..

cleanup() { kill 0; }
trap cleanup SIGINT SIGTERM

echo ""
echo "  yomeru dev"
echo "  frontend  →  http://localhost:3000  (vite HMR)"
echo "  backend   →  http://localhost:7788  (uvicorn --reload)"
echo "  ctrl+c to stop"
echo ""

(cd backend && python3 -m uvicorn main:app --host 0.0.0.0 --port 7788 --reload) &
(cd frontend && npm run dev) &
wait