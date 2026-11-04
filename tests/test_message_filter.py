"""Tests for MessageFilter evaluating incoming events."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from app.config import AppConfig
from app.message_filter import MessageFilter
from app.privacy_manager import PrivacyManager
from app.safety_manager import SafetyManager
from app.storage.database import Database


@dataclass
class MockEvent:
    out: bool = False
    sender_id: Optional[int] = 123
    chat_id: Optional[int] = 100
    is_channel: bool = False
    is_group: bool = False
    raw_text: str = "Hello"
    action: Optional[str] = None
    id: int = 1


def test_message_filter(tmp_path: Path):
    cfg = AppConfig(
        api_id=123,
        api_hash="dummy_hash",
        allowed_private_chats={100},
        data_dir=tmp_path,
    )
    db = Database(tmp_path / "filter.db")
    safety = SafetyManager(cfg, db)
    privacy = PrivacyManager(cfg)
    msg_filter = MessageFilter(my_user_id=9999, privacy_manager=privacy, safety_manager=safety)

    # 1. Eligible message
    eligible, reason = msg_filter.evaluate(MockEvent(sender_id=123, chat_id=100, raw_text="Hello"))
    assert eligible is True
    assert reason == "Eligible"

    # 2. Outgoing message from our account
    eligible, reason = msg_filter.evaluate(MockEvent(out=True))
    assert eligible is False
    assert "own account" in reason

    # 3. Message from our user ID
    eligible, reason = msg_filter.evaluate(MockEvent(sender_id=9999))
    assert eligible is False

    # 4. Service action message
    eligible, reason = msg_filter.evaluate(MockEvent(action="pin"))
    assert eligible is False
    assert "Service message" in reason

    # 5. Broadcast channel
    eligible, reason = msg_filter.evaluate(MockEvent(is_channel=True, is_group=False))
    assert eligible is False
    assert "Broadcast channel" in reason

    # 6. Unapproved chat
    eligible, reason = msg_filter.evaluate(MockEvent(chat_id=999))
    assert eligible is False
    assert "not allowlisted" in reason

    # 7. Sensitive OTP content
    eligible, reason = msg_filter.evaluate(MockEvent(chat_id=100, raw_text="Your OTP code is 44551"))
    assert eligible is False
    assert "sensitive OTP" in reason

    # 8. Bot slash command from contact
    eligible, reason = msg_filter.evaluate(MockEvent(chat_id=100, raw_text="/start"))
    assert eligible is False
    assert "slash command" in reason

    # 9. Standalone punctuation
    eligible, reason = msg_filter.evaluate(MockEvent(chat_id=100, raw_text="?"))
    assert eligible is False
    assert "punctuation" in reason
