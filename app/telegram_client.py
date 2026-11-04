"""Telethon MTProto client lifecycle, authentication verification, and connection management."""

from __future__ import annotations

import asyncio
from typing import Optional

from telethon import TelegramClient

from app.config import AppConfig
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
        await self.client.connect()

        if not await self.client.is_user_authorized():
            if self.config.session_mode == "string":
                raise RuntimeError(
                    "Telegram string session is invalid or unauthorized. "
                    "Generate a valid TG_SESSION_STRING using ./authenticate.sh (or: python3 run.py --auth)."
                )
            raise RuntimeError(
                "Telegram session is not authenticated. "
                "Run ./authenticate.sh (or: python3 run.py --auth) to log in interactively."
            )

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
        logger.info(f"Connected personal Telegram account: {name} {username} [ID: {user_id}]")

        # Resolve owner persona name (check database override first, else Telegram first name)
        custom_name = self.db.get_state("owner_name", "")
        owner_name = custom_name or me.first_name or name or "Kaif"
        self.reply_manager.generator.set_owner_name(owner_name)

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
                welcome_msg = (
                    f"👋 *Welcome to TeleAutomator, {owner_name}!*\n"
                    f"_Your Telegram account, powered by AI. 🤖_\n\n"
                    f"Your personal MTProto client is connected and active.\n"
                    f"• *Mode:* `{self.config.reply_mode}` (switch anytime with `/mode <draft|approval|auto>`)\n"
                    f"• *Account:* `{name}` [ID: `{user_id}`]\n"
                    f"• *AI Engine:* `{self.config.ai_provider}` (model: `{self.config.ai_model or 'default'}`)\n\n"
                    f"💡 *How to Use:*\n"
                    f"Whenever someone messages you from an allowlisted chat, TeleAutomator crafts natural, human context-aware replies.\n\n"
                    f"📌 *Key Commands (send here anytime):*\n"
                    f"• `/status` - Check health, mode, style & pause status\n"
                    f"• `/mode <draft|approval|auto>` - Switch automation mode\n"
                    f"• `/style <casual|concise|formal|humorous>` - Switch AI response style\n"
                    f"• `/chats` - View allowlisted private chats & groups\n"
                    f"• `/allowchat <id>` - Add a contact or group to allowlist\n"
                    f"• `/addrule <word> => <reply>` - Auto-reply when a word is detected\n"
                    f"• `/rules` - View active custom keyword triggers\n"
                    f"• `/pause 2h` - Snooze automated replies for 2 hours\n"
                    f"• `/resume` - Unpause and resume normal operation\n"
                    f"• `/mentiononly on` - In groups: reply only when mentioned\n"
                    f"• `/stop` - Emergency stop switch\n"
                    f"• `/prompt` - View your active AI persona prompt\n"
                    f"• `/setprompt <text>` - Update your prompt on the fly\n"
                    f"• `/help` - View complete command guide\n\n"
                    f"Enjoy your automated personal client! 🚀"
                )
                await self.client.send_message("me", welcome_msg, parse_mode="md")
                self.db.set_state("first_run_welcomed", "1")
                logger.info("Sent first-run welcome and command guide to Saved Messages.")
            except Exception as e:
                logger.warning(f"Could not send first-run welcome message: {e}")

        return self.client

    async def _heartbeat_loop(self) -> None:
        """Periodically write health status file."""
        while self._running:
            is_connected = bool(self.client and self.client.is_connected())
            self.health.update_heartbeat(
                is_connected=is_connected,
                emergency_stop=self.safety.is_emergency_stopped,
            )
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
