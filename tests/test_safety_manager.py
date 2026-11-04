"""Tests for SafetyManager: rate limits, duplicate prevention, sensitive content, and emergency stop."""

from pathlib import Path
from app.config import AppConfig
from app.safety_manager import SafetyManager
from app.storage.database import Database


def create_safety(tmp_path: Path, global_cd: int = 10, chat_cd: int = 20) -> SafetyManager:
    cfg = AppConfig(
        api_id=123,
        api_hash="dummy_hash",
        global_cooldown_seconds=global_cd,
        per_chat_cooldown_seconds=chat_cd,
        max_message_length=50,
        data_dir=tmp_path,
    )
    db = Database(tmp_path / "test.db")
    return SafetyManager(cfg, db)


def test_sensitive_content_detection(tmp_path: Path):
    safety = create_safety(tmp_path)
    assert safety.is_sensitive("Your OTP verification code is 12345.") is True
    assert safety.is_sensitive("Please send your private key or seed phrase.") is True
    assert safety.is_sensitive("Hello, are we still meeting today at 5?") is False


def test_duplicate_prevention(tmp_path: Path):
    safety = create_safety(tmp_path)
    chat_id = 1001
    msg_id = 42
    text = "Hello world"

    assert safety.is_duplicate(chat_id, msg_id, text) is False
    assert safety.is_duplicate(chat_id, msg_id, text) is True


def test_cooldown_enforcement(tmp_path: Path):
    safety = create_safety(tmp_path, global_cd=5, chat_cd=10)
    chat_id = 2002

    can_reply, reason = safety.can_reply(chat_id, "Test reply")
    assert can_reply is True

    # Mark as sent
    safety.mark_reply_sent(chat_id)

    # Immediately trying to reply again should be blocked by cooldown
    can_reply, reason = safety.can_reply(chat_id, "Test reply 2")
    assert can_reply is False
    assert "cooldown active" in reason


def test_emergency_stop(tmp_path: Path):
    safety = create_safety(tmp_path)
    assert safety.is_emergency_stopped is False

    safety.set_emergency_stop(True)
    assert safety.is_emergency_stopped is True

    can_reply, reason = safety.can_reply(1001, "Normal reply")
    assert can_reply is False
    assert reason == "Emergency stop active"

    safety.set_emergency_stop(False)
    can_reply, _ = safety.can_reply(1001, "Normal reply")
    assert can_reply is True
