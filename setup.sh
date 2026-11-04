#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Universal System Detection & Setup Script
# Works on: Arch Linux, Debian/Ubuntu, Fedora/RHEL, Alpine, macOS, WSL, VPS
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

echo "========================================================================"
echo " Telegram Chat Automation - Universal System Setup"
echo "========================================================================"

# 1. Detect Operating System & Environment
OS_TYPE="$(uname -s)"
DISTRO="unknown"
PACKAGE_INSTALLER=""

if [ "${OS_TYPE}" = "Linux" ]; then
    if [ -f /etc/os-release ]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        DISTRO="${ID:-linux}"
        DISTRO_NAME="${NAME:-Linux}"
    else
        DISTRO_NAME="Generic Linux"
    fi

    case "${DISTRO}" in
        arch|manjaro|endeavouros)
            PACKAGE_INSTALLER="sudo pacman -S --needed python python-pip"
            ;;
        debian|ubuntu|pop|mint)
            PACKAGE_INSTALLER="sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
            ;;
        fedora|rhel|centos|almalinux|rocky)
            PACKAGE_INSTALLER="sudo dnf install -y python3 python3-pip"
            ;;
        alpine)
            PACKAGE_INSTALLER="sudo apk add python3 py3-pip"
            ;;
        opensuse*|sles)
            PACKAGE_INSTALLER="sudo zypper install -y python3 python3-pip"
            ;;
        *)
            PACKAGE_INSTALLER="Use your system package manager to install Python 3.10+, venv, and pip."
            ;;
    esac
elif [ "${OS_TYPE}" = "Darwin" ]; then
    DISTRO_NAME="macOS"
    PACKAGE_INSTALLER="brew install python"
elif [[ "${OS_TYPE}" =~ MINGW|MSYS|CYGWIN ]]; then
    DISTRO_NAME="Windows (Bash/POSIX Environment)"
    PACKAGE_INSTALLER="Download Python 3.10+ from https://www.python.org/downloads/ (check 'Add python.exe to PATH')"
else
    DISTRO_NAME="${OS_TYPE}"
    PACKAGE_INSTALLER="Install Python 3.10+ and pip."
fi

# Detect Server / Headless / SSH Environment
IS_SERVER=false
if [ -n "${SSH_CLIENT:-}" ] || [ -n "${SSH_TTY:-}" ] || [ -n "${SSH_CONNECTION:-}" ]; then
    IS_SERVER=true
fi

echo "[*] Detected OS          : ${DISTRO_NAME} (${OS_TYPE})"
if [ "${IS_SERVER}" = true ]; then
    echo "[*] Environment Mode     : Remote Server / VPS (SSH Session Detected)"
else
    echo "[*] Environment Mode     : Local / Desktop System"
fi

# 2. Check Python 3.10+
PYTHON_CMD=""
for cmd in python3 python; do
    if command -v "${cmd}" &>/dev/null; then
        PY_VER=$("${cmd}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")
        PY_MAJOR=$("${cmd}" -c 'import sys; print(sys.version_info.major)' 2>/dev/null || echo "0")
        PY_MINOR=$("${cmd}" -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || echo "0")
        if [ "${PY_MAJOR}" -ge 3 ] && [ "${PY_MINOR}" -ge 10 ]; then
            PYTHON_CMD="${cmd}"
            echo "[*] Python Executable    : $(command -v "${cmd}") (v${PY_VER})"
            break
        fi
    fi
done

if [ -z "${PYTHON_CMD}" ]; then
    echo ""
    echo "[ERROR] Python 3.10 or higher is required but was not found."
    echo "To install Python on ${DISTRO_NAME}, run:"
    echo "   ${PACKAGE_INSTALLER}"
    exit 1
fi

# 3. Create Virtual Environment (.venv)
VENV_DIR="${SCRIPT_DIR}/.venv"
if [ ! -d "${VENV_DIR}" ]; then
    echo "[*] Creating Python virtual environment at ${VENV_DIR}..."
    "${PYTHON_CMD}" -m venv "${VENV_DIR}" || {
        echo "[ERROR] Failed to create virtual environment."
        echo "If on Debian/Ubuntu, ensure python3-venv is installed: sudo apt install -y python3-venv"
        exit 1
    }
else
    echo "[*] Virtual environment already exists: ${VENV_DIR}"
fi

# 4. Activate & Install Dependencies
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
echo "[*] Installing/updating requirements from requirements.txt..."
python -m pip install --upgrade pip --quiet
python -m pip install -r "${SCRIPT_DIR}/requirements.txt" --quiet
echo "[✓] Dependencies installed successfully."

# 5. Prepare Configuration (.env)
if [ ! -f "${SCRIPT_DIR}/.env" ]; then
    echo "[*] Creating .env from .env.example..."
    cp "${SCRIPT_DIR}/.env.example" "${SCRIPT_DIR}/.env"
    chmod 600 "${SCRIPT_DIR}/.env"
    echo ""
    echo "========================================================================"
    echo " [ACTION REQUIRED] Please configure your credentials in .env:"
    echo "   1. Open .env in your editor: nano .env  (or code .env)"
    echo "   2. Enter your TG_API_ID and TG_API_HASH from https://my.telegram.org/apps"
    echo "   3. (Optional) Set your GEMINI_API_KEY from Google AI Studio"
    echo "========================================================================"
else
    echo "[*] Existing .env found (secure permissions enforced: 0600)."
    chmod 600 "${SCRIPT_DIR}/.env"
fi

# 6. Secure Data Directory
mkdir -p "${SCRIPT_DIR}/data"
chmod 700 "${SCRIPT_DIR}/data"

# 7. Check Docker Presence (for 24/7 Server Deployments)
echo ""
echo "========================================================================"
echo " Setup Completed Successfully!"
echo "========================================================================"
echo "Next Steps:"
echo " 1. First-time Authentication (interactive code/2FA prompt):"
echo "    ./authenticate.sh   (or: python3 scripts/authenticate.py)"
echo ""
echo " 2. Start the Automation Client:"
echo "    ./start.sh          (or: python3 run.py)"
echo ""
echo " 3. Run Self-Check & Tests:"
echo "    ./test.sh"
echo ""
if command -v docker &>/dev/null && command -v docker-compose &>/dev/null || docker compose version &>/dev/null 2>&1; then
    echo " 4. (Optional) 24/7 Docker Server Deployment:"
    echo "    docker compose up -d --build"
    echo "========================================================================"
fi
