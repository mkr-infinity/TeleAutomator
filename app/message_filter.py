"""Message event inspection and filtering."""

from __future__ import annotations

from typing import Any, Tuple

from app.logger import setup_logger
from app.privacy_manager import PrivacyManager
from app.safety_manager import SafetyManager

logger = setup_logger(__name__)


class MessageFilter:
    """Filters incoming Telegram events according to privacy and safety policies."""

    def __init__(
        self,
        my_user_id: int,
        privacy_manager: PrivacyManager,
        safety_manager: SafetyManager,
        my_username: str = "",
        database: Optional[Any] = None,
    ):
        self.my_user_id = my_user_id
        self.privacy = privacy_manager
        self.safety = safety_manager
        self.my_username = (my_username or "").lstrip("@").lower()
        self.db = database

    def evaluate(self, event: Any) -> Tuple[bool, str]:
        """Evaluate an incoming message event. Returns (is_eligible, reason)."""
        # 1. Ignore outgoing messages sent by our own account
        if getattr(event, "out", False):
            return False, "Outgoing message from own account"

        sender_id = getattr(event, "sender_id", None)
        if sender_id and sender_id == self.my_user_id:
            return False, "Message from own account ID"

        # 2. Ignore service messages (e.g., pinned message, member joined)
        message_obj = getattr(event, "message", None)
        action = getattr(message_obj, "action", None) if message_obj else getattr(event, "action", None)
        if action is not None:
            return False, "Service message action"

        # 3. Ignore pure broadcast channels (supergroups have is_group=True)
        is_channel = getattr(event, "is_channel", False)
        is_group = getattr(event, "is_group", False)
        if is_channel and not is_group:
            return False, "Broadcast channel message"

        # 4. Check text content
        raw_text = getattr(event, "raw_text", "") or ""
        clean_stripped = raw_text.strip()
        if not clean_stripped:
            return False, "Empty message or unsupported media without text"

        # Ignore slash commands intended for other bots or systems
        if clean_stripped.startswith("/") and not clean_stripped.startswith("//"):
            return False, "Message is a slash command intended for a bot"

        # Ignore standalone punctuation noise (e.g. "?", ".", "!")
        if len(clean_stripped) == 1 and clean_stripped in (".", "?", "!", ",", ":", ";", "-"):
            return False, "Single punctuation character message"

        # 5. Check sender user exclusion
        if not self.privacy.is_user_allowed(sender_id):
            return False, f"Sender user {sender_id} is in ignored list"

        # 6. Check chat allowlist
        chat_id = getattr(event, "chat_id", None)
        if chat_id is None:
            return False, "Message has no chat ID"

        if not self.privacy.is_chat_allowed(chat_id, is_group):
            return False, f"Chat {chat_id} is not allowlisted"

        # 7. Group smart filtering: Strict mention-only mode check
        if is_group and self.db:
            strict_mention_only = self.db.get_state("group_mention_only", "0") == "1"
            if strict_mention_only:
                is_mentioned = False
                if message_obj and getattr(message_obj, "mentioned", False):
                    is_mentioned = True
                elif self.my_username and f"@{self.my_username}" in raw_text.lower():
                    is_mentioned = True
                else:
                    import re
                    owner_name = (self.db.get_state("owner_name", "") or "").strip().lower()
                    if owner_name and len(owner_name) >= 3 and re.search(r"\b" + re.escape(owner_name) + r"\b", raw_text.lower()):
                        is_mentioned = True
                    elif getattr(event, "is_reply", False):
                        is_mentioned = True

                if not is_mentioned:
                    return False, "Strict mention-only mode is enabled for groups"

        # 8. Check sensitive content / OTPs & Scammer links
        if self.safety.is_sensitive(raw_text):
            return False, "Message contains sensitive OTP or security keywords"

        if self.safety.is_scam_or_suspicious(raw_text):
            return False, "Message contains suspicious scam or phishing link pattern"

        # 9. Duplicate check
        message_id = getattr(event, "id", 0)
        if self.safety.is_duplicate(chat_id, message_id, raw_text):
            return False, "Duplicate message event"

        return True, "Eligible"
