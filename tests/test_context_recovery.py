"""Disk recovery, bounded summaries, and context concurrency without live services."""

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.ai.chat_context import ContextAgent
from app.storage.database import Database


def agent_for(db):
    privacy = SimpleNamespace(is_chat_allowed=lambda *_: True)
    generator = SimpleNamespace(summarize_chat_history=MagicMock(return_value="Recap"))
    return ContextAgent(db, privacy, generator)


def disk_seed(db, cid=123):
    data = dict(notes="Owner notes", pinned_text="Pinned", ai_memory="Older recap",
                prompt="Persona", voice_profile="Voice", style="casual")
    (db.contexts_dir / f"{cid}.json").write_text(json.dumps(data))
    return data


@pytest.mark.parametrize("first", ["sync", "summary", "prompt", "notes"])
def test_disk_only_recovery_preserves_every_field_across_restart(tmp_path, first):
    db = Database(tmp_path / "state.db")
    expected = disk_seed(db)
    {"sync": db.sync_chat_context_file, "summary": db.get_chat_summary,
     "prompt": db.get_chat_prompt, "notes": db.get_permanent_context}[first](123)
    assert db.sync_chat_context_file(123)
    restarted = Database(db.db_path)
    actual = json.loads((db.contexts_dir / "123.json").read_text())
    assert {key: actual[key] for key in expected} == expected
    snapshot = agent_for(restarted).snapshot(123)
    assert snapshot.persona == "Persona"
    assert snapshot.style == "casual"
    assert "Voice" in snapshot.background and "Older recap" in snapshot.background


def test_explicit_empty_fields_override_stale_disk_after_restart(tmp_path):
    db = Database(tmp_path / "state.db")
    disk_seed(db)
    for prefix in ("chat_summary_", "chat_prompt_", "chat_voice_profile_", "chat_style_"):
        db.set_state(prefix + "123", "")
    db.set_permanent_context(123, notes="", pinned_text="")
    disk_seed(db)  # A stale backup must not resurrect deliberate clears.
    restarted = Database(db.db_path)
    assert restarted.sync_chat_context_file(123)
    data = json.loads((db.contexts_dir / "123.json").read_text())
    assert all(data[key] == "" for key in
               ("notes", "pinned_text", "ai_memory", "prompt", "voice_profile", "style"))


def test_delete_survives_failed_unlink_and_restart(tmp_path, monkeypatch):
    db = Database(tmp_path / "state.db")
    disk_seed(db)
    path = db.contexts_dir / "123.json"
    original = type(path).unlink

    def fail_unlink(target, *args, **kwargs):
        if target == path:
            raise PermissionError("mock denied")
        return original(target, *args, **kwargs)

    with monkeypatch.context() as patcher:
        patcher.setattr(type(path), "unlink", fail_unlink)
        assert db.delete_permanent_context(123)
    restarted = Database(db.db_path)
    assert restarted.get_permanent_context(123) == {"notes": "", "pinned_text": ""}
    restarted.sync_chat_context_file(123)
    data = json.loads(path.read_text())
    assert data["notes"] == data["pinned_text"] == ""
    assert data["prompt"] == "Persona" and data["ai_memory"] == "Older recap"


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_sync_serializes_read_through_write_with_mutations(tmp_path, monkeypatch, operation):
    db = Database(tmp_path / "state.db")
    db.set_permanent_context(123, notes="Old", pinned_text="Keep")
    read, release, attempted, finished = (threading.Event() for _ in range(4))
    original = db.get_permanent_context

    def paused_read(cid):
        result = original(cid)
        if threading.current_thread().name.startswith("sync"):
            read.set()
            assert release.wait(3)
        return result

    monkeypatch.setattr(db, "get_permanent_context", paused_read)

    def mutate():
        attempted.set()
        if operation == "update":
            db.set_permanent_context(123, notes="New")
        else:
            db.delete_permanent_context(123)
        finished.set()

    with ThreadPoolExecutor(1, thread_name_prefix="sync") as sync_pool, ThreadPoolExecutor(1) as mutation_pool:
        saving = sync_pool.submit(db.sync_chat_context_file, 123)
        assert read.wait(3)
        changing = mutation_pool.submit(mutate)
        try:
            assert attempted.wait(3)
            assert not finished.wait(0.1), "Mutation escaped the snapshot read/write lock"
        finally:
            release.set()
        assert saving.result(3)
        changing.result(3)
    restarted = Database(db.db_path)
    restarted.sync_chat_context_file(123)
    actual = json.loads((db.contexts_dir / "123.json").read_text())
    assert actual["notes"] == ("New" if operation == "update" else "")
    assert actual["pinned_text"] == ("Keep" if operation == "update" else "")


def test_partial_update_hydrates_notes_before_updating_pins(tmp_path):
    db = Database(tmp_path / "state.db")
    disk_seed(db)
    db.set_permanent_context(123, pinned_text="New pin")
    assert Database(db.db_path).get_permanent_context(123) == {"notes": "Owner notes", "pinned_text": "New pin"}


def test_summary_batches_oldest_rows_and_does_not_skip_messages_arriving_during_call(tmp_path):
    db = Database(tmp_path / "state.db")
    for mid in range(1, 13):
        db.record_chat_message(123, mid, 2, "Contact", f"Detail {mid}")
    agent = agent_for(db)
    payloads = []

    def summarize(_title, _old, raw, **_kwargs):
        payloads.append(raw.splitlines())
        if len(payloads) == 1:
            db.record_chat_message(123, 13, 2, "Contact", "Detail 13")
        return f"Recap {len(payloads)}"

    agent.generator.summarize_chat_history.side_effect = summarize

    async def run():
        await agent.refresh(123, force=True, max_payload=5)
        assert db.get_state("chat_summary_marker_123") == "5"
        await agent.refresh(123, force=True, max_payload=5)
        assert db.get_state("chat_summary_marker_123") == "10"
        await agent.refresh(123, force=True, max_payload=5)
        assert db.get_state("chat_summary_marker_123") == "13"
        await agent.close()

    asyncio.run(run())
    assert [line for batch in payloads for line in batch] == [f"Contact: Detail {i}" for i in range(1, 14)]
    assert Database(db.db_path).get_chat_summary(123) == "Recap 3"


@pytest.mark.parametrize("cid,mention", [(123, False), (-123, True), (-123, False)])
def test_new_incoming_supersedes_snapshot_but_own_bubbles_do_not(tmp_path, cid, mention):
    db = Database(tmp_path / "state.db")
    db.record_chat_message(cid, 1, 2, "Contact", "First topic")
    agent = agent_for(db)
    snapshot = agent.snapshot(cid, is_mention=mention)
    assert snapshot.is_mention == mention
    for mid in (2, 3):
        db.record_chat_message(cid, mid, 1, "Owner", "Own bubble", is_outgoing=True, is_automated=True)
        assert agent.is_current(snapshot)
    db.record_chat_message(cid, 4, 2, "Contact", "New topic")
    if cid > 0:
        assert not agent.is_current(snapshot)  # a private chat: a newer message always supersedes
    else:
        # A busy group keeps talking: incoming chatter alone does not cancel a waiting reply.
        assert agent.is_current(snapshot)
        for mid in (5, 6):
            db.record_chat_message(cid, mid, 3, "Other", "More chatter")
        assert agent.is_current(snapshot)
        db.record_chat_message(cid, 7, 3, "Other", "Even more")
        assert agent.is_current(snapshot)
    assert agent.is_current(agent.snapshot(cid, is_mention=mention))


def test_close_flushes_pending_observation_without_model_call(tmp_path):
    db = Database(tmp_path / "state.db")
    db.record_chat_message(123, 1, 2, "Contact", "Final message")
    agent = agent_for(db)

    async def run():
        agent.observe(123)
        await agent.close()

    asyncio.run(run())
    actual = json.loads((db.contexts_dir / "123.json").read_text())
    assert actual["recent_messages"][-1]["text"] == "Final message"
    agent.generator.summarize_chat_history.assert_not_called()
    assert not agent.pending


def test_concurrent_authorization_changes_merge_and_revoke_seeds_across_instances(tmp_path):
    db = Database(tmp_path / "state.db")
    second = Database(db.db_path)
    barrier = threading.Barrier(2)

    def update(database, **kwargs):
        barrier.wait(3)
        return database.update_authorized_users(seeds={11}, **kwargs)

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(update, db, add={22}), pool.submit(update, second, add={33}, remove={11})]
        for future in futures:
            future.result(3)
    restarted = Database(db.db_path)
    assert restarted.update_authorized_users(seeds={11}) == {22, 33}
    assert json.loads(restarted.get_state("bot_revoked_users")) == [11]
    assert restarted.update_authorized_users(add={11}, seeds={11}) == {11, 22, 33}
    restarted.set_state("bot_granted_cmds_44", "/status")
    assert restarted.update_authorized_users(add={44}, remove={44}) == {11, 22, 33}
    assert restarted.get_state("bot_granted_cmds_44") == "all"


def test_memory_clear_during_summary_prevents_late_result_resurrection(tmp_path):
    db = Database(tmp_path / "state.db")
    disk_seed(db)
    db.record_chat_message(123, 1, 2, "Contact", "Old detail")
    agent = agent_for(db)

    def summarize(*_args, **_kwargs):
        db.clear_chat_context(123)
        return "Late result"

    agent.generator.summarize_chat_history.side_effect = summarize

    async def run():
        await agent.refresh(123, force=True)
        await agent.close()

    asyncio.run(run())
    restarted = Database(db.db_path)
    assert restarted.get_chat_summary(123) == ""
    assert restarted.get_state("chat_summary_marker_123") == "0"
    assert restarted.get_permanent_context(123)["notes"] == "Owner notes"
    assert json.loads((db.contexts_dir / "123.json").read_text())["ai_memory"] == ""


def test_failed_summary_keeps_marker_for_retry(tmp_path):
    db = Database(tmp_path / "state.db")
    db.record_chat_message(123, 1, 2, "Contact", "Outstanding detail")
    agent = agent_for(db)
    agent.generator.summarize_chat_history.side_effect = RuntimeError("mock provider failure")

    async def run():
        await agent.refresh(123, force=True)
        assert db.get_state("chat_summary_marker_123", "0") == "0"
        agent.generator.summarize_chat_history.side_effect = None
        await agent.refresh(123, force=True)
        assert db.get_state("chat_summary_marker_123") == "1"
        await agent.close()

    asyncio.run(run())
    assert db.list_actions("failed")[0]["action"] == "summary"


def test_close_does_not_flush_after_allowlist_revocation(tmp_path):
    db = Database(tmp_path / "state.db")
    db.record_chat_message(123, 1, 2, "Contact", "Private detail")
    agent = agent_for(db)

    async def run():
        agent.observe(123)
        agent.privacy.is_chat_allowed = lambda *_: False
        await agent.close()

    asyncio.run(run())
    assert not (db.contexts_dir / "123.json").exists()
    agent.generator.summarize_chat_history.assert_not_called()
