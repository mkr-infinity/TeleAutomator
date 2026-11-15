"""Regression cases found while auditing PR readiness. No live Telegram/model calls."""

import asyncio
import gzip
import json
import os
import sqlite3
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.prompt_manager import PromptManager
from app.config import load_config
from app.settings_transfer import export_preferences
from tests.test_miniapp import http_server, _get, _post, forge_init_data
from tests.test_workflow_regressions import make_stack


@pytest.mark.parametrize("low,high", [("NaN", "20"), ("1", "Infinity"), (-1, 20), (20, 1), (0, 86401)])
def test_invalid_custom_cooldowns_never_change_saved_values(tmp_path, low, high):
    s = make_stack(tmp_path)
    result = s.api.handle_action(111, "chat_cooldown", {"chat_id": 123, "min": low, "max": high})
    assert not result["ok"]
    assert s.db.get_state("chat_cooldown_min_123") == s.db.get_state("chat_cooldown_max_123") == ""


@pytest.mark.parametrize("command", ["/pause NaN", "/pause 1e309s", "/contextttl inf", "/chatty NaN", "/reactioncooldown NaN 20", "/debounce Infinity", "/temp NaN"])
def test_non_finite_command_values_are_rejected_before_writes(tmp_path, command):
    s = make_stack(tmp_path)
    result = asyncio.run(s.manager.handle_control_command(command))
    assert result.startswith("❌")
    for key in ("pause_until", "context_ttl_hours", "chatty_probability", "reaction_min_cooldown_seconds", "debounce_seconds", "ai_temperature"):
        assert s.db.get_state(key) == ""


@pytest.mark.parametrize("key", ["TYPING_DELAY_SECONDS", "MAX_REPLY_DELAY_SECONDS", "MIN_CHAT_COOLDOWN_SECONDS", "CHATTY_PROBABILITY"])
def test_invalid_environment_numbers_fail_configuration_validation(key):
    with patch.dict(os.environ, {"TG_API_ID": "123", "TG_API_HASH": "fixture-hash-long-enough", key: "Infinity"}, clear=True), patch("app.config.load_dotenv"):
        with pytest.raises(ValueError, match="finite"):
            load_config()


@pytest.mark.parametrize("persona,age", [("My age is 25. Keep replies brief", 25), ("Age: 42", 42), ("I'm 30 years old", 30),
                                         ("Reply like a 22-year-old", None), ("Talk like I'm 22 years old", None), ("Age: 999", None),
                                         ("Age: 1150", None), ("My age is 25ish", None), ("", None)])
def test_only_explicitly_configured_age_is_used(persona, age):
    pm = PromptManager(owner_name="Current Owner", custom_prompt=persona)
    assert pm.known_owner_age() == age
    rule = pm.get_system_instructions()
    assert "Name: Current Owner" in rule
    assert f"Age: {age}" in rule if age is not None else "Age: Unknown; never guess" in rule


def test_missing_age_question_stays_silent_without_a_model_request(tmp_path):
    s = make_stack(tmp_path)
    s.generator.prompt_manager.custom_prompt = "Speak like a 22-year-old"
    s.generator.generate = MagicMock(return_value="I'm 22 years old")
    asyncio.run(s.manager._process_incoming_message(123, "Contact", 1, 222, "Contact", "How old are you?"))
    s.generator.generate.assert_not_called()
    s.client.send_message.assert_not_awaited()


def test_preference_import_can_explicitly_clear_notes_and_pins(tmp_path):
    s = make_stack(tmp_path)
    s.db.set_permanent_context(123, notes="Old notes", pinned_text="Old pin")
    backup = export_preferences(s.context)
    chat = next(chat for chat in backup["chats"] if chat["id"] == 123)
    chat.update(notes="", pinned_text="")
    assert s.api.handle_settings_import(111, backup, preview=False)["ok"]
    assert s.db.get_permanent_context(123) == {"notes": "", "pinned_text": ""}
    stored = json.loads((s.db.contexts_dir / "123.json").read_text())
    assert stored["notes"] == stored["pinned_text"] == ""


def test_chat_list_uses_bounded_database_connections_and_keeps_chat_settings(tmp_path):
    ids = {-(10000 + index) for index in range(100)}
    s = make_stack(tmp_path, allowed_groups=ids)
    s.db.set_state("chat_style_-10000", "formal")
    s.db.set_state("chat_cooldown_min_-10000", "12")
    s.db.set_state("chat_cooldown_max_-10000", "24")
    s.db.set_permanent_context(-10000, notes="Group notes")
    with patch.object(s.db, "_get_connection", wraps=s.db._get_connection) as connections:
        result = s.api.handle_chats()
    assert connections.call_count < 20
    row = next(row for row in result["chats"] if row["id"] == -10000)
    assert row["style"] == "formal" and row["context"] == "Group notes"
    assert row["cooldown_min"] == 12 and row["cooldown_max"] == 24


def test_pending_count_and_reject_all_include_more_than_one_page(tmp_path):
    s = make_stack(tmp_path)
    for index in range(76):
        s.db.add_approval(123, "Contact", index + 1, 222, "Question", "A reply")
    revision = s.db.get_state("state_revision")
    assert s.api.handle_state()["pending_count"] == 76
    assert s.api.handle_pending()["total"] == 76
    assert len(s.api.handle_pending()["pending"]) == 50
    result = asyncio.run(s.manager.handle_control_command("/reject all"))
    assert "76" in result and s.db.count_pending_approvals() == 0
    assert s.db.get_state("state_revision") != revision


def test_legacy_invalid_numbers_cannot_break_chat_json(tmp_path):
    s = make_stack(tmp_path)
    s.db.set_state("chat_cooldown_min_123", "NaN")
    s.db.set_state("chat_cooldown_max_123", "Infinity")
    s.db.set_state("chatty_probability", "NaN")
    json.dumps(s.api.handle_chats(), allow_nan=False)
    json.dumps(s.api.handle_state(), allow_nan=False)


def test_approval_batch_does_not_block_stop_or_start_a_duplicate_batch(tmp_path):
    s = make_stack(tmp_path)
    for index in range(2):
        s.db.add_approval(123, "Contact", index + 1, 222, "Question", "A reply")

    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        async def approve(_draft, **_kwargs):
            started.set()
            await release.wait()
            return True, "Sent"
        s.manager._approve_draft = AsyncMock(side_effect=approve)
        response = await s.manager.handle_control_command("/approve all", actor_id=111)
        assert "background" in response
        await asyncio.wait_for(started.wait(), timeout=2)
        duplicate = await s.manager.handle_control_command("/approve all", actor_id=111)
        assert "already running" in duplicate
        await s.manager.handle_control_command("/stop")
        release.set()
        await s.manager._approval_batch_task
        assert s.manager._approve_draft.await_count == 1

    asyncio.run(run())


def test_revoked_operator_cannot_send_an_approval_waiting_on_cooldown(tmp_path):
    s = make_stack(tmp_path)
    s.bot._save_authorized({111, 222})
    s.db.set_state("bot_granted_cmds_222", "/approve")
    s.safety.can_reply = MagicMock(return_value=(False, "Chat cooldown"))
    s.safety.cooldown_remaining = MagicMock(return_value=(0.05, 0.05))

    async def run():
        task = asyncio.create_task(s.manager._deliver_message(123, "A reply", approved=True, operator_id=222))
        await asyncio.sleep(0.01)
        s.db.set_state("bot_granted_cmds_222", "/status")
        assert await asyncio.wait_for(task, timeout=2) is None

    asyncio.run(run())
    s.client.send_message.assert_not_awaited()


@pytest.mark.parametrize("change", ["incoming", "clear"])
def test_delayed_followup_drops_stale_context(tmp_path, change, monkeypatch):
    s = make_stack(tmp_path)
    s.db.set_state("spontaneous_followup_enabled", "1")
    s.db.record_chat_message(123, 7, None, "Owner", "Yep", True, True)
    def generate(**_):
        if change == "incoming":
            s.db.record_chat_message(123, 8, 222, "Contact", "New topic")
        else:
            s.db.clear_chat_context(123)
        return "One more thing"
    s.generator.generate = generate
    async def inline(function, *args, **kwargs):
        return function(*args, **kwargs)
    monkeypatch.setattr(asyncio, "to_thread", inline)
    asyncio.run(s.manager._schedule_spontaneous_followup(123, "Yep", delay_seconds=0))
    s.client.send_message.assert_not_awaited()


def test_quiet_hours_never_broadcasts_to_inactive_groups(tmp_path):
    s = make_stack(tmp_path, allowed_groups={-100111, -100222})
    s.db.record_reply_event(-100111, time.time())
    s.generator.generate_goodnight_signoff = MagicMock(return_value="Good night")
    s.manager._send_reply = AsyncMock(return_value=True)
    asyncio.run(s.manager.maybe_send_quiet_hours_goodnight(force=True))
    assert [call.args[0] for call in s.manager._send_reply.call_args_list] == [-100111]


def test_live_database_backup_is_private_and_consistent(tmp_path):
    s = make_stack(tmp_path)
    s.db.set_state("example", "Saved setting")
    destination = tmp_path / "snapshots" / "backup.db"
    s.db.backup_to(destination)
    with sqlite3.connect(destination) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT value FROM runtime_state WHERE key='example'").fetchone()[0] == "Saved setting"
    assert destination.stat().st_mode & 0o077 == 0
    s.manager._client = None
    with patch.object(s.db, "backup_to", wraps=s.db.backup_to) as backup:
        assert "backup" in asyncio.run(s.manager.handle_control_command("/backup")).lower()
        backup.assert_called_once()


def test_slow_bot_commands_leave_stop_responsive_and_are_bounded(tmp_path):
    s = make_stack(tmp_path)

    async def run():
        started, release, stopped = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def process(update):
            if update["message"]["text"] == "/stop":
                stopped.set()
                return
            started.set()
            await release.wait()
        s.bot._process_update = AsyncMock(side_effect=process)
        s.bot.send_message = AsyncMock()
        message = {"message": {"text": "/checkmodels", "chat": {"id": 111}}}
        await s.bot._dispatch_update(message)
        await asyncio.wait_for(started.wait(), timeout=2)
        await s.bot._dispatch_update({"message": {"text": "/stop", "chat": {"id": 111}}})
        assert stopped.is_set()
        for _ in range(4):
            await s.bot._dispatch_update(message)
        assert len(s.bot._command_tasks) == 4
        s.bot.send_message.assert_awaited_once()
        await s.bot.stop()
        assert not s.bot._command_tasks

    asyncio.run(run())


def test_http_compression_and_invalid_action_shapes(http_server):
    server, _ctx, _manager = http_server
    base = f"http://127.0.0.1:{server.server_port}"
    original = (Path(__file__).resolve().parent.parent / "miniapp" / "app.js").read_bytes()
    request = urllib.request.Request(base + "/app.js", headers={"Accept-Encoding": "gzip"})
    with urllib.request.urlopen(request) as response:
        body = response.read()
        assert response.headers["Content-Encoding"] == "gzip"
        assert gzip.decompress(body) == original and len(body) < len(original) / 2
        assert response.headers["Vary"] == "Accept-Encoding"
    request = urllib.request.Request(base + "/app.js", headers={"Accept-Encoding": "gzip;q=0"})
    with urllib.request.urlopen(request) as response:
        assert response.headers.get("Content-Encoding") is None and response.read() == original
    headers = {"X-Telegram-Init-Data": forge_init_data()}
    assert _post(base + "/api/action", {"action": "style", "params": ["wrong"]}, headers)[0] == 400
    assert _post(base + "/api/test_model", {"auto_apply": "false"}, headers)[0] == 400
