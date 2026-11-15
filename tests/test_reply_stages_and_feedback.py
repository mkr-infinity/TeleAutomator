"""Exercise context, writing, local final checks, and feedback without live services."""

import asyncio
import json
import sqlite3
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.event_handlers import register_handlers
from app.message_filter import MessageFilter
from app.miniapp_server import MiniAppRequestHandler
from app.storage.database import Database
from tests.test_miniapp import forge_init_data, _get, _post
from tests.test_workflow_regressions import make_stack


def incoming(chat_id=-100111, text="Anyone know when the release ships?", message_id=1):
    return SimpleNamespace(chat_id=chat_id, id=message_id, sender_id=222, out=False, is_group=chat_id < 0,
                           is_private=chat_id > 0, is_channel=False, is_reply=False, raw_text=text,
                           message=SimpleNamespace(mentioned=False, action=None),
                           get_chat=AsyncMock(return_value=SimpleNamespace(title="Development")),
                           get_sender=AsyncMock(return_value=SimpleNamespace(first_name="Alice")))


def test_context_observes_silent_chats_but_never_collects_sensitive_or_unallowed_messages(tmp_path):
    s = make_stack(tmp_path)
    s.db.set_state("group_mention_only", "1")
    handlers = []
    s.client.on = lambda _: lambda handler: handlers.append(handler) or handler
    mf = MessageFilter(111, s.privacy, s.safety, my_username="owner", database=s.db)
    register_handlers(s.client, 111, mf, s.manager)
    s.manager.handle_incoming_eligible_message = AsyncMock()

    async def run():
        await handlers[0](incoming())
        await handlers[0](incoming(text="Your login code is 24680", message_id=2))
        unknown = incoming(chat_id=999, text="This chat is private")
        await handlers[0](unknown)
        await asyncio.wait_for(asyncio.gather(*s.manager.context_agent.pending.values()), timeout=5)
        s.manager.handle_incoming_eligible_message.assert_not_awaited()
        unknown.get_chat.assert_not_awaited()
        assert s.db.count_chat_messages(-100111) == 1
        assert s.db.count_chat_messages(999) == 0
        stored = json.loads((s.db.contexts_dir / "-100111.json").read_text())
        assert stored["recent_messages"][0]["text"] == "Anyone know when the release ships?"
        assert "24680" not in json.dumps(stored)
        await s.manager.context_agent.close()

    asyncio.run(run())


def test_context_summaries_are_batched_coalesced_and_rate_limited(tmp_path):
    s = make_stack(tmp_path)
    for mid in range(1, 9):
        s.db.record_chat_message(-100111, mid, 222, "Alice", f"Release detail {mid}")
    s.generator.summarize_chat_history = MagicMock(return_value="The release is due Friday")

    async def run():
        agent = s.manager.context_agent
        await asyncio.gather(agent.refresh(-100111), agent.refresh(-100111))
        assert s.generator.summarize_chat_history.call_count == 1
        for mid in range(9, 17):
            s.db.record_chat_message(-100111, mid, 222, "Alice", f"New release detail {mid}")
        await agent.refresh(-100111)
        assert s.generator.summarize_chat_history.call_count == 1
        await agent.refresh(-100111, force=True)
        assert s.generator.summarize_chat_history.call_count == 2
        assert s.db.get_chat_summary(-100111) == "The release is due Friday"
        assert s.db.get_chat_summary(123) == ""
        await agent.close()

    asyncio.run(run())


def test_context_file_failures_are_visible_without_losing_database_memory(tmp_path):
    s = make_stack(tmp_path)
    s.db.record_chat_message(123, 1, 222, "Alice", "Release information")
    with patch.object(s.db, "sync_chat_context_file", return_value=False):
        s.manager.context_agent.observe(123)
    assert s.db.count_chat_messages(123) == 1
    assert s.db.list_actions("failed")[0]["action"] == "file_sync"


def test_context_files_keep_updating_while_a_summary_request_is_running(tmp_path):
    s = make_stack(tmp_path)
    for mid in range(1, 9):
        s.db.record_chat_message(-100111, mid, 222, "Alice", f"Release detail {mid}")
    started, release = threading.Event(), threading.Event()

    def summarize(*_args, **_kwargs):
        started.set()
        release.wait(5)
        return "Release context"

    s.generator.summarize_chat_history = MagicMock(side_effect=summarize)

    async def run():
        agent = s.manager.context_agent
        try:
            agent.observe(-100111)
            assert await asyncio.to_thread(started.wait, 3)
            s.db.record_chat_message(-100111, 9, 222, "Alice", "New details while the summary is busy")
            agent.observe(-100111)
            await asyncio.wait_for(asyncio.gather(*agent.pending.values()), timeout=3)
            data = json.loads((s.db.contexts_dir / "-100111.json").read_text())
            assert data["recent_messages"][-1]["text"] == "New details while the summary is busy"
            assert s.generator.summarize_chat_history.call_count == 1
        finally:
            release.set()
            await agent.close()
        assert not agent.pending and not agent.summary_tasks

    asyncio.run(run())


def test_context_summary_jobs_have_a_global_concurrency_bound(tmp_path):
    s = make_stack(tmp_path, allowed_groups={-100111, -100222, -100333})
    for cid in (-100111, -100222, -100333):
        s.db.record_chat_message(cid, 1, 222, "Alice", "Release details")
    started, release, counter_lock = threading.Event(), threading.Event(), threading.Lock()
    calls = []

    def summarize(*_args, **_kwargs):
        with counter_lock:
            calls.append(1)
            if len(calls) == 2:
                started.set()
        release.wait(5)
        return "Release context"

    s.generator.summarize_chat_history = MagicMock(side_effect=summarize)

    async def run():
        tasks = [asyncio.create_task(s.manager.context_agent.refresh(cid, min_new_messages=1)) for cid in (-100111, -100222, -100333)]
        try:
            assert await asyncio.to_thread(started.wait, 3)
            assert len(calls) == 2
        finally:
            release.set()
            await asyncio.gather(*tasks)
            await s.manager.context_agent.close()

    asyncio.run(run())


@pytest.mark.parametrize("change", ["new_topic", "clear_memory"])
def test_reply_is_discarded_if_its_context_changes_during_generation(tmp_path, change):
    s = make_stack(tmp_path)
    s.db.record_chat_message(-100111, 1, 222, "Alice", "When does this release ship?")
    s.manager.sync_pinned_context_from_telegram = AsyncMock(return_value="")

    def generate(**_):
        if change == "new_topic":
            s.db.record_chat_message(-100111, 2, 333, "Bob", "Let's discuss the next meetup instead")
        else:
            s.db.clear_chat_context(-100111)
        return "The release is due Friday"

    s.generator.generate = generate
    asyncio.run(s.manager._process_incoming_message(-100111, "Development", 1, 222, "Alice", "When does this release ship?"))
    s.client.send_message.assert_not_awaited()
    assert s.db.list_actions("skipped")[0]["source"] == "humanizer"


def test_deferred_and_transport_paths_also_reject_stale_context(tmp_path):
    s = make_stack(tmp_path)
    context = s.manager.context_agent.snapshot(-100111)
    s.db.record_chat_message(-100111, 2, 333, "Bob", "New topic")

    async def run():
        await s.manager._schedule_deferred_reply(-100111, 1, "Old reply", context=context)
        assert await s.manager._deliver_message(-100111, "Old reply", context=context) is None
        await s.manager.context_agent.close()

    asyncio.run(run())
    s.client.send_message.assert_not_awaited()


def test_writer_uses_chat_context_then_local_humanizer_with_one_model_call(tmp_path):
    s = make_stack(tmp_path)
    s.db.set_permanent_context(-100111, notes="Discuss release testing")
    s.db.set_permanent_context(123, notes="Private family plans")
    s.db.set_state("chat_voice_profile_-100111", "Short technical replies")
    s.db.set_state("chat_prompt_-100111", "Reply in 2 words in English")
    provider = SimpleNamespace(generate_reply=MagicMock(return_value="Deploy API today"))
    s.generator.provider = provider
    context = s.manager.context_agent.snapshot(-100111)
    with patch.object(s.generator, "humanize_reply", wraps=s.generator.humanize_reply) as humanizer:
        reply = s.generator.generate("Alice", "Which deployment?", context.history, persona_override=context.persona,
                                     permanent_context=context.background, is_group=True)
    assert reply == "Deploy API"
    humanizer.assert_called_once()
    provider.generate_reply.assert_called_once()
    prompt, instructions = provider.generate_reply.call_args.args
    assert "Discuss release testing" in prompt and "Short technical replies" in prompt
    assert "Private family plans" not in prompt
    assert "MANDATORY REPLY POLICY" in instructions


def test_feedback_updates_once_guides_only_its_chat_and_can_be_cleared(tmp_path):
    s = make_stack(tmp_path)
    assert asyncio.run(s.manager._send_reply(123, 1, "Release checks passed", adaptive_delay=False))
    row = s.api.handle_activity()["activity"][0]
    assert row["is_automated"]
    params = {"chat_id": 123, "id": row["message_id"], "value": "helpful"}
    assert s.api.handle_action(111, "feedback", params)["ok"]
    params["value"] = "off_topic"
    assert s.api.handle_action(111, "feedback", params)["ok"]
    ratings = s.db.list_reply_feedback([123])
    assert len(ratings) == 1 and ratings[0]["actor_id"] == 111
    assert s.manager._outgoing_text_reason(123, "Release checks passed.")
    assert "Release checks passed" in s.manager.context_agent.snapshot(123).background
    assert "Release checks passed" not in s.manager.context_agent.snapshot(-100111).background
    assert not s.manager._outgoing_text_reason(-100111, "Release checks passed")
    assert s.api.handle_feedback("off_topic")["counts"]["off_topic"] == 1
    assert s.api.handle_action(111, "feedback", {**params, "value": "clear"})["ok"]
    assert not s.db.list_reply_feedback([123])
    assert not s.manager._outgoing_text_reason(123, "Release checks passed")


def test_feedback_rejects_manual_unknown_unallowed_and_invalid_targets(tmp_path):
    s = make_stack(tmp_path)
    s.db.record_chat_message(123, 1, 111, "Owner", "Manual reply", True)
    for cid, mid, rating in ((123, 1, "helpful"), (123, 999, "helpful"), (999, 1, "helpful"), (123, 1, "arbitrary")):
        assert not s.api.handle_action(111, "feedback", {"chat_id": cid, "id": mid, "value": rating})["ok"]
    assert not s.db.list_reply_feedback([123, 999])


def test_feedback_survives_message_pruning_but_clear_removes_it_and_its_file_copy(tmp_path):
    s = make_stack(tmp_path)
    s.db.record_chat_message(123, 1, None, "Owner", "Old off-topic reply", True, True)
    s.db.set_reply_feedback(123, 1, "off_topic", 111)
    for mid in range(2, 65):
        s.db.record_chat_message(123, mid, 222, "Alice", "New incoming message")
    assert not s.db.has_chat_message(123, 1)
    s.db.set_reply_feedback(123, 1, "unnecessary", 111)
    s.db.sync_chat_context_file(123)
    assert "Old off-topic reply" in (s.db.contexts_dir / "123.json").read_text()
    s.db.clear_chat_context(123)
    assert not s.db.list_reply_feedback([123])
    assert "Old off-topic reply" not in (s.db.contexts_dir / "123.json").read_text()


def test_feedback_is_bounded_updates_edited_messages_and_blocks_older_rejections(tmp_path):
    s = make_stack(tmp_path)
    with s.db._get_connection() as conn:
        conn.executemany("INSERT INTO reply_feedback(chat_id,message_id,rating,reply_text) VALUES(123,?,'off_topic',?)",
                         [(mid, f"Rejected sample {mid}") for mid in range(1, 501)])
    s.db.record_chat_message(123, 777, None, "Owner", "A new reply", True, True)
    s.db.set_reply_feedback(123, 777, "style", 111)
    rows = s.db.list_reply_feedback([123], limit=500)
    assert len(rows) == 500 and not any(row["message_id"] == 1 for row in rows)
    assert s.manager._outgoing_text_reason(123, "Rejected sample 2")
    s.db.record_chat_message(123, 777, None, "Owner", "An edited reply", True, True)
    assert next(row for row in s.db.list_reply_feedback([123], limit=500) if row["message_id"] == 777)["reply_text"] == "An edited reply"


def test_existing_database_migration_retains_manual_and_automated_history(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE chat_messages(id INTEGER PRIMARY KEY,chat_id INTEGER,message_id INTEGER,sender_id INTEGER,sender_name TEXT,text TEXT,is_outgoing INTEGER,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(chat_id,message_id))")
        conn.executemany("INSERT INTO chat_messages(chat_id,message_id,sender_id,sender_name,text,is_outgoing) VALUES(123,?,?, 'Owner',?,1)",
                         [(1, None, "Automated reply"), (2, 111, "Manual reply")])
    db = Database(path)
    db.set_reply_feedback(123, 1, "helpful", 111)
    with pytest.raises(ValueError):
        db.set_reply_feedback(123, 2, "helpful", 111)
    assert db.count_chat_messages(123) == 2


def test_feedback_http_permissions_filters_and_command_path(tmp_path):
    s = make_stack(tmp_path)
    s.db.record_chat_message(123, 777, None, "Owner", "Release checks passed", True, True)
    bound = type("FeedbackHTTP", (MiniAppRequestHandler,), {"api": s.api})
    server = ThreadingHTTPServer(("127.0.0.1", 0), bound)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    headers = {"X-Telegram-Init-Data": forge_init_data(token=s.context.bot_token, user={"id": 111})}
    try:
        assert _get(base + "/api/feedback")[0] == 401
        params = {"chat_id": 123, "id": 777, "value": "off_topic"}
        assert _post(base + "/api/action", {"action": "feedback", "params": params}, headers)[1]["ok"]
        assert _get(base + "/api/activity", headers)[1]["activity"][0]["feedback"] == "off_topic"
        assert _get(base + "/api/feedback?rating=off_topic", headers)[1]["feedback"][0]["message_id"] == 777
        assert _get(base + "/api/feedback?rating=bad", headers)[0] == 400
        assert _post(base + "/api/cmd", {"command": "/feedback 123 777 style"}, headers)[1]["ok"]
        s.bot._save_authorized({111, 222})
        s.db.set_state("bot_granted_cmds_222", "/status")
        limited = {"X-Telegram-Init-Data": forge_init_data(token=s.context.bot_token, user={"id": 222})}
        assert _get(base + "/api/feedback", limited)[0] == 403
        assert not _post(base + "/api/action", {"action": "feedback", "params": params}, limited)[1]["ok"]
        assert s.db.list_reply_feedback([123])[0]["rating"] == "style"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
