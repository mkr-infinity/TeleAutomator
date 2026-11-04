#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv"

if [ ! -d "${VENV_DIR}" ]; then
    echo "Virtual environment not found. Running setup.sh first..."
    "${SCRIPT_DIR}/setup.sh"
fi

if [ ! -f "${PROJECT_ROOT}/.env" ]; then
    echo "[ERROR] .env file not found at ${PROJECT_ROOT}/.env."
    echo "Please copy local/.env.example to .env and configure your credentials."
    exit 1
fi

source "${VENV_DIR}/bin/activate"

cd "${PROJECT_ROOT}"
echo "Starting Telegram Personal Client..."
exec python3 -m app.main
