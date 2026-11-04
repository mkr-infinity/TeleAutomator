"""Privacy enforcement, chat allowlisting, and data minimization."""

from __future__ import annotations

from typing import Optional

from app.config import AppConfig
from app.logger import redact_secrets, setup_logger

logger = setup_logger(__name__)


class PrivacyManager:
    """Enforces explicit chat allowlisting, user exclusions, and data minimization."""

    def __init__(self, config: AppConfig):
        self.config = config

    def is_chat_allowed(self, chat_id: int, is_group: bool) -> bool:
        """Check if chat is explicitly permitted and not blocked."""
        # Check blocklist first
        if chat_id in self.config.blocked_chats:
            logger.debug(f"Chat {chat_id} is in BLOCKED_CHATS. Ignored.")
            return False

        # Explicit allowlist enforcement
        if is_group:
            if not self.config.allowed_groups:
                logger.debug("No groups in ALLOWED_GROUPS. Group message ignored.")
                return False
            allowed = chat_id in self.config.allowed_groups
            if not allowed:
                logger.debug(f"Group {chat_id} not in ALLOWED_GROUPS. Ignored.")
            return allowed
        else:
            if not self.config.allowed_private_chats:
                logger.debug("No private chats in ALLOWED_PRIVATE_CHATS. Private message ignored.")
                return False
            allowed = chat_id in self.config.allowed_private_chats
            if not allowed:
                logger.debug(f"Private chat {chat_id} not in ALLOWED_PRIVATE_CHATS. Ignored.")
            return allowed

    def is_user_allowed(self, user_id: int | None) -> bool:
        """Check if sender user ID is ignored."""
        if user_id is None:
            return True
        if user_id in self.config.ignored_users:
            logger.debug(f"User {user_id} is in IGNORED_USERS. Ignored.")
            return False
        return True

    def sanitize_text(self, text: str) -> str:
        """Redact sensitive patterns from text before internal processing or logging."""
        if not text:
            return ""
        return redact_secrets(text.strip())
