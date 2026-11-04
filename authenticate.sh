#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"

if [ ! -d "${VENV_DIR}" ]; then
    echo "Virtual environment not found. Running setup.sh first..."
    "${SCRIPT_DIR}/setup.sh"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
cd "${SCRIPT_DIR}"
exec python3 scripts/authenticate.py "$@"
