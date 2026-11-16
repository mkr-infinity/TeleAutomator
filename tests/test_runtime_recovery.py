"""Offline regressions for startup, reconnects, readiness and configuration."""

import asyncio
import json
import logging
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telethon.errors import (
    AuthKeyDuplicatedError, AuthKeyUnregisteredError, SessionExpiredError, SessionRevokedError,
)

from app.boot_guard import record_boot_and_maybe_safe_mode
from app.config import AppConfig, load_config
from app.health import HealthMonitor
from app.session_manager import get_local_session_file, get_telethon_session
from app.storage.database import Database
from app.telegram_client import TelegramService


def make_service(tmp_path):
    config = AppConfig(api_id=123, api_hash="fake_hash_value", data_dir=tmp_path)
    db = Database(tmp_path / "app.db")
    reply = MagicMock()
    reply.close = AsyncMock()
    reply.ensure_chat_context = AsyncMock()
    for method in ("maybe_send_quiet_hours_goodnight", "check_pause_expiry",
                   "maybe_recover_safe_mode", "refresh_group_summaries"):
        setattr(reply, method, AsyncMock())
    privacy = MagicMock()
    privacy.get_all_allowed_chats.return_value = (set(), set())
    service = TelegramService(config, db, SimpleNamespace(is_emergency_stopped=False),
                              privacy, reply, HealthMonitor(tmp_path))
    service.client = MagicMock()
    service.client.disconnect = AsyncMock()
    return service


@pytest.mark.parametrize("history", ['null', '{}', '[null, "bad", {}, 1e999]'])
def test_boot_history_corruption_cannot_disable_guard(tmp_path, history):
    db = Database(tmp_path / "app.db")
    db.set_state("boot_history", history)
    db.set_state("reply_mode", "restricted_auto")
    config = AppConfig(api_id=1, api_hash="fake", reply_mode="draft")
    for _ in range(3):
        result = record_boot_and_maybe_safe_mode(db, config)
    assert result == "safe-mode"
    assert db.get_state("reply_mode") == "draft"


def test_safe_mode_restart_excludes_downtime(tmp_path):
    db = Database(tmp_path / "app.db")
    db.set_state("safe_mode_active", "1")
    db.set_state("safe_mode_since", "1")
    db.set_state("reply_mode", "restricted_auto")
    with patch("app.boot_guard.time.time", return_value=10000):
        assert record_boot_and_maybe_safe_mode(db, AppConfig(1, "fake")) == "already-safe"
    assert db.get_state("safe_mode_since") == "10000"
    assert db.get_state("process_started_at") == "10000"
    assert db.get_state("reply_mode") == "draft"


@pytest.mark.parametrize("error", [AuthKeyDuplicatedError, AuthKeyUnregisteredError,
                                    SessionExpiredError, SessionRevokedError])
def test_terminal_authentication_errors_exit_reconnect_loop(tmp_path, error):
    async def run():
        service = make_service(tmp_path)
        service._initialized = True
        service.client.is_connected.return_value = True
        service.client.run_until_disconnected = AsyncMock(side_effect=error(request=None))
        try:
            with pytest.raises(RuntimeError, match="REVOKED"):
                await service.run()
            assert service.client.run_until_disconnected.await_count == 1
            assert not service.health.get_status()["ready"]
        finally:
            await service.stop()
    asyncio.run(run())


def test_reconnect_retries_failed_connect_and_validates_authorization(tmp_path):
    async def run():
        service = make_service(tmp_path)
        service._initialized = True
        service.client.is_connected.return_value = False
        service.client.connect = AsyncMock(side_effect=[OSError("offline"), None])
        service.client.is_user_authorized = AsyncMock(return_value=False)
        with patch("app.telegram_client.asyncio.sleep", new=AsyncMock()):
            try:
                with pytest.raises(RuntimeError, match="unauthorized"):
                    await service.run()
                assert service.client.connect.await_count == 2
                service.client.is_user_authorized.assert_awaited_once()
            finally:
                await service.stop()
    asyncio.run(run())


def test_run_until_disconnected_exception_reconnects(tmp_path):
    async def run():
        service = make_service(tmp_path)
        service._initialized = True
        service.client.is_connected.side_effect = [True, False]
        service.client.connect = AsyncMock(side_effect=SessionRevokedError(request=None))
        service.client.run_until_disconnected = AsyncMock(side_effect=OSError("lost"))
        with patch("app.telegram_client.asyncio.sleep", new=AsyncMock()):
            try:
                with pytest.raises(RuntimeError, match="REVOKED"):
                    await service.run()
                service.client.connect.assert_awaited_once()
            finally:
                service.client.is_connected.side_effect = None
                service.client.is_connected.return_value = False
                await service.stop()
    asyncio.run(run())


def test_initial_connection_failure_retries_without_duplicate_handlers(tmp_path):
    async def run():
        service = make_service(tmp_path)
        service.initialize = AsyncMock(side_effect=[OSError("offline"), RuntimeError("unauthorized")])
        with patch("app.telegram_client.asyncio.sleep", new=AsyncMock()):
            try:
                with pytest.raises(RuntimeError, match="unauthorized"):
                    await service.run()
                assert service.initialize.await_count == 2
                assert not service._scheduled_tasks
                service.client.disconnect.assert_awaited_once()
            finally:
                await service.stop()
    asyncio.run(run())


@pytest.mark.parametrize("saved_name", ["Custom persona", ""])
def test_startup_preserves_custom_name_and_enables_context_gate(tmp_path, saved_name):
    async def run():
        service = make_service(tmp_path)
        service.db.set_state("owner_name", saved_name)
        client = MagicMock()
        client.connect = AsyncMock()
        client.is_user_authorized = AsyncMock(return_value=True)
        client.get_me = AsyncMock(return_value=SimpleNamespace(
            id=123, first_name="Profile", last_name="Name", username="account", bot=False))
        def register(**kwargs):
            assert service.reply_manager._context_startup_enabled is True
        with patch("app.telegram_client.TelegramClient", return_value=client), \
             patch("app.telegram_client.get_telethon_session", return_value="mock"), \
             patch("app.telegram_client.register_handlers", side_effect=register):
            await service.initialize()
        assert service.db.get_state("owner_name") == (saved_name or "Profile")
        service.reply_manager.generator.set_owner_name.assert_called_once_with(saved_name or "Profile")
    asyncio.run(run())


def test_startup_context_workers_are_bounded_and_continue_after_failure(tmp_path):
    async def run():
        service = make_service(tmp_path)
        service._running = True
        service.privacy.get_all_allowed_chats.return_value = ({1, 2, 3, 4}, {-1, -2})
        active = peak = 0
        visited = set()
        async def ensure(chat_id):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            visited.add(chat_id)
            try:
                await asyncio.sleep(0)
                if chat_id == 2:
                    raise OSError("mock failure")
            finally:
                active -= 1
        service.reply_manager.ensure_chat_context.side_effect = ensure
        await service._initialize_allowed_chats()
        assert visited == {1, 2, 3, 4, -1, -2}
        assert 1 < peak <= 3
        assert active == 0
    asyncio.run(run())


def test_heartbeat_does_not_wait_for_scheduled_model_work_and_stop_cancels_jobs(tmp_path):
    async def run():
        service = make_service(tmp_path)
        service._running = service._initialized = True
        service.client.is_connected.return_value = True
        started = asyncio.Event()
        cancelled = asyncio.Event()
        async def blocked():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        service.reply_manager.maybe_send_quiet_hours_goodnight.side_effect = blocked
        sleep = asyncio.sleep
        ticks = 0
        async def tick(seconds):
            nonlocal ticks
            await sleep(0)
            ticks += 1
            if ticks == 3:
                service._running = False
        with patch("app.telegram_client.asyncio.sleep", side_effect=tick):
            await service._heartbeat_loop()
        assert started.is_set()
        assert ticks == 3
        assert service.reply_manager.maybe_send_quiet_hours_goodnight.await_count == 1
        assert service.health.is_healthy()
        await service.stop()
        assert cancelled.is_set()
        assert not service._scheduled_tasks
        assert not service.health.is_healthy()
    asyncio.run(run())


def test_health_requires_readiness_freshness_and_live_connection(tmp_path):
    monitor = HealthMonitor(tmp_path)
    assert not monitor.get_status()["ready"]
    assert not monitor.is_healthy()
    monitor.update_heartbeat(True, ready=False)
    assert not monitor.is_healthy()
    monitor.update_heartbeat(True, ready=True)
    assert monitor.is_healthy()
    assert monitor.get_status()["ready"]
    monitor.connection_probe = lambda: False
    assert not monitor.get_status()["ready"]
    monitor.connection_probe = None
    with patch("app.health.time.monotonic", return_value=monitor._last_heartbeat + 121):
        assert not monitor.get_status()["ready"]
    os.utime(monitor.health_file, (1, 1))
    assert not monitor.is_healthy()
    monitor.health_file.write_text("broken")
    assert not monitor.is_healthy()


@pytest.mark.parametrize("name", ["account.work", "account.work.session", "plain"])
def test_dotted_session_security_matches_telethon_filename(tmp_path, name):
    config = AppConfig(1, "fake", session_name=name, data_dir=tmp_path)
    filename = tmp_path / (name if name.endswith(".session") else name + ".session")
    filename.write_text("dummy")
    filename.chmod(0o644)
    assert get_local_session_file(tmp_path / name) == filename
    assert get_telethon_session(config) == str(tmp_path / name)
    if os.name == "posix":
        assert filename.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("key", ["QUIET_HOURS_START", "QUIET_HOURS_END"])
@pytest.mark.parametrize("value", ["24:00", "12:60", "2:00", "bad", "02:00:00", "-1:00"])
def test_quiet_time_rejects_invalid_values(monkeypatch, key, value):
    with patch.dict(os.environ, {"TG_API_ID": "1", "TG_API_HASH": "fake_hash_value", key: value}, clear=True), \
         patch("app.config.load_dotenv"):
        with pytest.raises(ValueError, match=key):
            load_config()


def test_quiet_time_accepts_day_boundaries():
    with patch.dict(os.environ, {"TG_API_ID": "1", "TG_API_HASH": "fake_hash_value",
                               "QUIET_HOURS_START": "00:00", "QUIET_HOURS_END": "23:59"}, clear=True), \
         patch("app.config.load_dotenv"):
        config = load_config()
    assert (config.quiet_hours_start, config.quiet_hours_end) == ("00:00", "23:59")


def test_explicit_log_level_reconfigures_imported_loggers_and_handlers():
    import app.logger as module
    previous_level = module._configured_level
    levels = {logger: (logger.level, [(handler, handler.level) for handler in logger.handlers])
              for logger in module._configured_loggers}
    try:
        early = module.setup_logger("runtime_recovery_early")
        with patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"}):
            module.setup_logger(level_name="DEBUG")
        assert early.level == logging.DEBUG
        assert all(handler.level == logging.DEBUG for handler in early.handlers)
        module.setup_logger(level_name="ERROR")
        assert early.level == logging.ERROR
        assert all(handler.level == logging.ERROR for handler in early.handlers)
    finally:
        module._configured_level = previous_level
        for logger, (level, handlers) in levels.items():
            logger.setLevel(level)
            for handler, handler_level in handlers:
                handler.setLevel(handler_level)


def test_health_cli_loads_dotenv_data_dir_without_telegram_credentials(tmp_path, monkeypatch):
    from app.main import run_health_check
    monitor = HealthMonitor(tmp_path)
    monitor.update_heartbeat(True, ready=True)
    with patch.dict(os.environ, {}, clear=True), \
         patch("app.main.load_dotenv", side_effect=lambda **kwargs: os.environ.update(DATA_DIR=str(tmp_path))):
        assert run_health_check() == 0
