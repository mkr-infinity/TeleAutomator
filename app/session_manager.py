"""Telegram session management for local files and cloud StringSession."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Union

from telethon.sessions import StringSession

from app.config import AppConfig
from app.logger import setup_logger

logger = setup_logger(__name__)


def ensure_secure_dir(path: Path) -> Path:
    """Ensure directory exists and has 0700 permissions on POSIX systems."""
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        try:
            path.chmod(stat.S_IRWXU)  # 0700
        except OSError as e:
            logger.warning(f"Could not enforce 0700 permissions on directory '{path}': {e}")
    return path


def ensure_secure_file(path: Path) -> None:
    """Ensure session file has 0600 permissions on POSIX systems."""
    if os.name == "posix" and path.exists():
        try:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
        except OSError as e:
            logger.warning(f"Could not enforce 0600 permissions on session file '{path}': {e}")


def get_local_session_path(data_dir: Path, session_name: str) -> Path:
    """Return the absolute path for local session storage."""
    ensure_secure_dir(data_dir)
    return (data_dir / session_name).resolve()


def get_telethon_session(config: AppConfig) -> Union[str, StringSession]:
    """Return appropriate Telethon session (file path string or StringSession)."""
    if config.session_mode == "string":
        if not config.session_string:
            raise ValueError("Cloud string session mode configured, but TG_SESSION_STRING is empty.")
        logger.info("Using Telethon StringSession for cloud authentication.")
        return StringSession(config.session_string)

    # Local mode: session file stored securely inside data_dir
    session_base = get_local_session_path(config.data_dir, config.session_name)
    session_file = session_base.with_suffix(".session")
    if session_file.exists():
        ensure_secure_file(session_file)
        logger.info(f"Loaded existing local session file: {session_file.name}")
    else:
        logger.info(f"No existing session found at {session_file.name}. New session will be created.")

    return str(session_base)
