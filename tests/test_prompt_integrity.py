"""Regressions for prompt isolation, faithful cleanup, and provider accounting."""

import asyncio
import io
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from app.ai.chat_context import ContextAgent
from app.ai.prompt_manager import PromptManager, VALID_STYLES
from app.ai.provider import GeminiProvider, OpenAIProvider
from app.ai.reply_generator import ReplyGenerator


@pytest.mark.parametrize('text', [
    '42', '2026-11-16 works', '16/11/2026 works', '3.14 is the result',
    'No, keep the backup', 'Re-test after the restart', '-5 degrees today',
    '12:30 works', 'Yes: keep it',
])
def test_cleaning_preserves_meaning(text):
    assert PromptManager(prompt_file=None).clean_reply(text) == text


@pytest.mark.parametrize('text', ['- Keep the backup', '1. Keep the backup', '• Keep the backup'])
def test_cleaning_still_removes_actual_list_markers(text):
    assert PromptManager(prompt_file=None).clean_reply(text) == 'Keep the backup'


def test_length_limit_never_cuts_a_thought():
    pm = PromptManager(prompt_file=None)
    assert pm.clean_reply('Do not delete the backup', custom_limit=3) == ''
    assert pm.clean_reply('Keep it. Do not delete the backup', custom_limit=3) == 'Keep it.'
    assert pm.clean_reply(' '.join(f'word{i}' for i in range(30))) == ''
    assert pm.clean_reply('3.14 is the result and needs review', custom_limit=2) == ''


def test_custom_length_preserves_all_requested_lines():
    pm = PromptManager(prompt_file=None)
    reply = 'First point.\nSecond point.\nThird point.\nFourth point.'
    assert pm.clean_reply(reply, custom_limit=20) == reply


def test_group_profiles_never_inherit_global_age():
    pm = PromptManager(prompt_file=None, custom_prompt='My age is 37.')
    assert pm.known_owner_age() == 37
    for persona in ('', 'Use a formal tone.', 'Talk like a 19-year-old.'):
        assert pm.known_owner_age(persona, is_group=True) is None
        instructions = pm.get_system_instructions(persona_override=persona, is_group=True)
        assert 'Age: Unknown; never guess' in instructions
        assert 'Age: 37' not in instructions
    assert pm.known_owner_age('Age: 29', is_group=True) == 29
    assert 'Age: 29' in pm.get_system_instructions(persona_override='Age: 29', is_group=True)
    assert 'Age: Unknown' in pm.get_default_instructions(is_group=True)
    assert pm.known_owner_age('Reply formally.') is None


def test_selected_history_and_style_reach_provider():
    provider = SimpleNamespace(generate_reply=Mock(return_value='The review is complete.'))
    generator = ReplyGenerator(SimpleNamespace(), provider=provider, style='concise')
    history = [{'sender': 'Contact', 'text': f'Context item {i:02d}'} for i in range(50)]
    assert generator.generate('Contact', 'Review status', history, is_group=True,
                              style_override='formal') == 'The review is complete.'
    prompt, instructions = provider.generate_reply.call_args.args
    for i in range(50):
        assert f'Context item {i:02d}' in prompt
    assert VALID_STYLES['formal'] in prompt and VALID_STYLES['formal'] in instructions
    assert VALID_STYLES['concise'] not in prompt


def test_custom_persona_overrides_global_brevity_in_both_prompts():
    provider = SimpleNamespace(generate_reply=Mock(return_value='The first point.\nThe second point.'))
    generator = ReplyGenerator(SimpleNamespace(), provider=provider, style='concise')
    generator.prompt_manager.custom_prompt = 'My age is 37. Reply in 3 words.'
    result = generator.generate('Contact', 'Explain the decision', is_group=True,
                                persona_override='Use formal detailed paragraphs, maximum 60 words.')
    assert result == 'The first point.\nThe second point.'
    prompt, instructions = provider.generate_reply.call_args.args
    assert 'max ONE short line' not in prompt
    assert VALID_STYLES['concise'] not in prompt + instructions
    assert '60 words maximum' in instructions
    assert '37' not in instructions


@pytest.mark.parametrize('provider_class', [OpenAIProvider, GeminiProvider])
@pytest.mark.parametrize('missing_content', [False, True])
def test_malformed_response_usage_is_counted_before_fallback(monkeypatch, provider_class, missing_content):
    usage = Mock()
    provider = provider_class(api_key='test-key', model='primary,fallback', usage_callback=usage)
    monkeypatch.setattr(provider, 'get_candidate_models', lambda: ['primary', 'fallback'])
    if provider_class is OpenAIProvider:
        body = {'usage': {'prompt_tokens': 11, 'completion_tokens': 2, 'total_tokens': 13}}
        if not missing_content:
            body['choices'] = [{'message': {'content': None}}]
        success = {'choices': [{'message': {'content': 'NONE'}}], 'usage': body['usage']}
        kind = 'custom'
    else:
        body = {'usageMetadata': {'promptTokenCount': 11, 'candidatesTokenCount': 2, 'totalTokenCount': 13}}
        if not missing_content:
            body['candidates'] = [{'content': {'parts': [{'text': None}]}}]
        success = {'candidates': [{'content': {'parts': [{'text': 'NONE'}]}}], 'usageMetadata': body['usageMetadata']}
        kind = 'gemini'
    request = Mock(side_effect=[io.BytesIO(json.dumps(value).encode()) for value in (body, success)])
    monkeypatch.setattr('app.ai.provider.urllib.request.urlopen', request)
    assert provider.generate_reply('prompt', 'instructions') == ''
    assert request.call_count == 2
    assert usage.call_args_list == [call(kind, 'primary', 11, 2, 13), call(kind, 'fallback', 11, 2, 13)]


def test_summary_failure_and_empty_output_reach_context_worker(monkeypatch):
    async def inline_thread(function, *args, **kwargs):
        return function(*args, **kwargs)
    monkeypatch.setattr('app.ai.chat_context.asyncio.to_thread', inline_thread)
    provider = SimpleNamespace(generate_reply=Mock(side_effect=RuntimeError('offline')))
    generator = ReplyGenerator(SimpleNamespace(), provider=provider)
    db = Mock()
    db.get_state.side_effect = lambda key, default='': default
    db.get_chat_message_batch.return_value = ('Release is due Friday', 8)
    db.get_chat_metadata.return_value = {'title': 'Development'}
    db.get_chat_summary.return_value = 'Existing memory'
    agent = ContextAgent(db, SimpleNamespace(is_chat_allowed=lambda *args: True), generator)
    asyncio.run(agent.refresh(-123, force=True))
    db.record_action.assert_called_once_with('context', 'summary', 'failed',
        'Summary update failed; recent messages remain available', chat_id=-123)
    db.set_chat_summary.assert_not_called()
    assert not agent.busy
    db.record_action.reset_mock()
    provider.generate_reply.side_effect = None
    provider.generate_reply.return_value = ''
    asyncio.run(agent.refresh(-123, force=True))
    db.record_action.assert_called_once_with('context', 'summary', 'failed',
        'Summary update failed; recent messages remain available', chat_id=-123)
    db.set_chat_summary.assert_not_called()
    assert provider.generate_reply.call_count == 2


def test_provider_reload_holds_database_lock_through_assignment(monkeypatch):
    lock = threading.RLock()
    generator = ReplyGenerator(SimpleNamespace(), provider=SimpleNamespace())
    generator.db = SimpleNamespace(_context_lock=lock)
    replacement = SimpleNamespace()
    def factory(config, database):
        assert lock._is_owned()
        return replacement
    monkeypatch.setattr('app.ai.reply_generator.create_ai_provider', factory)
    with lock:
        generator.reload_provider()
    assert generator.provider is replacement
