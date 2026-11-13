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
        self.client: Optional[TelegramClient] = None
        self._running = False
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

        # Automatically fetch owner persona name from connected Telegram profile
        # Fallback hierarchy: first_name -> full name / last_name -> username -> user ID
        owner_name = (me.first_name or "").strip() or name or raw_username or str(user_id)
        self.db.set_state("owner_name", owner_name)
        self.reply_manager.generator.set_owner_name(owner_name)
        logger.info(f"Automatically fetched and set AI owner persona from Telegram profile: '{owner_name}'")

        # Wire up reply manager and message filter
        self.reply_manager.set_telegram_client(self.client)
        message_filter = MessageFilter(
            my_user_id=user_id,
            privacy_manager=self.privacy,
            safety_manager=self.safety,
            my_username=me.username or "",
            database=self.db,
        )

        register_handlers(
            client=self.client,
            my_user_id=user_id,
            message_filter=message_filter,
            reply_manager=self.reply_manager,
        )

        # Send first-run onboarding welcome message to Saved Messages
        if not self.db.get_state("first_run_welcomed"):
            try:
                curr_mode = self.db.get_state("reply_mode", self.config.reply_mode)
                prov = self.db.get_state("ai_provider", self.config.ai_provider).upper()
                mod = self.db.get_state("ai_model", self.config.ai_model or "default")

                welcome_msg = (
                    f"👋 *Welcome to TeleAutomator v{__version__}*\n"
                    f"_Personal AI Assistant for {owner_name}_\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📱 *Account Connection*\n"
                    f"• *User:* `{name}` [ID: `{user_id}`]\n"
                    f"• *Active Mode:* `{curr_mode}`\n"
                    f"• *AI Engine:* `{prov}` (`{mod}`)\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"⚡ *Quick Setup Commands*\n"
                    f"• `/mode auto` — Direct automated replies\n"
                    f"• `/setai` — Configure custom AI endpoint & key\n"
                    f"• `/chats` — View or manage allowlisted chats\n"
                    f"• `/allowchat <id>` — Allow a contact or group\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🛠️ *Essential Remote Controls*\n"
                    f"• `/status` — System health, models & cooldowns\n"
                    f"• `/aiconfig` — Inspect AI engine & reasoning effort\n"
                    f"• `/usage` — Track daily & total token consumption\n"
                    f"• `/help` — Full interactive command reference\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🛑 *Safety Kill Switches*\n"
                    f"• `/pause 2h` — Snooze replies for 2 hours\n"
                    f"• `/stop` — Emergency stop (halts all messages)\n"
                    f"• `/resume` — Unpause and resume operations\n\n"
                    f"_Send any command right here in Saved Messages to control your assistant!_ 🚀"
                )
                await self.client.send_message("me", welcome_msg, parse_mode="md")
                self.db.set_state("first_run_welcomed", "1")
                logger.info("Sent structured first-run welcome and command guide to Saved Messages.")
            except Exception as e:
                logger.warning(f"Could not send first-run welcome message: {e}")

        return self.client

    async def _heartbeat_loop(self) -> None:
        """Periodically write health status file and trigger scheduled tasks."""
        while self._running:
            is_connected = bool(self.client and self.client.is_connected())
            self.health.update_heartbeat(
                is_connected=is_connected,
                emergency_stop=self.safety.is_emergency_stopped,
            )
            # Check quiet hours goodnight sign-off for active groups
            try:
                await self.reply_manager.maybe_send_quiet_hours_goodnight()
            except Exception as e:
                logger.debug(f"Quiet hours goodnight check error: {e}")

            # Timed-pause auto-resume: emit the 'pause ended' control alert when the window expires
            try:
                await self.reply_manager.check_pause_expiry()
            except Exception as e:
                logger.debug(f"Pause expiry check error: {e}")

            # Safe-mode boot guard: restore the real mode once the process proves stable
            try:
                await self.reply_manager.maybe_recover_safe_mode()
            except Exception as e:
                logger.debug(f"Safe-mode recovery check error: {e}")

            # Every 15 minutes, refresh AI-generated rolling context recaps for active chats
            # (shortened interval so busy community groups keep a fresh memory; per-chat
            # thresholds in refresh_group_summaries skip quiet chats anyway)
            now = time.monotonic()
            if now - self._last_summary_check >= 900.0:
                self._last_summary_check = now
                try:
                    await self.reply_manager.refresh_group_summaries()
                except Exception as e:
                    logger.debug(f"Group summary refresh error: {e}")

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
        await self.initialize()

        # Start health monitor loop
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info(f"Client is running in mode: '{self.config.reply_mode}'. Listening for events.")

        backoff = 2
        max_backoff = 60

        while self._running:
            try:
                # Maintain connection until disconnected or stopped
                if self.client:
                    await self.client.run_until_disconnected()
                if not self._running:
                    break

                logger.warning("Disconnected from Telegram. Attempting reconnection...")
                await asyncio.sleep(backoff)
                if self.client and not self.client.is_connected():
                    await self.client.connect()
                    logger.info("Successfully reconnected to Telegram MTProto.")
                    backoff = 2
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Telegram connection error: {e}")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    async def stop(self) -> None:
        """Gracefully disconnect and stop background tasks."""
        logger.info("Stopping Telegram service...")
        self._running = False

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        if self.client:
            try:
                await self.client.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting client: {e}")

        self.health.update_heartbeat(is_connected=False, emergency_stop=self.safety.is_emergency_stopped)
        logger.info("Telegram service stopped cleanly.")
