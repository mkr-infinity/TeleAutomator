"""Message event inspection and filtering."""

from __future__ import annotations

from typing import Any, Tuple

from app.logger import setup_logger
from app.privacy_manager import PrivacyManager
from app.safety_manager import SafetyManager

logger = setup_logger(__name__)


class MessageFilter:
    """Filters incoming Telegram events according to privacy and safety policies."""

    def __init__(self, my_user_id: int, privacy_manager: PrivacyManager, safety_manager: SafetyManager):
        self.my_user_id = my_user_id
        self.privacy = privacy_manager
        self.safety = safety_manager

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
        if not raw_text.strip():
            return False, "Empty message or unsupported media without text"

        # 5. Check sender user exclusion
        if not self.privacy.is_user_allowed(sender_id):
            return False, f"Sender user {sender_id} is in ignored list"

        # 6. Check chat allowlist
        chat_id = getattr(event, "chat_id", None)
        if chat_id is None:
            return False, "Message has no chat ID"

        if not self.privacy.is_chat_allowed(chat_id, is_group):
            return False, f"Chat {chat_id} is not allowlisted"

        # 7. Check sensitive content / OTPs
        if self.safety.is_sensitive(raw_text):
            return False, "Message contains sensitive OTP or security keywords"

        # 8. Duplicate check
        message_id = getattr(event, "id", 0)
        if self.safety.is_duplicate(chat_id, message_id, raw_text):
            return False, "Duplicate message event"

        return True, "Eligible"
