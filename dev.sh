#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if ! command -v node &>/dev/null; then
  echo "node not found — install node 18+ to run the UI dev server"
  echo "or use ./start.sh to serve the pre-built UI"
  exit 1
fi

[ ! -d ui/node_modules ] && (cd ui && npm install --silent)

cleanup() { kill 0; }
trap cleanup SIGINT SIGTERM

echo ""
echo "  yomeru dev"
echo "  ui      →  http://localhost:3000/ui  (vite HMR)"
echo "  backend →  http://localhost:7788     (uvicorn --reload)"
echo "  api     →  http://localhost:7788/api/docs"
echo "  ctrl+c to stop"
echo ""

(cd src && python3 -m uvicorn yomeru.app:app --host 0.0.0.0 --port 7788 --reload) &
(cd ui && npm run dev) &
wait
