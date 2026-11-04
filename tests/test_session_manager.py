"""Tests for session management and permissions."""

import os
import stat
from pathlib import Path
from app.config import AppConfig
from app.session_manager import ensure_secure_dir, ensure_secure_file, get_telethon_session
from telethon.sessions import StringSession


def test_ensure_secure_dir(tmp_path: Path):
    target = tmp_path / "private_data"
    res = ensure_secure_dir(target)
    assert res.exists()
    if os.name == "posix":
        mode = stat.S_IMODE(target.stat().st_mode)
        assert mode == 0o700


def test_ensure_secure_file(tmp_path: Path):
    target = tmp_path / "test.session"
    target.write_text("dummy")
    ensure_secure_file(target)
    if os.name == "posix":
        mode = stat.S_IMODE(target.stat().st_mode)
        assert mode == 0o600


def test_get_telethon_session_string(tmp_path: Path):
    from telethon.crypto import AuthKey

    s = StringSession()
    s.set_dc(2, "149.154.167.50", 443)
    s.auth_key = AuthKey(b"x" * 256)
    dummy_session = s.save()

    cfg = AppConfig(
        api_id=123,
        api_hash="hash_value",
        session_mode="string",
        session_string=dummy_session,
        data_dir=tmp_path,
    )
    sess = get_telethon_session(cfg)
    assert isinstance(sess, StringSession)
    assert sess.dc_id == 2
