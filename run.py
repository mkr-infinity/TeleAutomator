#!/usr/bin/env python3
"""Universal cross-platform launcher and management CLI for TeleAutomator (Telegram Chat Automation).

Works out-of-the-box on Linux, Windows, macOS, and remote servers without bash or PowerShell.
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent


def get_venv_python() -> Path:
    """Return the platform-specific path to the virtual environment Python executable."""
    if platform.system() == "Windows":
        return ROOT_DIR / ".venv" / "Scripts" / "python.exe"
    return ROOT_DIR / ".venv" / "bin" / "python3"


def ensure_environment() -> Path:
    """Ensure virtual environment exists and dependencies are installed."""
    venv_python = get_venv_python()
    venv_dir = ROOT_DIR / ".venv"

    if not venv_python.exists():
        print(f"[*] Creating Python virtual environment at {venv_dir}...")
        import venv
        venv.create(venv_dir, with_pip=True)

        print("[*] Installing dependencies from requirements.txt...")
        subprocess.check_call([
            str(venv_python), "-m", "pip", "install", "--upgrade", "pip", "--quiet"
        ])
        subprocess.check_call([
            str(venv_python), "-m", "pip", "install", "-r", str(ROOT_DIR / "requirements.txt"), "--quiet"
        ])
        print("[✓] Virtual environment initialized and dependencies installed.")

    # Ensure .env exists
    env_file = ROOT_DIR / ".env"
    example_file = ROOT_DIR / ".env.example"
    if not env_file.exists() and example_file.exists():
        import shutil
        shutil.copyfile(example_file, env_file)
        if platform.system() != "Windows":
            os.chmod(env_file, 0o600)
        print("[*] Created .env from .env.example. Please configure your API credentials.")

    # Ensure data directory exists
    data_dir = ROOT_DIR / "data"
    data_dir.mkdir(exist_ok=True)
    if platform.system() != "Windows":
        os.chmod(data_dir, 0o700)

    return venv_python


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Universal Runner for TeleAutomator - Telegram Chat Automation"
    )
    parser.add_argument("--setup", action="store_true", help="Set up environment and install dependencies")
    parser.add_argument("--auth", action="store_true", help="Run interactive Telegram phone/2FA authentication")
    parser.add_argument("--test", action="store_true", help="Run unit test suite")
    parser.add_argument("--check", action="store_true", help="Check MTProto connection status")
    parser.add_argument("--draft", action="store_true", help="Launch directly in draft-only mode (never sends)")
    parser.add_argument("--mode", choices=["draft", "approval", "restricted_auto"], help="Override automation mode")
    parser.add_argument("--style", choices=["casual", "concise", "formal", "humorous"], help="Override AI reply style")
    args, extra = parser.parse_known_args()

    venv_python = ensure_environment()
    python_str = str(venv_python)

    if args.setup:
        print("[✓] Setup complete.")
        return

    if args.auth:
        cmd = [python_str, str(ROOT_DIR / "scripts" / "authenticate.py")] + extra
        sys.exit(subprocess.call(cmd))

    if args.test:
        cmd = [python_str, "-m", "pytest", str(ROOT_DIR / "tests")] + extra
        sys.exit(subprocess.call(cmd))

    if args.check:
        cmd = [python_str, str(ROOT_DIR / "scripts" / "check_connection.py")] + extra
        sys.exit(subprocess.call(cmd))

    # Default action: run main application daemon
    extra_flags = list(extra)
    if args.draft:
        extra_flags.append("--draft")
    if args.mode:
        extra_flags.extend(["--mode", args.mode])
    if args.style:
        extra_flags.extend(["--style", args.style])

    cmd = [python_str, "-m", "app.main"] + extra_flags
    sys.exit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
