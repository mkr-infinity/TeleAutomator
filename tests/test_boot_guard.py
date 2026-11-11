"""Tests for the safe-mode boot guard (boot_guard.py + recovery flow)."""

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.boot_guard import record_boot_and_maybe_safe_mode
from app.config import AppConfig
from app.reply_manager import ReplyManager
from app.safety_manager import SafetyManager
from app.privacy_manager import PrivacyManager
from app.ai.reply_generator import ReplyGenerator
from app.storage.database import Database


def _make_manager(tmp_path: Path) -> tuple[ReplyManager, Database, AppConfig]:
    cfg = AppConfig(api_id=123, api_hash="dummy_hash", data_dir=tmp_path, reply_mode="restricted_auto")
    db = Database(tmp_path / "boot.db")
    mgr = ReplyManager(cfg, db, SafetyManager(cfg, db), PrivacyManager(cfg, database=db), ReplyGenerator(cfg, database=db))
    return mgr, db, cfg


def test_single_boot_never_triggers_safe_mode(tmp_path: Path) -> None:
    _mgr, db, cfg = _make_manager(tmp_path)
    status = record_boot_and_maybe_safe_mode(db, cfg)
    assert status is None
    assert db.get_state("safe_mode_active", "0") == "0"
    assert db.get_state("reply_mode") != "draft"


def test_crash_loop_boots_engage_safe_mode(tmp_path: Path) -> None:
    _mgr, db, cfg = _make_manager(tmp_path)
    db.set_state("reply_mode", "restricted_auto")
    for _ in range(3):
        status = record_boot_and_maybe_safe_mode(db, cfg)
    assert status == "safe-mode"
    assert db.get_state("safe_mode_active") == "1"
    assert db.get_state("safe_mode_prev_mode") == "restricted_auto"
    assert db.get_state("reply_mode") == "draft"  # automation held in draft


def test_safe_mode_persists_and_second_boot_stays_safe(tmp_path: Path) -> None:
    _mgr, db, cfg = _make_manager(tmp_path)
    db.set_state("reply_mode", "restricted_auto")
    for _ in range(3):
        record_boot_and_maybe_safe_mode(db, cfg)
    assert record_boot_and_maybe_safe_mode(db, cfg) == "already-safe"
    assert db.get_state("reply_mode") == "draft"  # stays draft across further boots


def test_old_boots_outside_window_do_not_trigger(tmp_path: Path) -> None:
    _mgr, db, cfg = _make_manager(tmp_path)
    old = time.time() - 7200  # 2 hours ago
    db.set_state("boot_history", json.dumps([old, old - 5, old - 10]))
    status = record_boot_and_maybe_safe_mode(db, cfg)
    assert status is None
    assert db.get_state("safe_mode_active", "0") == "0"


def test_recovery_restores_mode_and_alerts(tmp_path: Path) -> None:
    mgr, db, _cfg = _make_manager(tmp_path)
    alerts: list[str] = []

    async def fake_alert(text: str, parse_markdown: bool = True) -> bool:
        alerts.append(text)
        return True

    db.set_state("safe_mode_prev_mode", "restricted_auto")
    db.set_state("safe_mode_active", "1")
    db.set_state("safe_mode_since", str(time.time() - 16 * 60))  # 16 min ago

    with patch.object(mgr, "_send_control_alert", fake_alert):
        asyncio.run(mgr.maybe_recover_safe_mode())

    assert db.get_state("safe_mode_active") == "0"
    assert db.get_state("reply_mode") == "restricted_auto"
    assert alerts and "Safe mode recovered" in alerts[0]

    # Second check: nothing more to do
    asyncio.run(mgr.maybe_recover_safe_mode())
    assert len(alerts) == 1


def test_recovery_waits_for_calm_uptime(tmp_path: Path) -> None:
    mgr, db, _cfg = _make_manager(tmp_path)
    db.set_state("reply_mode", "draft")  # safe mode had forced draft
    db.set_state("safe_mode_prev_mode", "restricted_auto")
    db.set_state("safe_mode_active", "1")
    db.set_state("safe_mode_since", str(time.time() - 60))  # only 1 min ago, needs 15

    asyncio.run(mgr.maybe_recover_safe_mode())
    assert db.get_state("safe_mode_active") == "1"
    assert db.get_state("reply_mode") == "draft"


def test_safemode_status_command(tmp_path: Path) -> None:
    mgr, db, _cfg = _make_manager(tmp_path)
    status = asyncio.run(mgr.handle_control_command("/safemode"))
    assert "READY" in status

    db.set_state("safe_mode_active", "1")
    db.set_state("safe_mode_since", str(time.time() - 300))
    active_status = asyncio.run(mgr.handle_control_command("/safemode"))
    assert "ACTIVE" in active_status and "draft" in active_status
