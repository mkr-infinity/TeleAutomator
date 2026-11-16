"""Control boundaries and races, with local fakes and no live service calls."""

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.bot_control import authorized_user_ids
from app.miniapp_server import BoundedHTTPServer, MiniAppAPI, MiniAppRequestHandler
from app.settings_transfer import export_preferences
from tests.test_bot_control import _make_bot
from tests.test_miniapp import make_ctx
from tests.test_workflow_regressions import make_stack


def update(text, user=111):
    return {"message": {"text": text, "chat": {"id": user}, "from": {"id": user}}}


@pytest.mark.parametrize("command", ["/testmodels", "/syncpin", "/genvoice", "/exportdb", "/sleep", "/goodnight", "/authlist", "/addauth @user", "/removeauth @user"])
def test_slow_aliases_leave_stop_immediately_dispatchable(tmp_path, command):
    bot, _, _ = _make_bot(tmp_path)

    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        stopped = []

        async def process(event):
            if event["message"]["text"] == "/stop":
                stopped.append(True)
            else:
                started.set()
                await release.wait()

        bot._process_update = process
        await asyncio.wait_for(bot._dispatch_update(update(command)), 0.5)
        await asyncio.wait_for(started.wait(), 0.5)
        await asyncio.wait_for(bot._dispatch_update(update("/stop")), 0.5)
        assert stopped and len(bot._command_tasks) == 1
        release.set()
        await asyncio.gather(*bot._command_tasks)

    asyncio.run(run())


@pytest.mark.parametrize("command,grants,expected_status", [
    ("/start", "/help", False), ("/authlist", "/help", False),
    ("/start", "/start", False), ("/start", "/start,/status", True),
])
def test_start_and_authlist_respect_permissions(tmp_path, command, grants, expected_status):
    bot, manager, db = _make_bot(tmp_path)
    db.set_state("bot_granted_cmds_222", grants)
    bot.send_message = AsyncMock()
    bot.get_chat_name = AsyncMock(return_value="Owner")
    manager.handle_control_command = AsyncMock(return_value="status")
    asyncio.run(bot._process_update(update(command, 222)))
    assert bool(manager.handle_control_command.await_count) is expected_status
    bot.get_chat_name.assert_not_awaited()
    if command == "/start" and grants == "/start":
        assert bot.send_message.await_count == 1
    else:
        assert bot.send_message.await_count >= 1


def test_prefix_does_not_enter_start_bypass(tmp_path):
    bot, manager, db = _make_bot(tmp_path)
    db.set_state("bot_granted_cmds_222", "/start")
    bot.send_message = AsyncMock()
    manager.handle_control_command = AsyncMock()
    asyncio.run(bot._process_update(update("/startanything", 222)))
    manager.handle_control_command.assert_not_awaited()
    assert "Permission denied" in bot.send_message.call_args.args[1]


def test_concurrent_api_access_updates_preserve_all_changes(tmp_path):
    ctx, _ = make_ctx(tmp_path, authorized=(111, 222))
    api = MiniAppAPI(ctx)
    barrier = threading.Barrier(3)
    api._resolve_user_target = lambda _: (None, None, None)

    def change(action, target):
        barrier.wait(timeout=3)
        return api.handle_action(111, action, {"user_id": target})

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(change, "addauth", 333), pool.submit(change, "addauth", 444), pool.submit(change, "removeauth", 222)]
        assert all(f.result(timeout=5)["ok"] for f in futures)
    assert authorized_user_ids(ctx.db) == {111, 333, 444}


@pytest.mark.parametrize("action", ["prompt", "chatprompt", "setcontext"])
def test_action_preserves_user_braces_and_newlines(tmp_path, action):
    ctx, _ = make_ctx(tmp_path)
    text = "Keep {owner_name}\n{literal} and {{nested}}"
    command = MiniAppAPI(ctx).map_action_to_command(action, {"chat_id": 111, "value": text})
    assert command.endswith(text)


def test_approve_all_forwards_selected_ids(tmp_path):
    ctx, _ = make_ctx(tmp_path)
    api = MiniAppAPI(ctx)
    assert api.map_action_to_command("approve_all", {"ids": [4, 2, 4]}) == "/approveall 4,2"
    for ids in ([], [True], [0], [-1], ["4"], "4,2"):
        with pytest.raises(ValueError):
            api.map_action_to_command("approve_all", {"ids": ids})


@pytest.mark.parametrize("action,value", [("setcontext", "x" * 8001), ("setcontext", None), ("setcontext", "bad\x00note"), ("chatstyle", "imaginary")])
def test_invalid_profile_saves_do_not_mutate(tmp_path, action, value):
    ctx, _ = make_ctx(tmp_path)
    result = MiniAppAPI(ctx).handle_action(555000111, action, {"chat_id": 111, "value": value})
    assert not result["ok"]
    assert not ctx.db.get_state("chat_style_111")
    assert not ctx.db.get_permanent_context(111).get("notes")


def test_note_boundary_and_legacy_export_are_lossless(tmp_path):
    s = make_stack(tmp_path)
    assert s.api.handle_action(111, "setcontext", {"chat_id": 123, "value": "n" * 8000})["ok"]
    legacy = "n" * 8001
    s.db.set_permanent_context(123, notes=legacy)
    s.db.set_state("chat_style_123", "legacy-style")
    result = s.api.handle_settings_export(111)
    assert result["ok"]
    token = result["download_url"].split("token=", 1)[1]
    backup = json.loads(s.api.settings_download(token)[0])
    chat = next(chat for chat in backup["chats"] if chat["id"] == 123)
    assert chat["notes"] == legacy and chat["style"] == "legacy-style"
    assert not s.api.handle_settings_import(111, backup)["ok"]


def test_hourly_counts_cover_more_than_recent_list_and_only_automated_allowed(tmp_path):
    ctx, _ = make_ctx(tmp_path)
    with ctx.db._get_connection() as conn:
        conn.executemany(
            "INSERT INTO chat_messages(chat_id,message_id,is_outgoing,is_automated,text,created_at) VALUES(?,?,?,?,'fixture',datetime('now',?))",
            [(111, i, 1, 1, '-1 hour') for i in range(30)] +
            [(111, 31, 1, 0, '-1 hour'), (999, 32, 1, 1, '-1 hour'), (111, 33, 0, 1, '-1 hour'), (111, 34, 1, 1, '-25 hours')],
        )
    result = MiniAppAPI(ctx).handle_activity()
    assert len(result["activity"]) <= 25
    assert sum(row["count"] for row in result["hourly_activity"]) == 30
    assert all(row["hour"].endswith(":00:00Z") for row in result["hourly_activity"])


@pytest.mark.parametrize("ready,legacy_healthy,expected", [(False, True, 503), (True, True, 200), (True, False, 503)])
def test_health_monitor_readiness_and_legacy_status(ready, legacy_healthy, expected):
    ctx = SimpleNamespace(health_monitor=SimpleNamespace(is_healthy=lambda: ready), health_status={"healthy": legacy_healthy})
    handler = object.__new__(MiniAppRequestHandler)
    handler.api = SimpleNamespace(ctx=ctx)
    handler.path = "/api/health"
    handler._json = Mock()
    handler.do_GET()
    assert handler._json.call_args.args[0] == expected


def test_unauthenticated_post_rejects_without_reading_body(tmp_path):
    ctx, _ = make_ctx(tmp_path)
    handler = object.__new__(MiniAppRequestHandler)
    handler.api = MiniAppAPI(ctx)
    handler.path = "/api/action"
    handler.headers = {"Content-Length": "999999"}
    handler.rfile = Mock()
    handler._json = Mock()
    handler._init_user = lambda: None
    handler.do_POST()
    assert handler._json.call_args.args[0] == 401
    handler.rfile.read1.assert_not_called()
    assert handler.close_connection


def test_auth_body_has_total_deadline(tmp_path, monkeypatch):
    ctx, _ = make_ctx(tmp_path)
    handler = object.__new__(MiniAppRequestHandler)
    handler.api = MiniAppAPI(ctx)
    handler.path = "/api/auth"
    handler.headers = {"Content-Length": "10"}
    handler.rfile = Mock()
    handler.rfile.read1.return_value = b"{"
    handler.connection = Mock()
    handler._json = Mock()
    handler._init_user = lambda: None
    times = iter([100, 101, 106])
    monkeypatch.setattr("app.miniapp_server.time.monotonic", lambda: next(times))
    handler.do_POST()
    assert handler._json.call_args.args[0] == 400
    assert handler.rfile.read1.call_count == 1
    handler.connection.settimeout.assert_called_once_with(4)


def test_http_worker_bound_rejects_before_thread_creation():
    server = object.__new__(BoundedHTTPServer)
    server._request_slots = threading.BoundedSemaphore(1)
    server._request_slots.acquire()
    server.shutdown_request = Mock()
    request = object()
    server.process_request(request, ("127.0.0.1", 1))
    server.shutdown_request.assert_called_once_with(request)


@pytest.mark.parametrize("change", ["revision", "provider"])
def test_stale_model_test_does_not_activate_after_settings_change(tmp_path, monkeypatch, change):
    ctx, _ = make_ctx(tmp_path)
    api = MiniAppAPI(ctx)
    replacement = object()
    ctx.db.set_state("ai_provider", "custom")

    class Response:
        def __enter__(self):
            with ctx.db._context_lock:
                if change == "revision":
                    ctx.db.set_state("state_revision", "newer-import")
                else:
                    ctx.generator.provider = replacement
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b'{"choices":[{"message":{"content":"Hello"}}]}'

    monkeypatch.setattr("app.miniapp_server.urllib.request.urlopen", lambda *a, **kw: Response())
    monkeypatch.setattr("app.ai.reply_generator.create_ai_provider", lambda *a, **kw: object())
    original = ctx.generator.provider
    result = api.handle_test_model(model="candidate", base_url="https://example.test/v1", api_key="fake")
    assert result["ok"] and not result["auto_applied"]
    assert not ctx.db.get_state("ai_model")
    assert ctx.generator.provider is (replacement if change == "provider" else original)


def test_import_holds_shared_lock_through_provider_activation(tmp_path, monkeypatch):
    s = make_stack(tmp_path)
    backup = export_preferences(s.context)
    backup["settings"]["reply_style"] = "formal"
    entered = threading.Event()
    contender_started = threading.Event()
    acquired = threading.Event()
    provider = object()

    def create(*args, **kwargs):
        entered.set()
        assert contender_started.wait(2)
        assert not acquired.wait(0.05)
        return provider

    def concurrent_change():
        assert entered.wait(2)
        contender_started.set()
        with s.db._context_lock:
            assert s.generator.provider is provider
            assert s.generator.style == "formal"
            acquired.set()

    monkeypatch.setattr("app.miniapp_server.create_ai_provider", create)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(concurrent_change)
        assert s.api.handle_settings_import(111, backup, preview=False)["ok"]
        future.result(timeout=3)
    assert acquired.is_set()
