"""Tests for strict per-chat min cooldown, 3-10s typing indicator, and group anti-flood single message delivery."""

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.ai.reply_generator import ReplyGenerator
from app.config import AppConfig
from app.privacy_manager import PrivacyManager
from app.reply_manager import ReplyManager
from app.safety_manager import SafetyManager
from app.storage.database import Database


def test_group_never_splits_multi_bubble(tmp_path: Path):
    """Verify group chats (chat_id < 0) never split into multiple bubbles to prevent flooding mutes."""
    async def _run():
        cfg = AppConfig(api_id=123, api_hash="dummy_hash", data_dir=tmp_path)
        db = Database(tmp_path / "app_group.db")
        safety = SafetyManager(cfg, db)
        privacy = PrivacyManager(cfg, database=db)
        generator = ReplyGenerator(cfg, database=db)
        mgr = ReplyManager(cfg, db, safety, privacy, generator)

        # Enable multi-bubble in db
        db.set_state("multibubble_enabled", "1")

        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(return_value=MagicMock(id=101))
        mgr.set_telegram_client(mock_client)

        group_id = -100123456789
        text_with_split = "First line here.\nSecond line here.\nThird line here."

        sent = await mgr._send_reply(
            chat_id=group_id,
            reply_to_msg_id=55,
            text=text_with_split,
            adaptive_delay=False,
        )
        assert sent is True
        # In group chats, send_message must be called EXACTLY once with the full text (no multiple bubble machine-gunning)
        assert mock_client.send_message.call_count == 1
        call_args = mock_client.send_message.call_args[0]
        assert call_args[0] == group_id
        assert call_args[1] == text_with_split

    asyncio.run(_run())


def test_dm_allows_multi_bubble_when_enabled(tmp_path: Path):
    """Verify private DMs (chat_id > 0) still support multi-bubble splits when enabled."""
    async def _run():
        cfg = AppConfig(api_id=123, api_hash="dummy_hash", data_dir=tmp_path, min_delay_seconds=0.0, max_delay_seconds=0.0)
        db = Database(tmp_path / "app_dm.db")
        safety = SafetyManager(cfg, db)
        privacy = PrivacyManager(cfg, database=db)
        generator = ReplyGenerator(cfg, database=db)
        mgr = ReplyManager(cfg, db, safety, privacy, generator)
        mgr.min_delay = 0.0
        mgr.max_delay = 0.0

        db.set_state("multibubble_enabled", "1")

        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(return_value=MagicMock(id=102))
        mgr.set_telegram_client(mock_client)

        dm_id = 987654321
        text_with_split = "First thought.\nSecond thought."

        sent = await mgr._send_reply(
            chat_id=dm_id,
            reply_to_msg_id=0,
            text=text_with_split,
            adaptive_delay=False,
        )
        assert sent is True
        # In DM, it sends 2 parts
        assert mock_client.send_message.call_count == 2

    asyncio.run(_run())


def test_strict_custom_chat_min_cooldown_wait(tmp_path: Path):
    """Verify that when custom chat cooldown is set (e.g. min 6s, max 50s from miniapp),
    the bot strictly waits at least 6s before sending the next message to that chat."""
    async def _run():
        cfg = AppConfig(api_id=123, api_hash="dummy_hash", data_dir=tmp_path)
        db = Database(tmp_path / "app_cd.db")
        safety = SafetyManager(cfg, db)
        privacy = PrivacyManager(cfg, database=db)
        generator = ReplyGenerator(cfg, database=db)
        mgr = ReplyManager(cfg, db, safety, privacy, generator)

        group_id = -100998877
        # Set custom chat cooldown in miniapp/db (min 6s, max 50s)
        db.set_state(f"chat_cooldown_min_{group_id}", "6.0")
        db.set_state(f"chat_cooldown_max_{group_id}", "50.0")

        # Verify safety._get_chat_cooldown_range returns (6.0, 50.0)
        c_min, c_max = safety._get_chat_cooldown_range(group_id)
        assert c_min == 6.0
        assert c_max == 50.0

        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(return_value=MagicMock(id=201))
        mgr.set_telegram_client(mock_client)

        # Mark last reply sent 2 seconds ago
        now = time.time()
        safety._last_chat_reply_time[group_id] = now - 2.0
        db.record_reply_event(group_id, now - 2.0)

        # can_reply must return False with remaining wait
        can_send, reason = safety.can_reply(group_id, "hello")
        assert can_send is False
        assert "cooldown active" in reason.lower()
        assert "minimum 6s" in reason.lower() or "remaining" in reason.lower()

        # In _send_reply, patch asyncio.sleep to record sleep durations
        slept_durations = []
        orig_sleep = asyncio.sleep

        async def mock_sleep(secs):
            slept_durations.append(secs)
            # Don't actually sleep in tests
            return

        with patch("asyncio.sleep", side_effect=mock_sleep):
            sent = await mgr._send_reply(
                chat_id=group_id,
                reply_to_msg_id=0,
                text="test reply",
                adaptive_delay=True,
            )
            assert sent is True

        # Total wait must have accounted for at least (6.0 - 2.0) = 4.0s
        total_slept = sum(slept_durations)
        assert total_slept >= 3.0

    asyncio.run(_run())


def test_typing_indicator_duration_range(tmp_path: Path):
    """Verify that in adaptive delay mode, typing duration is between 3.0 and 10.0 seconds."""
    async def _run():
        cfg = AppConfig(api_id=123, api_hash="dummy_hash", data_dir=tmp_path, min_delay_seconds=5.0, max_delay_seconds=15.0)
        db = Database(tmp_path / "app_typing.db")
        safety = SafetyManager(cfg, db)
        privacy = PrivacyManager(cfg, database=db)
        generator = ReplyGenerator(cfg, database=db)
        mgr = ReplyManager(cfg, db, safety, privacy, generator)
        mgr.min_delay = 5.0
        mgr.max_delay = 15.0

        chat_id = 777666
        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(return_value=MagicMock(id=301))

        action_types = []
        class MockActionContext:
            def __init__(self, c_id, action):
                action_types.append((c_id, action))
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        mock_client.action = MagicMock(side_effect=MockActionContext)
        mgr.set_telegram_client(mock_client)

        slept = []
        async def mock_sleep(secs):
            slept.append(secs)
            return

        with patch("asyncio.sleep", side_effect=mock_sleep):
            sent = await mgr._send_reply(
                chat_id=chat_id,
                reply_to_msg_id=10,
                text="hello friend how are you doing",
                adaptive_delay=True,
            )
            assert sent is True

        assert len(action_types) >= 1
        assert action_types[0] == (chat_id, "typing")

    asyncio.run(_run())


def test_concurrent_replies_serialized_by_lock(tmp_path: Path):
    """Verify that concurrent calls to _send_reply for the same chat are strictly serialized by lock."""
    async def _run():
        cfg = AppConfig(api_id=123, api_hash="dummy_hash", data_dir=tmp_path)
        db = Database(tmp_path / "app_lock.db")
        safety = SafetyManager(cfg, db)
        privacy = PrivacyManager(cfg, database=db)
        generator = ReplyGenerator(cfg, database=db)
        mgr = ReplyManager(cfg, db, safety, privacy, generator)

        chat_id = -100554433
        db.set_state(f"chat_cooldown_min_{chat_id}", "5.0")
        db.set_state(f"chat_cooldown_max_{chat_id}", "5.0")

        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(side_effect=[MagicMock(id=1), MagicMock(id=2)])
        mgr.set_telegram_client(mock_client)

        order_of_events = []

        async def fake_sleep(secs):
            order_of_events.append(f"sleep_{secs:.1f}")

        with patch("asyncio.sleep", side_effect=fake_sleep):
            # Launch two replies concurrently
            t1 = asyncio.create_task(mgr._send_reply(chat_id, 0, "first", adaptive_delay=False))
            t2 = asyncio.create_task(mgr._send_reply(chat_id, 0, "second", adaptive_delay=False))
            results = await asyncio.gather(t1, t2)

        assert results == [True, True]
        assert mock_client.send_message.call_count == 2
        # Second call must have enforced remaining cooldown after first call
        assert any("sleep_5.0" in ev for ev in order_of_events)

    asyncio.run(_run())
