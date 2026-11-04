#!/usr/bin/env bash
set -euo pipefail

# Determine repository root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "=========================================================="
echo " Personal Telegram MTProto Client - Local Setup"
echo "=========================================================="
echo "Project Directory: ${PROJECT_ROOT}"

# 1. Check Python installation
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] Python 3 is required but was not found in PATH."
    echo "Please install Python 3.10+ (e.g., sudo pacman -S python on Arch Linux)."
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "Found Python version: ${PYTHON_VERSION}"

# 2. Check/create virtual environment
VENV_DIR="${PROJECT_ROOT}/.venv"
if [ ! -d "${VENV_DIR}" ]; then
    echo "Creating virtual environment at ${VENV_DIR}..."
    python3 -m venv "${VENV_DIR}"
else
    echo "Virtual environment already exists at ${VENV_DIR}."
fi

# 3. Activate venv & install dependencies
source "${VENV_DIR}/bin/activate"
echo "Upgrading pip and installing requirements..."
pip install --upgrade pip
pip install -r "${PROJECT_ROOT}/requirements.txt"

# 4. Prepare local .env
if [ ! -f "${PROJECT_ROOT}/.env" ]; then
    echo "Creating .env from local/.env.example..."
    cp "${SCRIPT_DIR}/.env.example" "${PROJECT_ROOT}/.env"
    chmod 600 "${PROJECT_ROOT}/.env"
    echo ""
    echo "=========================================================="
    echo " [ACTION REQUIRED] Please edit .env with your credentials:"
    echo "   1. Open ${PROJECT_ROOT}/.env"
    echo "   2. Set your TG_API_ID and TG_API_HASH"
    echo "   3. Add allowed chat IDs in ALLOWED_PRIVATE_CHATS or ALLOWED_GROUPS"
    echo "=========================================================="
else
    echo ".env file already exists."
    chmod 600 "${PROJECT_ROOT}/.env"
fi

# 5. Ensure secure data directory
mkdir -p "${PROJECT_ROOT}/data"
chmod 700 "${PROJECT_ROOT}/data"

echo ""
echo "Setup completed successfully!"
echo "Next step: Run './local/authenticate.sh' to log in to Telegram."
