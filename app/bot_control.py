"""Telegram Bot API control channel.

Replaces Saved Messages as the control + alert channel when BOT_API_KEY is set:
  - Long-polls getUpdates and routes authorized commands to ReplyManager.
  - Only the main account (first BOT_AUTHORIZED_USERS entry) can add/remove authorized users.
  - Unauthorized users get a friendly "not authorized" message (max twice), then a
    "don't spam please" note, then are ignored entirely until authorized (saves Railway usage).
  - All replies/authorized add/remove notifications are sent instantly via the Bot API.
"""

from __future__ import annotations

import asyncio
import json
import urllib.parse
import urllib.request
from typing import Any, Optional

from app.logger import setup_logger
from app.storage.database import Database

logger = setup_logger(__name__)

BOT_COMMAND_HELP = (
    "🤖 *TeleAutomator Control*\n"
    "You are authorized — send any command from the menu below.\n"
    "_Every command also works as_ `/command <args>` — e.g. `/prompt <your prompt here>`, `/mode restricted_auto`, `/addauth <user_id>`."
)

UNAUTHORIZED_MESSAGE = (
    "🔒 *TeleAutomator — Access Restricted*\n\n"
    "Hi there! This control panel belongs to a private automation project, "
    "and your account isn't authorized to use it yet.\n\n"
    "👉 Want access? Reach out on Telegram: [@mkr_infinity](https://t.me/mkr_infinity)\n"
    "Just mention __TeleAutomator__ and the project you'd like authorization for.\n\n"
    "_Thanks for understanding! 🙏_"
)

UNAUTHORIZED_MESSAGE_HTML = (
    "<b>🔒 TeleAutomator — Access Restricted</b>\n\n"
    "Hi there! This control panel belongs to a private automation project, "
    "and your account isn't authorized to use it yet.\n\n"
    "👉 Want access? Contact <b>@mkr_infinity</b>\n"
    "<a href=\"https://t.me/mkr_infinity\">Open chat: @mkr_infinity</a>\n"
    "Just mention <b>TeleAutomator</b> and the project you'd like authorization for.\n\n"
    "<i>Thanks for understanding! 🙏</i>"
)

SPAM_WARNING_MESSAGE = (
    "🙇 *Please don't spam*\n\n"
    "This channel is for project control only. I'll stay silent until you're authorized.\n"
    "If you need access, contact <b>@mkr_infinity</b>."
)

AUTHORIZED_NOTICE = (
    "✅ *You're in!*\n\n"
    "Your account now has authorized access to the TeleAutomator control bot.\n"
    "Use the menu button to browse commands, or send any /command directly."
)

REMOVED_NOTICE = (
    "👋 *Access removed*\n\n"
    "Your account no longer has access to the TeleAutomator control bot.\n"
    "Contact the project owner if you believe this is a mistake."
)


class BotControl:
    """Async Telegram Bot API client with long-poll command routing."""

    BASE_URL = "https://api.telegram.org"

    def __init__(
        self,
        api_key: str,
        db: Database,
        reply_manager: Any,
        seed_user_ids: set[int],
    ) -> None:
        self.api_key = api_key.strip()
        self.db = db
        self.reply_manager = reply_manager
        self._offset: int = 0
        self._running = False
        self._me_cache: Optional[dict] = None
        # Bootstrap: seed authorized users from env once (DB list owns it afterwards)
        existing = self._load_authorized()
        if not existing and seed_user_ids:
            self._save_authorized(seed_user_ids)
            logger.info(f"Seeded bot authorized users from env: {sorted(seed_user_ids)}")
        elif existing and seed_user_ids:
            # Keep the main account (env first entry) authoritative even if DB lost it
            main_env = sorted(seed_user_ids)[0]
            if main_env not in existing:
                existing.add(main_env)
                self._save_authorized(existing)

    # ------------------------------------------------------------------ state
    def _load_authorized(self) -> set[int]:
        try:
            raw = self.db.get_state("bot_authorized_users", "")
            return set(json.loads(raw)) if raw else set()
        except Exception:
            return set()

    def _save_authorized(self, users: set[int]) -> None:
        self.db.set_state("bot_authorized_users", json.dumps(sorted(users)))

    @property
    def main_user_id(self) -> int:
        """Main authorized user (project owner) — first env-provided ID, lowest ID fallback."""
        users = self._load_authorized()
        if not users:
            return 0
        return min(users)

    def is_authorized(self, user_id: int) -> bool:
        """Read live from DB on every message so /addauth & /removeauth apply instantly."""
        if not user_id or int(user_id) <= 0:
            return False
        return int(user_id) in self._load_authorized()

    def is_main_user(self, user_id: int) -> bool:
        return self.main_user_id == int(user_id)

    # ------------------------------------------------------------------- api
    def _api_url(self, method: str) -> str:
        return f"{self.BASE_URL}/bot{self.api_key}/{method}"

    def _post(self, method: str, payload: dict) -> dict:
        data = urllib.parse.urlencode(payload, doseq=True).encode("utf-8")
        req = urllib.request.Request(self._api_url(method), data=data, method="POST")
        with urllib.request.urlopen(req, timeout=40) as resp:
            return json.loads(resp.read().decode("utf-8"))

    async def _call(self, method: str, payload: dict) -> dict:
        return await asyncio.to_thread(self._post, method, payload)

    async def get_me(self) -> dict:
        if self._me_cache is None:
            try:
                result = await self._call("getMe", {})
                self._me_cache = result.get("result", {})
            except Exception as e:
                logger.warning(f"Bot getMe failed: {e}")
        return self._me_cache or {}

    async def send_message(self, chat_id: int, text: str, parse_markdown: bool = True) -> bool:
        """Send a message via the Bot API (primary parse mode Markdown, HTML fallback)."""
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if parse_markdown:
            payload["parse_mode"] = "Markdown"
        try:
            result = await self._call("sendMessage", payload)
            if result.get("ok"):
                return True
        except Exception as e:
            logger.debug(f"Bot sendMessage failed for {chat_id}: {e}")
        # Fallback: retry as plain text (unparseable markdown entities are the usual cause)
        if parse_markdown:
            return await self.send_message(chat_id, text, parse_markdown=False)
        try:
            await self._call("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
            return True
        except Exception as e:
            logger.warning(f"Bot sendMessage fallback failed for {chat_id}: {e}")
            return False

    async def register_commands(self) -> None:
        """Publish the command menu (type '/' in the bot to get descriptions + usage)."""
        commands = [
            {"command": "status", "description": "Show current automation status, mode and settings"},
            {"command": "mode", "description": "Set reply mode — usage /mode draft|approval|restricted_auto"},
            {"command": "pause", "description": "Pause auto-replies — usage /pause <minutes>"},
            {"command": "resume", "description": "Resume auto-replies after a pause"},
            {"command": "prompt", "description": "Set custom AI persona — usage /prompt <your prompt here>"},
            {"command": "style", "description": "Set AI style — usage /style casual|concise|formal|humorous"},
            {"command": "quiet", "description": "Quiet hours — usage /quiet on|off HH:MM HH:MM"},
            {"command": "cooldown", "description": "Global reply cooldown — usage /cooldown <seconds>"},
            {"command": "editfix", "description": "Toggle self-typo-then-edit fix — usage /editfix on|off"},
            {"command": "ownreact", "description": "Toggle reactions on own replies — usage /ownreact on|off"},
            {"command": "approve", "description": "Approve pending draft — usage /approve <id>"},
            {"command": "reject", "description": "Reject pending draft — usage /reject <id>"},
            {"command": "allow", "description": "Allowlist a chat — usage /allow <chat_id>"},
            {"command": "ban", "description": "Remove chat — usage /ban <chat_id>"},
            {"command": "authlist", "description": "List users authorized for this control bot"},
            {"command": "addauth", "description": "Add an authorized user (main owner only) — usage /addauth <user_id>"},
            {"command": "removeauth", "description": "Remove an authorized user (main owner only) — usage /removeauth <user_id>"},
        ]
        result = await self._call(
            "setMyCommands",
            {"commands": json.dumps(commands, ensure_ascii=False)},
        )
        if not result.get("ok"):
            logger.warning(f"Bot setMyCommands failed: {result}")

    # ----------------------------------------------------------- poll + route
    async def run(self) -> None:
        """Main long-poll loop with exponential backoff on failures."""
        self._running = True
        me = await self.get_me()
        bot_name = me.get("username") or "bot"
        logger.info(f"Bot control channel active (long polling as @{bot_name}).")
        try:
            await self.register_commands()
        except Exception as e:
            logger.warning(f"Could not register bot commands: {e}")

        backoff = 2.0
        while self._running:
            try:
                data = await self._call(
                    "getUpdates",
                    {
                        "offset": self._offset,
                        "timeout": 25,  # long poll — Telegram holds the request
                        "allowed_updates": json.dumps(["message"]),
                    },
                )
                backoff = 2.0
                if not data.get("ok"):
                    logger.debug(f"Bot getUpdates returned not-ok: {data}")
                    await asyncio.sleep(backoff)
                    continue
                for update in data.get("result", []):
                    self._offset = max(self._offset, update.get("update_id", 0) + 1)
                    try:
                        await self._process_update(update)
                    except Exception as e:
                        logger.debug(f"Bot update processing error: {e}")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.debug(f"Bot long-poll error: {e}. Backing off {backoff}s.")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

        logger.info("Bot control channel stopped.")

    async def stop(self) -> None:
        self._running = False

    @staticmethod
    def _extract_message(update: dict) -> Optional[dict]:
        msg = update.get("message")
        if not msg:
            return None
        frm = msg.get("from") or {}
        # Never react to other bots
        if frm.get("is_bot"):
            return None
        text = (msg.get("text") or "").strip()
        if not text:
            return None
        return {"chat_id": msg.get("chat", {}).get("id"), "user_id": frm.get("id"), "text": text}

    async def _process_update(self, update: dict) -> None:
        msg = self._extract_message(update)
        if not msg:
            return
        chat_id = msg["chat_id"]
        user_id = int(msg["user_id"]) if msg["user_id"] else 0
        text = msg["text"]

        if not self.is_authorized(user_id):
            await self._handle_unauthorized(chat_id, user_id)
            return

        authorization_link = "tg://resolve?domain=mkr_infinity"

        # Bot-specific auth management (main user only, plus plain /start help)
        parts = text.split()
        lowered = text.lower()
        if lowered.startswith("/start"):
            await self.send_message(chat_id, BOT_COMMAND_HELP)
            try:
                response = await self.reply_manager.handle_control_command("/status")
                if response:
                    await self.send_message(chat_id, response)
            except Exception as e:
                logger.debug(f"Could not send status on /start: {e}")
            return

        if lowered.startswith("/authlist"):
            users = sorted(self._load_authorized())
            if not users:
                await self.send_message(chat_id, "No authorized users yet.")
                return
            lines = "\n".join(f"{i + 1}. `{uid}`{' 👑 main owner' if uid == self.main_user_id else ''}" for i, uid in enumerate(users))
            await self.send_message(chat_id, f"👥 *Authorized users:*\n{lines}")
            return

        if lowered.startswith("/addauth"):
            if not self.is_main_user(user_id):
                await self.send_message(chat_id, "👑 Only the main account owner can add authorized users.")
                return
            if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
                await self.send_message(chat_id, "Usage: `/addauth <telegram_user_id>`")
                return
            new_id = int(parts[1].lstrip("-"))
            users = self._load_authorized()
            if new_id in users:
                await self.send_message(chat_id, f"User `{new_id}` is already authorized.")
                return
            users.add(new_id)
            self._save_authorized(users)
            await self.send_message(chat_id, f"✅ User `{new_id}` is now authorized.")
            await self.send_message(new_id, AUTHORIZED_NOTICE)
            logger.info(f"Bot auth added: {new_id} (by {user_id}).")
            return

        if lowered.startswith("/removeauth"):
            if not self.is_main_user(user_id):
                await self.send_message(chat_id, "👑 Only the main account owner can remove authorized users.")
                return
            if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
                await self.send_message(chat_id, "Usage: `/removeauth <telegram_user_id>`")
                return
            target = int(parts[1].lstrip("-"))
            users = self._load_authorized()
            if target not in users:
                await self.send_message(chat_id, f"User `{target}` is not in the authorized list.")
                return
            if target == self.main_user_id:
                await self.send_message(chat_id, "🛡️ The main account owner cannot be removed (at least one user must remain).")
                return
            users.discard(target)
            if not users:
                await self.send_message(chat_id, "🛡️ At least one authorized user must remain.")
                return
            self._save_authorized(users)
            await self.send_message(chat_id, f"🗑️ User `{target}` removed from authorized list.")
            await self.send_message(target, REMOVED_NOTICE)
            logger.info(f"Bot auth removed: {target} (by {user_id}).")
            return

        # All remaining commands route to the shared command engine of ReplyManager
        response = await self.reply_manager.handle_control_command(text)
        if response:
            if len(response) > 4000:
                response = response[:4000] + "\n…"
            await self.send_message(chat_id, response)

    async def _handle_unauthorized(self, chat_id: int, user_id: int) -> None:
        if not user_id:
            return
        key = f"bot_spam_counter_{user_id}"
        try:
            strikes = int(self.db.get_state(key, "0"))
        except Exception:
            strikes = 0
        strikes += 1
        self.db.set_state(key, str(strikes))
        if strikes <= 2:
            logger.info(f"Bot: unauthorized user {user_id} messaged (strike {strikes}).")
            await self.send_message(chat_id, UNAUTHORIZED_MESSAGE_HTML, parse_markdown=False)
            if strikes == 2:
                await asyncio.sleep(2.0)
                await self.send_message(chat_id, SPAM_WARNING_MESSAGE, parse_markdown=False)
        else:
            # Silently ignored until the user is added to authorized list (reduce Railway usage)
            if strikes == 3:
                logger.info(f"Bot: ignoring unauthorized user {user_id} (spammer) until authorized.")
            self.db.set_state(key, str(strikes))

    async def send_alert(self, text: str) -> bool:
        """Route project alerts to the main account owner."""
        main_id = self.main_user_id
        if not main_id:
            logger.warning("Bot send_alert: no main user configured; alert dropped.")
            return False
        return await self.send_message(main_id, text)
