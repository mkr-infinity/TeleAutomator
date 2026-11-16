"""When the owner replies by hand, automation stays quiet in that chat for a while, then resumes."""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.event_handlers import record_own_outgoing_message
from tests.test_workflow_regressions import make_stack


def owner_typed(s, minutes_ago, message_id=900):
    s.db.record_chat_message(chat_id=123, message_id=message_id, sender_id=1, sender_name="You",
                             text="I'll handle this", is_outgoing=True)
    with s.db._get_connection() as conn:
        conn.execute("UPDATE chat_messages SET created_at = datetime('now', ?) WHERE message_id = ?",
                     (f"-{minutes_ago} minutes", message_id))


def incoming(s):
    s.generator.provider = SimpleNamespace(generate_reply=MagicMock(return_value="Coming now"))
    asyncio.run(s.manager._process_incoming_message(123, "Sam", 5, 123, "Sam", "where are you", is_mention=True))
    return s.generator.provider.generate_reply


def test_recent_manual_reply_keeps_automation_quiet(tmp_path):
    s = make_stack(tmp_path)
    owner_typed(s, 5)
    model = incoming(s)
    model.assert_not_called()
    s.client.send_message.assert_not_awaited()


def test_automation_resumes_after_the_quiet_window(tmp_path):
    s = make_stack(tmp_path)
    owner_typed(s, 20)
    incoming(s)
    s.client.send_message.assert_awaited_once()


def test_window_is_configurable_and_can_be_disabled(tmp_path):
    s = make_stack(tmp_path)
    owner_typed(s, 5)
    s.db.set_state("owner_active_minutes", "3")
    assert not s.manager.owner_recently_active(123)
    s.db.set_state("owner_active_minutes", "0")
    owner_typed(s, 0, message_id=901)
    assert not s.manager.owner_recently_active(123)


def test_reply_in_flight_is_dropped_when_owner_answers_first(tmp_path):
    s = make_stack(tmp_path)
    context = s.manager.context_agent.snapshot(123, is_mention=True)
    assert s.manager._context_current(context)
    owner_typed(s, 0)
    assert not s.manager._context_current(context)
    assert s.manager._context_current(context, approved=True)  # an explicit approval still goes out


def test_own_automated_message_echo_is_not_a_manual_reply(tmp_path):
    s = make_stack(tmp_path)
    s.manager.expect_own_send(123, "Coming now")
    record_own_outgoing_message(s.manager, SimpleNamespace(chat_id=123, id=901, raw_text="Coming now"), 111)
    assert not s.manager.owner_recently_active(123)
    record_own_outgoing_message(s.manager, SimpleNamespace(chat_id=123, id=902, raw_text="Something I typed"), 111)
    assert s.manager.owner_recently_active(123)


def test_sending_a_reply_never_silences_the_next_one(tmp_path):
    s = make_stack(tmp_path)
    incoming(s)
    sent_text = s.client.send_message.await_args.args[1]
    record_own_outgoing_message(s.manager, SimpleNamespace(chat_id=123, id=777, raw_text=sent_text), 111)
    assert not s.manager.owner_recently_active(123)


def test_reactions_also_pause_while_owner_is_active(tmp_path):
    s = make_stack(tmp_path)
    assert asyncio.run(s.manager.maybe_send_reaction(123, 5, "congrats awesome work")) is True
    owner_typed(s, 1)
    s.manager._next_reaction_time_by_chat.clear()
    s.manager._last_reaction_time = 0.0
    assert asyncio.run(s.manager.maybe_send_reaction(123, 6, "congrats awesome work")) is False
