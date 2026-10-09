#!/usr/bin/env bash
# yomeru setup — creates .venv with uv and installs everything.
#   bash setup.sh          → full install (detection, OCR, inpainting)
#   bash setup.sh --core   → analysis only (no torch, much smaller)
set -e
cd "$(dirname "$0")"

BOLD="\033[1m"; GREEN="\033[32m"; CYAN="\033[36m"; RED="\033[31m"; RESET="\033[0m"
echo -e "\n${BOLD}yomeru · setup${RESET}\n"

if ! command -v uv &>/dev/null; then
  echo -e "${RED}error${RESET}: uv not found"
  echo "  install: curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi

if [ "$1" = "--core" ]; then
  echo -e "${CYAN}installing core dependencies${RESET}"
  uv sync --no-default-groups
else
  echo -e "${CYAN}installing all dependencies (torch included, this takes a while)${RESET}"
  uv sync
fi

[ ! -f .env ] && cp .env.example .env && echo -e "${CYAN}created${RESET} .env"

echo -e "\n${GREEN}done!${RESET} run ${BOLD}bash start.sh${RESET}"
echo -e "model weights download automatically the first time each phase needs them.\n"
