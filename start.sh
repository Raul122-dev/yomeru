#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
[ -f .env ] && set -a && . ./.env && set +a
[ -f src/yomeru/static/index.html ] || echo "note: the web UI is not built yet — run: cd ui && npm ci && npm run build"
exec uv run --no-sync python -m yomeru "$@"
