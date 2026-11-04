"""Tests for ReplyManager workflows, modes, and control commands."""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from app.ai.reply_generator import ReplyGenerator
from app.config import AppConfig
from app.privacy_manager import PrivacyManager
from app.reply_manager import ReplyManager
from app.safety_manager import SafetyManager
from app.storage.database import Database


def test_draft_only_mode(tmp_path: Path):
    async def _run():
        cfg = AppConfig(
            api_id=123,
            api_hash="dummy_hash",
            reply_mode="draft",
            allowed_private_chats={100},
            data_dir=tmp_path,
        )
        db = Database(tmp_path / "app.db")
        safety = SafetyManager(cfg, db)
        privacy = PrivacyManager(cfg, database=db)
        generator = ReplyGenerator(cfg)
        mgr = ReplyManager(cfg, db, safety, privacy, generator)

        mock_client = AsyncMock()
        mgr.set_telegram_client(mock_client)

        # Handle eligible message
        await mgr.handle_incoming_eligible_message(
            chat_id=100,
            chat_title="Friend",
            message_id=55,
            sender_id=123,
            sender_name="Alice",
            text="Hello!",
        )

        # In draft mode, no message must be sent
        mock_client.send_message.assert_not_called()
        # But a draft record should be kept
        approvals = db.list_pending_approvals()
        assert len(approvals) == 1
        assert "Alice" in approvals[0]["incoming_text"] or "Hello" in approvals[0]["incoming_text"]

    asyncio.run(_run())


def test_approval_mode_and_commands(tmp_path: Path):
    async def _run():
        cfg = AppConfig(
            api_id=123,
            api_hash="dummy_hash",
            reply_mode="approval",
            allowed_private_chats={100},
            global_cooldown_seconds=0,
            per_chat_cooldown_seconds=0,
            data_dir=tmp_path,
        )
        db = Database(tmp_path / "app.db")
        safety = SafetyManager(cfg, db)
        privacy = PrivacyManager(cfg, database=db)
        generator = ReplyGenerator(cfg)
        mgr = ReplyManager(cfg, db, safety, privacy, generator)

        mock_client = AsyncMock()
        mgr.set_telegram_client(mock_client)

        # Handle incoming message in approval mode
        await mgr.handle_incoming_eligible_message(
            chat_id=100,
            chat_title="Friend",
            message_id=55,
            sender_id=123,
            sender_name="Alice",
            text="Hello!",
        )

        # Notification sent to 'me'
        assert mock_client.send_message.call_count == 1
        call_args = mock_client.send_message.call_args[0]
        assert call_args[0] == "me"
        assert "/approve" in call_args[1]

        # Test commands
        # 1. /status
        res = await mgr.handle_control_command("/status")
        assert "Client Status" in res

        # 2. /approve 1
        res = await mgr.handle_control_command("/approve 1")
        assert "sent successfully" in res
        # Verified message was sent to the chat
        assert mock_client.send_message.call_count == 2
        second_call = mock_client.send_message.call_args_list[1]
        assert second_call[0][0] == 100  # chat_id

        # 3. /stop and /resume
        stop_res = await mgr.handle_control_command("/stop")
        assert "ACTIVATED" in stop_res
        assert safety.is_emergency_stopped is True

        resume_res = await mgr.handle_control_command("/resume")
        assert "RESUMED" in resume_res or "DEACTIVATED" in resume_res
        assert safety.is_emergency_stopped is False

        # 4. /pause 2h
        pause_res = await mgr.handle_control_command("/pause 2h")
        assert "PAUSED" in pause_res
        assert safety.get_remaining_pause_seconds() > 3600

        # /resume clears timed pause
        await mgr.handle_control_command("/resume")
        assert safety.get_remaining_pause_seconds() == 0.0

        # 5. /name custom identity
        name_res = await mgr.handle_control_command("/name Rahul")
        assert "Rahul" in name_res
        assert generator.prompt_manager.owner_name == "Rahul"

        # 6. /setprompt
        prompt_res = await mgr.handle_control_command("/setprompt You are a chill friend.")
        assert "updated" in prompt_res.lower()
        assert "chill friend" in generator.prompt_manager.system_instructions

        # 7. /allowchat and /chats
        allow_res = await mgr.handle_control_command("/allowchat 555666")
        assert "added" in allow_res.lower()
        chats_res = await mgr.handle_control_command("/chats")
        assert "555666" in chats_res

        # 8. /mentiononly
        mentions_res = await mgr.handle_control_command("/mentiononly on")
        assert "Mentions Only" in mentions_res

        # 9. /removechat
        rem_res = await mgr.handle_control_command("/removechat 555666")
        assert "removed" in rem_res.lower()

    asyncio.run(_run())
