#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"

if [ ! -d "${VENV_DIR}" ]; then
    echo "Virtual environment not found. Running setup.sh..."
    "${SCRIPT_DIR}/setup.sh"
fi

if [ ! -f "${SCRIPT_DIR}/.env" ]; then
    echo "[ERROR] .env file not found at ${SCRIPT_DIR}/.env."
    echo "Please run ./setup.sh or copy .env.example to .env and configure your credentials."
    exit 1
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
cd "${SCRIPT_DIR}"
exec python3 -m app.main "$@"
