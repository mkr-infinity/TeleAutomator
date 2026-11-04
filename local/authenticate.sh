#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv"

if [ ! -d "${VENV_DIR}" ]; then
    echo "Virtual environment not found. Running setup.sh first..."
    "${SCRIPT_DIR}/setup.sh"
fi

source "${VENV_DIR}/bin/activate"

cd "${PROJECT_ROOT}"
python3 "${PROJECT_ROOT}/scripts/authenticate.py"
