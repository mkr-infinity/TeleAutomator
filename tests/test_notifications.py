"""Operator notices: model issues, quiet-hours flips, the Mini App change log and new payload fields."""

import asyncio
import datetime
import io
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.ai.provider import AIProvider, OpenAIProvider
from app.ai.reply_generator import ReplyGenerator
from app.bot_control import BotControl
from app.config import AppConfig
from app.logger import register_secret
from app.miniapp_server import MiniAppAPI, MiniAppRequestHandler
from app.notifications import (QUIET_HOURS_STATE_KEY, check_quiet_hours_transition, format_change,
                               model_error_callback, notify_authorized, report_model_issue)
from app.safety_manager import SafetyManager
from app.settings_transfer import export_preferences
from app.storage.database import Database
from tests.test_bot_control import _make_bot
from tests.test_miniapp import make_ctx
from tests.test_workflow_regressions import make_stack

SECRET = "unit-test-secret-QX7w9Z2kLm"


def bot_calls(sent, attempted=None, fail_for=()):
    async def fake_call(method, payload):
        if method == "sendMessage":
            if attempted is not None:
                attempted.append(payload["chat_id"])
            if payload["chat_id"] in fail_for:
                raise OSError("Forbidden: bot was blocked by the user")
            sent.append((payload["chat_id"], payload["text"]))
            return {"ok": True}
        return {"ok": True, "result": {}}
    return patch.object(BotControl, "_call", new=AsyncMock(side_effect=fake_call))


# ------------------------------------------------------------------ delivery

def test_send_alert_all_reaches_authorized_users_and_main_owner(tmp_path):
    bot, _mgr, db = _make_bot(tmp_path, seed="111,222")
    db.update_authorized_users(add=(333, 444), seeds=bot.seed_user_ids)
    db.update_authorized_users(remove=(222,), seeds=bot.seed_user_ids)
    db.set_state("main_owner_id", "999")  # a main owner outside the stored list still gets notices
    sent, attempted = [], []
    with bot_calls(sent, attempted, fail_for={333}):
        assert asyncio.run(bot.send_alert_all("notice")) is True
    assert [uid for uid, _ in sent] == [111, 444, 999]
    assert 222 not in attempted and 333 in attempted
    with bot_calls([], fail_for={111, 333, 444, 999}):
        assert asyncio.run(bot.send_alert_all("notice")) is False


def test_notify_authorized_uses_fallback_without_bot_and_never_raises():
    manager = SimpleNamespace(bot_control=None, _send_control_alert_unlocked=AsyncMock(return_value=True))
    assert asyncio.run(notify_authorized(manager, "hello")) is True
    manager._send_control_alert_unlocked.assert_awaited_once_with("hello")
    broken = SimpleNamespace(bot_control=SimpleNamespace(send_alert_all=AsyncMock(side_effect=OSError("offline"))))
    assert asyncio.run(notify_authorized(broken, "hello")) is False


# --------------------------------------------------------------- model issues

def test_model_issue_is_throttled_persisted_and_redacted(tmp_path):
    register_secret(SECRET)
    bot, mgr, db = _make_bot(tmp_path, seed="111,222")
    provider = OpenAIProvider(api_key=SECRET, model="model-a,model-b", base_url="https://example.test/v1")
    provider.active_model = "model-a"
    mgr.generator.provider = provider
    sent = []
    with bot_calls(sent):
        error = RuntimeError(f"401 Unauthorized for key {SECRET} " + "x" * 1000)
        assert asyncio.run(report_model_issue(mgr, "chat summary", error)) is True
        assert asyncio.run(report_model_issue(mgr, "chat summary", RuntimeError("again"))) is False
        restarted = SimpleNamespace(db=db, generator=mgr.generator, bot_control=bot)
        assert asyncio.run(report_model_issue(restarted, "chat summary", RuntimeError("after restart"))) is False
        assert asyncio.run(report_model_issue(mgr, "chat summary", TimeoutError("slow"))) is True
        assert asyncio.run(report_model_issue(mgr, "voice profile", RuntimeError("other task"))) is True
    assert [uid for uid, _ in sent] == [111, 222] * 3
    text = sent[0][1]
    for part in ("chat summary", "OpenAIProvider", "model-a,model-b", "last working", "RuntimeError", "IST"):
        assert part in text
    assert all(SECRET not in body for _, body in sent) and "[REDACTED]" in text
    error_line = next(line for line in text.splitlines() if line.startswith("• Error"))
    assert len(error_line) < 330

    db.set_state("model_issue_last_chat summary:RuntimeError", str(time.time() - 601))
    sent.clear()
    with bot_calls(sent):
        assert asyncio.run(report_model_issue(mgr, "chat summary", RuntimeError("later"))) is True
    assert len(sent) == 2


def test_model_error_callback_crosses_threads_and_tolerates_closed_loop(tmp_path):
    _bot, mgr, _db = _make_bot(tmp_path, seed="111")
    sent = []

    async def run():
        callback = model_error_callback(asyncio.get_running_loop(), mgr)
        await asyncio.to_thread(callback, "pinned messages", ConnectionError("offline"))
        for _ in range(5):
            await asyncio.sleep(0)
        await asyncio.gather(*mgr._background_tasks)

    with bot_calls(sent):
        asyncio.run(run())
    assert len(sent) == 1 and "pinned messages" in sent[0][1]
    closed = asyncio.new_event_loop()
    closed.close()
    model_error_callback(closed, mgr)("reply", RuntimeError("late"))  # must not raise


class FailingProvider(AIProvider):
    model = "broken-model"

    def __init__(self, error):
        self.error = error

    def generate_reply(self, prompt, system_instructions):
        raise self.error


def make_generator(provider):
    generator = ReplyGenerator(AppConfig(api_id=1, api_hash="fake"), provider=provider)
    calls = []
    generator.on_model_error = lambda task, exc: calls.append((task, exc))
    return generator, calls


def test_model_error_callback_names_each_task_and_keeps_results():
    error = ConnectionError("provider down")
    generator, calls = make_generator(FailingProvider(error))
    with pytest.raises(RuntimeError, match="AI generation failed"):
        generator.generate("Friend", "hello")
    with pytest.raises(ConnectionError):
        generator.summarize_chat_history("Group", "", "new messages")
    assert generator.generate_voice_profile("Group", "messages") == ""
    assert generator.distill_group_context("Group", "Pinned rules") == "Pinned rules"
    with pytest.raises(ConnectionError):
        generator.generate_goodnight_signoff()
    assert calls == [(task, error) for task in ("reply", "chat summary", "voice profile", "pinned messages", "goodnight")]


def test_broken_callback_cannot_change_generation_behaviour():
    generator, _ = make_generator(FailingProvider(ConnectionError("provider down")))
    generator.on_model_error = Mock(side_effect=ValueError("callback bug"))
    with pytest.raises(RuntimeError, match="provider down"):
        generator.generate("Friend", "hello")
    with pytest.raises(ConnectionError):
        generator.summarize_chat_history("Group", "", "new messages")
    assert generator.on_model_error.call_count == 2


def test_success_and_intentional_silence_skip_callback():
    class Provider(AIProvider):
        model = "ok-model"

        def __init__(self):
            self.replies = iter([" Recap text ", ""])

        def generate_reply(self, prompt, system_instructions):
            return next(self.replies)

    generator, calls = make_generator(Provider())
    assert generator.summarize_chat_history("Group", "", "new messages") == "Recap text"
    assert generator.summarize_chat_history("Group", "", "new messages") == ""
    assert calls == []


def test_goodnight_signoff_uses_group_rules_not_the_global_dm_persona():
    class Recorder(AIProvider):
        model = "m"

        def __init__(self):
            self.instructions = []

        def generate_reply(self, prompt, system_instructions):
            self.instructions.append(system_instructions)
            return "Night all"

    provider = Recorder()
    generator = ReplyGenerator(AppConfig(api_id=1, api_hash="fake"), provider=provider)
    generator.prompt_manager.custom_prompt = "Talk like a pirate captain in DMs. Max 3 words."
    assert generator.generate_goodnight_signoff()
    assert "pirate" not in provider.instructions[0]
    assert "pirate" in generator.prompt_manager.get_system_instructions()  # DMs keep the persona


# ---------------------------------------------------------------- quiet hours

def quiet_manager(tmp_path, send=None):
    config = AppConfig(api_id=1, api_hash="fake", quiet_hours_enabled=True, quiet_hours_start="02:00", quiet_hours_end="08:00")
    db = Database(tmp_path / "quiet.db")
    safety = SafetyManager(config, db)
    clock = {"now": datetime.time(1, 0)}
    real = safety.is_in_quiet_hours
    safety.is_in_quiet_hours = lambda now_time=None: real(now_time=clock["now"])
    send = send or AsyncMock(return_value=True)
    return SimpleNamespace(db=db, safety=safety, bot_control=SimpleNamespace(send_alert_all=send)), clock, send


def check(manager):
    return asyncio.run(check_quiet_hours_transition(manager))


def test_quiet_hours_announce_each_natural_flip_once(tmp_path):
    manager, clock, send = quiet_manager(tmp_path)
    assert check(manager) is False and check(manager) is False  # first run baselines silently
    clock["now"] = datetime.time(2, 30)
    assert check(manager) is True
    assert send.await_args.args[0] == "🌙 Quiet hours started. Replies are paused until 08:00 IST."
    assert check(manager) is False
    restarted = SimpleNamespace(db=manager.db, safety=manager.safety, bot_control=manager.bot_control)
    assert check(restarted) is False  # restart in the middle of quiet hours
    clock["now"] = datetime.time(8, 1)
    assert check(manager) is True
    assert send.await_args.args[0] == "☀️ Quiet hours ended. Replies are active again."
    assert check(manager) is False
    assert send.await_count == 2


def test_quiet_hours_schedule_edits_rebaseline_silently(tmp_path):
    manager, clock, send = quiet_manager(tmp_path)
    check(manager)
    clock["now"] = datetime.time(9, 30)
    manager.safety.set_quiet_hours(True, "09:00", "10:00")  # the edit itself starts quiet hours
    assert check(manager) is False
    manager.safety.set_quiet_hours(False)
    assert check(manager) is False
    manager.safety.set_quiet_hours(True)
    assert check(manager) is False
    assert not send.await_count
    clock["now"] = datetime.time(10, 30)
    manager.safety.set_emergency_stop(True)
    assert check(manager) is True
    assert "still held: Emergency stop active" in send.await_args.args[0]


def test_quiet_hours_state_is_saved_before_a_failed_send(tmp_path):
    manager, clock, send = quiet_manager(tmp_path, AsyncMock(side_effect=OSError("offline")))
    check(manager)
    clock["now"] = datetime.time(3, 0)
    assert check(manager) is False and check(manager) is False
    assert send.await_count == 1 and manager.db.get_state(QUIET_HOURS_STATE_KEY) == "1|02:00|08:00|1"


# -------------------------------------------------------------- change log

@pytest.fixture()
def loop_thread():
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    yield loop
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    loop.close()


def spy_announcements(api):
    futures, announce = [], api.announce_change

    def spy(*args, **kwargs):
        futures.append(announce(*args, **kwargs))
        return futures[-1]
    api.announce_change = spy
    return futures


def change_api(tmp_path, loop):
    ctx, reply_mgr = make_ctx(tmp_path)
    ctx.loop = loop
    reply_mgr._send_control_alert_unlocked = AsyncMock(return_value=True)
    reply_mgr.bot_control = SimpleNamespace(send_alert_all=AsyncMock(return_value=True))
    api = MiniAppAPI(ctx)
    return api, reply_mgr.bot_control.send_alert_all, spy_announcements(api)


def sent_texts(send, futures):
    for future in futures:
        if future is not None:
            assert future.result(timeout=5) is True
    return [call.args[0] for call in send.await_args_list]


def test_change_log_reports_successful_actions_only(tmp_path, loop_thread):
    api, send, futures = change_api(tmp_path, loop_thread)
    assert api.handle_action(555000111, "pause", {"minutes": 15}, actor_name="Kaif")["ok"]
    assert not api.handle_action(555000111, "chatstyle", {"chat_id": 111, "value": "imaginary"}, actor_name="Kaif")["ok"]
    assert not api.handle_action(555000111, "no_such_action", {}, actor_name="Kaif")["ok"]
    assert api.handle_action(555000111, "safemode", {}, actor_name="Kaif")["ok"]
    assert api.handle_action(555000111, "backup", {}, actor_name="Kaif")["ok"]
    texts = sent_texts(send, futures)
    assert len(texts) == 1
    for part in ("Mini App change", "`pause`", "`Kaif (555000111)`", "OK /pause 15", "IST"):
        assert part in texts[0]


def test_change_log_skips_double_taps(tmp_path, loop_thread):
    api, send, futures = change_api(tmp_path, loop_thread)
    for value in ("40", "40", "50"):
        api.handle_action(555000111, "chat_chatty", {"chat_id": -222, "value": value}, actor_name="Kaif")
    api._recent_changes = {key: stamp - 11 for key, stamp in api._recent_changes.items()}
    api.handle_action(555000111, "chat_chatty", {"chat_id": -222, "value": "40"}, actor_name="Kaif")
    texts = sent_texts(send, futures)
    assert futures[1] is None and len(texts) == 3
    assert "`chat chatty · chat -222`" in texts[0]


def test_change_log_needs_an_open_loop_and_a_control_channel(tmp_path, loop_thread):
    api, send, futures = change_api(tmp_path, loop_thread)
    api.ctx.loop = None
    assert api.handle_action(555000111, "pause", {"minutes": 5})["ok"]
    closed = asyncio.new_event_loop()
    closed.close()
    api.ctx.loop = closed
    assert api.announce_change(1, "x", "label", "result") is None
    api.ctx.loop = loop_thread
    del api.ctx.reply_manager._send_control_alert_unlocked
    assert api.announce_change(1, "x", "label", "result") is None
    assert futures == [None, None, None] and not send.await_count


def test_console_change_log_covers_edits_and_controls_not_views(tmp_path, loop_thread):
    api, send, futures = change_api(tmp_path, loop_thread)
    for command in ("/status", "/chatty", "/chatty 30", "/stop", "/syncpins"):
        assert api.run_command(command, 555000111, actor_name="Kaif")["ok"]
    assert not api.run_command("/stop", 777000222, actor_name="Stranger")["ok"]
    whats = [text.split("• What: ")[1].splitlines()[0] for text in sent_texts(send, futures)]
    assert whats == ["`console /chatty`", "`console /stop`", "`console /syncpins`"]


def test_change_log_reaches_authorized_users_through_the_bot(tmp_path, loop_thread):
    s = make_stack(tmp_path)
    s.context.loop = loop_thread
    s.manager.bot_control = s.bot
    s.db.update_authorized_users(add=(222,), seeds=s.bot.seed_user_ids)
    futures, sent = spy_announcements(s.api), []
    with bot_calls(sent):
        assert s.api.handle_action(111, "stop", {}, actor_name="Owner")["ok"]
        assert futures[0].result(timeout=5) is True
    assert sorted(uid for uid, _ in sent) == [111, 222]
    assert "`stop`" in sent[0][1] and "`Owner (111)`" in sent[0][1]


def test_settings_import_announces_after_releasing_the_shared_lock(tmp_path):
    s = make_stack(tmp_path)
    backup = export_preferences(s.context)
    lock_free = []

    def announce(*args):
        def probe():
            acquired = s.db._context_lock.acquire(timeout=1)
            lock_free.append(acquired)
            if acquired:
                s.db._context_lock.release()
        thread = threading.Thread(target=probe)
        thread.start()
        thread.join()

    s.api.announce_change = Mock(side_effect=announce)
    assert s.api.handle_settings_import(111, backup, preview=True)["ok"]
    s.api.announce_change.assert_not_called()
    assert s.api.handle_settings_import(111, backup, preview=False, actor_name="Owner")["ok"]
    assert s.api.announce_change.call_args.args[1:3] == ("Owner", "preferences imported")
    assert lock_free == [True]


def test_format_change_redacts_and_caps_the_result():
    register_secret(SECRET)
    text = format_change(555000111, "Kaif", "apikey", f"Key {SECRET} saved " + "y" * 500)
    assert SECRET not in text and "[REDACTED]" in text
    assert "`Kaif (555000111)`" in text and "`apikey`" in text and "IST" in text
    assert len(text.split("• Result: ")[1]) <= 300
    assert "`555000111`" in format_change(555000111, "", "pause", "ok")


# ------------------------------------------------------------------ HTTP layer

def post(api, path, body, user):
    raw = json.dumps(body).encode()
    handler = object.__new__(MiniAppRequestHandler)
    handler.api, handler.path = api, path
    handler.headers = {"Content-Length": str(len(raw))}
    handler.rfile = io.BytesIO(raw)
    handler.connection = Mock()
    handler._json = Mock()
    handler._init_user = lambda: user
    handler.do_POST()
    return handler._json.call_args.args


@pytest.mark.parametrize("user,expected", [
    ({"id": 555000111, "first_name": "Kaif", "username": "kaif_dev"}, "Kaif"),
    ({"id": 555000111, "username": "kaif_dev"}, "@kaif_dev"),
    ({"id": 555000111}, "555000111"),
])
def test_do_post_passes_actor_name_from_init_data(tmp_path, user, expected):
    ctx, _ = make_ctx(tmp_path)
    api = MiniAppAPI(ctx)
    api.handle_action = Mock(return_value={"ok": True})
    api.run_command = Mock(return_value={"ok": True})
    api.handle_settings_import = Mock(return_value={"ok": True})
    assert post(api, "/api/action", {"action": "pause", "params": {}}, user)[0] == 200
    assert api.handle_action.call_args.kwargs["actor_name"] == expected
    assert post(api, "/api/cmd", {"command": "/status"}, user)[0] == 200
    assert api.run_command.call_args.kwargs["actor_name"] == expected
    assert post(api, "/api/settings/import", {"backup": {}}, user)[0] == 200
    assert api.handle_settings_import.call_args.kwargs["actor_name"] == expected


@pytest.mark.parametrize("applied", [True, False])
def test_model_test_logs_only_auto_applied_rotations(tmp_path, applied):
    ctx, _ = make_ctx(tmp_path)
    api = MiniAppAPI(ctx)
    api.handle_test_model = Mock(return_value={"ok": True, "auto_applied": applied, "active_model": "m1,m2"})
    api.announce_change = Mock()
    assert post(api, "/api/test_model", {"message": "hi"}, {"id": 555000111, "first_name": "Kaif"})[0] == 200
    assert api.announce_change.called is applied
    if applied:
        args = api.announce_change.call_args.args
        assert args[:2] == (555000111, "Kaif") and "m1,m2" in args[3]


# ------------------------------------------------------------------- payloads

def test_state_reports_the_latest_context_job(tmp_path):
    ctx, _ = make_ctx(tmp_path)
    api = MiniAppAPI(ctx)
    assert api.handle_state()["pipeline"]["last_context"] is None
    ctx.db.record_action("context", "summary", "failed", "Summary update failed", chat_id=-222)
    ctx.db.record_action("context", "summary", "success", "Chat memory updated", chat_id=-222)
    ctx.db.record_action("miniapp", "pause", "success", "Action completed")
    pipeline = api.handle_state()["pipeline"]
    assert pipeline["context_jobs"] == 0
    last = pipeline["last_context"]
    assert set(last) == {"status", "detail", "created_at"}
    assert (last["status"], last["detail"]) == ("success", "Chat memory updated") and last["created_at"]


def test_chats_report_chatty_rate_source_and_fractional_cooldowns(tmp_path):
    ctx, reply_mgr = make_ctx(tmp_path)
    api = MiniAppAPI(ctx)
    ctx.db.set_state("chatty_probability", "0.2")

    def chat(cid):
        return next(c for c in api.handle_chats()["chats"] if c["id"] == cid)

    assert (chat(-222)["chatty_effective"], chat(-222)["chatty_source"]) == (0.2, "global")
    ctx.db.set_state("chat_chatty_-222", "0.4")
    assert (chat(-222)["chatty_effective"], chat(-222)["chatty_source"]) == (0.4, "chat")
    ctx.db.set_state("chat_chatty_-222", "")
    reply_mgr.group_chatty_probability = lambda cid: 0.35
    assert chat(-222)["chatty_source"] == "global"  # no number in the prompt or notes: no rate to parse
    ctx.db.set_state("chat_prompt_-222", "Reply 35% of the time")
    assert (chat(-222)["chatty_effective"], chat(-222)["chatty_source"]) == (0.35, "prompt")
    reply_mgr.group_chatty_probability = lambda cid: 0.2
    assert chat(-222)["chatty_source"] == "global"
    ctx.db.set_state("chat_chatty_-222", "abc")
    assert (chat(-222)["chatty_effective"], chat(-222)["chatty_source"]) == (0.0, "chat")  # matches the runtime parse

    assert api.handle_action(555000111, "chat_cooldown", {"chat_id": 111, "min": 0.5, "max": 2})["response"].endswith("0.5s - 2s.")
    assert chat(111)["cooldown_str"] == "0.5s - 2s"


def test_chats_use_the_runtime_rate_written_in_a_chat_prompt(tmp_path):
    s = make_stack(tmp_path)
    s.db.set_state("chat_prompt_-100111", "Reply 40% of the time in this group")
    group = next(c for c in s.api.handle_chats()["chats"] if c["id"] == -100111)
    assert (group["chatty_effective"], group["chatty_source"]) == (0.4, "prompt")
