"""Telegram session management for local files and cloud StringSession."""

from __future__ import annotations

import ipaddress
import os
import stat
import struct
from pathlib import Path
from typing import Union

from telethon.crypto import AuthKey
from telethon.sessions import StringSession

from app.config import AppConfig
from app.logger import setup_logger

logger = setup_logger(__name__)


class RobustStringSession(StringSession):
    """Resilient StringSession that normalizes whitespace, quotes, line wraps, and buffer sizes."""

    def __init__(self, string: str | None = None):
        super().__init__()
        if not string:
            return

        # Sanitize whitespace, newlines (from terminal line wraps), and accidental quotes
        clean = "".join(str(string).split()).strip("\"'")
        if not clean:
            return

        if clean[0] != "1":
            raise ValueError("Invalid Telegram session string (must start with '1').")

        # Fix base64 padding if stripped during copy-paste
        b64_part = clean[1:]
        rem = len(b64_part) % 4
        if rem != 0:
            b64_part += "=" * (4 - rem)

        decoded = StringSession.decode(b64_part)

        # Detect IP length directly from the decoded binary payload length:
        # IPv4 payload = 1 (dc_id) + 4 (ip) + 2 (port) + 256 (auth_key) = 263 bytes
        # IPv6 payload = 1 (dc_id) + 16 (ip) + 2 (port) + 256 (auth_key) = 275 bytes
        if len(decoded) == 263:
            ip_len = 4
        elif len(decoded) == 275:
            ip_len = 16
        else:
            ip_len = 4 if len(b64_part) == 352 else 16

        self._dc_id, ip, self._port, key = struct.unpack(
            f">B{ip_len}sH256s", decoded
        )
        self._server_address = ipaddress.ip_address(ip).compressed
        if any(key):
            self._auth_key = AuthKey(key)


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


def get_telethon_session(config: AppConfig) -> Union[str, RobustStringSession]:
    """Return appropriate Telethon session (file path string or RobustStringSession)."""
    if config.session_mode == "string":
        if not config.session_string:
            raise ValueError("Cloud string session mode configured, but TG_SESSION_STRING is empty.")
        logger.info("Using Telethon StringSession for cloud authentication.")
        return RobustStringSession(config.session_string)

    # Local mode: session file stored securely inside data_dir
    session_base = get_local_session_path(config.data_dir, config.session_name)
    session_file = session_base.with_suffix(".session")
    if session_file.exists():
        ensure_secure_file(session_file)
        logger.info(f"Loaded existing local session file: {session_file.name}")
    else:
        logger.info(f"No existing session found at {session_file.name}. New session will be created.")

    return str(session_base)
