"""Telethon MTProto client lifecycle, authentication verification, and connection management."""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from telethon import TelegramClient
from telethon.errors import (
    AuthKeyDuplicatedError,
    AuthKeyUnregisteredError,
    SessionExpiredError,
    SessionRevokedError,
)

from app.config import AppConfig
from app import __version__
from app.event_handlers import register_handlers
from app.health import HealthMonitor
from app.logger import setup_logger
from app.message_filter import MessageFilter
from app.notifications import check_quiet_hours_transition
from app.privacy_manager import PrivacyManager
from app.reply_manager import ReplyManager
from app.safety_manager import SafetyManager
from app.session_manager import get_telethon_session
from app.storage.database import Database

logger = setup_logger(__name__)


class TelegramService:
    """Manages Telethon MTProto client connection, session validation, and heartbeat."""

    def __init__(
        self,
        config: AppConfig,
        database: Database,
        safety_manager: SafetyManager,
        privacy_manager: PrivacyManager,
        reply_manager: ReplyManager,
        health_monitor: HealthMonitor,
    ):
        self.config = config
        self.db = database
        self.safety = safety_manager
        self.privacy = privacy_manager
        self.reply_manager = reply_manager
        self.health = health_monitor
        self.health.connection_probe = lambda: bool(self._initialized and self._running and self.client and self.client.is_connected())
        self.client: Optional[TelegramClient] = None
        self._running = False
        self._initialized = False
        self._scheduled_tasks: dict[str, asyncio.Task] = {}
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._last_summary_check = 0.0
        self._last_daily_prune = 0.0

    async def initialize(self) -> TelegramClient:
        """Create and connect the Telethon client, verifying personal account identity."""
        session = get_telethon_session(self.config)
        self.client = TelegramClient(
            session=session,
            api_id=self.config.api_id,
            api_hash=self.config.api_hash,
            connection_retries=5,
            retry_delay=3,
        )

        logger.info("Connecting to Telegram MTProto servers...")
        try:
            await self.client.connect()
            if not await self.client.is_user_authorized():
                if self.config.session_mode == "string":
                    raise RuntimeError(
                        "Telegram string session is invalid or unauthorized. "
                        "Generate a fresh TG_SESSION_STRING using './session.sh --new' (or: python3 run.py --session --new)."
                    )
                raise RuntimeError(
                    "Telegram session is not authenticated. "
                    "Run ./authenticate.sh (or: python3 run.py --auth) to log in interactively."
                )
        except (AuthKeyDuplicatedError, AuthKeyUnregisteredError, SessionRevokedError, SessionExpiredError) as e:
            if self.config.session_mode == "string":
                msg = (
                    "CRITICAL: Telegram session was REVOKED by Telegram servers (AuthKeyDuplicatedError).\n"
                    "CAUSE: The session string (TG_SESSION_STRING) was used under two different IP addresses "
                    "simultaneously (e.g. running locally on your computer while deployed to Railway/cloud), "
                    "or the session was terminated in Telegram Settings > Devices.\n"
                    "HOW TO FIX:\n"
                    "1. Stop any local instance of TeleAutomator if running.\n"
                    "2. Generate a dedicated cloud session by running: ./session.sh --new (or: python3 run.py --session --new)\n"
                    "3. Update TG_SESSION_STRING in your Railway dashboard with the newly generated session string."
                )
            else:
                msg = (
                    "CRITICAL: Local Telegram session was REVOKED by Telegram servers (AuthKeyDuplicatedError).\n"
                    "CAUSE: The session file was used from multiple IP addresses simultaneously (e.g. while deployed on cloud), "
                    "or terminated in Telegram Settings > Devices.\n"
                    "HOW TO FIX:\n"
                    "1. Delete the revoked session: rm data/telegram_client.session\n"
                    "2. Re-authenticate cleanly: ./authenticate.sh (or: python3 run.py --auth)"
                )
            logger.critical(msg)
            raise RuntimeError(msg) from e

        # Confirm identity of the connected account
        me = await self.client.get_me()
        if getattr(me, "bot", False):
            raise RuntimeError(
                "Connected account is a Bot account! This client is designed strictly "
                "for personal MTProto user accounts. Please authenticate with your personal account."
            )

        user_id = me.id
        name = f"{me.first_name or ''} {me.last_name or ''}".strip()
        username = f"@{me.username}" if me.username else "(no username)"
        raw_username = (me.username or "").strip().lstrip("@")
        logger.info(f"Connected personal Telegram account: {name} {username} [ID: {user_id}]")

        # Preserve an explicit persona; otherwise seed it from Telegram.
        # Fallback hierarchy: first_name -> full name / last_name -> username -> user ID
        owner_name = self.db.get_state("owner_name") or (me.first_name or "").strip() or name or raw_username or str(user_id)
        self.db.set_state("owner_name", owner_name)
        self.reply_manager.generator.set_owner_name(owner_name)
        logger.info("Owner persona loaded.")

        # Wire up reply manager and message filter
        self.reply_manager.set_telegram_client(self.client)
        message_filter = MessageFilter(
            my_user_id=user_id,
            privacy_manager=self.privacy,
            safety_manager=self.safety,
            my_username=me.username or "",
            database=self.db,
        )

        self.reply_manager._context_startup_enabled = True
        register_handlers(
            client=self.client,
            my_user_id=user_id,
            message_filter=message_filter,
            reply_manager=self.reply_manager,
        )

        # Mark first-run welcomed in DB (onboarding & controls route strictly through the control bot)
        if not self.db.get_state("first_run_welcomed"):
            self.db.set_state("first_run_welcomed", "1")

        self._initialized = True
        return self.client

    async def _initialize_allowed_chats(self) -> None:
        """Warm allowlisted context with bounded workers without delaying controls."""
        private, groups = self.privacy.get_all_allowed_chats()
        pending = iter(private | groups)

        async def worker():
            for chat_id in pending:
                if not self._running:
                    return
                try:
                    await self.reply_manager.ensure_chat_context(chat_id)
                except Exception as exc:
                    logger.debug("Startup context initialization failed: %s", type(exc).__name__)

        workers = [asyncio.create_task(worker()) for _ in range(min(3, len(private | groups)))]
        try:
            await asyncio.gather(*workers)
        finally:
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

    def _schedule(self, name, operation) -> None:
        previous = self._scheduled_tasks.get(name)
        if previous is not None and not previous.done():
            return

        async def run():
            try:
                await operation()
            except Exception as exc:
                logger.debug("Scheduled %s failed: %s", name, type(exc).__name__)

        self._scheduled_tasks[name] = asyncio.create_task(run())

    async def _heartbeat_loop(self) -> None:
        """Periodically write health status file and trigger scheduled tasks."""
        while self._running:
            is_connected = bool(self.client and self.client.is_connected())
            self.health.update_heartbeat(
                is_connected=is_connected,
                emergency_stop=self.safety.is_emergency_stopped,
                ready=self._initialized,
            )
            if self._initialized and is_connected:
                self._schedule("quiet_hours", self.reply_manager.maybe_send_quiet_hours_goodnight)
                self._schedule("pause_expiry", self.reply_manager.check_pause_expiry)
                self._schedule("quiet_hours_notice", lambda: check_quiet_hours_transition(self.reply_manager))
                self._schedule("safe_mode", self.reply_manager.maybe_recover_safe_mode)

            now = time.monotonic()
            if self._initialized and is_connected and now - self._last_summary_check >= 60.0:
                self._last_summary_check = now
                self._schedule("summaries", self.reply_manager.refresh_group_summaries)

            # Automated SQLite daily maintenance (every 24 hours / 1 day)
            # Performs non-blocking WAL checkpointing; messages and reactions are preserved
            # in context storage for AI intelligence and never automatically deleted.
            if now - self._last_daily_prune >= 86400.0:
                self._last_daily_prune = now
                try:
                    with self.db._get_connection() as conn:
                        conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                    logger.info("[DAILY MAINTENANCE] Automated 24h SQLite WAL maintenance completed (all messages/reactions preserved).")
                except Exception as e:
                    logger.debug(f"Daily maintenance error: {e}")

            await asyncio.sleep(30)

    async def run(self) -> None:
        """Run the client and sustain connection with exponential backoff on disconnects."""
        self._running = True
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        backoff = 2
        try:
            while self._running:
                try:
                    if not self._initialized:
                        await self.initialize()
                        self._schedule("startup_context", self._initialize_allowed_chats)
                    elif self.client and not self.client.is_connected():
                        await self.client.connect()
                        if not await self.client.is_user_authorized():
                            raise RuntimeError("Telegram session is unauthorized; re-authentication required.")
                    connected_at = time.monotonic()
                    self.health.update_heartbeat(True, self.safety.is_emergency_stopped, ready=True)
                    await self.client.run_until_disconnected()
                    if time.monotonic() - connected_at >= 30:
                        backoff = 2
                except (AuthKeyDuplicatedError, AuthKeyUnregisteredError, SessionRevokedError, SessionExpiredError) as exc:
                    raise RuntimeError("Telegram session REVOKED; re-authentication required.") from exc
                except RuntimeError:
                    raise
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("Telegram connection failed: %s", type(exc).__name__)
                    if not self._initialized and self.client:
                        try:
                            await self.client.disconnect()
                        except Exception:
                            pass
                if self._running:
                    self.health.update_heartbeat(False, self.safety.is_emergency_stopped, ready=False)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60)
        finally:
            self._initialized = False
            self._running = False
            self.health.update_heartbeat(False, self.safety.is_emergency_stopped, ready=False)

    async def stop(self) -> None:
        """Gracefully disconnect and stop background tasks."""
        logger.info("Stopping Telegram service...")
        self._running = False

        tasks = list(self._scheduled_tasks.values())
        if self._heartbeat_task:
            tasks.append(self._heartbeat_task)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._scheduled_tasks.clear()

        await self.reply_manager.close()

        if self.client:
            try:
                await self.client.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting client: {e}")

        self.health.update_heartbeat(is_connected=False, emergency_stop=self.safety.is_emergency_stopped)
        logger.info("Telegram service stopped cleanly.")
