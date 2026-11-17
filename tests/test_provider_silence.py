"""Provider silence is a successful response, never a reason to try another model."""

import io
import json
import logging
import urllib.error
from unittest.mock import MagicMock, Mock, call

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
    with pytest.raises(RuntimeError, match="reply generation failed|returned empty content"):
        provider.generate_reply("prompt", "instructions")
    assert urlopen.call_count == 2
    kind = "custom" if isinstance(provider, OpenAIProvider) else "gemini"
    assert provider.usage_callback.call_args_list == [
        call(kind, "primary", 11, 2, 13), call(kind, "fallback", 11, 2, 13),
    ]
    if isinstance(provider, OpenAIProvider):
        assert provider.active_model == ""


INCEPTION = "https://api.inceptionlabs.ai/v1"


def mercury(max_tokens, effort="default", base=INCEPTION):
    return OpenAIProvider(api_key="k", model="mercury-3", base_url=base, max_tokens=max_tokens, reasoning_effort=effort)


@pytest.mark.parametrize("configured,effort,expected", [
    (512, "default", 3000), (256, "low", 3000), (2999, "high", 3000), (3000, "default", 3000), (8000, "default", 8000),
    (512, "instant", 512), (100, "instant", 256), (None, "default", None),
])
def test_reasoning_models_never_get_a_token_limit_that_starves_the_answer(configured, effort, expected):
    assert mercury(configured, effort).effective_max_tokens() == expected


def test_other_openai_compatible_endpoints_keep_the_owners_limit():
    assert mercury(512, base="https://api.groq.com/openai/v1").effective_max_tokens() == 512


def test_request_sends_the_raised_limit_and_a_user_agent(monkeypatch):
    provider = mercury(512, "instant")
    captured = []

    def fake_urlopen(req, timeout=0):
        captured.append(req)
        raise urllib.error.URLError("stop")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(Exception):
        provider.generate_reply("hi", "be brief")
    body = json.loads(captured[0].data)
    assert body["max_tokens"] == 512 and body["reasoning_effort"] == "instant"
    assert captured[0].get_header("User-agent").startswith("TeleAutomator")


def test_custom_base_url_without_v1_is_retried_under_v1_and_remembered(monkeypatch):
    provider = OpenAIProvider(api_key="k", model="m", base_url="https://llm.example.com")
    seen = []

    def fake_urlopen(req, timeout=0):
        seen.append(req.full_url)
        if req.full_url == "https://llm.example.com/chat/completions":
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
        reply = MagicMock()
        reply.read.return_value = json.dumps({"choices": [{"message": {"content": "hey there"}}]}).encode()
        reply.__enter__.return_value = reply
        return reply

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert provider.generate_reply("hi", "x") == "hey there"
    assert seen == ["https://llm.example.com/chat/completions", "https://llm.example.com/v1/chat/completions"]
    assert provider.generate_reply("hi", "x") == "hey there"
    assert seen[-1] == "https://llm.example.com/v1/chat/completions" and len(seen) == 3


@pytest.mark.parametrize("typed", ["https://api.example.com/v1/chat/completions", "https://api.example.com/v1/", "api.example.com/v1"])
def test_pasted_endpoint_forms_all_resolve_to_one_chat_endpoint(typed):
    assert OpenAIProvider(api_key="k", model="m", base_url=typed).endpoint_url == "https://api.example.com/v1/chat/completions"


def test_empty_answer_logs_why(monkeypatch, caplog):
    provider = mercury(512)
    reply = MagicMock()
    reply.read.return_value = json.dumps({"choices": [{"message": {"content": None}, "finish_reason": "length"}],
                                          "usage": {"completion_tokens": 3000}}).encode()
    reply.__enter__.return_value = reply
    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: reply)
    with caplog.at_level("WARNING"), pytest.raises(RuntimeError, match="empty content"):
        provider.generate_reply("hi", "x")
    assert "finish_reason=length" in caplog.text and "max_tokens=3000" in caplog.text


@pytest.mark.parametrize("base", ["https://inceptionlabs.example/v1", "https://custom.example/inceptionlabs", "https://openai.com.example/v1", "https://custom.example/nvidia"])
def test_custom_provider_does_not_inherit_vendor_models_or_limits(base):
    provider = OpenAIProvider("fixture", model="custom-model", base_url=base, max_tokens=512)
    assert provider.get_candidate_models() == ["custom-model"]
    assert provider.effective_max_tokens() == 512


@pytest.mark.parametrize("content,working", [("Ready", True), (None, False), ("", False), ("NONE", True)])
def test_model_check_uses_custom_endpoint_fallback_and_rejects_empty_answers(monkeypatch, content, working):
    provider = OpenAIProvider("fixture", model="custom-model", base_url="https://custom.example")
    requests = []

    def request(req, timeout):
        requests.append(req.full_url)
        if req.full_url.endswith(".example/chat/completions"):
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
        reply = MagicMock()
        reply.read.return_value = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
        reply.__enter__.return_value = reply
        return reply

    monkeypatch.setattr("urllib.request.urlopen", request)
    assert provider.check_working_models()[0][1] is working
    assert requests == ["https://custom.example/chat/completions", "https://custom.example/v1/chat/completions"]
    assert provider.endpoint_url == requests[-1]
