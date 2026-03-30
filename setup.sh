#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

BOLD="\033[1m"; GREEN="\033[32m"; CYAN="\033[36m"; RED="\033[31m"; RESET="\033[0m"

echo -e "\n${BOLD}yomeru · setup${RESET}\n"

# verify python version — 3.11+ required
if ! command -v python3 &>/dev/null; then
  echo -e "${RED}error${RESET}: python3 not found"
  echo "  install python 3.11+ (pyenv, system package manager, python.org)"
  exit 1
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")

echo -e "${CYAN}python${RESET} $PY_VERSION"

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
  echo -e "${RED}error${RESET}: python 3.11+ required (found $PY_VERSION)"
  echo "  with pyenv: pyenv install 3.12.x && pyenv local 3.12.x"
  exit 1
fi

echo -e "${CYAN}installing dependencies${RESET}"
pip install --quiet -r backend/requirements.txt

[ ! -f .env ] && cp .env.example .env && echo -e "${CYAN}created${RESET} .env"

echo -e "\n${GREEN}done!${RESET} run ${BOLD}start.sh${RESET}\n"