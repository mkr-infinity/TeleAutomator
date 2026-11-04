"""Structured logging with secret redaction."""

from __future__ import annotations

import logging
import os
import re
import sys
from typing import Any

# Patterns matching sensitive information
SENSITIVE_PATTERNS = [
    # 5-digit Telegram login codes
    re.compile(r"\b\d{5}\b"),
    # Phone numbers (+ followed by 9 to 15 digits)
    re.compile(r"\+?[0-9]{10,15}"),
    # 32-character hex hashes (API hash)
    re.compile(r"\b[0-9a-fA-F]{32}\b"),
    # Telethon StringSession (base64 token typically 200-400 chars)
    re.compile(r"\b1[A-Za-z0-9+/=_-]{60,}\b"),
    # Common API key formats (sk-..., AIzaSy...)
    re.compile(r"\b(?:sk-[A-Za-z0-9_-]{20,}|AIzaSy[A-Za-z0-9_-]{30,})\b"),
]

KNOWN_SECRETS: set[str] = set()


def register_secret(secret: str | None) -> None:
    """Register a runtime secret string to guarantee its redaction."""
    if secret and len(secret) >= 4:
        KNOWN_SECRETS.add(secret)


def redact_secrets(message: str) -> str:
    """Replace sensitive tokens, hashes, phone numbers, and codes with [REDACTED]."""
    text = message
    # Redact explicitly registered secrets first
    for secret in KNOWN_SECRETS:
        if secret in text:
            text = text.replace(secret, "[REDACTED]")

    # Redact pattern matches
    for pattern in SENSITIVE_PATTERNS:
        text = pattern.sub("[REDACTED]", text)

    return text


class RedactingFormatter(logging.Formatter):
    """Logging formatter that redacts secrets from all formatted messages."""

    def format(self, record: logging.LogRecord) -> str:
        original = super().format(record)
        return redact_secrets(original)


def setup_logger(name: str = "telegram_client", level_name: str | None = None) -> logging.Logger:
    """Set up and return the application logger."""
    level = getattr(logging, (level_name or os.getenv("LOG_LEVEL", "INFO")).upper(), logging.INFO)
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid adding duplicate handlers if already configured
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)
        formatter = RedactingFormatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
