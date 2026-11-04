"""Tests for PrivacyManager allowlisting, blocklists, and user exclusions."""

from pathlib import Path
from app.config import AppConfig
from app.privacy_manager import PrivacyManager


def test_explicit_allowlist():
    cfg = AppConfig(
        api_id=123,
        api_hash="dummy_hash",
        allowed_private_chats={100, 200},
        allowed_groups={-1001, -1002},
        blocked_chats={200},
        ignored_users={999},
    )
    privacy = PrivacyManager(cfg)

    # Allowed private chat 100
    assert privacy.is_chat_allowed(100, is_group=False) is True
    # Non-allowed private chat 300
    assert privacy.is_chat_allowed(300, is_group=False) is False
    # Blocked private chat 200 (in both allowlist and blocklist -> blocklist wins)
    assert privacy.is_chat_allowed(200, is_group=False) is False

    # Allowed group
    assert privacy.is_chat_allowed(-1001, is_group=True) is True
    # Non-allowed group
    assert privacy.is_chat_allowed(-1009, is_group=True) is False

    # Ignored user
    assert privacy.is_user_allowed(999) is False
    assert privacy.is_user_allowed(888) is True
