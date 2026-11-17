"""Reply restraint, metadata diagnostics, and preference restore boundaries. No live calls."""

import asyncio
import json
import time
import urllib.error
import urllib.request
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.prompt_manager import outgoing_block_reason
from app.event_handlers import register_handlers
from app.logger import register_secret
from app.message_filter import is_account_addressed
from app.settings_transfer import export_preferences, validate_preferences
from tests.test_miniapp import http_server, forge_init_data, _get, _post
from tests.test_workflow_regressions import make_stack


# Negative test inputs: each string must be blocked; none is an outgoing reply template.
@pytest.mark.parametrize("text", ["Hello @alice", "Thanks ＠alice", "Visit https://example.test", "t.me/alice",
                                  "[Open](tg://user?id=12)", "Email a@example.test", "I’m an AI", "I'm not a bot", "Thanks Alice",
                                  "I'm a large language model", "I am a virtual assistant", "I am human"])
def test_outgoing_names_tags_links_and_identity_are_blocked(text):
    assert outgoing_block_reason(text, ["Alice (to Bob)"])
    assert not outgoing_block_reason("That should work well", ["Alice (to Bob)"])


def test_address_detection_uses_boundaries_and_direct_address():
    assert is_account_addressed("Hey Kaif, can you check this?", owner_name="Kaif")
    assert is_account_addressed("@owner can you check?", username="owner")
    assert not is_account_addressed("@owner_else can you check?", username="owner")
    assert not is_account_addressed("I spoke with Kaif yesterday", owner_name="Kaif")


def test_group_participation_requires_relevance_and_respects_zero(tmp_path):
    s = make_stack(tmp_path)
    handlers = []
    s.client.on = lambda _: lambda handler: handlers.append(handler) or handler
    register_handlers(s.client, 111, SimpleNamespace(my_username="owner", evaluate_context=lambda _: (True, "Eligible")), s.manager)
    s.manager.handle_incoming_eligible_message = AsyncMock()
    s.manager.maybe_send_reaction = AsyncMock(return_value=False)
    s.client.get_messages.return_value = []
    event = SimpleNamespace(chat_id=-100111, id=1, sender_id=222, out=False, is_group=True, is_private=False,
                            is_reply=False, raw_text="Anyone have thoughts on this release?", message=SimpleNamespace(mentioned=False),
                            get_chat=AsyncMock(return_value=SimpleNamespace(title="Development")),
                            get_sender=AsyncMock(return_value=SimpleNamespace(first_name="Alice", last_name="Jones", username="alice_dev")))
    s.db.set_state("chat_chatty_-100111", "0")
    s.db.set_state("chat_prompt_-100111", "reply 10 times in 10 sends")
    with patch("random.random", return_value=0):
        asyncio.run(handlers[0](event))
    s.manager.handle_incoming_eligible_message.assert_not_awaited()
    s.db.set_state("chat_chatty_-100111", "1")
    # Tagging a specific member is never joined, even at 100%.
    event.raw_text = "@somebody what did you think?"
    event.id += 1
    with patch("random.random", return_value=0):
        asyncio.run(handlers[0](event))
    s.manager.handle_incoming_eligible_message.assert_not_awaited()
    # At 100% a hello to everyone and an ordinary statement are both chances to join in.
    for text in ("Good morning everyone", "I have already finished all of my work for today"):
        event.raw_text = text
        event.id += 1
        with patch("random.random", side_effect=[0, 0.5, 0.5, 0.5]):  # chance roll passes, reaction roll says "reply in words"
            asyncio.run(handlers[0](event))
    assert s.manager.handle_incoming_eligible_message.await_count == 2
    s.manager.handle_incoming_eligible_message.reset_mock()
    event.raw_text = "Anyone have thoughts on this release?"
    event.is_reply = True
    event.get_reply_message = AsyncMock(return_value=None)
    with patch("random.random", return_value=0):
        asyncio.run(handlers[0](event))
    s.manager.handle_incoming_eligible_message.assert_not_awaited()
    event.is_reply = False
    event.id += 1
    with patch("random.random", return_value=0):
        asyncio.run(handlers[0](event))
    s.manager.handle_incoming_eligible_message.assert_awaited_once()
    assert s.manager._outgoing_text_reason(-100111, "Ask alice_dev")
    assert s.manager._outgoing_text_reason(-100111, "Jones can help")


def test_intentional_silence_and_identity_questions_never_alert_or_send(tmp_path):
    s = make_stack(tmp_path)
    s.generator.generate = lambda **_: "NONE"
    s.manager._notify_issue_to_saved_messages = AsyncMock()
    for text in ("What time is the meeting?", "Are you a bot?", "Which model are you?"):
        asyncio.run(s.manager._process_incoming_message(123, "Alice", 1, 222, "Alice", text))
    s.client.send_message.assert_not_awaited()
    s.manager._notify_issue_to_saved_messages.assert_not_awaited()
    assert all(row["status"] == "skipped" for row in s.db.list_actions())


def test_transport_guard_also_covers_approved_and_keyword_replies(tmp_path):
    s = make_stack(tmp_path)
    s.db.record_chat_message(123, 1, 222, "Alice", "Question", False)
    for text in ("Thanks Alice", "Hi @alice", "Go to example.test", "I'm an AI"):
        assert not asyncio.run(s.manager._send_reply(123, 1, text, adaptive_delay=False, approved=True))
    s.db.add_keyword_rule("pricing", "Ask Alice")
    s.generator.generate = MagicMock(return_value="Ask Alice")
    asyncio.run(s.manager._process_incoming_message(123, "Alice", 2, 222, "Alice", "pricing"))
    s.client.send_message.assert_not_awaited()
    assert len(s.db.list_actions("blocked")) == 5


def test_action_history_redacts_bounds_and_paginates(tmp_path):
    s = make_stack(tmp_path)
    register_secret("sk-private-example-credential")
    with s.db._get_connection() as conn:
        conn.executemany("INSERT INTO action_history(source,action,status) VALUES ('test','reply','skipped')", [()] * 1099)
    s.db.record_action("test", "provider", "failed", "Key sk-private-example-credential")
    with s.db._get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM action_history").fetchone()[0] == 1000
    first = s.api.handle_history(limit=20)
    second = s.api.handle_history(before=first["next_before"], limit=20)
    assert len(first["events"]) == len(second["events"]) == 20
    assert first["events"][-1]["id"] > second["events"][0]["id"]
    failures = s.api.handle_history(status="failed")["events"]
    assert len(failures) == 1 and "sk-private" not in failures[0]["detail"]
    assert "ai_engine" in first["diagnostics"]
    assert not s.api.handle_history(status="unknown")["ok"]
    with patch.object(s.db, "_get_connection", side_effect=OSError("full")):
        s.db.record_action("test", "reply", "sent")  # Audit failures cannot trigger a duplicate send.


def test_control_history_never_stores_command_arguments(tmp_path):
    s = make_stack(tmp_path)
    asyncio.run(s.manager.handle_control_command("/setprompt private custom persona", audit_source="bot", actor_id=111))
    assert s.api.handle_action(111, "chat_chatty", {"chat_id": -100111, "value": "25"})["ok"]
    rows = s.db.list_actions()
    assert {row["source"] for row in rows} == {"bot", "miniapp"}
    assert "private custom persona" not in json.dumps(rows)
    assert rows[1]["actor_id"] == 111


def test_preferences_roundtrip_preserves_separate_chats_access_and_memory(tmp_path):
    s = make_stack(tmp_path)
    s.db.set_state("ai_api_key", "private-key")
    s.db.set_state("chat_cooldown_min_-100111", "12")
    s.db.set_state("chat_cooldown_max_-100111", "28")
    s.db.set_state("chat_prompt_-100111", "Talk about development")
    s.db.set_permanent_context(-100111, notes="Group notes", pinned_text="Group pin")
    s.db.set_permanent_context(123, notes="Private notes")
    s.db.record_chat_message(123, 1, 222, "Alice", "Existing memory", False)
    s.db.add_keyword_rule("test", "Try again")
    backup = export_preferences(s.context)
    assert "private-key" not in json.dumps(backup)
    validate_preferences(backup, s.db)
    backup["settings"].update(reply_style="formal", owner_name="Owner", min_chat_cooldown_seconds="3", max_chat_cooldown_seconds="9")
    backup["chats"][0]["notes"] = "Updated group notes"
    preview = s.api.handle_settings_import(111, backup)
    assert preview["ok"] and preview["summary"]["chats"] == 2
    assert s.generator.style == "casual" and s.db.get_permanent_context(-100111)["notes"] == "Group notes"
    assert s.api.handle_settings_import(111, backup, preview=False)["ok"]
    assert s.generator.style == "formal" and s.generator.prompt_manager.owner_name == "Owner"
    assert s.db.get_permanent_context(-100111)["notes"] == "Updated group notes"
    assert s.db.get_permanent_context(123)["notes"] == "Private notes"
    assert s.db.get_state("chat_cooldown_min_-100111") == "12.0"
    assert s.safety.min_chat_cooldown == 3 and s.safety.max_chat_cooldown == 9
    assert s.privacy.get_all_allowed_chats() == ({123}, {-100111})
    assert s.db.count_chat_messages(123) == 1
    assert s.db.get_state("ai_api_key") == "private-key"
    assert json.loads((s.db.contexts_dir / "-100111.json").read_text())["notes"] == "Updated group notes"


@pytest.mark.parametrize("change", [
    lambda b: b["settings"].update(ai_api_key="smuggled"),
    lambda b: b["settings"].update(min_chat_cooldown_seconds="100", max_chat_cooldown_seconds="2"),
    lambda b: b["settings"].update(chatty_probability="NaN"),
    lambda b: b["chats"].append({"id": 999, "cooldown_min": "1"}),
    lambda b: b["keyword_rules"].append({"keyword": "broken", "reply": []}),
    lambda b: b.update(version=True),
])
def test_invalid_import_never_partially_changes_preferences(tmp_path, change):
    s = make_stack(tmp_path)
    backup = export_preferences(s.context)
    backup["settings"]["reply_style"] = "formal"
    change(backup)
    assert not s.api.handle_settings_import(111, backup, preview=False)["ok"]
    assert s.db.get_state("reply_style") == "" and s.generator.style == "casual"


def test_restore_cannot_grant_chat_access_and_provider_failure_is_atomic(tmp_path):
    s = make_stack(tmp_path)
    backup = export_preferences(s.context)
    backup["chats"].append({"id": 999, "notes": "Dormant profile"})
    backup["settings"]["reply_style"] = "formal"
    with patch("app.miniapp_server.create_ai_provider", side_effect=ValueError("bad provider")):
        assert not s.api.handle_settings_import(111, backup, preview=False)["ok"]
    assert s.db.get_state("reply_style") == ""
    assert s.api.handle_settings_import(111, backup, preview=False)["ok"]
    assert not s.privacy.is_chat_allowed(999, False)


def test_http_history_and_private_download_expiry(http_server):
    server, ctx, _ = http_server
    base = f"http://127.0.0.1:{server.server_port}"
    headers = {"X-Telegram-Init-Data": forge_init_data()}
    ctx.db.record_action("automation", "reply", "blocked", "Participant name rejected", chat_id=-222)
    assert _get(base + "/api/history?status=blocked", headers)[1]["events"][0]["chat_id"] == -222
    assert _get(base + "/api/history?before=bad", headers)[0] == 400
    assert _get(base + "/api/history")[0] == 401
    exported = _get(base + "/api/settings/export", headers)[1]
    assert exported["ok"] and "initData" not in exported["download_url"]
    download = base + exported["download_url"]
    with urllib.request.urlopen(download) as response:
        backup = json.load(response)
        assert response.headers["Cache-Control"] == "no-store"
        assert "attachment" in response.headers["Content-Disposition"]
    with urllib.request.urlopen(urllib.request.Request(download, method="HEAD")) as response:
        assert not response.read() and int(response.headers["Content-Length"]) > 0
    assert _post(base + "/api/settings/preview", {"backup": backup}, headers)[1]["ok"]
    ctx.db.set_state("bot_authorized_users", json.dumps([555000111, 222]))
    other = {"X-Telegram-Init-Data": forge_init_data(user={"id": 222})}
    for path in ("/api/settings/preview", "/api/settings/import"):
        assert _post(base + path, {"backup": backup}, other)[0] == 403
    assert _get(base + "/api/settings/export", other)[0] == 403
    for token, (_, content, filename) in list(ctx.settings_downloads.items()):
        ctx.settings_downloads[token] = (time.monotonic() - 1, content, filename)
    with pytest.raises(urllib.error.HTTPError) as expired:
        urllib.request.urlopen(download)
    assert expired.value.code == 404
