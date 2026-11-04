#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv"

if [ ! -d "${VENV_DIR}" ]; then
    echo "Virtual environment not found. Running setup.sh first..."
    "${SCRIPT_DIR}/setup.sh"
    exit 0
fi

source "${VENV_DIR}/bin/activate"
echo "Reinstalling dependencies from requirements.txt..."
pip install --upgrade pip
pip install -r "${PROJECT_ROOT}/requirements.txt"
echo "Dependencies updated successfully."
