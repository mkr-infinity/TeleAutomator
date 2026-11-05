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


def test_scam_link_detection(tmp_path: Path):
    safety = create_safety(tmp_path)
    assert safety.is_scam_or_suspicious("Join our channel t.me/+AbCdEfGhIj for 100x signals!") is True
    assert safety.is_scam_or_suspicious("Claim your free airdrop tokens now: https://bit.ly/claim") is True
    assert safety.is_scam_or_suspicious("Hey, are we still meeting tomorrow?") is False


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


def test_randomized_cooldown_bounds(tmp_path: Path):
    cfg = AppConfig(
        api_id=123,
        api_hash="dummy_hash",
        data_dir=tmp_path,
    )
    db = Database(tmp_path / "test_cd.db")
    safety = SafetyManager(cfg, db)

    assert safety.min_chat_cooldown == 5.0
    assert safety.max_chat_cooldown == 60.0
    assert safety.min_global_cooldown == 5.0
    assert safety.max_global_cooldown == 60.0

    # Pick 20 randomized cooldowns; all must be between 5.0 and 60.0
    for _ in range(20):
        cd = safety._pick_random_chat_cooldown()
        assert 5.0 <= cd <= 60.0
        gcd = safety._pick_random_global_cooldown()
        assert 5.0 <= gcd <= 60.0

    # After sending reply, chat cooldown target is within [5.0, 60.0]
    safety.mark_reply_sent(500)
    assert 5.0 <= safety._next_chat_cooldown[500] <= 60.0


def test_quiet_hours_schedule(tmp_path: Path):
    import datetime
    cfg = AppConfig(
        api_id=123,
        api_hash="dummy_hash",
        data_dir=tmp_path,
    )
    db = Database(tmp_path / "test_qh.db")
    safety = SafetyManager(cfg, db)

    # Off by default
    assert safety.quiet_hours_enabled is False
    is_quiet, _ = safety.is_in_quiet_hours()
    assert is_quiet is False

    # Configure overnight schedule: 23:00 to 07:00
    safety.set_quiet_hours(True, start="23:00", end="07:00")
    assert safety.quiet_hours_enabled is True

    # Check times
    night_time = datetime.time(23, 30)
    assert safety.is_in_quiet_hours(night_time)[0] is True

    early_morning = datetime.time(4, 15)
    assert safety.is_in_quiet_hours(early_morning)[0] is True

    day_time = datetime.time(14, 0)
    assert safety.is_in_quiet_hours(day_time)[0] is False

    # Blocked by can_reply during quiet hours
    can_reply, reason = safety.can_reply(101, "Hello",)
    # If currently tested with night_time simulated:
    safety.set_quiet_hours(True, start="00:00", end="23:59")
    can_reply, reason = safety.can_reply(101, "Hello")
    assert can_reply is False
    assert "Quiet hours active" in reason

    # Turn off quiet hours
    safety.set_quiet_hours(False)
    assert safety.quiet_hours_enabled is False
    can_reply, _ = safety.can_reply(101, "Hello")
    assert can_reply is True
