"""Telegram Bot API control channel.

Replaces Saved Messages as the control + alert channel when BOT_API_KEY is set:
  - Long-polls getUpdates and routes authorized commands to ReplyManager.
  - Only the main account (first BOT_AUTHORIZED_USERS entry) can add/remove authorized users
    and grant per-command restrictions (via /grantperm & /revokeperm).
  - Unauthorized users get a friendly "not authorized" message (max twice), then a
    "don't spam please" note, then are ignored entirely until authorized (saves Railway usage).
  - All alerts/approvals are sent instantly via the Bot API (approvals with inline buttons).
  - Sends a welcome card on every deploy/restart and keeps a heartbeat watchdog.
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

from app import __version__
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
        health_file: Optional[Path] = None,
    ) -> None:
        self.api_key = api_key.strip()
        self.db = db
        self.reply_manager = reply_manager
        self.health_file = health_file
        self._offset: int = 0
        self._running = False
        self._me_cache: Optional[dict] = None
        self._watchdog_last_alert: float = 0.0
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
            {"command": "status", "description": "📊 Live status — mode, AI engine, chat rules, safe-mode"},
            {"command": "mode", "description": "🔁 Reply mode — /mode draft|approval|restricted_auto"},
            {"command": "pause", "description": "⏸️ Pause automation — /pause <minutes>"},
            {"command": "resume", "description": "▶️ Resume automation after a pause"},
            {"command": "prompt", "description": "🎭 AI persona — /prompt <text> to set · bare /prompt to view"},
            {"command": "style", "description": "🎨 AI style — /style casual|concise|formal|humorous"},
            {"command": "quiet", "description": "🌙 Quiet hours (IST) — /quiet on|off HH:MM HH:MM"},
            {"command": "cooldown", "description": "⏱️ Global reply cooldown — /cooldown <seconds>"},
            {"command": "editfix", "description": "✏️ Typo-then-edit fix — /editfix on|off"},
            {"command": "ownreact", "description": "💬 Reactions to own replies — /ownreact on|off"},
            {"command": "approve", "description": "✅ Approve a pending draft — /approve <id>"},
            {"command": "reject", "description": "❌ Reject a pending draft — /reject <id>"},
            {"command": "allow", "description": "➕ Allowlist a chat — /allow <chat_id>"},
            {"command": "ban", "description": "🚫 Remove a chat — /ban <chat_id>"},
            {"command": "authlist", "description": "👥 Authorized users & their permissions"},
            {"command": "addauth", "description": "👤 Add authorized user (owner only) — /addauth <user_id>"},
            {"command": "removeauth", "description": "👋 Remove authorized user (owner only) — /removeauth <user_id>"},
            {"command": "grantperm", "description": "🔑 Restrict user to commands — /grantperm <user_id> all|/status,/prompt"},
            {"command": "revokeperm", "description": "🔓 Remove user command restrictions — /revokeperm <user_id>"},
            {"command": "watchdog", "description": "🐕 Crash-alert threshold — /watchdog <minutes> (default 5)"},
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
        try:
            await self.send_welcome_card(bot_name)
        except Exception as e:
            logger.debug(f"Could not send welcome card: {e}")

        backoff = 2.0
        while self._running:
            try:
                await self._watchdog_check()
                data = await self._call(
                    "getUpdates",
                    {
                        "offset": self._offset,
                        "timeout": 25,  # long poll — Telegram holds the request
                        "allowed_updates": json.dumps(["message", "callback_query"]),
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

    async def send_welcome_card(self, bot_name: str) -> None:
        """Beautiful welcome card sent to the main owner on every deploy/restart so they
        always know the deployment is back up and the bot is synced."""
        from datetime import datetime

        now_str = datetime.now().strftime("%d %b, %H:%M:%S")
        users = sorted(self._load_authorized())
        main_id = users[0] if users else 0
        extra = f" + {len(users) - 1} more" if len(users) > 1 else ""
        card = (
            "🚀 *TeleAutomator is live!*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"♻️ *Deploy/Restart:* {now_str}\n"
            f"🏷️ *Version:* v{__version__}\n"
            f"🤖 *Control bot:* @{bot_name}\n"
            f"👑 *Main owner:* `{main_id}`{extra}\n"
            f"🔒 *Authorized users:* {len(users)}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "✅ Bot is active & in sync with the project\n"
            "📬 Alerts, approvals & errors will arrive right here\n"
            "⌨️ Type */* for the command menu, or */start* for a guided tour\n\n"
            "_Your personal account stays clean — this bot is your control room._"
        )
        await self.send_alert(card)

    async def _watchdog_check(self) -> None:
        """Alert the main owner when the main process heartbeat goes stale (silent crash /
        revoked session detected on Railway). Alerts once per staleness episode + every 30 min."""
        if not self.health_file:
            return
        threshold_min = max(2, int(self.db.get_state("watchdog_minutes", "5")))
        try:
            stale_for = time.time() - self.health_file.stat().st_mtime
        except FileNotFoundError:
            stale_for = float("inf")
        except Exception:
            return
        alert_window = time.time() - self._watchdog_last_alert
        if stale_for >= threshold_min * 60 and alert_window >= 1800:
            self._watchdog_last_alert = time.time()
            mins = int(stale_for // 60) if stale_for != float("inf") else threshold_min
            logger.warning(f"Watchdog: main process heartbeat stale for ~{mins} min.")
            await self.send_alert(
                "⏱️ *Watchdog Alert!*\n\n"
                f"The main automation process heartbeat has been silent for ~*{mins} minutes*.\n"
                "Possible causes: a crash, the Telegram session got revoked, or Railway stopped the service.\n\n"
                "👉 *Check your Railway logs & deployment status.*\n"
                f"_Threshold adjustable via_ `/watchdog <minutes>`_."
            )

    async def get_chat_name(self, user_id: int) -> str:
        """Best-effort display name for an authorized user id via getChat."""
        try:
            result = await self._call("getChat", {"chat_id": user_id})
            info = result.get("result", {})
            name = " ".join(
                filter(None, [info.get("first_name"), info.get("last_name")])
            ).strip()
            username = info.get("username")
            label = name or ("@" + username if username else "")
            return label or str(user_id)
        except Exception:
            return str(user_id)

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

    # ---------------------------------------------------------------- routing
    async def _process_update(self, update: dict) -> None:
        # Inline button callbacks (approval ✅ / ❌)
        if update.get("callback_query"):
            await self._handle_callback(update["callback_query"])
            return

        msg = self._extract_message(update)
        if not msg:
            return
        chat_id = msg["chat_id"]
        user_id = int(msg["user_id"]) if msg["user_id"] else 0
        text = msg["text"]

        if not self.is_authorized(user_id):
            await self._handle_unauthorized(chat_id, user_id)
            return

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
            await self._handle_authlist(chat_id)
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
            self.db.set_state(f"bot_granted_cmds_{target}", "all")  # reset any restriction
            await self.send_message(chat_id, f"🗑️ User `{target}` removed from authorized list.")
            await self.send_message(target, REMOVED_NOTICE)
            logger.info(f"Bot auth removed: {target} (by {user_id}).")
            return

        # Per-command permissions (suggestion #1): main owner can restrict a secondary user
        if lowered.startswith("/grantperm"):
            if not self.is_main_user(user_id):
                await self.send_message(chat_id, "👑 Only the main account owner can manage permissions.")
                return
            if len(parts) < 3 or not parts[1].lstrip("-").isdigit():
                await self.send_message(chat_id, "Usage: `/grantperm <user_id> all` — or limit to specific commands:\n`/grantperm 555 /status,/prompt,/pause`")
                return
            target = int(parts[1].lstrip("-"))
            if target not in self._load_authorized():
                await self.send_message(chat_id, f"User `{target}` is not authorized yet. `/addauth` them first.")
                return
            granted = ",".join(p.strip().lower() for p in parts[2:] if p.strip())
            if granted.lower() == "all":
                self.db.set_state(f"bot_granted_cmds_{target}", "all")
                await self.send_message(chat_id, f"✅ User `{target}` now has access to *all* commands.")
            else:
                cmds = granted.replace(" ", "").split(",")
                if not cmds or not all(c.startswith("/") for c in cmds if c):
                    await self.send_message(chat_id, "Commands must be comma-separated and start with `/` (e.g. `/status,/prompt`).")
                    return
                self.db.set_state(f"bot_granted_cmds_{target}", ",".join(sorted(set(cmds))))
                await self.send_message(chat_id, f"🔒 User `{target}` is now restricted to:\n{'  '.join(sorted(set(cmds)))}")
            await self.send_message(target, "✨ *Your bot permissions were updated by the owner.*\nType `/start` to see what you can use.")
            return

        if lowered.startswith("/revokeperm"):
            if not self.is_main_user(user_id):
                await self.send_message(chat_id, "👑 Only the main account owner can manage permissions.")
                return
            if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
                await self.send_message(chat_id, "Usage: `/revokeperm <user_id>`")
                return
            target = int(parts[1].lstrip("-"))
            if self.db.get_state(f"bot_granted_cmds_{target}", "all") == "all":
                await self.send_message(chat_id, f"User `{target}` has no restrictions to remove.")
                return
            self.db.set_state(f"bot_granted_cmds_{target}", "all")
            await self.send_message(chat_id, f"🔓 User `{target}` restrictions removed — full access restored.")
            await self.send_message(target, "🔓 *Your bot permissions were updated by the owner.*\nYou now have full command access.")
            return

        if lowered.startswith("/watchdog"):
            if not self.is_main_user(user_id):
                await self.send_message(chat_id, "👑 Only the main account owner can change watchdog settings.")
                return
            if len(parts) < 2 or not parts[1].isdigit():
                curr = self.db.get_state("watchdog_minutes", "5")
                await self.send_message(chat_id, f"⏱️ *Watchdog threshold:* {curr} min\nUsage: `/watchdog <minutes>` — alerts you here if the main process heartbeat goes silent that long.")
                return
            mins = max(2, int(parts[1]))
            self.db.set_state("watchdog_minutes", str(mins))
            await self.send_message(chat_id, f"⏱️ Watchdog threshold set to *{mins} minutes*.")
            return

        # Per-command permission enforcement (main owner always unrestricted)
        if not self.is_main_user(user_id) and not self._user_can(user_id, text.split()[0]):
            await self.send_message(
                chat_id,
                f"⛔ `{text.split()[0].split('@')[0]}` is not permitted for your account. Ask the owner to grant it via `/grantperm`.",
            )
            return

        # All remaining commands route to the shared command engine of ReplyManager
        response = await self.reply_manager.handle_control_command(text)
        if response:
            if len(response) > 4000:
                response = response[:4000] + "\n…"
            await self.send_message(chat_id, response)

    def _user_can(self, user_id: int, raw_command: str) -> bool:
        """Check this user's granted command list ('all' or trailing-specific commands like /prompt)."""
        granted = self.db.get_state(f"bot_granted_cmds_{user_id}", "all")
        if not granted or granted.strip() == "all":
            return True
        root = raw_command.strip().split()[0].lower().split("@")[0]
        return root in {c.strip().lower().split("@")[0] for c in granted.split(",") if c.strip()}

    async def _handle_authlist(self, chat_id: int) -> None:
        users = sorted(self._load_authorized())
        if not users:
            await self.send_message(chat_id, "No authorized users yet.")
            return
        lines = []
        for uid in users:
            name = await self.get_chat_name(uid)
            perms = self.db.get_state(f"bot_granted_cmds_{uid}", "all")
            perm_label = "all commands" if perms.strip() == "all" else f"limited: {perms}"
            badge = " 👑 main owner" if uid == self.main_user_id else ""
            lines.append(f"• `{uid}` — {name} — {perm_label}{badge}")
        await self.send_message(chat_id, "👥 *Authorized users:*\n" + "\n".join(lines))

    async def _handle_callback(self, cb: dict) -> None:
        """Approval inline buttons: ✅ approve / ❌ reject a pending draft."""
        user_id = int((cb.get("from") or {}).get("id") or 0)
        data = cb.get("data") or ""
        cb_id = cb.get("id")
        if not self.is_authorized(user_id):
            await self._call("answerCallbackQuery", {"callback_query_id": cb_id, "text": "Not authorized 🔒"})
            return
        if data not in ("approve", "reject") and ":" not in data:
            await self._call("answerCallbackQuery", {"callback_query_id": cb_id})
            return
        action, _, target_id = data.partition(":")
        if action not in ("approve", "reject") or not target_id.isdigit():
            await self._call("answerCallbackQuery", {"callback_query_id": cb_id})
            return
        if not (self.is_main_user(user_id) or self._user_can(user_id, f"/{action}")):
            await self._call("answerCallbackQuery", {"callback_query_id": cb_id, "text": "⛔ Not permitted for your account."})
            return
        response = await self.reply_manager.handle_control_command(f"/{action} {target_id}") or "Done."
        # Popup answer + update the message so the buttons disappear once handled
        await self._call("answerCallbackQuery", {"callback_query_id": cb_id, "text": response[:180], "show_alert": True})
        message = cb.get("message") or {}
        try:
            await self._call(
                "deleteMessage",
                {"chat_id": message.get("chat", {}).get("id"), "message_id": message.get("message_id")},
            )
            await self.send_message(
                message.get("chat", {}).get("id"),
                f"*Draft #{target_id} — {'sent ✅' if action == 'approve' else 'rejected ❌'}*\n{response}",
            )
        except Exception as e:
            logger.debug(f"Could not refresh approval message: {e}")


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

    async def send_approval_card(self, text: str, approval_id: int) -> bool:
        """Send an approval notification with ✅/❌ inline buttons (suggestion #2)."""
        main_id = self.main_user_id
        if not main_id:
            return False
        keyboard = json.dumps({
            "inline_keyboard": [[
                {"text": f"✅ Approve #{approval_id}", "callback_data": f"approve:{approval_id}"},
                {"text": f"❌ Reject #{approval_id}", "callback_data": f"reject:{approval_id}"},
            ]]
        }, ensure_ascii=False)

        async def _attempt(parse_mode: Optional[str]) -> bool:
            payload: dict[str, Any] = {"chat_id": main_id, "text": text, "reply_markup": keyboard}
            if parse_mode:
                payload["parse_mode"] = parse_mode
            result = await self._call("sendMessage", payload)
            return result.get("ok")

        try:
            if await _attempt("Markdown"):
                return True
            if await _attempt("HTML"):
                return True
            return await _attempt(None)
        except Exception as e:
            logger.warning(f"Bot approval card failed for draft #{approval_id}: {e}")
            return False
