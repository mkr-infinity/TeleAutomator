"""Regression cases from the full workflow audit. No live Telegram/AI calls."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.reply_generator import ReplyGenerator
from app.ai.provider import OpenAIProvider
from app.bot_control import BotControl
from app.config import AppConfig
from app.event_handlers import is_thread_ender, record_own_outgoing_message, register_handlers
from app.miniapp_server import MiniAppAPI, MiniAppContext, _authorized_user_ids
from app.privacy_manager import PrivacyManager
from app.reply_manager import ReplyManager, capitalize_message
from app.safety_manager import SafetyManager
from app.storage.database import Database
from tests.test_miniapp import http_server, forge_init_data, _get, _post


def make_stack(tmp_path, **overrides):
    values = dict(api_id=123, api_hash="dummy-hash", data_dir=tmp_path,
                  reply_mode="restricted_auto", quiet_hours_enabled=False,
                  allowed_private_chats={123}, allowed_groups={-100111},
                  bot_authorized_users={111}, global_cooldown_seconds=0,
                  per_chat_cooldown_seconds=0, min_delay_seconds=0, max_delay_seconds=0,
                  min_chat_cooldown_seconds=0, max_chat_cooldown_seconds=0,
                  min_global_cooldown_seconds=0, max_global_cooldown_seconds=0,
                  typing_delay_seconds=0)
    values.update(overrides)
    config = AppConfig(**values)
    db = Database(tmp_path / "workflow.db")
    safety = SafetyManager(config, db)
    safety.set_auto_authorization(True)
    privacy = PrivacyManager(config, db)
    generator = ReplyGenerator(config, database=db)
    manager = ReplyManager(config, db, safety, privacy, generator)
    db.set_state("typo_correction_enabled", "0")
    db.set_state("editfix_enabled", "0")
    db.set_state("ownreact_enabled", "0")
    db.set_state("spontaneous_followup_enabled", "0")
    client = AsyncMock()
    client.send_message.return_value = SimpleNamespace(id=777)
    manager.set_telegram_client(client)
    bot = BotControl("audit-dummy-token", db, manager, config.bot_authorized_users)
    context = MiniAppContext(db, safety, privacy, manager, generator, "audit-token", bot_control=bot)
    return SimpleNamespace(config=config, db=db, safety=safety, privacy=privacy,
                           generator=generator, manager=manager, client=client,
                           bot=bot, context=context, api=MiniAppAPI(context))


def test_unapproved_chats_are_ignored_before_any_lookup_or_storage(tmp_path):
    s = make_stack(tmp_path)
    handlers = []
    s.client.on = lambda _: lambda handler: handlers.append(handler) or handler
    message_filter = MagicMock()
    register_handlers(s.client, 111, message_filter, s.manager)
    for outgoing in (False, True):
        event = SimpleNamespace(chat_id=999, id=1, raw_text="private", out=outgoing, is_group=False)
        asyncio.run(handlers[0](event))
        record_own_outgoing_message(s.manager, event, 111)
    message_filter.evaluate.assert_not_called()
    assert s.db.count_chat_messages(999) == 0
    assert not s.api.handle_activity()["activity"]


def test_removing_env_chat_survives_restart_and_readding(tmp_path):
    s = make_stack(tmp_path)
    s.privacy.remove_chat(-100111)
    restarted = PrivacyManager(s.config, s.db)
    assert not restarted.is_chat_allowed(-100111, True)
    assert -100111 not in restarted.get_all_allowed_chats()[1]
    restarted.allow_chat(-100111)
    assert restarted.is_chat_allowed(-100111, True)
    restarted.block_chat(-100111)
    assert -100111 not in restarted.get_all_allowed_chats()[1]


def test_env_user_revocation_agrees_between_bot_and_panel_after_restart(tmp_path):
    s = make_stack(tmp_path, bot_authorized_users={111, 222})
    assert s.api.handle_action(111, "removeauth", {"user_id": 222})["ok"]
    s.context.bot_control = BotControl("dummy", s.db, s.manager, {111, 222})
    assert not s.context.bot_control.is_authorized(222)
    assert 222 not in _authorized_user_ids(s.context)
    assert not s.api.handle_auth({"id": 222})["authorized"]
    assert s.api.handle_action(111, "addauth", {"user_id": 222})["ok"]
    assert s.context.bot_control.is_authorized(222)
    assert s.api.handle_auth({"id": 222})["authorized"]


def test_limited_member_keeps_access_but_cannot_bypass_command_permissions(tmp_path):
    s = make_stack(tmp_path)
    s.bot._save_authorized({111, 222})
    s.db.set_state("bot_granted_cmds_222", "/status")
    assert s.api.handle_auth({"id": 222})["authorized"]
    assert not s.api.handle_action(222, "stop", {})["ok"]
    assert not s.api.run_command("/stop", 222)["ok"]
    assert not s.safety.is_emergency_stopped
    assert s.api.handle_action(111, "stop", {})["ok"]
    assert s.safety.is_emergency_stopped


def test_http_valid_limited_user_gets_permission_error_not_paywall(http_server):
    server, ctx, manager = http_server
    ctx.db.set_state("bot_authorized_users", json.dumps([555000111, 222]))
    ctx.db.set_state("bot_granted_cmds_222", "/status")
    headers = {"X-Telegram-Init-Data": forge_init_data(user={"id": 222})}
    base = f"http://127.0.0.1:{server.server_port}"
    assert _get(base + "/api/state", headers)[0] == 200
    for path, payload in (("/api/action", {"action": "stop"}), ("/api/cmd", {"command": "/stop"}),
                          ("/api/fetch_models", {}), ("/api/test_model", {})):
        _, result = _post(base + path, payload, headers)
        assert result["ok"] is False
        assert "Permission denied" in result["response"]
        assert "paywall" not in result
    assert not manager.commands


def test_fallback_chain_survives_success_and_later_primary_failure():
    provider = OpenAIProvider("dummy", "first,second", "https://example.test/v1/models")
    assert provider.endpoint_url == "https://example.test/v1/chat/completions"
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = b'{"choices":[{"message":{"content":"hello"}}]}'
    with patch("urllib.request.urlopen", return_value=response):
        provider.generate_reply("hi", "system")
    assert provider.model == "first,second"
    with patch("urllib.request.urlopen", side_effect=[RuntimeError("primary failed"), response]) as request:
        assert provider.generate_reply("hi again", "system") == "hello"
    assert request.call_count == 2
    assert provider.active_model == "second"
    assert provider.get_candidate_models() == ["first", "second"]
    with patch("urllib.request.urlopen", return_value=response):
        assert all(ok for _, ok, _ in provider.check_working_models())
    assert provider.model == "first,second"


def test_model_playground_reload_is_atomic_with_manual_selection(tmp_path):
    s = make_stack(tmp_path, ai_enabled=True, ai_provider="custom", ai_model="old-model",
                   ai_api_key="old-key", ai_base_url="https://old.test/v1")
    s.db.set_state("models_manually_set", "1")
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = b'{"choices":[{"message":{"content":"hello"}}]}'
    with patch("urllib.request.urlopen", return_value=response):
        preview = s.api.handle_test_model("test", "new-model", "new.test/v1/models", "new-key")
        assert preview["ok"] and not preview["auto_applied"]
        assert s.db.get_state("ai_api_key") == ""
        assert s.generator.provider.api_key == "old-key"
        applied = s.api.handle_test_model("test", "new-model", "new.test/v1/models", "new-key", auto_apply=True)
    assert applied["auto_applied"]
    assert s.generator.provider.endpoint_url == "https://new.test/v1/chat/completions"
    assert s.generator.provider.api_key == s.db.get_state("ai_api_key") == "new-key"
    assert s.generator.provider.model == s.db.get_state("ai_model") == "new-model"


def test_reaction_toggle_state_matches_engine(tmp_path):
    s = make_stack(tmp_path)
    asyncio.run(s.manager.handle_control_command("/reaction off"))
    assert not s.api.handle_state()["auto_reactions"]
    asyncio.run(s.manager.handle_control_command("/reaction on"))
    assert s.api.handle_state()["auto_reactions"]


def test_owner_username_lookup_uses_existing_resolver(tmp_path):
    from telethon.tl.types import User
    s = make_stack(tmp_path)
    s.client.get_entity.return_value = User(id=222, first_name="Owner", username="new_owner")
    result = s.api.handle_action(111, "addauth", {"user_id": "@new_owner"})
    assert result["ok"]
    assert 222 in _authorized_user_ids(s.context)
    assert s.db.get_chat_metadata(222)["username"] == "new_owner"


@pytest.mark.parametrize("text", ["कल कितने बजे मिलेंगे?", "明天几点见面？", "موعد الاجتماع؟"])
def test_real_non_latin_questions_are_not_thread_endings(text):
    assert not is_thread_ender(text)


def test_custom_frequency_cannot_interrupt_another_group_member(tmp_path):
    s = make_stack(tmp_path)
    s.db.set_state("chat_prompt_-100111", "reply 6 times in 10 sends")
    handlers = []
    s.client.on = lambda _: lambda handler: handlers.append(handler) or handler
    message_filter = SimpleNamespace(my_username="", evaluate_context=lambda _: (True, "Eligible"))
    register_handlers(s.client, 111, message_filter, s.manager)
    s.manager.handle_incoming_eligible_message = AsyncMock()
    s.manager.maybe_send_reaction = AsyncMock(return_value=False)
    reply = SimpleNamespace(sender_id=333, out=False, raw_text="new release",
                            get_sender=AsyncMock(return_value=SimpleNamespace(first_name="Other")))
    event = SimpleNamespace(chat_id=-100111, raw_text="What do you think of the new release?",
                            id=2, sender_id=222, out=False, is_private=False, is_group=True,
                            is_reply=True, message=SimpleNamespace(mentioned=False),
                            get_reply_message=AsyncMock(return_value=reply),
                            get_chat=AsyncMock(return_value=SimpleNamespace(title="Audit Group")),
                            get_sender=AsyncMock(return_value=SimpleNamespace(first_name="Contact")))
    s.client.get_messages.return_value = []
    with patch("random.random", return_value=0):
        asyncio.run(handlers[0](event))
    s.manager.handle_incoming_eligible_message.assert_not_awaited()
    assert s.db.list_actions()[0]["status"] == "skipped"


def test_sensitive_history_is_filtered_for_every_ai_path(tmp_path):
    s = make_stack(tmp_path)
    secret = "Your login code is 24680"
    provider = SimpleNamespace(generate_reply=MagicMock(return_value="safe reply"))
    s.generator.provider = provider
    s.generator.generate("Contact", "hello", [{"sender": "You", "text": secret}])
    s.generator.summarize_chat_history("group", "", secret)
    s.generator.generate_voice_profile("group", secret)
    s.generator.distill_group_context("group", secret)
    for call in provider.generate_reply.call_args_list:
        assert secret not in call.args[0]
        assert "24680" not in call.args[0]
    event = SimpleNamespace(chat_id=123, id=1, raw_text=secret)
    record_own_outgoing_message(s.manager, event, 111)
    assert s.db.count_chat_messages(123) == 0


def test_custom_persona_length_never_leaks_into_another_chat(tmp_path):
    s = make_stack(tmp_path)
    s.generator.prompt_manager.custom_prompt = "reply in 1 word"
    s.generator.provider = SimpleNamespace(generate_reply=MagicMock(return_value="see you there tomorrow"))
    assert s.generator.generate("Contact", "hi") == "see"
    assert s.generator.generate("Contact", "hi", persona_override="reply in 2 words", is_group=True) == "see you"
    assert s.generator.generate("Contact", "hi", persona_override="be casual", is_group=True) == "see you there tomorrow"
    assert s.generator.generate("Contact", "hi", is_group=True) == "see you there tomorrow"
    assert s.generator.generate("Contact", "hi") == "see"


def test_inflight_history_backfill_cannot_restore_cleared_memory(tmp_path):
    s = make_stack(tmp_path)
    s.client.get_entity.return_value = SimpleNamespace(first_name="Contact", username="contact")
    async def old_history(*args, **kwargs):
        s.db.clear_chat_context(123)
        return [SimpleNamespace(id=1, text="old chat", sender_id=222, out=False,
                                get_sender=AsyncMock(return_value=SimpleNamespace(first_name="Contact")))]
    s.client.get_messages.side_effect = old_history
    asyncio.run(s.manager.init_chat_context(123))
    assert s.db.count_chat_messages(123) == 0
    assert s.db.get_chat_summary(123) == ""


def test_per_chat_memory_clear_preserves_other_chat_and_permanent_settings(tmp_path):
    s = make_stack(tmp_path)
    for cid in (123, -100111):
        s.db.set_permanent_context(cid, pinned_text=f"pin {cid}", notes=f"notes {cid}")
        s.db.set_state(f"chat_prompt_{cid}", f"persona {cid}")
        s.db.set_chat_summary(cid, f"old summary {cid}")
        s.db.record_chat_message(cid, 1, 222, "Contact", "old message")
    old_epoch = s.db.get_state("chat_memory_epoch_123")
    assert s.db.clear_chat_context(123) == 1
    assert not s.db.get_chat_summary(123)
    assert s.db.get_chat_summary(-100111) == "old summary -100111"
    assert s.db.get_permanent_context(123) == {"pinned_text": "pin 123", "notes": "notes 123"}
    assert s.db.get_chat_prompt(123) == "persona 123"
    assert not s.db.set_chat_summary(123, "stale in-flight summary", epoch=old_epoch)
    snapshot = json.loads(s.db._get_context_file_path(123).read_text())
    assert snapshot["ai_memory"] == ""
    assert s.db.clear_all_chat_context() == 1
    assert not s.db.get_chat_summary(-100111)


def test_history_initialization_works_and_does_not_reload_cleared_messages(tmp_path):
    s = make_stack(tmp_path)
    message = SimpleNamespace(id=1, message="previous message", out=False, sender_id=222,
                              get_sender=AsyncMock(return_value=SimpleNamespace(first_name="Contact")))
    s.client.get_messages.return_value = [message]
    s.client.get_entity.return_value = SimpleNamespace(first_name="Contact", last_name="", username="contact")
    s.manager.refresh_single_chat_summary = AsyncMock()
    asyncio.run(s.manager.init_chat_context(123))
    assert s.db.get_recent_chat_messages(123)[0]["text"] == "previous message"
    assert s.db.count_chat_messages(-100111) == 0
    s.db.clear_chat_context(123)
    s.client.get_messages.reset_mock()
    asyncio.run(s.manager.init_chat_context(123))
    s.client.get_messages.assert_not_called()
    assert s.db.count_chat_messages(123) == 0


def test_inflight_summary_cannot_restore_cleared_memory(tmp_path, monkeypatch):
    s = make_stack(tmp_path)
    s.db.record_chat_message(123, 1, 222, "Contact", "old message")

    async def run():
        started, resume = asyncio.Event(), asyncio.Event()
        async def delayed_thread(*args, **kwargs):
            started.set()
            await resume.wait()
            return "stale summary"
        monkeypatch.setattr(asyncio, "to_thread", delayed_thread)
        task = asyncio.create_task(s.manager.refresh_single_chat_summary(123, min_new_messages=1))
        await started.wait()
        s.db.clear_chat_context(123)
        resume.set()
        await task
    asyncio.run(run())
    assert s.db.get_chat_summary(123) == ""


@pytest.mark.parametrize("mode", ["draft", "approval", "restricted_auto"])
def test_cli_mode_override_replaces_frozen_configuration(tmp_path, mode):
    from app.main import run_app
    s = make_stack(tmp_path)
    service = SimpleNamespace(run=AsyncMock(), stop=AsyncMock())
    with patch("app.main.load_config", return_value=s.config), \
            patch("app.main.TelegramService", return_value=service) as service_class, \
            patch("app.miniapp_server.MiniAppServer"):
        asyncio.run(run_app(mode_override=mode))
    assert service_class.call_args.kwargs["config"].reply_mode == mode
    assert s.config.reply_mode == "restricted_auto"


@pytest.mark.parametrize("mode", ["draft", "approval", "stopped", "paused", "revoked"])
def test_reactions_and_scheduled_signoff_obey_all_stop_controls(tmp_path, mode, monkeypatch):
    s = make_stack(tmp_path)
    if mode in ("draft", "approval"):
        s.manager.set_mode(mode)
    elif mode == "stopped":
        s.safety.set_emergency_stop(True)
    elif mode == "paused":
        s.safety.set_timed_pause(300)
    else:
        s.privacy.remove_chat(123)
        s.privacy.remove_chat(-100111)
    s.generator.generate_goodnight_signoff = MagicMock(return_value="night everyone")
    async def inline(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    monkeypatch.setattr(asyncio, "to_thread", inline)
    async def run():
        assert not await s.manager.maybe_send_reaction(123, 1, "thanks")
        await s.manager.maybe_send_quiet_hours_goodnight(force=True)
    asyncio.run(run())
    s.client.send_message.assert_not_called()
    assert s.client.await_count == 0


@pytest.mark.parametrize("change", ["stop", "pause", "draft", "remove", "deauthorize"])
def test_stop_controls_are_rechecked_after_typing(tmp_path, clock, change):
    s = make_stack(tmp_path, typing_delay_seconds=2, min_delay_seconds=1, max_delay_seconds=1)
    class Typing:
        async def __aenter__(self):
            if change == "stop": s.safety.set_emergency_stop(True)
            elif change == "pause": s.safety.set_timed_pause(300)
            elif change == "draft": s.manager.set_mode("draft")
            elif change == "remove": s.privacy.remove_chat(-100111)
            else: s.safety.set_auto_authorization(False)
        async def __aexit__(self, *_):
            return False
    s.client.action = MagicMock(return_value=Typing())
    assert not asyncio.run(s.manager._send_reply(-100111, 1, "hello", adaptive_delay=False))
    s.client.send_message.assert_not_called()


@pytest.mark.parametrize("custom", [None, 6.0, 0.0])
def test_every_dm_bubble_obeys_custom_or_default_cooldown(tmp_path, clock, custom):
    s = make_stack(tmp_path)
    s.db.set_state("min_chat_cooldown_seconds", "4")
    s.db.set_state("max_chat_cooldown_seconds", "4")
    if custom is not None:
        result = s.api.handle_action(111, "chat_cooldown", {"chat_id": 123, "min": custom, "max": custom})
        assert result["ok"]
    times = []
    async def send(*args, **kwargs):
        times.append(clock.now)
        return SimpleNamespace(id=len(times))
    s.client.send_message.side_effect = send
    assert asyncio.run(s.manager._send_reply(123, 1, "First thought.\nSecond thought.", adaptive_delay=False))
    expected = 4.0 if custom is None else custom
    assert len(times) == 2
    assert times[1] - times[0] >= expected


def test_updated_cooldown_takes_effect_while_a_reply_is_waiting(tmp_path, clock):
    s = make_stack(tmp_path)
    times = []
    async def send(*args, **kwargs):
        times.append(clock.now)
        return SimpleNamespace(id=len(times))
    s.client.send_message.side_effect = send
    async def run():
        assert await s.manager._send_reply(123, 1, "first", adaptive_delay=False)
        s.safety.set_chat_cooldown(123, 6, 6)
        def update(seconds):
            s.safety.set_chat_cooldown(123, 12, 12)
            clock.on_sleep = lambda seconds: None
        clock.on_sleep = update
        assert await s.manager._send_reply(123, 2, "second", adaptive_delay=False)
    asyncio.run(run())
    assert times[1] - times[0] >= 12


def test_concurrent_chats_share_account_cooldown_and_recheck_minute_cap(tmp_path, clock):
    s = make_stack(tmp_path)
    s.db.set_state("min_chat_cooldown_seconds", "1")
    s.db.set_state("max_chat_cooldown_seconds", "1")
    s.db.set_state("min_global_cooldown_seconds", "6")
    s.db.set_state("max_global_cooldown_seconds", "6")
    s.db.set_state("max_chat_replies_per_minute", "1")
    times = []
    async def send(*args, **kwargs):
        times.append(clock.now)
        return SimpleNamespace(id=len(times))
    s.client.send_message.side_effect = send
    async def run():
        results = await asyncio.gather(s.manager._send_reply(123, 1, "first", adaptive_delay=False),
                                       s.manager._send_reply(-100111, 1, "second", adaptive_delay=False))
        assert results == [True, True]
        assert not await s.manager._send_reply(123, 2, "too many", adaptive_delay=False)
    asyncio.run(run())
    assert times[1] - times[0] >= 6
    assert len(times) == 2


def test_cooldown_reset_returns_to_default_and_survives_restart(tmp_path, clock):
    s = make_stack(tmp_path)
    s.db.set_state("min_chat_cooldown_seconds", "4")
    s.db.set_state("max_chat_cooldown_seconds", "4")
    s.safety.set_chat_cooldown(123, 10, 10)
    s.safety.mark_reply_sent(123)
    restarted = SafetyManager(s.config, s.db)
    assert restarted.cooldown_remaining(123)[0] == 10
    restarted.reset_chat_cooldown(123)
    assert restarted.cooldown_remaining(123)[0] == 4
    assert restarted._get_chat_cooldown_range(-100111) == (4, 4)


@pytest.mark.parametrize("change", ["shorten", "reset"])
def test_queued_reply_uses_live_cooldown_instead_of_original_wait(tmp_path, clock, change):
    s = make_stack(tmp_path)
    s.db.set_state("min_chat_cooldown_seconds", "4")
    s.db.set_state("max_chat_cooldown_seconds", "4")
    s.safety.set_chat_cooldown(123, 60, 60)
    s.safety.mark_reply_sent(123)
    s.manager.refresh_single_chat_summary = AsyncMock()
    def update(seconds):
        if change == "shorten":
            s.safety.set_chat_cooldown(123, 0, 0)
        else:
            s.safety.reset_chat_cooldown(123)
        clock.on_sleep = lambda seconds: None
    clock.on_sleep = update
    asyncio.run(s.manager._schedule_deferred_reply(123, 1, "hello"))
    s.client.send_message.assert_awaited_once()
    elapsed = clock.now - 1000
    assert (1 if change == "shorten" else 4) <= elapsed < 15


@pytest.mark.parametrize("command", ["/baseurl file:///bad", "/setai custom new-key file:///bad new-model"])
def test_invalid_endpoint_does_not_change_runtime_settings(tmp_path, command):
    s = make_stack(tmp_path)
    provider = s.generator.provider
    assert "Invalid API base URL" in asyncio.run(s.manager.handle_control_command(command))
    assert s.db.get_state("ai_base_url") == ""
    assert s.db.get_state("ai_api_key") == ""
    assert s.generator.provider is provider


def test_gemini_generation_uses_live_temperature_and_token_limit(tmp_path):
    s = make_stack(tmp_path, ai_enabled=True, ai_provider="gemini", ai_api_key="test-key")
    s.db.set_state("ai_temperature", "0.2")
    s.db.set_state("ai_max_tokens", "128")
    s.generator.reload_provider()
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = b'{"candidates":[{"content":{"parts":[{"text":"hi"}]}}]}'
    with patch("urllib.request.urlopen", return_value=response) as request:
        assert s.generator.provider.generate_reply("hello", "be brief") == "hi"
    payload = json.loads(request.call_args.args[0].data)
    assert payload["generationConfig"] == {"temperature": 0.2, "maxOutputTokens": 128}


def test_concurrent_approvals_and_retries_send_draft_once(tmp_path, clock):
    s = make_stack(tmp_path)
    approval = s.db.add_approval(-100111, "Group", 1, 222, "hi", "hello")
    async def run():
        results = await asyncio.gather(s.manager.handle_control_command(f"/approve {approval}"),
                                       s.manager.handle_control_command(f"/approve {approval}"))
        assert sum("sent successfully" in result for result in results) == 1
        assert "already being handled" in (await s.manager.handle_control_command(f"/approve {approval}"))
    asyncio.run(run())
    s.client.send_message.assert_awaited_once()
    assert not s.db.list_pending_approvals()


def test_typo_correction_keeps_room_greeting_unthreaded(tmp_path, clock):
    s = make_stack(tmp_path)
    s.db.set_state("typo_correction_enabled", "1")
    s.manager.maybe_inject_typo_correction = MagicMock(return_value=("goood morning guys", ""))
    assert asyncio.run(s.manager._send_reply(-100111, 1, "good morning guys", adaptive_delay=False))
    s.client.send_message.assert_awaited_once()
    assert s.client.send_message.call_args.kwargs["reply_to"] is None
    s.client.edit_message.assert_awaited_once()


def test_access_list_never_waits_on_telegram_profile_lookups(tmp_path):
    s = make_stack(tmp_path)
    s.api._resolve_user_target = MagicMock(side_effect=AssertionError("Read-only lists must use cached metadata"))
    users = s.api.handle_access()["users"]
    assert users[0]["id"] == 111
    s.api._resolve_user_target.assert_not_called()


def test_chat_list_returns_actual_default_cooldown_without_rebuilding_dashboard(tmp_path):
    s = make_stack(tmp_path)
    s.db.set_state("min_chat_cooldown_seconds", "3")
    s.db.set_state("max_chat_cooldown_seconds", "8")
    s.db.set_state("chatty_probability", "0.4")
    s.api.handle_state = MagicMock(side_effect=AssertionError("Chat lists should not rebuild the whole dashboard"))
    result = s.api.handle_chats()
    assert result["chatty_global"] == 0.4
    assert all(chat["cooldown_default_min"] == 3 and chat["cooldown_default_max"] == 8 for chat in result["chats"])


@pytest.mark.parametrize(("text", "expected"), [
    ("hello API and iPhone", "Hello API and iPhone"),
    ("😊 hello NASA", "😊 Hello NASA"),
    ('"hello there"', '"Hello there"'),
    ("123 ready", "123 Ready"),
    ("привет", "Привет"),
    ("नमस्ते", "नमस्ते"),
    ("👍", "👍"),
    ("", ""),
])
def test_message_capitalization_preserves_remaining_case(text, expected):
    assert capitalize_message(text) == expected


def test_each_sent_bubble_and_approval_uses_capitalized_text_in_its_history(tmp_path, clock):
    s = make_stack(tmp_path)
    s.client.send_message.side_effect = [SimpleNamespace(id=1), SimpleNamespace(id=2), SimpleNamespace(id=3)]
    s.db.set_state("max_chat_replies_per_minute", "10")
    s.db.set_state("max_replies_per_minute", "20")
    async def run():
        assert await s.manager._send_reply(123, 1, "hello API\n😊 meet iPhone users", adaptive_delay=False)
        s.manager.set_mode("approval")
        approval = s.db.add_approval(-100111, "Group", 1, 222, "hi", "ready for NASA")
        assert "sent successfully" in await s.manager.handle_control_command(f"/approve {approval}")
    asyncio.run(run())
    assert [call.args[1] for call in s.client.send_message.await_args_list] == ["Hello API", "😊 Meet iPhone users", "Ready for NASA"]
    assert [row["text"] for row in s.db.get_recent_chat_messages(123)] == ["Hello API", "😊 Meet iPhone users"]
    assert s.db.get_recent_chat_messages(-100111)[0]["text"] == "Ready for NASA"
