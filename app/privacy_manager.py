"""Privacy enforcement, chat allowlisting, and data minimization."""

from __future__ import annotations

from typing import Any, Optional

from app.config import AppConfig
from app.logger import redact_secrets, setup_logger

logger = setup_logger(__name__)


class PrivacyManager:
    """Enforces explicit chat allowlisting, user exclusions, and data minimization."""

    def __init__(self, config: AppConfig, database: Optional[Any] = None):
        self.config = config
        self.db = database

    def _get_dynamic_set(self, key: str) -> set[int]:
        if not self.db:
            return set()
        raw = self.db.get_state(key, "")
        if not raw.strip():
            return set()
        res = set()
        for item in raw.split(","):
            item = item.strip()
            if item:
                try:
                    res.add(int(item))
                except ValueError:
                    pass
        return res

    def _save_dynamic_set(self, key: str, ids: set[int]) -> None:
        if self.db:
            self.db.set_state(key, ",".join(str(i) for i in sorted(ids)))

    def allow_chat(self, chat_id: int) -> None:
        """Dynamically add chat to allowlist from Telegram command."""
        allowed = self._get_dynamic_set("dynamic_allowed_chats")
        allowed.add(chat_id)
        self._save_dynamic_set("dynamic_allowed_chats", allowed)
        # Remove from blocked if present
        blocked = self._get_dynamic_set("dynamic_blocked_chats")
        if chat_id in blocked:
            blocked.discard(chat_id)
            self._save_dynamic_set("dynamic_blocked_chats", blocked)

    def remove_chat(self, chat_id: int) -> None:
        """Remove chat from dynamic allowlist."""
        allowed = self._get_dynamic_set("dynamic_allowed_chats")
        allowed.discard(chat_id)
        self._save_dynamic_set("dynamic_allowed_chats", allowed)

    def block_chat(self, chat_id: int) -> None:
        """Dynamically block a chat."""
        blocked = self._get_dynamic_set("dynamic_blocked_chats")
        blocked.add(chat_id)
        self._save_dynamic_set("dynamic_blocked_chats", blocked)
        self.remove_chat(chat_id)

    def get_all_allowed_chats(self) -> tuple[set[int], set[int]]:
        """Return all allowed (private_chats, group_chats)."""
        dynamic = self._get_dynamic_set("dynamic_allowed_chats")
        all_private = set(self.config.allowed_private_chats)
        all_groups = set(self.config.allowed_groups)

        for cid in dynamic:
            if cid < 0:
                all_groups.add(cid)
            else:
                all_private.add(cid)

        return all_private, all_groups

    def is_chat_allowed(self, chat_id: int, is_group: bool) -> bool:
        """Check if chat is explicitly permitted and not blocked."""
        # Check static and dynamic blocklists first
        if chat_id in self.config.blocked_chats or chat_id in self._get_dynamic_set("dynamic_blocked_chats"):
            logger.debug(f"Chat {chat_id} is in BLOCKED_CHATS. Ignored.")
            return False

        # Dynamic allowlist check
        dynamic_allowed = self._get_dynamic_set("dynamic_allowed_chats")
        if chat_id in dynamic_allowed:
            return True

        # Explicit allowlist enforcement from config
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
