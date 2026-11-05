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


def test_quiethours_commands_and_suppression(tmp_path: Path):
    """Verify quiet hours customization from Telegram and auto-reply suppression during sleep schedule."""
    async def _run():
        cfg = AppConfig(
            api_id=123,
            api_hash="dummy_hash",
            reply_mode="restricted_auto",
            allowed_private_chats={100},
            data_dir=tmp_path,
        )
        db = Database(tmp_path / "app_qh.db")
        safety = SafetyManager(cfg, db)
        safety.set_auto_authorization(True)
        privacy = PrivacyManager(cfg, database=db)
        generator = ReplyGenerator(cfg)
        mgr = ReplyManager(cfg, db, safety, privacy, generator)

        mock_client = AsyncMock()
        mgr.set_telegram_client(mock_client)

        # 1. Default quiet hours is ON (02:00 to 08:00 IST)
        status_res = await mgr.handle_control_command("/quiethours")
        assert "Quiet Hours" in status_res
        assert "ENABLED" in status_res or "ON" in status_res

        # 2. Turn on with custom hours
        on_res = await mgr.handle_control_command("/quiethours on 01:00 08:00")
        assert "ENABLED" in on_res
        assert "01:00" in on_res and "08:00" in on_res
        assert safety.quiet_hours_enabled is True
        assert safety.quiet_hours_window == ("01:00", "08:00")

        # 3. Turn off
        off_res = await mgr.handle_control_command("/quiethours off")
        assert "DISABLED" in off_res
        assert safety.quiet_hours_enabled is False

        # 4. Set direct schedule
        set_res = await mgr.handle_control_command("/quiethours 23:00 07:00")
        assert "23:00" in set_res and "07:00" in set_res
        assert safety.quiet_hours_enabled is True

        # 5. Verify suppression during quiet hours without spamming Saved Messages
        # Set schedule spanning whole day to guarantee match
        safety.set_quiet_hours(True, start="00:00", end="23:59")
        await mgr.handle_incoming_eligible_message(
            chat_id=100,
            chat_title="Friend",
            message_id=50,
            sender_id=123,
            sender_name="Alice",
            text="Hello during sleep hours",
        )
        # No message sent to user chat or saved messages
        mock_client.send_message.assert_not_called()

    asyncio.run(_run())


def test_reaction_randomized_interval_cooldown(tmp_path: Path):
    """Verify that reaction cooldown randomizes between 3s and 9s and blocks rapid successive reactions."""
    async def _run():
        cfg = AppConfig(
            api_id=123,
            api_hash="dummy_hash",
            reaction_enabled=True,
            reaction_min_cooldown_seconds=3.0,
            reaction_max_cooldown_seconds=9.0,
            data_dir=tmp_path,
        )
        db = Database(tmp_path / "app_react.db")
        safety = SafetyManager(cfg, db)
        privacy = PrivacyManager(cfg, database=db)
        generator = ReplyGenerator(cfg)
        mgr = ReplyManager(cfg, db, safety, privacy, generator)

        mock_client = AsyncMock()
        mgr.set_telegram_client(mock_client)

        # First reaction succeeds
        sent1 = await mgr.maybe_send_reaction(chat_id=100, message_id=1, text="Haha this is hilarious")
        assert sent1 is True
        assert 3.0 <= mgr._next_reaction_cooldown <= 9.0

        # Immediate second reaction blocked by 3s-9s cooldown
        sent2 = await mgr.maybe_send_reaction(chat_id=100, message_id=2, text="Another funny message")
        assert sent2 is False

    asyncio.run(_run())


def test_status_and_chats_dataframe_display(tmp_path: Path):
    """Verify DataFrame table rendering with numbering, type, title, and username in /status and /chats."""
    async def _run():
        cfg = AppConfig(
            api_id=123,
            api_hash="dummy_hash",
            allowed_private_chats={1001},
            allowed_groups={-1002003},
            data_dir=tmp_path,
        )
        db = Database(tmp_path / "app_df.db")
        safety = SafetyManager(cfg, db)
        privacy = PrivacyManager(cfg, database=db)
        generator = ReplyGenerator(cfg)
        mgr = ReplyManager(cfg, db, safety, privacy, generator)

        # Store metadata for chats
        db.record_chat_metadata(1001, title="Alice Walker", username="alicew", chat_type="Private")
        db.record_chat_metadata(-1002003, title="Crypto Alpha", username="cryptoalpha", chat_type="Group")

        # 1. /status command contains DataFrame with columns and rows
        status_res = await mgr.handle_control_command("/status")
        assert "DataFrame" in status_res
        assert "Alice Walker" in status_res
        assert "@alicew" in status_res
        assert "Crypto Alpha" in status_res
        assert "@cryptoalpha" in status_res
        assert "# | Type" in status_res or "# |" in status_res

        # 2. /chats command contains DataFrame
        chats_res = await mgr.handle_control_command("/chats")
        assert "DataFrame" in chats_res
        assert "1 |" in chats_res
        assert "2 |" in chats_res

    asyncio.run(_run())


def test_per_chat_persona_override(tmp_path: Path):
    """Verify per-chat style customization and fallback to default persona when not customized."""
    async def _run():
        cfg = AppConfig(
            api_id=123,
            api_hash="dummy_hash",
            allowed_private_chats={2001, 2002},
            data_dir=tmp_path,
        )
        db = Database(tmp_path / "app_persona.db")
        safety = SafetyManager(cfg, db)
        privacy = PrivacyManager(cfg, database=db)
        generator = ReplyGenerator(cfg)
        mgr = ReplyManager(cfg, db, safety, privacy, generator)

        # 1. Default global style is casual
        assert generator.style == "casual"

        # 2. Set custom style for chat 2001 to formal
        res_custom = await mgr.handle_control_command("/style 2001 formal")
        assert "formal" in res_custom
        assert db.get_state("chat_style_2001") == "formal"

        # 3. /styles lists the override
        styles_res = await mgr.handle_control_command("/styles")
        assert "2001" in styles_res
        assert "formal" in styles_res

        # 4. Chat 2002 has no override; should fall back to default (empty state)
        assert db.get_state("chat_style_2002") == ""

        # 5. Reset chat 2001 to default
        reset_res = await mgr.handle_control_command("/style 2001 default")
        assert "reset to default" in reset_res.lower()
        assert db.get_state("chat_style_2001") == ""

    asyncio.run(_run())


def test_token_usage_tracker_and_ai_parameters(tmp_path: Path):
    """Verify token usage tracking against 100M free pool and dynamic AI parameters."""
    async def _run():
        cfg = AppConfig(
            api_id=123,
            api_hash="dummy_hash",
            ai_provider="custom",
            ai_model="mercury-3,mercury-3-preview-1014",
            ai_base_url="https://api.inceptionlabs.ai/v1",
            data_dir=tmp_path,
        )
        db = Database(tmp_path / "app_usage.db")
        safety = SafetyManager(cfg, db)
        privacy = PrivacyManager(cfg, database=db)
        generator = ReplyGenerator(cfg)
        mgr = ReplyManager(cfg, db, safety, privacy, generator)

        # 1. Record simulated token usage
        db.record_token_usage("custom", "mercury-3", prompt_tokens=15, completion_tokens=25, total_tokens=40)
        db.record_token_usage("custom", "mercury-3-preview-1014", prompt_tokens=10, completion_tokens=10, total_tokens=20)

        # 2. /usage command
        usage_res = await mgr.handle_control_command("/usage")
        assert "Token Tracker" in usage_res
        assert "60" in usage_res  # total tokens 40+20
        assert "100,000,000" in usage_res
        assert "mercury-3" in usage_res

        # 3. /reasoning command
        effort_res = await mgr.handle_control_command("/reasoning high")
        assert "high" in effort_res
        assert db.get_state("ai_reasoning_effort") == "high"

        # 4. /temp command
        temp_res = await mgr.handle_control_command("/temp 0.85")
        assert "0.85" in temp_res
        assert db.get_state("ai_temperature") == "0.85"

        # 5. /maxtokens command
        tokens_res = await mgr.handle_control_command("/maxtokens 180")
        assert "180" in tokens_res
        assert db.get_state("ai_max_tokens") == "180"

        # 6. /aiconfig command
        config_res = await mgr.handle_control_command("/aiconfig")
        assert "AI Engine Configuration" in config_res
        assert "mercury-3" in config_res
        assert "high" in config_res

    asyncio.run(_run())


def test_telegram_setprompt_and_prompt_commands(tmp_path: Path):
    """Verify customizing system prompt from Telegram Saved Messages and resetting to default."""
    async def _run():
        cfg = AppConfig(
            api_id=123,
            api_hash="dummy_hash",
            data_dir=tmp_path,
        )
        db = Database(tmp_path / "app_prompt.db")
        safety = SafetyManager(cfg, db)
        privacy = PrivacyManager(cfg, database=db)
        generator = ReplyGenerator(cfg, database=db)
        mgr = ReplyManager(cfg, db, safety, privacy, generator)

        # 1. Initially default
        p_res = await mgr.handle_control_command("/prompt")
        assert "*Anti-AI Guardrails:* ACTIVE" in p_res
        assert "Default Persona" in p_res

        # 2. Update prompt via /setprompt
        update_res = await mgr.handle_control_command("/setprompt I am a game developer who loves retro games")
        assert "updated" in update_res
        assert db.get_state("custom_system_prompt") == "I am a game developer who loves retro games"

        # 3. Check /prompt shows custom persona
        p_res2 = await mgr.handle_control_command("/prompt")
        assert "game developer" in p_res2
        assert "Custom Persona" in p_res2
        assert "*Anti-AI Guardrails:* ACTIVE" in p_res2

        # 4. Reset prompt via /setprompt default
        reset_res = await mgr.handle_control_command("/setprompt default")
        assert "reset to default" in reset_res.lower()
        assert db.get_state("custom_system_prompt") == ""

    asyncio.run(_run())


def test_mention_fallback_on_ai_failure(tmp_path: Path):
    """Verify mentions never leak error notifications to Saved Messages on AI failure and receive human fallbacks."""
    async def _run():
        cfg = AppConfig(
            api_id=123,
            api_hash="dummy_hash",
            allowed_groups={-100999},
            reply_mode="restricted_auto",
            auto_authorize=True,
            data_dir=tmp_path,
        )
        db = Database(tmp_path / "app_mention.db")
        safety = SafetyManager(cfg, db)
        safety.set_auto_authorization(True)
        privacy = PrivacyManager(cfg, database=db)
        generator = ReplyGenerator(cfg, database=db)
        # Mock generator to simulate API failure
        generator.generate = MagicMock(side_effect=RuntimeError("Inception Labs rate limit"))
        mgr = ReplyManager(cfg, db, safety, privacy, generator)

        sent_messages = []
        async def mock_send_message(chat_id, text, **kwargs):
            sent_messages.append((chat_id, text))
            msg = MagicMock()
            msg.id = 777
            return msg

        mock_client = MagicMock()
        mock_client.send_message = AsyncMock(side_effect=mock_send_message)
        mgr.set_telegram_client(mock_client)

        # Incoming mention message
        await mgr.handle_incoming_eligible_message(
            chat_id=-100999,
            chat_title="Dev Group",
            message_id=501,
            sender_id=12345,
            sender_name="Alice",
            text="@Kaif hii",
            is_mention=True,
        )

        # Verify: Did NOT send error to Saved Messages ("me")
        saved_msg_errors = [m for m in sent_messages if m[0] == "me"]
        assert len(saved_msg_errors) == 0

        # Verify: Sent a natural human fallback reply to the group
        group_replies = [m for m in sent_messages if m[0] == -100999]
        assert len(group_replies) >= 1
        reply_text = group_replies[0][1]
        assert any(phrase in reply_text for phrase in ("kya chal raha", "batao", "update", "what's up", "caught up", "yo", "hii", "hey", "sup", "haan bolo"))

    asyncio.run(_run())


def test_context_aging_and_clearcontext_safety(tmp_path: Path):
    """Verify context auto-aging and /clearcontext command safely resets local context without touching Telegram."""
    async def _run():
        cfg = AppConfig(
            api_id=123,
            api_hash="dummy_hash",
            data_dir=tmp_path,
        )
        db = Database(tmp_path / "app_aging.db")
        safety = SafetyManager(cfg, db)
        privacy = PrivacyManager(cfg, database=db)
        generator = ReplyGenerator(cfg, database=db)
        mgr = ReplyManager(cfg, db, safety, privacy, generator)

        chat_id = 998877
        db.record_chat_message(chat_id, 1, 111, "Bob", "Hello context", is_outgoing=False)
        db.record_chat_message(chat_id, 2, None, "Kaif", "Hey Bob", is_outgoing=True)

        history = db.get_recent_chat_messages(chat_id)
        assert len(history) == 2

        # 1. /contextttl command
        ttl_res = await mgr.handle_control_command("/contextttl 1.5")
        assert "1.5 hours" in ttl_res
        assert db.get_state("context_ttl_hours") == "1.5"

        # 2. /clearcontext command
        clear_res = await mgr.handle_control_command(f"/clearcontext {chat_id}")
        assert "Cleared" in clear_res
        assert "Zero Telegram messages were touched or deleted" in clear_res

        # 3. Verified local cached context is cleared so AI starts fresh
        history_after = db.get_recent_chat_messages(chat_id)
        assert len(history_after) == 0

    asyncio.run(_run())


def test_version_and_typing_speed_modulation(tmp_path: Path):
    """Verify v2.0.5 branding in status and smart typing speed modulation."""
    async def _run():
        cfg = AppConfig(
            api_id=123,
            api_hash="dummy_hash",
            min_delay_seconds=3.0,
            max_delay_seconds=30.0,
            data_dir=tmp_path,
        )
        db = Database(tmp_path / "app_mod.db")
        safety = SafetyManager(cfg, db)
        privacy = PrivacyManager(cfg, database=db)
        generator = ReplyGenerator(cfg, database=db)
        mgr = ReplyManager(cfg, db, safety, privacy, generator)

        # 1. Version v2.0.5 in /status
        st = await mgr.handle_control_command("/status")
        assert "TeleAutomator v2.0.5 Status:" in st

        # 2. Smart typing delay modulation
        # Banter reply ("haha lol cool") vs thoughtful question ("why do you think this happens?")
        import random
        random.seed(42)
        banter_delay = mgr.calculate_adaptive_delay(12345, reply_text="haha yeah lol", incoming_text="yo haha")
        random.seed(42)
        thoughtful_delay = mgr.calculate_adaptive_delay(12345, reply_text="i think we need to carefully evaluate options", incoming_text="why do you think that?")
        # Thoughtful replies allow more reading & formulation time than quick banter
        assert thoughtful_delay > banter_delay

    asyncio.run(_run())


def test_daily_quota_threshold_alert(tmp_path: Path):
    """Verify daily quota alert triggers heads-up message to Saved Messages when consumption exceeds threshold."""
    async def _run():
        cfg = AppConfig(
            api_id=123,
            api_hash="dummy_hash",
            data_dir=tmp_path,
        )
        db = Database(tmp_path / "app_quota.db")
        safety = SafetyManager(cfg, db)
        privacy = PrivacyManager(cfg, database=db)
        generator = ReplyGenerator(cfg, database=db)
        mgr = ReplyManager(cfg, db, safety, privacy, generator)

        sent_to_me = []
        async def mock_send_message(chat_id, text, **kwargs):
            if chat_id == "me":
                sent_to_me.append(text)
            msg = MagicMock()
            msg.id = 888
            return msg

        mock_client = MagicMock()
        mock_client.send_message = AsyncMock(side_effect=mock_send_message)
        mgr.set_telegram_client(mock_client)

        # 1. Configure threshold to 50,000 tokens
        thresh_res = await mgr.handle_control_command("/quotathreshold 50000")
        assert "50,000" in thresh_res
        assert db.get_state("quota_threshold_tokens") == "50000"

        # 2. Record 60,000 tokens consumed in the last 24h
        db.record_token_usage("custom", "mercury-3", 20000, 40000, 60000)
        daily = db.get_daily_token_usage()
        assert daily == 60000

        # 3. Check daily quota warning
        await mgr.check_daily_quota_warning()
        assert len(sent_to_me) == 1
        assert "Daily Token Quota Threshold Alert" in sent_to_me[0]
        assert "60,000" in sent_to_me[0]

        # 4. Check that /usage reports 24h consumption
        usage_res = await mgr.handle_control_command("/usage")
        assert "24h Daily Consumption" in usage_res
        assert "60,000" in usage_res

    asyncio.run(_run())


def test_automatic_owner_name_sync(tmp_path: Path):
    """Verify owner name is automatically fetched and updated from Telegram profile."""
    async def _run():
        cfg = AppConfig(
            api_id=123,
            api_hash="dummy_hash",
            data_dir=tmp_path,
        )
        db = Database(tmp_path / "app_name.db")
        safety = SafetyManager(cfg, db)
        privacy = PrivacyManager(cfg, database=db)
        generator = ReplyGenerator(cfg, database=db)
        mgr = ReplyManager(cfg, db, safety, privacy, generator)

        # Case 1: Has first_name
        mock_me = MagicMock()
        mock_me.first_name = "Alex"
        mock_me.last_name = "Mercer"
        mock_me.username = "alexmercer"
        mock_me.id = 12345
        mock_client = MagicMock()
        mock_client.get_me = AsyncMock(return_value=mock_me)
        mgr.set_telegram_client(mock_client)

        fetched_name = await mgr.sync_owner_name_from_telegram()
        assert fetched_name == "Alex"
        assert generator.prompt_manager.owner_name == "Alex"
        assert db.get_state("owner_name") == "Alex"

        # Case 2: No first_name, has last_name
        mock_me.first_name = ""
        mock_me.last_name = "Mercer"
        fetched_name = await mgr.sync_owner_name_from_telegram()
        assert fetched_name == "Mercer"
        assert generator.prompt_manager.owner_name == "Mercer"

        # Case 3: No first or last name, has username
        mock_me.first_name = ""
        mock_me.last_name = ""
        mock_me.username = "@shadow_dev"
        fetched_name = await mgr.sync_owner_name_from_telegram()
        assert fetched_name == "shadow_dev"
        assert generator.prompt_manager.owner_name == "shadow_dev"

        # Case 4: No names, no username -> falls back to user ID
        mock_me.first_name = ""
        mock_me.last_name = ""
        mock_me.username = ""
        mock_me.id = 987654321
        fetched_name = await mgr.sync_owner_name_from_telegram()
        assert fetched_name == "987654321"
        assert generator.prompt_manager.owner_name == "987654321"

    asyncio.run(_run())


def test_permanent_group_context_and_pinned_sync(tmp_path: Path):
    """Verify permanent chat context storage, pinned message syncing, and safe context clearing."""
    async def _run():
        cfg = AppConfig(
            api_id=123,
            api_hash="dummy_hash",
            allowed_groups={-100999},
            data_dir=tmp_path,
        )
        db = Database(tmp_path / "app_perm.db")
        safety = SafetyManager(cfg, db)
        privacy = PrivacyManager(cfg, database=db)
        generator = ReplyGenerator(cfg, database=db)
        mgr = ReplyManager(cfg, db, safety, privacy, generator)

        mock_msg = MagicMock()
        mock_msg.text = "Pinned Announcement: Daily standup at 10 AM UTC. No promotions."
        mock_client = MagicMock()
        mock_client.get_messages = AsyncMock(return_value=[mock_msg])
        mgr.set_telegram_client(mock_client)

        # 1. Sync pinned context
        res = await mgr.handle_control_command("/syncpin -100999")
        assert "Synced pinned context" in res

        # 2. Add custom notes
        res2 = await mgr.handle_control_command("/setcontext -100999 CS graduation project team")
        assert "Permanent context saved" in res2

        # 3. View context
        res3 = await mgr.handle_control_command("/showcontext -100999")
        assert "Daily standup at 10 AM UTC" in res3
        assert "CS graduation project team" in res3

        # 4. Verify permanent context survives clear_chat_context
        # Insert some rolling context and clear it
        db.record_chat_message(-100999, 1, 10, "Alice", "hello", False)
        assert len(db.get_recent_chat_messages(-100999)) == 1
        clear_res = await mgr.handle_control_command("/clearcontext -100999")
        assert "Cleared 1 cached context" in clear_res
        assert len(db.get_recent_chat_messages(-100999)) == 0

        # Permanent context MUST still be intact!
        ctx_after = db.get_permanent_context(-100999)
        assert "Daily standup at 10 AM UTC" in ctx_after["pinned_text"]
        assert "CS graduation project team" in ctx_after["notes"]

        # 5. Delete permanent context explicitly
        del_res = await mgr.handle_control_command("/delcontext -100999")
        assert "has been removed" in del_res
        ctx_deleted = db.get_permanent_context(-100999)
        assert ctx_deleted["pinned_text"] == ""
        assert ctx_deleted["notes"] == ""

    asyncio.run(_run())


def test_ai_distill_group_context(tmp_path: Path):
    """Verify AI distill_group_context summarizes raw pinned texts."""
    cfg = AppConfig(api_id=123, api_hash="dummy_hash", data_dir=tmp_path)
    db = Database(tmp_path / "app_distill.db")
    generator = ReplyGenerator(cfg, database=db)

    # With mock provider
    mock_provider = MagicMock()
    mock_provider.generate_reply.return_value = "- Purpose: Solana DEX development\n- Rules: No spam or scams"
    generator.provider = mock_provider

    distilled = generator.distill_group_context("Solana Developers", "Announcement: We are building a DEX. Strict rule: no spam.")
    assert "- Purpose: Solana DEX development" in distilled
    assert "- Rules: No spam or scams" in distilled


def test_custom_ai_remote_configuration(tmp_path: Path):
    """Verify modifying custom AI, API keys, and endpoints remotely via Telegram commands."""
    async def _run():
        cfg = AppConfig(api_id=123, api_hash="dummy_hash", data_dir=tmp_path)
        db = Database(tmp_path / "app_ai_cfg.db")
        safety = SafetyManager(cfg, db)
        privacy = PrivacyManager(cfg, database=db)
        generator = ReplyGenerator(cfg, database=db)
        mgr = ReplyManager(cfg, db, safety, privacy, generator)

        # 1. Update API key via /apikey
        res1 = await mgr.handle_control_command("/apikey sk_test_1234567890abcdef")
        assert "AI API key updated" in res1
        assert db.get_state("ai_api_key") == "sk_test_1234567890abcdef"

        # 2. Update baseurl via /baseurl
        res2 = await mgr.handle_control_command("/baseurl https://api.mycustomai.com/v1")
        assert "AI base URL updated" in res2
        assert db.get_state("ai_base_url") == "https://api.mycustomai.com/v1"

        # 3. Update model via /model
        res3 = await mgr.handle_control_command("/model custom-fast-model")
        assert "AI model switched" in res3
        assert db.get_state("ai_model") == "custom-fast-model"

        # 4. Quick setup Mercury via /setai mercury <key>
        res4 = await mgr.handle_control_command("/setai mercury sk_mercury_test_dummy_key_1234567890")
        assert "Inception Labs Mercury Configured" in res4
        assert db.get_state("ai_provider") == "custom"
        assert db.get_state("ai_base_url") == "https://api.inceptionlabs.ai/v1"
        assert "mercury-3" in db.get_state("ai_model")

        # 5. Full custom setup via /setai custom <key> <url> <model>
        res5 = await mgr.handle_control_command("/setai custom sk_new_key https://api.together.xyz/v1 meta-llama/Llama-3-70b")
        assert "Custom AI Configured & Activated" in res5
        assert db.get_state("ai_provider") == "custom"
        assert db.get_state("ai_api_key") == "sk_new_key"
        assert db.get_state("ai_base_url") == "https://api.together.xyz/v1"
        assert db.get_state("ai_model") == "meta-llama/Llama-3-70b"

    asyncio.run(_run())


def test_database_backup_and_data_persistence(tmp_path: Path):
    """Verify database backup command creates valid snapshot and permanent context persists."""
    async def _run():
        cfg = AppConfig(api_id=123, api_hash="dummy_hash", data_dir=tmp_path)
        db = Database(tmp_path / "app_test_backup.db")
        safety = SafetyManager(cfg, db)
        privacy = PrivacyManager(cfg, database=db)
        generator = ReplyGenerator(cfg, database=db)
        mgr = ReplyManager(cfg, db, safety, privacy, generator)

        mock_client = MagicMock()
        mock_client.send_file = AsyncMock()
        mgr.set_telegram_client(mock_client)

        # Populate permanent context
        db.set_permanent_context(-100555, pinned_text="Critical Rules", notes="Tech Project")
        assert db.get_permanent_context(-100555)["pinned_text"] == "Critical Rules"

        # Execute /backup
        res = await mgr.handle_control_command("/backup")
        assert "Database backup" in res
        mock_client.send_file.assert_called_once()

        # Simulate update: re-initialize Database on same file to ensure everything persists
        db_reloaded = Database(tmp_path / "app_test_backup.db")
        reloaded_ctx = db_reloaded.get_permanent_context(-100555)
        assert reloaded_ctx["pinned_text"] == "Critical Rules"
        assert reloaded_ctx["notes"] == "Tech Project"

    asyncio.run(_run())


def test_group_relevance_and_20m_idle(tmp_path: Path):
    """Verify smart group relevance scoring and 20-minute idle tracker."""
    import time
    cfg = AppConfig(api_id=123, api_hash="dummy_hash", data_dir=tmp_path)
    db = Database(tmp_path / "test_group_rel.db")
    safety = SafetyManager(cfg, db)
    privacy = PrivacyManager(cfg, database=db)
    generator = ReplyGenerator(cfg, database=db)
    mgr = ReplyManager(cfg, db, safety, privacy, generator)

    chat_id = -100999888
    # 1. 20m idle check initially false (marks first encounter)
    assert mgr.check_group_20m_idle(chat_id) is False

    # Simulate 21 minutes passing
    mgr._last_group_activity[chat_id] = time.time() - 1300.0
    assert mgr.check_group_20m_idle(chat_id) is True

    # Mark activity resets timer
    mgr.mark_group_activity(chat_id)
    assert mgr.check_group_20m_idle(chat_id) is False

    # 2. Relevance checking via permanent context & keywords
    db.set_permanent_context(chat_id, pinned_text="Python automation project rules", notes="FastAPI backend")

    # Message matching keywords is relevant
    assert mgr.is_group_message_relevant(chat_id, "anyone worked with python here", "Dev Group") is True
    assert mgr.is_group_message_relevant(chat_id, "how to resolve this error", "General") is True
    # Off-topic chatter without questions or keywords is not relevant
    assert mgr.is_group_message_relevant(chat_id, "random chat potato salad", "Music Lounge") is False


def test_alerts_suppressed_when_paused_stopped_or_quiet(tmp_path: Path):
    """Verify approval and issue alerts are suppressed when paused, stopped, in quiet hours, or in draft mode."""
    async def _run():
        cfg = AppConfig(api_id=123, api_hash="dummy_hash", reply_mode="draft", data_dir=tmp_path)
        db = Database(tmp_path / "test_alerts.db")
        safety = SafetyManager(cfg, db)
        privacy = PrivacyManager(cfg, database=db)
        generator = ReplyGenerator(cfg, database=db)
        mgr = ReplyManager(cfg, db, safety, privacy, generator)

        mock_client = MagicMock()
        mock_client.send_message = AsyncMock()
        mgr.set_telegram_client(mock_client)

        # In draft mode: issue alert is suppressed
        await mgr._notify_issue_to_saved_messages(101, "Test Chat", "Alice", "Test Error")
        mock_client.send_message.assert_not_called()

        # Switch to auto mode, but pause safety
        mgr.db.set_state("reply_mode", "auto")
        safety.set_timed_pause(300)
        await mgr._notify_approval_needed(1, 101, "Test Chat", "Alice", "hi", "hey")
        await mgr._notify_issue_to_saved_messages(101, "Test Chat", "Alice", "Test Error")
        mock_client.send_message.assert_not_called()

    asyncio.run(_run())


def test_prompt_command_displays_full_text(tmp_path: Path):
    """Verify /prompt command returns complete system instructions without slicing at 1200 chars."""
    async def _run():
        cfg = AppConfig(api_id=123, api_hash="dummy_hash", data_dir=tmp_path)
        db = Database(tmp_path / "test_prompt.db")
        safety = SafetyManager(cfg, db)
        privacy = PrivacyManager(cfg, database=db)
        generator = ReplyGenerator(cfg, database=db)
        mgr = ReplyManager(cfg, db, safety, privacy, generator)

        res = await mgr.handle_control_command("/prompt")
        assert "CRITICAL TEXTING RULES" in res
        assert "NEVER USE QUESTION MARKS" in res
        assert "NO REPETITION / NO SPAM" in res
        assert len(res) > 1200

    asyncio.run(_run())

