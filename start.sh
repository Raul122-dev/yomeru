#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
[ -f .env ] && set -a && . ./.env && set +a
[ -f backend/yomeru/static/index.html ] || echo "note: the web UI is not built yet — run: cd frontend && npm ci && npm run build"
cd backend
exec uv run --no-sync python -m yomeru "$@"
