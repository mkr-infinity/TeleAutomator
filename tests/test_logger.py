"""Tests for structured logger and secret redaction."""

from app.logger import redact_secrets, register_secret


def test_redact_phone_numbers():
    raw = "Login requested for phone +14155552671 now."
    redacted = redact_secrets(raw)
    assert "+14155552671" not in redacted
    assert "[REDACTED]" in redacted


def test_redact_verification_code():
    raw = "Your login code is 84920. Do not share it."
    redacted = redact_secrets(raw)
    assert "84920" not in redacted
    assert "[REDACTED]" in redacted


def test_redact_api_hash():
    api_hash = "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d"
    raw = f"Using hash {api_hash} for connection."
    redacted = redact_secrets(raw)
    assert api_hash not in redacted
    assert "[REDACTED]" in redacted


def test_registered_secret():
    custom_secret = "super_secret_token_12345"
    register_secret(custom_secret)
    raw = f"Header Authorization: Bearer {custom_secret}"
    redacted = redact_secrets(raw)
    assert custom_secret not in redacted
    assert "[REDACTED]" in redacted
