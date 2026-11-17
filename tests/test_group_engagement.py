"""Group engagement: open invitations, thread joining, 100% chatty, reactions, and pending-reply tolerance."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.event_handlers import register_handlers
from app.message_filter import MessageFilter
from tests.test_workflow_regressions import make_stack

GROUP = -100111


def plan(s, text, **kwargs):
    kwargs.setdefault("recent_active", 3)
    return s.manager.plan_group_engagement(GROUP, text, "Crypto Builders", **kwargs)


@pytest.mark.parametrize("text", ["hello everyone", "Hi guys", "good morning all", "anyone here", "how does staking work", "what do you all think about this"])
def test_default_chatty_still_answers_messages_for_everyone(tmp_path, text):
    s = make_stack(tmp_path)
    chance, mode, reason = plan(s, text, recent_active=1)  # even in a quiet room
    assert mode == "open" and reason == ""
    assert chance >= s.manager.OPEN_INVITE_MIN_CHANCE


def test_conversation_starter_after_a_quiet_spell_is_an_invitation(tmp_path):
    s = make_stack(tmp_path)
    chance, mode, _ = plan(s, "new wallet update dropped today", idle_before=True)
    assert mode == "open" and chance >= s.manager.OPEN_INVITE_MIN_CHANCE


def test_chatty_zero_means_never_even_for_invitations(tmp_path):
    s = make_stack(tmp_path)
    s.db.set_state("chat_chatty_-100111", "0")
    assert plan(s, "hello everyone")[0] == 0.0


def test_unrelated_statement_is_skipped_at_default_but_not_at_full_chatty(tmp_path):
    s = make_stack(tmp_path)
    assert plan(s, "my cat knocked a glass over")[0] == 0.0
    s.db.set_state("chat_chatty_-100111", "1.0")
    chance, mode, _ = plan(s, "my cat knocked a glass over", recent_active=0)
    assert chance == 1.0 and mode == ""  # no quiet-room reduction at 100%


def test_quiet_room_still_reduces_ordinary_chances_below_full(tmp_path):
    s = make_stack(tmp_path)
    s.db.set_state("chat_chatty_-100111", "0.5")
    s.db.set_permanent_context(GROUP, notes="We discuss staking rewards and validators")
    assert plan(s, "validators changed their staking policy", recent_active=1)[0] == pytest.approx(0.3)


def test_message_tagging_a_specific_member_is_never_joined(tmp_path):
    s = make_stack(tmp_path)
    s.db.set_state("chat_chatty_-100111", "1.0")
    chance, _, reason = plan(s, "@alex can you send the file")
    assert chance == 0.0 and "specific member" in reason


def test_thread_between_others_is_joined_only_when_about_the_group_topics(tmp_path):
    s = make_stack(tmp_path)
    s.db.set_state("chat_chatty_-100111", "1.0")
    s.db.set_permanent_context(GROUP, notes="Daily staking rewards and validator updates")
    chance, mode, _ = plan(s, "validator rewards were lower today", is_reply_to_other=True)
    assert mode == "thread" and chance == 1.0
    chance, mode, reason = plan(s, "lol that movie was great", is_reply_to_other=True)
    assert chance == 0.0 and "unrelated" in reason


def test_prompt_tells_the_model_how_to_join_without_sample_text(tmp_path):
    s = make_stack(tmp_path)
    pm = s.generator.prompt_manager
    open_prompt = pm.build_user_prompt("Sam", "hello everyone", is_group=True, engagement="open")
    assert "open to everyone" in open_prompt and "overrides the general advice that greetings need no reply" in open_prompt
    assert "addresses another participant" not in open_prompt
    thread_prompt = pm.build_user_prompt("Sam", "validator news", is_group=True, engagement="thread")
    assert "between other members" in thread_prompt
    plain = pm.build_user_prompt("Sam", "validator news", is_group=True)
    assert "Group Engagement" not in plain and "addresses another participant" in plain


def build_handler(s):
    handlers = []
    client = AsyncMock()
    client.on = lambda _event: (lambda func: handlers.append(func) or func)
    s.manager.set_telegram_client(client)
    s.privacy.allow_chat(GROUP)
    s.db.set_state("owner_name", "Danish")
    mf = MessageFilter(privacy_manager=s.privacy, safety_manager=s.safety, my_username="danish", my_user_id=111, database=s.db)
    register_handlers(client, 111, mf, s.manager)
    s.manager.handle_incoming_eligible_message = AsyncMock()
    s.manager.maybe_send_reaction = AsyncMock(return_value=False)
    return handlers[0]


def event(text, message_id=300, reply=False):
    ev = MagicMock()
    ev.chat_id, ev.is_group, ev.is_channel, ev.out = GROUP, True, False, False
    ev.sender_id, ev.id, ev.raw_text, ev.is_reply = 9999, message_id, text, reply
    ev.message = MagicMock(mentioned=False, action=None)
    ev.get_chat = AsyncMock(return_value=MagicMock(title="Crypto Builders", username=None))
    ev.get_sender = AsyncMock(return_value=MagicMock(first_name="Sam", username="sam"))
    return ev


def test_handler_forwards_open_invitation_even_when_the_roll_is_unlucky(tmp_path):
    s = make_stack(tmp_path)
    callback = build_handler(s)
    with patch("random.random", return_value=0.55):  # below the 0.6 invitation floor, above the 0.15 default
        asyncio.run(callback(event("hello everyone")))
    s.manager.handle_incoming_eligible_message.assert_awaited_once()
    assert s.manager.handle_incoming_eligible_message.await_args.kwargs["engagement"] == "open"


def test_handler_at_full_chatty_replies_in_words_for_questions_and_mostly_for_statements(tmp_path):
    s = make_stack(tmp_path)
    s.db.set_state("chat_chatty_-100111", "1.0")
    callback = build_handler(s)
    # A question never becomes a reaction-only chime-in, whatever the roll.
    with patch("random.random", return_value=0.0):
        asyncio.run(callback(event("which wallet are you using?", 301)))
    assert s.manager.handle_incoming_eligible_message.await_count == 1  # went to the writer, not a reaction-only exit
    # A plain statement: 10% reaction share at 100%, so a 0.5 roll still answers in words.
    with patch("random.random", side_effect=[0.0, 0.5]):
        asyncio.run(callback(event("so the new release is live now", 302)))
    assert s.manager.handle_incoming_eligible_message.await_count == 2


def test_skips_are_logged_with_a_reason(tmp_path, caplog):
    s = make_stack(tmp_path)
    callback = build_handler(s)
    with caplog.at_level("INFO"):
        asyncio.run(callback(event("@alex did you send it", 303)))
    assert "[GROUP SKIP]" in caplog.text and "specific member" in caplog.text
    s.manager.handle_incoming_eligible_message.assert_not_awaited()
    assert s.db.list_actions("skipped")[0]["detail"].startswith("Message is addressed")


def test_pending_group_reply_survives_a_few_unrelated_messages_but_not_a_new_topic(tmp_path):
    s = make_stack(tmp_path)
    s.db.record_chat_message(GROUP, 1, 222, "Alice", "anyone know when the release ships")
    context = s.manager.context_agent.snapshot(GROUP)
    for number in (2, 3, 4):
        s.db.record_chat_message(GROUP, number, 333, "Bob", f"random chatter {number}")
    assert s.manager.context_agent.is_current(context)
    s.db.record_chat_message(GROUP, 5, 333, "Bob", "more chatter")
    assert not s.manager.context_agent.is_current(context)


def test_failing_summaries_back_off_instead_of_retrying_every_minute(tmp_path):
    s = make_stack(tmp_path)
    s.db.set_permanent_context(GROUP, notes="x")
    for number in range(1, 12):
        s.db.record_chat_message(GROUP, number, 222, "Alice", f"message number {number}")
    s.generator.summarize_chat_history = MagicMock(side_effect=RuntimeError("model down"))
    agent = s.manager.context_agent

    async def run():
        await agent.refresh(GROUP)
        assert s.generator.summarize_chat_history.call_count == 1
        agent.last_attempt[GROUP] = float("-inf")  # the old 60 s gap has passed
        await agent.refresh(GROUP)
        assert s.generator.summarize_chat_history.call_count == 1  # still backing off
        agent.retry_after[GROUP] = 0.0
        await agent.refresh(GROUP)
        assert s.generator.summarize_chat_history.call_count == 2
        assert agent.failures[GROUP] == 2
        await agent.close()

    asyncio.run(run())
