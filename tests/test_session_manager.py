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


def test_robust_string_session_normalizes_dirty_inputs(tmp_path: Path):
    """Verify that RobustStringSession handles multiline wraps, quotes, spaces, and missing padding without 275-byte unpack errors."""
    from telethon.crypto import AuthKey
    from app.session_manager import RobustStringSession

    s = StringSession()
    s.set_dc(2, "149.154.167.50", 443)
    s.auth_key = AuthKey(b"y" * 256)
    base_session = s.save()

    # 1. Wrapped multiline session from terminal line wrap
    multiline_session = base_session[:50] + "\n" + base_session[50:120] + "\r\n" + base_session[120:]
    sess1 = RobustStringSession(multiline_session)
    assert sess1.dc_id == 2
    assert sess1.server_address == "149.154.167.50"

    # 2. Quoted with double and single quotes
    quoted_double = f'"{base_session}"'
    sess2 = RobustStringSession(quoted_double)
    assert sess2.dc_id == 2

    quoted_single = f"'{base_session}'"
    sess3 = RobustStringSession(quoted_single)
    assert sess3.dc_id == 2

    # 3. Trailing and leading whitespace
    padded_spaces = f"   {base_session}   \n  "
    sess4 = RobustStringSession(padded_spaces)
    assert sess4.dc_id == 2

    # 4. Missing padding '='
    unpadded = base_session.rstrip("=")
    sess5 = RobustStringSession(unpadded)
    assert sess5.dc_id == 2
