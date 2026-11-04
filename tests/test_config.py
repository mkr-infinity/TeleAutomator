"""Tests for configuration parsing and validation."""

import os
import pytest
from app.config import load_config, _parse_id_set


def test_parse_id_set():
    assert _parse_id_set("") == set()
    assert _parse_id_set("123, 456, -789") == {123, 456, -789}
    with pytest.raises(ValueError, match="Invalid Telegram ID"):
        _parse_id_set("123, abc")


def test_missing_credentials(monkeypatch):
    monkeypatch.setenv("TG_API_ID", "")
    monkeypatch.setenv("TG_API_HASH", "")
    with pytest.raises(ValueError, match="Missing required configuration: TG_API_ID"):
        load_config()


def test_invalid_api_id(monkeypatch):
    monkeypatch.setenv("TG_API_ID", "not_a_number")
    monkeypatch.setenv("TG_API_HASH", "0123456789abcdef0123456789abcdef")
    with pytest.raises(ValueError, match="Invalid TG_API_ID"):
        load_config()


def test_valid_config(monkeypatch):
    monkeypatch.setenv("TG_API_ID", "1234567")
    monkeypatch.setenv("TG_API_HASH", "abcdef0123456789abcdef0123456789")
    monkeypatch.setenv("TG_SESSION_MODE", "local")
    monkeypatch.setenv("ALLOWED_PRIVATE_CHATS", "111,222")
    monkeypatch.setenv("REPLY_MODE", "draft")

    cfg = load_config()
    assert cfg.api_id == 1234567
    assert cfg.session_mode == "local"
    assert cfg.allowed_private_chats == {111, 222}
    assert cfg.reply_mode == "draft"

    # Verify secret is not exposed in repr
    rep = repr(cfg)
    assert "abcdef0123456789abcdef0123456789" not in rep


def test_string_session_missing_secret(monkeypatch):
    monkeypatch.setenv("TG_API_ID", "1234567")
    monkeypatch.setenv("TG_API_HASH", "abcdef0123456789abcdef0123456789")
    monkeypatch.setenv("TG_SESSION_MODE", "string")
    monkeypatch.setenv("TG_SESSION_STRING", "")
    with pytest.raises(ValueError, match="TG_SESSION_STRING is empty"):
        load_config()
