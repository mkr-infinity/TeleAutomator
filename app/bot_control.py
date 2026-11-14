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
    "🔒 *Access Restricted*\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "✨ *TeleAutomator Control*\n\n"
    "This control panel belongs to a private automation project. "
    "Your Telegram account is not authorized yet.\n\n"
    "💳 *Authorization Plan:*\n"
    "• ⭐ *100 Telegram Stars* or 💎 *1 TON* (1 month access)\n\n"
    "💬 *Get Access:*\n"
    "Contact [@mkr_infinity](https://t.me/mkr_infinity) on Telegram with payment confirmation for instant authorization.\n"
    "━━━━━━━━━━━━━━━━━━━━"
)

UNAUTHORIZED_MESSAGE_HTML = (
    "🔒 <b>ACCESS RESTRICTED</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "🤖 <b>TeleAutomator Control Bot</b>\n\n"
    "This bot belongs to a private automation project.\n"
    "Your Telegram account is currently <b>not authorized</b> to run commands.\n\n"
    "💎 <b>Authorization Plans:</b>\n"
    "• ⭐ <b>100 Telegram Stars</b> (1 Month Access)\n"
    "• 💎 <b>1 TON</b> (1 Month Access)\n\n"
    "📲 <b>How to Activate:</b>\n"
    "1. Transfer Stars or TON to <b>@mkr_infinity</b>\n"
    "2. Send your payment screenshot\n"
    "3. Your account will receive instant authorization.\n"
    "━━━━━━━━━━━━━━━━━━━━"
)

SPAM_WARNING_MESSAGE = (
    "⚠️ <b>Notice: Private Automation System</b>\n\n"
    "Commands from unauthorized accounts are strictly restricted.\n"
    "To authorize your account, contact <b>@mkr_infinity</b> on Telegram."
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

# Complete command menu published via setMyCommands — every command the bot understands,
# beautifully described. Telegram allows up to 100; we register all of them so typing '/'
# always shows the full structured toolbox.
BOT_COMMAND_MENU: list[dict] = [
    # -- Overview & control --
    {"command": "start", "description": "🚀 Guided tour — help menu + live status"},
    {"command": "help", "description": "📖 Full command reference, grouped by section"},
    {"command": "status", "description": "📊 Live status — mode, AI engine, chat rules, safe-mode"},
    {"command": "mode", "description": "🔁 Reply mode — /mode draft|approval|restricted_auto"},
    {"command": "pause", "description": "⏸️ Pause automation — /pause <minutes|30m|2h|90s>"},
    {"command": "resume", "description": "▶️ Resume automation after a pause"},
    {"command": "stop", "description": "🛑 Emergency stop — halts all replies instantly"},
    {"command": "auto", "description": "⚡ Restricted-auto authorization — /auto on|off"},
    {"command": "safemode", "description": "🛡️ Crash-loop guard status — draft-mode protection info"},
    {"command": "watchdog", "description": "🐕 Crash-alert threshold — /watchdog <minutes> (default 5)"},
    # -- Persona & language --
    {"command": "prompt", "description": "🎭 AI persona — /prompt <text> to set · bare /prompt to view"},
    {"command": "name", "description": "👤 Owner identity name the AI texts as — /name <name>"},
    {"command": "style", "description": "🎨 AI style — /style casual|concise|formal|humorous"},
    {"command": "styles", "description": "🗂️ List per-chat style overrides"},
    {"command": "chatprompt", "description": "🗣 Per-chat AI persona — /chatprompt <chat_id> <text>"},
    {"command": "lang", "description": "🌐 Reply language — /lang dynamic|english|hindi|..."},
    {"command": "chatty", "description": "💬 Per-group banter picker (buttons) — bare /chatty"},
    # -- AI engine --
    {"command": "aiconfig", "description": "🤖 AI engine dashboard — provider, model, temperature"},
    {"command": "setai", "description": "⚙️ 1-step AI setup — /setai <provider> <key>"},
    {"command": "apikey", "description": "🔑 Set AI API key — /apikey <key>"},
    {"command": "provider", "description": "🔌 Switch AI engine — /provider custom|gemini|openai|nvidia|local"},
    {"command": "model", "description": "🧠 Set model or fallback chain — /model <name[,name2]>"},
    {"command": "baseurl", "description": "🔗 Custom API endpoint — /baseurl <url>"},
    {"command": "checkmodels", "description": "📡 Ping candidate models live & pick working ones"},
    {"command": "thinking", "description": "🧩 Reasoning effort — /thinking default|low|medium|high|off"},
    {"command": "temp", "description": "🌡️ AI creativity — /temp <0.0-1.0>"},
    {"command": "maxtokens", "description": "📏 Max output tokens — /maxtokens <tokens>"},
    {"command": "usage", "description": "📈 Token tracker — daily use & free-quota remaining"},
    # -- Human behavior sim --
    {"command": "reaction", "description": "❤️ Auto-reactions — /reaction on|off"},
    {"command": "reactioncooldown", "description": "⏱️ Reaction cooldown — /reactioncooldown <min> <max> seconds"},
    {"command": "ownreact", "description": "💬 Reactions to own replies — /ownreact on|off"},
    {"command": "chatcooldown", "description": "⏳ Per-chat reply cooldown — /chatcooldown <min> <max> seconds"},
    {"command": "globalcooldown", "description": "🌐 Global reply cooldown — /globalcooldown <min> <max> seconds"},
    {"command": "ratelimit", "description": "🚦 Anti-spam burst limit — /ratelimit <replies/min>"},
    {"command": "editfix", "description": "✏️ Typo-then-edit simulation — /editfix on|off"},
    {"command": "typo", "description": "🔤 Natural typo + correction follow-up — /typo on|off"},
    {"command": "followup", "description": "➕ Spontaneous delayed follow-ups — /followup on|off"},
    {"command": "debounce", "description": "🧵 Stitch rapid incoming bursts — /debounce on|off|<seconds>"},
    {"command": "multibubble", "description": "🫧 Multi-bubble reply splitting — /multibubble on|off"},
    {"command": "quiethours", "description": "🌙 Sleep schedule (IST) — /quiethours on|off HH:MM HH:MM"},
    {"command": "sleep", "description": "😴 Good-night shortcut — pauses automation till morning — /sleep [hours]"},
    # -- Chats & context --
    {"command": "chats", "description": "📋 Allowlisted contacts & groups table"},
    {"command": "allowchat", "description": "➕ Allowlist a chat — /allowchat <chat_id>"},
    {"command": "removechat", "description": "➖ Remove chat from allowlist — /removechat <chat_id>"},
    {"command": "blockchat", "description": "🚫 Block a chat ID — /blockchat <chat_id>"},
    {"command": "mentiononly", "description": "🎯 Group safety — reply only when mentioned — /mentiononly on|off"},
    {"command": "contextttl", "description": "⏳ Context aging window — /contextttl <hours>"},
    {"command": "clearcontext", "description": "🧹 Reset cached AI context — /clearcontext <chat_id>"},
    {"command": "syncpins", "description": "📌 Sync pinned messages into permanent context — /syncpins [chat_id]"},
    {"command": "setcontext", "description": "📝 Save permanent notes for a group — /setcontext <chat_id> <notes>"},
    {"command": "showcontext", "description": "👁️ View permanent context — /showcontext <chat_id>"},
    {"command": "gencontext", "description": "🧠 Rebuild group AI voice profile — /gencontext <chat_id>"},
    {"command": "delcontext", "description": "🗑️ Delete permanent context — /delcontext <chat_id>"},
    # -- Custom keyword rules --
    {"command": "addrule", "description": "📜 Keyword auto-reply — /addrule <word> => <reply>"},
    {"command": "delrule", "description": "🗑️ Delete keyword rule — /delrule <word>"},
    {"command": "rules", "description": "📚 List active keyword rules"},
    # -- Approvals --
    {"command": "pending", "description": "📝 List drafts waiting for approval"},
    {"command": "approve", "description": "✅ Approve a pending draft — /approve <id>"},
    {"command": "reject", "description": "❌ Reject a pending draft — /reject <id>"},
    # -- Data & maintenance --
    {"command": "backup", "description": "💾 Backup database & settings — /backup <directory>"},
    # -- Access management (main owner) --
    {"command": "authlist", "description": "👥 Authorized users & their permissions"},
    {"command": "addauth", "description": "👤 Add authorized user — /addauth <user_id>"},
    {"command": "removeauth", "description": "👋 Remove authorized user — /removeauth <user_id>"},
    {"command": "grantperm", "description": "🔑 Restrict user to commands — /grantperm <user_id> all|/status,/prompt"},
    {"command": "revokeperm", "description": "🔓 Remove user command restrictions — /revokeperm <user_id>"},
    {"command": "miniapp", "description": "📱 Launch TeleAutomator Mini App — /miniapp"},
]


def quick_menu_markup(miniapp_url: Optional[str] = None) -> dict:
    """Inline quick-action keyboard attached to key cards (welcome, /start, /status, /help).
    Callbacks arrive as 'cmd:<command>' and are routed through the normal command engine."""
    rows = []
    if not miniapp_url:
        try:
            from app.miniapp_server import resolve_miniapp_url
            miniapp_url = resolve_miniapp_url()
        except Exception:
            miniapp_url = None

    if miniapp_url:
        rows.append([{"text": "Open", "web_app": {"url": miniapp_url}}])

    rows.extend([
        [
            {"text": "📊 Status", "callback_data": "cmd:/status"},
            {"text": "📝 Pending", "callback_data": "cmd:/pending"},
        ],
        [
            {"text": "⏸ Pause 30m", "callback_data": "cmd:/pause 30"},
            {"text": "▶️ Resume", "callback_data": "cmd:/resume"},
        ],
        [
            {"text": "🛡 Safe-mode", "callback_data": "cmd:/safemode"},
            {"text": "🤖 AI Config", "callback_data": "cmd:/aiconfig"},
        ],
        [
            {"text": "📋 Chats", "callback_data": "cmd:/chats"},
            {"text": "📖 Help", "callback_data": "cmd:/help"},
        ],
    ])
    return {"inline_keyboard": rows}


def chatty_picker_markup(chats: list[tuple[int, str]]) -> dict:
    """Inline picker for per-chat banter rates: one row per allowed group.
    Name button shows the current setting; 10/30/50/70 presets set it; DEF resets to the default band."""
    rows = []
    for cid, name in chats:
        label = name if len(name) <= 16 else name[:15] + "…"
        rows.append([
            {"text": f"💬 {label}", "callback_data": f"chatty:{cid}:show"},
            {"text": "10", "callback_data": f"chatty:{cid}:10"},
            {"text": "30", "callback_data": f"chatty:{cid}:30"},
            {"text": "50", "callback_data": f"chatty:{cid}:50"},
            {"text": "70", "callback_data": f"chatty:{cid}:70"},
            {"text": "DEF", "callback_data": f"chatty:{cid}:default"},
        ])
    if not rows:
        rows.append([{"text": "ℹ️ No allowlisted groups yet", "callback_data": "noop"}])
    return {"inline_keyboard": rows}


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
        self.seed_user_ids: set[int] = {int(x) for x in (seed_user_ids or ()) if int(x) > 0}
        self._offset: int = 0
        self._running = False
        self._me_cache: Optional[dict] = None
        self._watchdog_last_alert: float = 0.0
        # Bootstrap: seed authorized users from env (DB list persists dynamic changes)
        existing = self._load_authorized()
        if not existing and self.seed_user_ids:
            self._save_authorized(self.seed_user_ids)
            self.db.set_state("main_owner_id", str(sorted(self.seed_user_ids)[0]))
            logger.info(f"Seeded bot authorized users from env: {sorted(self.seed_user_ids)}")
        elif existing and self.seed_user_ids:
            # Synchronize seed IDs into database so all env IDs are recognized
            merged = existing.union(self.seed_user_ids)
            if merged != existing:
                self._save_authorized(merged)
                logger.info(f"Updated bot authorized users with env seed: {sorted(merged)}")
            if not self.db.get_state("main_owner_id", ""):
                self.db.set_state("main_owner_id", str(sorted(self.seed_user_ids)[0]))

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
        """Main authorized user (project owner) — first env-provided ID or saved main owner."""
        if self.seed_user_ids:
            return sorted(self.seed_user_ids)[0]
        try:
            saved = self.db.get_state("main_owner_id", "")
            if saved and int(saved) > 0:
                return int(saved)
        except Exception:
            pass
        users = self._load_authorized()
        if not users:
            return 0
        return min(users)

    def is_authorized(self, user_id: int) -> bool:
        """Read live from DB on every message so /addauth & /removeauth apply instantly."""
        if not user_id or int(user_id) <= 0:
            return False
        uid = int(user_id)
        if uid == self.main_user_id:
            return True
        authorized = self._load_authorized()
        if not authorized and self.seed_user_ids:
            return uid in self.seed_user_ids
        return uid in authorized

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

    async def send_message(
        self,
        chat_id: int,
        text: str,
        parse_markdown: bool = True,
        parse_mode: Optional[str] = None,
        reply_markup: Optional[dict] = None,
    ) -> bool:
        """Send a message via the Bot API.
        Automatically selects Markdown or HTML based on content or explicit parse_mode,
        with graceful fallback to clean text so raw formatting tags like <b> never leak."""
        if parse_mode is None:
            if "<" in text and ">" in text and any(t in text for t in ("<b>", "<i>", "<code>", "<a ", "<pre>")):
                parse_mode = "HTML"
            elif parse_markdown:
                parse_mode = "Markdown"
            else:
                parse_mode = None

        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup is not None:
            payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)

        try:
            result = await self._call("sendMessage", payload)
            if result.get("ok"):
                return True
        except Exception as e:
            logger.debug(f"Bot sendMessage primary failed for {chat_id} (parse_mode={parse_mode}): {e}")

        # Fallback for Markdown: retry as plain text (unparseable markdown entities are the usual cause)
        if parse_mode == "Markdown":
            try:
                plain_payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
                if reply_markup is not None:
                    plain_payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
                res = await self._call("sendMessage", plain_payload)
                if res.get("ok"):
                    return True
            except Exception:
                pass

        # Fallback for HTML: strip HTML tags so raw tags like <b> never leak as broken code
        if parse_mode == "HTML":
            try:
                import re
                clean_text = re.sub(r"<[^>]+>", "", text)
                plain_payload = {"chat_id": chat_id, "text": clean_text}
                if reply_markup is not None:
                    plain_payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
                res = await self._call("sendMessage", plain_payload)
                return bool(res.get("ok"))
            except Exception as e:
                logger.warning(f"Bot sendMessage fallback failed for {chat_id}: {e}")
                return False

        return False

    async def register_commands(self) -> None:
        """Publish the FULL command menu (type '/' in the bot to get every command + description)."""
        result = await self._call(
            "setMyCommands",
            {"commands": json.dumps(BOT_COMMAND_MENU, ensure_ascii=False)},
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
        main_id = self.main_user_id or (users[0] if users else 0)
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
        await self.send_alert(card, reply_markup=quick_menu_markup())

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
            await self.send_message(chat_id, BOT_COMMAND_HELP, reply_markup=quick_menu_markup())
            try:
                response = await self.reply_manager.handle_control_command("/status")
                if response:
                    await self.send_message(chat_id, response, reply_markup=quick_menu_markup())
            except Exception as e:
                logger.debug(f"Could not send status on /start: {e}")
            return

        if lowered.startswith("/authlist"):
            await self._handle_authlist(chat_id)
            return

        if lowered.startswith("/addauth"):
            if not self.is_main_user(user_id):
                await self.send_message(
                    chat_id,
                    "❌ Permission denied\nMissing: Main owner privileges\nFix: Only the main account owner can add authorized users.",
                )
                return
            if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
                await self.send_message(
                    chat_id,
                    "❌ /addauth failed\nMissing: Valid Telegram User ID\nFix: /addauth <user_id> (e.g. /addauth 123456789)",
                )
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
                await self.send_message(
                    chat_id,
                    "❌ Permission denied\nMissing: Main owner privileges\nFix: Only the main account owner can remove authorized users.",
                )
                return
            if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
                await self.send_message(
                    chat_id,
                    "❌ /removeauth failed\nMissing: Valid Telegram User ID\nFix: /removeauth <user_id> (e.g. /removeauth 123456789)",
                )
                return
            target = int(parts[1].lstrip("-"))
            users = self._load_authorized()
            if target not in users:
                await self.send_message(
                    chat_id,
                    f"❌ /removeauth failed\nMissing: User in authorized list\nFix: User `{target}` is not in the authorized list.",
                )
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
                await self.send_message(
                    chat_id,
                    "❌ Permission denied\nMissing: Main owner privileges\nFix: Only the main account owner can manage permissions.",
                )
                return
            if len(parts) < 3 or not parts[1].lstrip("-").isdigit():
                await self.send_message(
                    chat_id,
                    "❌ /grantperm failed\nMissing: Target user ID and command list\nFix: /grantperm <user_id> all — or limit to specific commands:\n/grantperm 555 /status,/prompt,/pause",
                )
                return
            target = int(parts[1].lstrip("-"))
            if target not in self._load_authorized():
                await self.send_message(
                    chat_id,
                    f"❌ /grantperm failed\nMissing: Authorized user\nFix: User `{target}` is not authorized yet. /addauth {target} first.",
                )
                return
            granted = ",".join(p.strip().lower() for p in parts[2:] if p.strip())
            if granted.lower() == "all":
                self.db.set_state(f"bot_granted_cmds_{target}", "all")
                await self.send_message(chat_id, f"✅ User `{target}` now has access to *all* commands.")
            else:
                cmds = granted.replace(" ", "").split(",")
                if not cmds or not all(c.startswith("/") for c in cmds if c):
                    await self.send_message(
                        chat_id,
                        "❌ /grantperm failed\nMissing: Valid command names\nFix: Commands must be comma-separated and start with `/` (e.g. `/status,/prompt`).",
                    )
                    return
                self.db.set_state(f"bot_granted_cmds_{target}", ",".join(sorted(set(cmds))))
                await self.send_message(chat_id, f"🔒 User `{target}` is now restricted to:\n{'  '.join(sorted(set(cmds)))}")
            await self.send_message(target, "✨ *Your bot permissions were updated by the owner.*\nType `/start` to see what you can use.")
            return

        if lowered.startswith("/revokeperm"):
            if not self.is_main_user(user_id):
                await self.send_message(
                    chat_id,
                    "❌ Permission denied\nMissing: Main owner privileges\nFix: Only the main account owner can manage permissions.",
                )
                return
            if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
                await self.send_message(
                    chat_id,
                    "❌ /revokeperm failed\nMissing: Target user ID\nFix: /revokeperm <user_id> (e.g. /revokeperm 123456789)",
                )
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
                await self.send_message(
                    chat_id,
                    "❌ Permission denied\nMissing: Main owner privileges\nFix: Only the main account owner can change watchdog settings.",
                )
                return
            if len(parts) < 2 or not parts[1].isdigit():
                curr = self.db.get_state("watchdog_minutes", "5")
                await self.send_message(
                    chat_id,
                    f"⏱️ *Watchdog threshold:* {curr} min\nUsage: `/watchdog <minutes>` — alerts you here if the main process heartbeat goes silent that long.\nExample: `/watchdog 5`",
                )
                return
            mins = max(2, int(parts[1]))
            self.db.set_state("watchdog_minutes", str(mins))
            await self.send_message(chat_id, f"⏱️ Watchdog threshold set to *{mins} minutes*.")
            return

        # Per-command permission enforcement (main owner always unrestricted)
        if not self.is_main_user(user_id) and not self._user_can(user_id, text.split()[0]):
            cmd_root = text.split()[0].split('@')[0]
            await self.send_message(
                chat_id,
                f"❌ Permission denied\nMissing: Permission for `{cmd_root}`\nFix: `{cmd_root}` is not permitted for your account. Ask the owner to grant it via `/grantperm {user_id} {cmd_root}`.",
            )
            return

        # All remaining commands route to the shared command engine of ReplyManager
        response = await self.reply_manager.handle_control_command(text)
        if response:
            if len(response) > 4000:
                response = response[:4000] + "\n…"
            # Key overview commands get the inline quick-action keyboard;
            # /chatty gets the per-chat banter picker instead
            root_cmd = text.strip().split()[0].lower().split("@")[0]
            if root_cmd in ("/status", "/help", "/miniapp", "/panel", "/gui", "/app"):
                markup = quick_menu_markup()
            elif root_cmd in ("/chatty", "/banter"):
                markup = chatty_picker_markup(self._allowed_chat_summaries())
            else:
                markup = None
            await self.send_message(chat_id, response, reply_markup=markup)

    def _allowed_chat_summaries(self) -> list[tuple[int, str]]:
        """(chat_id, display name) for every allowlisted chat — used by the /chatty picker."""
        priv, grps = self.reply_manager.privacy.get_all_allowed_chats()
        summaries = []
        for cid in sorted(priv | grps):
            meta = self.reply_manager.db.get_chat_metadata(cid) or {}
            name = meta.get("title") or f"Chat {cid}"
            summaries.append((cid, name))
        return summaries

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
        """Inline button callbacks: ✅/❌ approval cards + cmd:<command> quick-menu buttons."""
        user_id = int((cb.get("from") or {}).get("id") or 0)
        data = cb.get("data") or ""
        cb_id = cb.get("id")
        if not self.is_authorized(user_id):
            await self._call("answerCallbackQuery", {
                "callback_query_id": cb_id,
                "text": "❌ Access denied\nMissing: Authorized account\nFix: Contact @mkr_infinity. Note: Pay 100 Stars or 1 TON to @mkr_infinity for authentication.",
                "show_alert": True,
            })
            return

        if data == "noop":
            await self._call("answerCallbackQuery", {
                "callback_query_id": cb_id,
                "text": "ℹ️ No allowlisted groups yet.\nFix: Use /allowchat <group_id> to add one.",
                "show_alert": True,
            })
            return

        # Quick-menu buttons: route the embedded command through the normal engine,
        # then refresh the card in place so the chat stays clean.
        if data.startswith("cmd:"):
            command = data[4:].strip()
            message = cb.get("message") or {}
            chat_id = message.get("chat", {}).get("id")
            msg_id = message.get("message_id")
            if not command.startswith("/") or not chat_id:
                await self._call("answerCallbackQuery", {"callback_query_id": cb_id, "text": "❌ Invalid command button", "show_alert": False})
                return
            if not (self.is_main_user(user_id) or self._user_can(user_id, command)):
                await self._call("answerCallbackQuery", {
                    "callback_query_id": cb_id,
                    "text": f"❌ Permission denied\nMissing: Permission for {command.split()[0]}\nFix: `{command.split()[0]}` is not permitted for your account. Ask owner to grant it via /grantperm.",
                    "show_alert": True,
                })
                return
            response = await self.reply_manager.handle_control_command(command) or "Done."
            await self._call("answerCallbackQuery", {"callback_query_id": cb_id, "text": response[:180], "show_alert": False})
            new_text = f"⚡ *{command.split()[0]}* →\n\n{response[:3500]}"
            edited = await self._call(
                "editMessageText",
                {
                    "chat_id": chat_id,
                    "message_id": msg_id,
                    "text": new_text,
                    "parse_mode": "Markdown",
                    "reply_markup": json.dumps(quick_menu_markup(), ensure_ascii=False),
                },
            )
            if not edited.get("ok"):
                # Markdown entity failure fallback: edit as plain text
                await self._call(
                    "editMessageText",
                    {
                        "chat_id": chat_id,
                        "message_id": msg_id,
                        "text": new_text,
                        "reply_markup": json.dumps(quick_menu_markup(), ensure_ascii=False),
                    },
                )
            return

        # Per-chat banter picker: 'chatty:<chat_id>:<pct|default|show>'
        if data.startswith("chatty:"):
            _, cid_s, action = data.split(":", 2)
            try:
                cid = int(cid_s)
            except ValueError:
                await self._call("answerCallbackQuery", {"callback_query_id": cb_id, "text": "❌ Invalid chat ID", "show_alert": False})
                return
            if not (self.is_main_user(user_id) or self._user_can(user_id, "/chatty")):
                await self._call("answerCallbackQuery", {
                    "callback_query_id": cb_id,
                    "text": "❌ Permission denied\nMissing: Permission for /chatty\nFix: /chatty is not permitted for your account. Ask owner to grant via /grantperm.",
                    "show_alert": True,
                })
                return
            meta = self.reply_manager.db.get_chat_metadata(cid) or {}
            name = meta.get("title") or f"Chat {cid}"
            if action == "show":
                cur = self.reply_manager.db.get_state(f"chat_chatty_{cid}")
                if cur:
                    try:
                        text = f"💬 {name}: per-chat {int(float(cur) * 100)}% banter"
                    except ValueError:
                        text = f"💬 {name}: default band (30-60%)"
                else:
                    text = f"💬 {name}: default band (30-60%)"
                await self._call("answerCallbackQuery", {"callback_query_id": cb_id, "text": text[:180], "show_alert": False})
                return
            if action == "default":
                self.reply_manager.db.set_state(f"chat_chatty_{cid}", "")
                await self._call("answerCallbackQuery", {"callback_query_id": cb_id, "text": f"♻️ {name}: reset to default 30-60% band", "show_alert": True})
                return
            try:
                pct = max(0, min(100, int(action)))
            except ValueError:
                await self._call("answerCallbackQuery", {"callback_query_id": cb_id, "text": "❌ Invalid banter value", "show_alert": False})
                return
            self.reply_manager.db.set_state(f"chat_chatty_{cid}", str(pct / 100.0))
            await self._call("answerCallbackQuery", {"callback_query_id": cb_id, "text": f"✅ {name}: {pct}% banter (always respects cooldowns)", "show_alert": True})
            return

        if data not in ("approve", "reject") and ":" not in data:
            await self._call("answerCallbackQuery", {"callback_query_id": cb_id, "text": "ℹ️ Button recognized", "show_alert": False})
            return
        action, _, target_id = data.partition(":")
        if action not in ("approve", "reject") or not target_id.isdigit():
            await self._call("answerCallbackQuery", {"callback_query_id": cb_id, "text": "❌ Unknown action", "show_alert": False})
            return
        if not (self.is_main_user(user_id) or self._user_can(user_id, f"/{action}")):
            await self._call("answerCallbackQuery", {
                "callback_query_id": cb_id,
                "text": f"❌ Permission denied\nMissing: Permission for /{action}\nFix: /{action} is not permitted for your account. Ask owner to grant via /grantperm.",
                "show_alert": True,
            })
            return

        response = await self.reply_manager.handle_control_command(f"/{action} {target_id}") or "Done."
        # Popup answer + update the message in-place so buttons disappear and message is preserved (never delete)
        await self._call("answerCallbackQuery", {"callback_query_id": cb_id, "text": response[:180], "show_alert": True})
        message = cb.get("message") or {}
        chat_id = message.get("chat", {}).get("id")
        msg_id = message.get("message_id")
        title_action = "sent ✅" if action == "approve" else "rejected ❌"
        if response.startswith("❌") or response.startswith("⚠️"):
            title_action = "status"
        card_text = f"*Draft #{target_id} — {title_action}*\n{response}"
        try:
            if chat_id and msg_id:
                await self._call(
                    "editMessageText",
                    {
                        "chat_id": chat_id,
                        "message_id": msg_id,
                        "text": card_text,
                        "parse_mode": "Markdown",
                    },
                )
            elif chat_id:
                await self.send_message(chat_id, card_text)
        except Exception as e:
            logger.debug(f"Could not edit approval message: {e}")


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
            from app.miniapp_server import resolve_miniapp_url
            miniapp_url = resolve_miniapp_url()
            buttons = [
                [{"text": "💬 Contact @mkr_infinity", "url": "https://t.me/mkr_infinity"}]
            ]
            if miniapp_url:
                buttons.append([{"text": "📱 Open Control Panel", "web_app": {"url": miniapp_url}}])
            contact_markup = {"inline_keyboard": buttons}
            await self.send_message(chat_id, UNAUTHORIZED_MESSAGE_HTML, parse_mode="HTML", reply_markup=contact_markup)
            if strikes == 2:
                await asyncio.sleep(2.0)
                await self.send_message(chat_id, SPAM_WARNING_MESSAGE, parse_mode="HTML", reply_markup=contact_markup)
        else:
            # Silently ignored until the user is added to authorized list (reduce Railway usage)
            if strikes == 3:
                logger.info(f"Bot: ignoring unauthorized user {user_id} (spammer) until authorized.")
            self.db.set_state(key, str(strikes))

    async def send_alert(self, text: str, reply_markup: Optional[dict] = None) -> bool:
        """Route project alerts to the main account owner."""
        main_id = self.main_user_id
        if not main_id:
            logger.warning("Bot send_alert: no main user configured; alert dropped.")
            return False
        return await self.send_message(main_id, text, reply_markup=reply_markup)

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
