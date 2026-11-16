"""Delivery guards, live group preferences, and exact approval snapshots."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.test_workflow_regressions import make_stack


def test_reply_retry_rechecks_operator_and_memory(tmp_path):
    s = make_stack(tmp_path)
    context = s.manager.context_agent.snapshot(123, is_mention=True)

    async def failed(*args, **kwargs):
        s.db.clear_chat_context(123)
        raise RuntimeError('reply target missing')

    s.client.send_message.side_effect = failed
    assert asyncio.run(s.manager._deliver_message(123, 'Ready to review', reply_to=1, context=context)) is None
    assert s.client.send_message.await_count == 1


def test_reply_retry_rechecks_revoked_operator(tmp_path):
    s = make_stack(tmp_path)
    s.bot._save_authorized({111, 222})
    s.db.set_state('bot_granted_cmds_222', '/approve')

    async def failed(*args, **kwargs):
        s.db.set_state('bot_granted_cmds_222', '/status')
        raise RuntimeError('reply target missing')

    s.client.send_message.side_effect = failed
    assert asyncio.run(s.manager._deliver_message(123, 'Ready to review', reply_to=1, approved=True, operator_id=222)) is None
    assert s.client.send_message.await_count == 1


def test_group_probability_does_not_parse_dates_and_is_isolated(tmp_path):
    s = make_stack(tmp_path)
    s.db.set_state('chatty_probability', '0.12')
    s.db.set_permanent_context(-100111, notes='Meeting on 6/10; rating 8/10')
    assert s.manager.group_chatty_probability(-100111) == 0.12
    s.db.set_state('chat_prompt_-100111', 'Reply 6 times in 10 messages')
    assert s.manager.group_chatty_probability(-100111) == 0.6
    s.db.set_state('chat_chatty_-100111', '0')
    assert s.manager.group_chatty_probability(-100111) == 0
    assert s.manager.group_chatty_probability(-100222) == 0.12


@pytest.mark.parametrize('value,expected', [('1%', '0.01'), ('0.5%', '0.005'), ('0.5', '0.5')])
def test_chatty_percentage_units(tmp_path, value, expected):
    s = make_stack(tmp_path)
    asyncio.run(s.manager.handle_control_command('/chatty ' + value))
    assert s.db.get_state('chatty_probability') == expected


def test_pending_participation_rechecks_live_preferences(tmp_path):
    s = make_stack(tmp_path)
    context = s.manager.context_agent.snapshot(-100111, is_mention=False)
    s.db.set_state('chat_chatty_-100111', '0')
    assert asyncio.run(s.manager._deliver_message(-100111, 'The release looks ready', context=context)) is None
    s.client.send_message.assert_not_awaited()


def test_approval_memory_clear_during_typing_does_not_send(tmp_path):
    s = make_stack(tmp_path)
    aid = s.db.add_approval(123, 'Test chat', 1, 222, 'Review it', 'Ready for review')

    async def typing(*_):
        s.db.clear_chat_context(123)

    s.manager._type_before_send = typing
    result, _ = asyncio.run(s.manager._approve_draft(aid))
    assert not result
    s.client.send_message.assert_not_awaited()


def test_partial_approval_is_not_requeued(tmp_path):
    s = make_stack(tmp_path)
    s.manager.split_reply_messages = MagicMock(return_value=['First detail', 'Second detail'])
    s.manager._deliver_message = AsyncMock(side_effect=[SimpleNamespace(id=901), None])
    aid = s.db.add_approval(123, 'Test chat', 1, 222, 'Review it', 'First detail\nSecond detail')
    result, response = asyncio.run(s.manager._approve_draft(aid))
    assert not result and 'partly' in response
    with s.db._get_connection() as conn:
        assert conn.execute('SELECT status FROM pending_approvals WHERE id=?', (aid,)).fetchone()[0] == 'failed'
    assert not s.db.list_pending_approvals()


def test_batch_only_claims_confirmed_ids(tmp_path):
    s = make_stack(tmp_path)
    first = s.db.add_approval(123, 'Test', 1, 222, 'A', 'Draft A')
    other = s.db.add_approval(123, 'Test', 2, 222, 'B', 'Draft B')
    s.manager._approve_draft = AsyncMock(return_value=(True, 'sent'))

    async def run():
        await s.manager.handle_control_command(f'/approveall {first}')
        await s.manager._approval_batch_task

    asyncio.run(run())
    s.manager._approve_draft.assert_awaited_once_with(first, actor_id=None)
    assert s.db.get_pending_approval(other)


def test_cleared_pins_preserve_notes(tmp_path):
    s = make_stack(tmp_path)
    s.db.set_permanent_context(-100111, notes='Keep this rule', pinned_text='Expired pin')
    s.client.get_messages.return_value = []
    asyncio.run(s.manager.sync_pinned_context_from_telegram(-100111))
    assert s.db.get_permanent_context(-100111) == {'pinned_text': '', 'notes': 'Keep this rule'}


def test_ignored_history_never_enters_context_or_voice(tmp_path):
    s = make_stack(tmp_path, ignored_users={333})
    ignored = SimpleNamespace(id=1, text='Hidden participant text', message='Hidden participant text', sender_id=333, out=False)
    s.client.get_messages.return_value = [ignored] * 12
    s.generator.generate_voice_profile = MagicMock()
    s.generator.summarize_chat_history = MagicMock(return_value='')
    asyncio.run(s.manager.init_chat_context(-100111))
    assert s.db.count_chat_messages(-100111) == 0
    s.generator.generate_voice_profile.assert_not_called()


def test_model_check_preserves_newer_selection(tmp_path):
    s = make_stack(tmp_path)
    s.db.set_state('ai_api_key', 'test-only-key')
    provider = SimpleNamespace(model='old')

    def check():
        s.db.set_state('ai_model', 'new')
        return [('old', True, 'healthy')]

    provider.check_working_models = check
    s.generator.provider = provider
    result = asyncio.run(s.manager.handle_control_command('/checkmodels'))
    assert 'newer choices' in result
    assert s.db.get_state('ai_model') == 'new'
    assert provider.model == 'old'


def test_sleep_now_creates_immediate_pause_and_resume_wakes(tmp_path):
    s = make_stack(tmp_path)
    s.manager.maybe_send_quiet_hours_goodnight = AsyncMock()
    asyncio.run(s.manager.handle_control_command('/sleep'))
    assert s.safety.get_remaining_pause_seconds() > 0
    asyncio.run(s.manager.handle_control_command('/resume'))
    assert s.safety.get_remaining_pause_seconds() == 0
    assert not s.safety.quiet_hours_enabled


def test_lowered_rate_limit_invalidates_cached_cap(tmp_path):
    s = make_stack(tmp_path)
    s.safety._minute_cap = 100
    s.safety._minute_cap_ts = 999
    asyncio.run(s.manager.handle_control_command('/ratelimit 1'))
    assert s.safety._minute_cap == 1
    assert s.safety._minute_cap_ts == 0
