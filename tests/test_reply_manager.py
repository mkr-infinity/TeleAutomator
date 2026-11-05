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
            typing_delay_seconds=0.0,
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
        assert "Status" in res

        # 2. /approve 1
        res = await mgr.handle_control_command("/approve 1")
        assert "sent successfully" in res
        # Verified message parts were sent to the chat
        assert mock_client.send_message.call_count >= 2
        sent_chat_ids = [c[0][0] for c in mock_client.send_message.call_args_list[1:]]
        assert 100 in sent_chat_ids

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

        # 6. /setprompt (use tmp_path file to avoid modifying root system_prompt.txt)
        generator.prompt_manager.prompt_file = tmp_path / "system_prompt.txt"
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

        # 10. Keyword trigger rules (/addrule, /rules, /delrule)
        rule_add = await mgr.handle_control_command("/addrule portfolio => Check out my github profile!")
        assert "rule added" in rule_add.lower()

        rules_list = await mgr.handle_control_command("/rules")
        assert "portfolio" in rules_list

        # Test trigger matching in incoming message
        assert db.match_keyword_rule("Hey can I see your portfolio please?") == "Check out my github profile!"

        rule_del = await mgr.handle_control_command("/delrule portfolio")
        assert "deleted" in rule_del.lower()
        assert db.match_keyword_rule("portfolio") is None

        # 11. Mode switching (/mode draft, /mode approval, /mode auto)
        mode_res = await mgr.handle_control_command("/mode")
        assert "Current Reply Mode" in mode_res
        await mgr.handle_control_command("/mode draft")
        assert mgr.current_mode == "draft"
        await mgr.handle_control_command("/mode auto")
        assert mgr.current_mode == "restricted_auto"
        assert safety.is_auto_authorized is True

        # 12. Style switching (/style casual, /style concise, /style formal, /style humorous)
        style_res = await mgr.handle_control_command("/style")
        assert "Current AI Style" in style_res
        await mgr.handle_control_command("/style concise")
        assert generator.style == "concise"
        await mgr.handle_control_command("/style casual")
        assert generator.style == "casual"

    asyncio.run(_run())


def test_adaptive_delay_group_and_private(tmp_path: Path):
    """Verify adaptive randomized delay across group chats, private DMs, and text complexity."""
    cfg = AppConfig(
        api_id=123,
        api_hash="dummy_hash",
        min_delay_seconds=5.0,
        max_delay_seconds=60.0,
        data_dir=tmp_path,
    )
    db = Database(tmp_path / "app.db")
    safety = SafetyManager(cfg, db)
    privacy = PrivacyManager(cfg, database=db)
    generator = ReplyGenerator(cfg)
    mgr = ReplyManager(cfg, db, safety, privacy, generator)

    # 1. Group chat (chat_id < 0) should stay within group range (5 to 25s)
    group_chat_id = -1001234567890
    for _ in range(20):
        group_delay = mgr.calculate_adaptive_delay(group_chat_id, "Sounds good bro!")
        assert 5.0 <= group_delay <= 25.0, f"Group delay out of range: {group_delay}"

    # 2. Private 1-on-1 chat (chat_id > 0) stays within DM range (10 to 60s)
    private_chat_id = 987654321
    for _ in range(20):
        dm_delay = mgr.calculate_adaptive_delay(private_chat_id, "Hey Alice, how are you doing?")
        assert 5.0 <= dm_delay <= 60.0, f"Private delay out of range: {dm_delay}"

    # 3. Disabled delay returns 0.0
    zero_cfg = AppConfig(
        api_id=123,
        api_hash="dummy_hash",
        min_delay_seconds=0.0,
        max_delay_seconds=0.0,
        data_dir=tmp_path,
    )
    zero_mgr = ReplyManager(zero_cfg, db, safety, privacy, generator)
    assert zero_mgr.calculate_adaptive_delay(group_chat_id, "yo") == 0.0
    assert zero_mgr.calculate_adaptive_delay(private_chat_id, "yo") == 0.0


def test_send_reply_abort_on_emergency_stop(tmp_path: Path):
    """Verify _send_reply aborts without sending if emergency stop is triggered."""
    async def _run():
        cfg = AppConfig(
            api_id=123,
            api_hash="dummy_hash",
            min_delay_seconds=0.0,
            max_delay_seconds=0.0,
            typing_delay_seconds=0.0,
            data_dir=tmp_path,
        )
        db = Database(tmp_path / "app.db")
        safety = SafetyManager(cfg, db)
        privacy = PrivacyManager(cfg, database=db)
        generator = ReplyGenerator(cfg)
        mgr = ReplyManager(cfg, db, safety, privacy, generator)

        mock_client = AsyncMock()
        mgr.set_telegram_client(mock_client)

        # Trigger emergency stop
        safety.set_emergency_stop(True)

        # Attempt to send reply with mock delay
        mgr.min_delay = 0.05
        mgr.max_delay = 0.05
        sent = await mgr._send_reply(100, 1, "test message", adaptive_delay=True)
        assert sent is False
        mock_client.send_message.assert_not_called()

    asyncio.run(_run())


def test_errors_and_fallbacks_never_sent_to_groups_or_chats(tmp_path: Path):
    """Verify that when errors or issues occur, zero messages are sent to groups; alerts only route to Saved Messages."""
    async def _run():
        cfg = AppConfig(
            api_id=123,
            api_hash="dummy_hash",
            reply_mode="restricted_auto",
            allowed_groups={-100123456789},
            min_delay_seconds=0.0,
            max_delay_seconds=0.0,
            typing_delay_seconds=0.0,
            data_dir=tmp_path,
        )
        db = Database(tmp_path / "app.db")
        safety = SafetyManager(cfg, db)
        safety.set_auto_authorization(True)
        privacy = PrivacyManager(cfg, database=db)

        # Mock generator that raises an AI generation error
        failing_generator = MagicMock()
        failing_generator.generate.side_effect = RuntimeError("API rate limit exceeded 429")

        mgr = ReplyManager(cfg, db, safety, privacy, failing_generator)
        mock_client = AsyncMock()
        mgr.set_telegram_client(mock_client)

        group_id = -100123456789

        # Inbound eligible message arrives in group
        await mgr.handle_incoming_eligible_message(
            chat_id=group_id,
            chat_title="Developer Group",
            message_id=999,
            sender_id=456,
            sender_name="Bob",
            text="Hey Kaif can you review this PR?",
        )

        # Crucial Assertion 1: Zero messages were sent to the group!
        for call in mock_client.send_message.call_args_list:
            dest = call[0][0]
            assert dest != group_id, f"Error/fallback was leaked to group {group_id}!"

        # Crucial Assertion 2: Exactly one issue alert was delivered to private Saved Messages ('me')
        assert mock_client.send_message.call_count == 1
        saved_call = mock_client.send_message.call_args[0]
        assert saved_call[0] == "me"
        assert "TeleAutomator Alert" in saved_call[1]
        assert "API rate limit exceeded 429" in saved_call[1]
        assert "Developer Group" in saved_call[1]

    asyncio.run(_run())


def test_message_splitting_meaning_and_bounds():
    """Verify responses divide into 2 or 3 complete thoughts without breaking words or syntax."""
    # 1. Single brief word or short phrase should stay single message
    assert ReplyManager.split_reply_messages("hii") == ["hii"]
    assert ReplyManager.split_reply_messages("hello bro") == ["hello bro"]

    # 2. Divided by newline (multi-thought from prompt)
    two_parts = ReplyManager.split_reply_messages("hii bro\nall ok bro what about you")
    assert two_parts == ["hii bro", "all ok bro what about you"]

    # 3. Divided by sentence boundaries
    sent_parts = ReplyManager.split_reply_messages("hii bro. all ok bro what about you")
    assert sent_parts == ["hii bro.", "all ok bro what about you"]

    # 4. Never breaks words or tiny punctuation
    single_word_dot = ReplyManager.split_reply_messages("ok.")
    assert single_word_dot == ["ok."]

    # 5. Cap at 3 messages max
    four_parts = ReplyManager.split_reply_messages("part one\npart two\npart three\npart four")
    assert len(four_parts) == 3


def test_reaction_and_cooldown_controls(tmp_path: Path):
    """Verify runtime customization of reactions, reaction cooldowns, and chat cooldowns."""
    async def _run():
        cfg = AppConfig(
            api_id=123,
            api_hash="dummy_hash",
            reply_mode="restricted_auto",
            data_dir=tmp_path,
        )
        db = Database(tmp_path / "app.db")
        safety = SafetyManager(cfg, db)
        privacy = PrivacyManager(cfg, database=db)
        generator = ReplyGenerator(cfg)
        mgr = ReplyManager(cfg, db, safety, privacy, generator)

        mock_client = AsyncMock()
        mgr.set_telegram_client(mock_client)

        # 1. /lang command
        lang_res = await mgr.handle_control_command("/lang")
        assert "Current Reply Language" in lang_res
        await mgr.handle_control_command("/lang english")
        assert generator.language == "english"
        assert db.get_state("chat_language") == "english"

        # 2. /reaction commands
        react_res = await mgr.handle_control_command("/reaction")
        assert "Auto-Reactions" in react_res
        await mgr.handle_control_command("/reaction off")
        assert db.get_state("reaction_enabled") == "0"
        await mgr.handle_control_command("/reaction on")
        assert db.get_state("reaction_enabled") == "1"

        # 3. /reactioncooldown <count> <minutes>
        cd_res = await mgr.handle_control_command("/reactioncooldown 4 10")
        assert "Max *4* reactions" in cd_res
        assert db.get_state("reaction_max_per_window") == "4"
        assert db.get_state("reaction_window_seconds") == "600.0"

        # 4. /chatcooldown and /globalcooldown
        chat_res = await mgr.handle_control_command("/chatcooldown 25")
        assert "25s" in chat_res
        assert safety.per_chat_cooldown_seconds == 25

        glob_res = await mgr.handle_control_command("/globalcooldown 12")
        assert "12s" in glob_res
        assert safety.global_cooldown_seconds == 12

        # 5. Database reaction tracking and limit enforcement
        import time
        db.record_reaction(time.time())
        assert db.get_recent_reaction_count(3600) >= 1

    asyncio.run(_run())


def test_cooldown_suppression_does_not_alert_saved_messages(tmp_path: Path):
    """Verify that when a message is suppressed due to cooldown, zero alerts are sent to Saved Messages."""
    async def _run():
        cfg = AppConfig(
            api_id=123,
            api_hash="dummy_hash",
            reply_mode="restricted_auto",
            allowed_private_chats={100},
            global_cooldown_seconds=60,
            per_chat_cooldown_seconds=60,
            data_dir=tmp_path,
        )
        db = Database(tmp_path / "app.db")
        safety = SafetyManager(cfg, db)
        safety.set_auto_authorization(True)
        privacy = PrivacyManager(cfg, database=db)
        generator = ReplyGenerator(cfg)
        mgr = ReplyManager(cfg, db, safety, privacy, generator)

        mock_client = AsyncMock()
        mgr.set_telegram_client(mock_client)

        # Simulate a reply was recently sent
        safety.mark_reply_sent(100)

        # Incoming eligible message arrives while cooldown is active
        await mgr.handle_incoming_eligible_message(
            chat_id=100,
            chat_title="Friend",
            message_id=200,
            sender_id=123,
            sender_name="Alice",
            text="Are you there?",
        )

        # Neither the chat NOR Saved Messages ('me') should receive any message
        mock_client.send_message.assert_not_called()

    asyncio.run(_run())


def test_mention_queue_never_skipped(tmp_path: Path):
    """Verify that mentions are never skipped when cooldown is active; they are queued and sent."""
    async def _run():
        cfg = AppConfig(
            api_id=123,
            api_hash="dummy_hash",
            reply_mode="restricted_auto",
            allowed_private_chats={100},
            global_cooldown_seconds=1,
            per_chat_cooldown_seconds=1,
            min_delay_seconds=0.0,
            max_delay_seconds=0.0,
            typing_delay_seconds=0.0,
            data_dir=tmp_path,
        )
        db = Database(tmp_path / "app.db")
        safety = SafetyManager(cfg, db)
        safety.set_auto_authorization(True)
        privacy = PrivacyManager(cfg, database=db)
        generator = ReplyGenerator(cfg)
        mgr = ReplyManager(cfg, db, safety, privacy, generator)

        mock_client = AsyncMock()
        mgr.set_telegram_client(mock_client)

        # Active cooldown
        safety.mark_reply_sent(100)

        # Incoming mention message arrives
        await mgr.handle_incoming_eligible_message(
            chat_id=100,
            chat_title="Friend",
            message_id=205,
            sender_id=123,
            sender_name="Alice",
            text="@Kaif are you free tonight?",
            is_mention=True,
        )

        # Wait for deferred queue execution (1s cooldown + buffer)
        await asyncio.sleep(2.2)

        # Verified message was sent to the chat after cooldown!
        assert mock_client.send_message.call_count >= 1
        assert any(c[0][0] == 100 for c in mock_client.send_message.call_args_list)

    asyncio.run(_run())


def test_chat_context_database_caching(tmp_path: Path):
    """Verify that conversation context caches in SQLite to save AI usage and avoid repeated network calls."""
    db = Database(tmp_path / "app.db")
    db.record_chat_message(chat_id=500, message_id=1, sender_id=10, sender_name="Rahul", text="wassup bro", is_outgoing=False)
    db.record_chat_message(chat_id=500, message_id=2, sender_id=None, sender_name="Kaif", text="all good", is_outgoing=True)
    db.record_chat_message(chat_id=500, message_id=3, sender_id=10, sender_name="Rahul", text="game tonight?", is_outgoing=False)

    history = db.get_recent_chat_messages(chat_id=500, limit=5)
    assert len(history) == 3
    assert history[0]["sender"] == "Rahul"
    assert history[0]["text"] == "wassup bro"
    assert history[1]["sender"] == "You"
    assert history[1]["text"] == "all good"
    assert history[2]["sender"] == "Rahul"
    assert history[2]["text"] == "game tonight?"


def test_openai_compatible_provider_custom_base_url():
    """Verify custom base URL and model support (e.g., NVIDIA, Groq, DeepSeek)."""
    from app.ai.provider import OpenAIProvider
    provider = OpenAIProvider(
        api_key="nvapi-test123",
        model="meta/llama-3.1-70b-instruct",
        base_url="https://integrate.api.nvidia.com/v1",
    )
    assert provider.endpoint_url == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert provider.model == "meta/llama-3.1-70b-instruct"


def test_control_commands_model_baseurl_provider_chatty(tmp_path: Path):
    """Verify Saved Messages commands for switching model, base URL, provider, and banter."""
    async def _run():
        cfg = AppConfig(
            api_id=123,
            api_hash="dummy_hash",
            reply_mode="restricted_auto",
            data_dir=tmp_path,
        )
        db = Database(tmp_path / "app.db")
        safety = SafetyManager(cfg, db)
        privacy = PrivacyManager(cfg, database=db)
        generator = ReplyGenerator(cfg)
        mgr = ReplyManager(cfg, db, safety, privacy, generator)

        # 1. /model
        model_info = await mgr.handle_control_command("/model")
        assert "Current AI Model" in model_info
        model_set = await mgr.handle_control_command("/model gemini-2.5-flash-lite")
        assert "gemini-2.5-flash-lite" in model_set
        assert db.get_state("ai_model") == "gemini-2.5-flash-lite"

        # 2. /baseurl
        url_info = await mgr.handle_control_command("/baseurl")
        assert "Current AI Base URL" in url_info
        url_set = await mgr.handle_control_command("/baseurl https://integrate.api.nvidia.com/v1")
        assert "https://integrate.api.nvidia.com/v1" in url_set
        assert db.get_state("ai_base_url") == "https://integrate.api.nvidia.com/v1"

        # 3. /chatty
        chatty_info = await mgr.handle_control_command("/chatty")
        assert "Group Banter Participation" in chatty_info
        chatty_set = await mgr.handle_control_command("/chatty 20")
        assert "20%" in chatty_set
        assert float(db.get_state("chatty_probability")) == 0.20

    asyncio.run(_run())
