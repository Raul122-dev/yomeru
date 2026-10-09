#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
[ -f .env ] && set -a && . ./.env && set +a
exec uv run --no-sync python -m yomeru "$@"
