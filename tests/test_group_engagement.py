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


@pytest.mark.parametrize("text", ["Any update?", "Who knows?", "Is it live?"])
def test_short_open_questions_are_invites_at_default_chatty(tmp_path, text):
    s = make_stack(tmp_path)
    chance, mode, reason = plan(s, text, recent_active=4)
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
    assert chance == 1.0 and mode == "active"  # no quiet-room reduction at 100%


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


def test_thread_relevance_is_delegated_to_the_existing_writer(tmp_path):
    s = make_stack(tmp_path)
    s.db.set_state("chat_chatty_-100111", "1.0")
    s.db.set_permanent_context(GROUP, notes="Daily staking rewards and validator updates")
    chance, mode, _ = plan(s, "validator rewards were lower today", is_reply_to_other=True)
    assert mode == "thread" and chance == 1.0
    chance, mode, reason = plan(s, "lol that movie was great", is_reply_to_other=True)
    assert chance == 1.0 and mode == "thread" and not reason


def test_prompt_tells_the_model_how_to_join_without_sample_text(tmp_path):
    s = make_stack(tmp_path)
    pm = s.generator.prompt_manager
    open_prompt = pm.build_user_prompt("Sam", "hello everyone", is_group=True, engagement="open")
    assert "open to everyone" in open_prompt and "overrides the general advice that greetings need no reply" in open_prompt
    assert "addresses another participant" not in open_prompt
    thread_prompt = pm.build_user_prompt("Sam", "validator news", is_group=True, engagement="thread")
    assert "between other members" in thread_prompt
    assert "ignore other people's threads" not in thread_prompt
    active = pm.build_user_prompt("Sam", "news today", is_group=True, engagement="active")
    assert "full participation" in active
    plain = pm.build_user_prompt("Sam", "validator news", is_group=True)
    assert "Group Engagement:" not in plain and "addresses another participant" in plain


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


def test_failed_reaction_falls_back_to_text_reply(tmp_path):
    s = make_stack(tmp_path)
    s.db.set_state("chat_chatty_-100111", "1.0")
    s.db.record_chat_message(GROUP, 1, 111, "Alex", "validator network discussion one")
    s.db.record_chat_message(GROUP, 2, 222, "Sam", "validator network discussion two")
    callback = build_handler(s)
    s.manager.maybe_send_reaction = AsyncMock(return_value=False)
    with patch("random.random", side_effect=[0.0, 0.05]):  # select the 10% reaction path
        asyncio.run(callback(event("the validator rewards look great", 303)))
    s.manager.maybe_send_reaction.assert_awaited_once()
    s.manager.handle_incoming_eligible_message.assert_awaited_once()


def test_short_group_question_cannot_be_consumed_by_reaction_only_path(tmp_path):
    s = make_stack(tmp_path)
    s.db.set_state("chat_chatty_-100111", "1.0")
    callback = build_handler(s)
    s.manager.maybe_send_reaction = AsyncMock(return_value=True)
    with patch("random.random", side_effect=[0.0, 0.5]):
        asyncio.run(callback(event("Anyone?", 304)))
    s.manager.handle_incoming_eligible_message.assert_awaited_once()
    s.manager.maybe_send_reaction.assert_not_awaited()


def test_skips_are_logged_with_a_reason(tmp_path, caplog):
    s = make_stack(tmp_path)
    callback = build_handler(s)
    with caplog.at_level("INFO"):
        asyncio.run(callback(event("@alex did you send it", 303)))
    assert caplog.text.count("[GROUP SKIP]") == 1
    assert "chat -100111" in caplog.text and "specific member" in caplog.text
    assert "@alex did you send it" not in caplog.text
    s.manager.handle_incoming_eligible_message.assert_not_awaited()
    assert s.db.list_actions("skipped")[0]["detail"].startswith("Message is addressed")


def test_later_group_skip_is_logged_from_action_history_without_message_text(tmp_path, caplog):
    s = make_stack(tmp_path)
    s.manager.owner_recently_active = lambda _: True
    sensitive_detail = "private words from this group message"
    with caplog.at_level("INFO"):
        asyncio.run(s.manager._process_incoming_message(
            GROUP, "Crypto Builders", 304, 222, "Member", sensitive_detail))
    assert caplog.text.count("[GROUP SKIP]") == 1
    assert "chat -100111" in caplog.text and "Owner replied by hand recently" in caplog.text
    assert sensitive_detail not in caplog.text


def test_pending_group_reply_survives_chatter_but_not_memory_clear(tmp_path):
    s = make_stack(tmp_path)
    s.db.record_chat_message(GROUP, 1, 222, "Alice", "anyone know when the release ships")
    context = s.manager.context_agent.snapshot(GROUP)
    for number in (2, 3, 4):
        s.db.record_chat_message(GROUP, number, 333, "Bob", f"random chatter {number}")
    assert s.manager.context_agent.is_current(context)
    s.db.record_chat_message(GROUP, 5, 333, "Bob", "more chatter")
    assert s.manager.context_agent.is_current(context)
    s.db.clear_chat_context(GROUP)
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
        s.db.set_chat_summary_retry_state(GROUP, '{"failures":1,"retry_after":0}')
        await agent.refresh(GROUP)
        assert s.generator.summarize_chat_history.call_count == 2
        assert agent.failures[GROUP] == 2
        await agent.close()

    asyncio.run(run())


@pytest.mark.parametrize("change", ["owner", "revoke", "clear", "lower_chatty", "mention_only"])
def test_pending_group_reply_keeps_final_authorization_guards(tmp_path, change):
    s = make_stack(tmp_path)
    s.db.set_state("chat_chatty_-100111", "1")
    context = s.manager.context_agent.snapshot(GROUP)
    for number in range(1, 12):
        s.db.record_chat_message(GROUP, number, 222, "Member", "More conversation")
    assert s.manager._context_current(context)
    if change == "owner":
        s.manager.owner_recently_active = lambda _: True
    elif change == "revoke":
        s.privacy.is_chat_allowed = lambda *_: False
    elif change == "clear":
        s.db.clear_chat_context(GROUP)
    elif change == "lower_chatty":
        s.db.set_state("chat_chatty_-100111", "0.5")
    else:
        s.db.set_state("group_mention_only", "1")
    assert not s.manager._context_current(context)


def test_other_group_send_does_not_cancel_pending_reply(tmp_path):
    s = make_stack(tmp_path)

    async def run():
        release = asyncio.Event()
        pending = asyncio.create_task(release.wait())
        s.manager._pending_deferred_replies[GROUP] = pending
        await s.manager._send_reply(GROUP, 0, "A separate message", adaptive_delay=False)
        assert not pending.done()
        release.set()
        await pending
        await s.manager.close()

    asyncio.run(run())


def test_pending_group_reply_sends_before_later_messages_and_uses_current_context(tmp_path):
    s = make_stack(tmp_path)
    s.db.set_state("chat_chatty_-100111", "1")
    queued_context = s.manager.context_agent.snapshot(GROUP)
    release_pending = asyncio.Event()
    generated = []
    original_send = s.manager._send_reply
    send_order = []

    async def send_with_order(chat_id, message_id, text, **kwargs):
        send_order.append(text)
        kwargs["adaptive_delay"] = False
        return await original_send(chat_id, message_id, text, **kwargs)

    s.manager._send_reply = send_with_order

    async def pending_delivery():
        await release_pending.wait()
        await original_send(GROUP, 90, "Queued group reply", adaptive_delay=False, context=queued_context)
        send_order.append("Queued group reply")
        s.manager._pending_deferred_replies.pop(GROUP, None)

    def write_reply(**kwargs):
        generated.append((kwargs["incoming_text"], [row["text"] for row in kwargs["conversation_history"]]))
        return f"A useful thought about {kwargs['incoming_text']}"

    s.generator.generate = MagicMock(side_effect=write_reply)

    async def run():
        pending = asyncio.create_task(pending_delivery())
        s.manager._pending_deferred_replies[GROUP] = pending
        await asyncio.sleep(0)
        s.db.record_chat_message(GROUP, 1, 222, "Member", "First newer group message")
        s.db.record_chat_message(GROUP, 2, 333, "Another", "Second newer group message")
        first = asyncio.create_task(s.manager._process_incoming_message(
            GROUP, "Crypto Builders", 1, 222, "Member", "First newer group message"))
        second = asyncio.create_task(s.manager._process_incoming_message(
            GROUP, "Crypto Builders", 2, 333, "Another", "Second newer group message"))
        await asyncio.sleep(0.05)
        assert not pending.cancelled()
        assert generated == []
        release_pending.set()
        await asyncio.gather(pending, first, second)

    asyncio.run(run())
    assert send_order[0] == "Queued group reply"
    assert [item[0] for item in generated] == ["First newer group message", "Second newer group message"]
    assert all("First newer group message" in history and "Second newer group message" in history
               for _, history in generated)


def test_summary_backoff_schedule_caps_and_resets_after_success(tmp_path):
    s = make_stack(tmp_path)
    s.db.record_chat_message(GROUP, 1, 222, "Member", "Release details")
    agent = s.manager.context_agent
    s.generator.summarize_chat_history = MagicMock(side_effect=RuntimeError("offline"))

    async def run():
        with patch("app.ai.chat_context.time", SimpleNamespace(monotonic=lambda: 10000, time=lambda: 50000)):
            for delay in (300, 900, 3600, 3600):
                await agent.refresh(GROUP, force=True)
                assert agent.retry_after[GROUP] == 50000 + delay
            s.generator.summarize_chat_history.side_effect = None
            s.generator.summarize_chat_history.return_value = "Release details"
            await agent.refresh(GROUP, force=True)
            assert GROUP not in agent.failures and GROUP not in agent.retry_after
            assert s.db.get_state(f"chat_summary_retry_{GROUP}") == ""
        await agent.close()

    asyncio.run(run())


def test_summary_backoff_survives_context_agent_restart(tmp_path):
    s = make_stack(tmp_path)
    for number in range(1, 10):
        s.db.record_chat_message(GROUP, number, 222, "Alice", f"message number {number}")
    s.generator.summarize_chat_history = MagicMock(side_effect=RuntimeError("model down"))
    first = s.manager.context_agent

    async def run():
        with patch("app.ai.chat_context.time", SimpleNamespace(monotonic=lambda: 10000, time=lambda: 50000)):
            original_revision = s.db.get_state("state_revision")
            await first.refresh(GROUP, force=True)
            assert first.failures[GROUP] == 1
            assert s.db.get_state("state_revision") == original_revision
            saved = s.db.get_state(f"chat_summary_retry_{GROUP}")
            assert '"retry_after":50300.0' in saved

            from app.ai.chat_context import ContextAgent
            from app.storage.database import Database
            restarted_db = Database(s.db.db_path)
            revision = restarted_db.get_state("state_revision")
            restarted = ContextAgent(restarted_db, s.privacy, s.generator)
            await restarted.refresh(GROUP)
            s.generator.summarize_chat_history.assert_called_once()
            assert restarted.failures[GROUP] == 1
            assert restarted.retry_after[GROUP] == 50300

            with patch("app.ai.chat_context.time", SimpleNamespace(monotonic=lambda: 10001, time=lambda: 50301)):
                s.generator.summarize_chat_history.side_effect = None
                s.generator.summarize_chat_history.return_value = "Release details"
                await restarted.refresh(GROUP)
            assert s.generator.summarize_chat_history.call_count == 2
            assert restarted_db.get_state(f"chat_summary_retry_{GROUP}") == ""
            assert restarted_db.get_state("state_revision") == revision
            await restarted.close()
        await first.close()

    asyncio.run(run())


@pytest.mark.parametrize("base,effort,expected", [("https://api.inceptionlabs.ai/v1", "default", 3000), ("https://api.inceptionlabs.ai/v1", "instant", 512), ("https://custom.example", "default", 512)])
def test_miniapp_playground_obeys_provider_limits_and_url_fallback(tmp_path, monkeypatch, base, effort, expected):
    import json
    import urllib.error
    from app.ai.provider import OpenAIProvider
    s = make_stack(tmp_path)
    s.generator.provider = OpenAIProvider("fixture", model="selected", base_url=base, max_tokens=512, reasoning_effort=effort)
    s.db.set_state("ai_reasoning_effort", effort)
    requests = []

    def request(req, timeout):
        requests.append(req)
        if req.full_url == "https://custom.example/chat/completions":
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
        reply = MagicMock()
        reply.read.return_value = json.dumps({"choices": [{"message": {"content": "Ready"}}]}).encode()
        reply.__enter__.return_value = reply
        return reply

    monkeypatch.setattr("urllib.request.urlopen", request)
    result = s.api.handle_test_model(model="selected", base_url=base, api_key="fixture")
    assert result["ok"]
    payload = json.loads(requests[-1].data)
    assert payload["max_tokens"] == expected
    if effort == "instant":
        assert payload["reasoning_effort"] == "instant"
    if base == "https://custom.example":
        assert requests[-1].full_url == base + "/v1/chat/completions"


@pytest.mark.parametrize("incoming", ["The payout shrank again", "aaj kam mila kyun", "आज इतना कम क्यों मिला", "That movie was great"])
def test_thread_writer_gets_context_across_languages_and_can_choose_silence(tmp_path, incoming):
    s = make_stack(tmp_path)
    s.db.set_state("chat_chatty_-100111", "1")
    s.db.set_permanent_context(GROUP, notes="Daily staking rewards and validator updates")
    s.db.record_chat_message(GROUP, 1, 222, "Member", "Staking rewards fell this week")
    chance, mode, reason = plan(s, incoming, is_reply_to_other=True)
    assert chance == 1 and mode == "thread" and not reason
    provider = SimpleNamespace(generate_reply=MagicMock(return_value=""))
    s.generator.provider = provider
    s.manager.sync_pinned_context_from_telegram = AsyncMock(return_value="")
    asyncio.run(s.manager._process_incoming_message(GROUP, "Crypto Builders", 2, 333, "Member", incoming, engagement=mode))
    provider.generate_reply.assert_called_once()
    prompt, instructions = provider.generate_reply.call_args.args
    assert incoming in prompt and "Staking rewards fell" in prompt
    assert "Daily staking rewards" in prompt and "Crypto Builders" in prompt
    assert "Use NONE for unrelated threads" in prompt
    assert "paraphrases, Hindi and Hinglish" in prompt
    assert "English Only" in prompt
    s.client.send_message.assert_not_awaited()


def test_duplicate_suppression_logs_no_conversation_text(tmp_path, caplog):
    s = make_stack(tmp_path)
    secret_text = "Private conversation fixture"
    s.manager._recent_replies_history[GROUP] = [secret_text]
    with caplog.at_level("WARNING"):
        assert s.manager._prevent_duplicate_reply(GROUP, secret_text) == ""
    assert "Suppressed duplicate" in caplog.text
    assert secret_text not in caplog.text


def test_stitching_logs_counts_without_conversation_text(tmp_path, clock, caplog):
    s = make_stack(tmp_path)
    secret_text = "Private burst fixture"
    s.manager._debounce_buffers[GROUP] = [dict(message_id=i, sender_name="Member", sender_id=222,
                                             chat_title="Group", text=secret_text) for i in (1, 2)]
    s.manager._process_incoming_message = AsyncMock()
    with caplog.at_level("INFO"):
        asyncio.run(s.manager._debounce_worker(GROUP, 0))
    assert "Stitched 2" in caplog.text
    assert secret_text not in caplog.text
    s.manager._process_incoming_message.assert_awaited_once()
