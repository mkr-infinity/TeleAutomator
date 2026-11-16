"""Provider silence is a successful response, never a reason to try another model."""

import io
import json
import logging
import urllib.error
from unittest.mock import Mock, call

import pytest

from app.ai.provider import GeminiProvider, OpenAIProvider


@pytest.fixture(params=[OpenAIProvider, GeminiProvider], ids=["openai", "gemini"])
def provider(request, monkeypatch):
    instance = request.param(api_key="test-key", model="primary", usage_callback=Mock())
    monkeypatch.setattr(instance, "get_candidate_models", lambda: ["primary", "fallback"])
    return instance


def response(provider, text, usage=True):
    if isinstance(provider, OpenAIProvider):
        body = {"choices": [{"message": {"content": text}}]}
        if usage:
            body["usage"] = {"prompt_tokens": 11, "completion_tokens": 2, "total_tokens": 13}
    else:
        body = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
        if usage:
            body["usageMetadata"] = {
                "promptTokenCount": 11, "candidatesTokenCount": 2, "totalTokenCount": 13,
            }
    return io.BytesIO(json.dumps(body).encode())


def mock_requests(monkeypatch, *results):
    urlopen = Mock(side_effect=results)
    monkeypatch.setattr("app.ai.provider.urllib.request.urlopen", urlopen)
    return urlopen


def assert_usage(provider, model="primary", tokens=(11, 2, 13)):
    kind = "custom" if isinstance(provider, OpenAIProvider) else "gemini"
    provider.usage_callback.assert_called_once_with(kind, model, *tokens)
    if isinstance(provider, OpenAIProvider):
        assert provider.active_model == model


@pytest.mark.parametrize("text", [
    "NONE", "none", "NoNe", " \n NONE\t", "none.", '"NONE"', "'none.'",
    ' \n " None. " \t', "`NONE`", "**NONE**", "__none__", "NONE?", "NONE!",
])
def test_none_is_successful_silence(provider, monkeypatch, caplog, text):
    urlopen = mock_requests(monkeypatch, response(provider, text))
    with caplog.at_level(logging.INFO, logger="app.ai.provider"):
        assert provider.generate_reply("prompt", "instructions") == ""

    assert urlopen.call_count == 1
    assert_usage(provider)
    assert any("intentional silence" in record.message for record in caplog.records)
    assert all(record.levelno < logging.WARNING for record in caplog.records)


@pytest.mark.parametrize("text", [None, "", " \n\t ", '""', "''", "null", "NULL.", '"null"', "undefined", " UNDEFINED. "])
def test_empty_content_uses_fallback(provider, monkeypatch, caplog, text):
    urlopen = mock_requests(monkeypatch, response(provider, text), response(provider, "hello"))
    assert provider.generate_reply("prompt", "instructions") == "hello"
    assert urlopen.call_count == 2
    kind = "custom" if isinstance(provider, OpenAIProvider) else "gemini"
    assert provider.usage_callback.call_args_list == [
        call(kind, "primary", 11, 2, 13), call(kind, "fallback", 11, 2, 13),
    ]
    if isinstance(provider, OpenAIProvider):
        assert provider.active_model == "fallback"
    assert any("malformed empty" in record.message and record.levelno == logging.WARNING
               for record in caplog.records)
    assert not any("intentional silence" in record.message for record in caplog.records)


@pytest.mark.parametrize("failure", ["http", "network", "invalid-json", "json-null", "missing-content"])
def test_failed_or_invalid_response_uses_fallback(provider, monkeypatch, failure):
    failures = {
        "http": urllib.error.HTTPError("https://example.test", 503, "Unavailable", {}, None),
        "network": urllib.error.URLError("offline"),
        "invalid-json": io.BytesIO(b"invalid json"),
        "json-null": io.BytesIO(b"null"),
        "missing-content": io.BytesIO(b"{}"),
    }
    urlopen = mock_requests(monkeypatch, failures[failure], response(provider, "NONE"))
    assert provider.generate_reply("prompt", "instructions") == ""
    assert urlopen.call_count == 2
    assert_usage(provider, "fallback")


@pytest.mark.parametrize("usage", [False, True])
def test_silence_survives_missing_usage_or_callback_failure(provider, monkeypatch, usage):
    provider.usage_callback.side_effect = RuntimeError("usage store unavailable")
    urlopen = mock_requests(monkeypatch, response(provider, "NONE", usage=usage))
    assert provider.generate_reply("prompt", "instructions") == ""
    assert urlopen.call_count == 1
    if usage:
        assert_usage(provider)
    elif isinstance(provider, GeminiProvider):
        assert_usage(provider, tokens=(0, 0, 0))
    else:
        provider.usage_callback.assert_not_called()
        assert provider.active_model == "primary"


@pytest.mark.parametrize("text", ["none of those", "NONE because no reply is needed", '"hello"'])
def test_non_marker_reply_is_preserved(provider, monkeypatch, text):
    urlopen = mock_requests(monkeypatch, response(provider, text))
    assert provider.generate_reply("prompt", "instructions") == text.strip('"')
    assert urlopen.call_count == 1
    assert_usage(provider)


def test_all_empty_responses_still_fail(provider, monkeypatch):
    urlopen = mock_requests(monkeypatch, response(provider, None), response(provider, ""))
    with pytest.raises(RuntimeError, match="reply generation failed"):
        provider.generate_reply("prompt", "instructions")
    assert urlopen.call_count == 2
    kind = "custom" if isinstance(provider, OpenAIProvider) else "gemini"
    assert provider.usage_callback.call_args_list == [
        call(kind, "primary", 11, 2, 13), call(kind, "fallback", 11, 2, 13),
    ]
    if isinstance(provider, OpenAIProvider):
        assert provider.active_model == ""
