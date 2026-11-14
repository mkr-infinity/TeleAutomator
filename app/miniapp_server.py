"""Mini App server: serves the TeleAutomator GUI (miniapp/) and a small JSON API.

The GUI is a face over the SAME command engine the Telegram bot uses — every
button maps to a real bot command handled by ReplyManager, so the mini app and
the bot always agree. Bot commands themselves are untouched.

Auth: Telegram Mini App `initData` is validated with HMAC-SHA256 against the
bot token (per https://core.telegram.org/bots/webapps#validating-data-received-
via-the-mini-app). Access uses the SAME authorized users list as the control bot.
Unauthorized users get a paywall payload (contact + price), never the controls.

Run: stdlib http.server in a background thread; engine calls are bridged onto
the main asyncio loop with run_coroutine_threadsafe. Started from app.main.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

from app import __version__ as APP_VERSION
from app.logger import setup_logger

logger = setup_logger(__name__)

MINIAPP_DIR = Path(__file__).resolve().parent.parent / "miniapp"

# initData may be up to a day old (Telegram sends a fresh one on every app open)
INIT_DATA_MAX_AGE_SECONDS = 86400.0

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}

# Structured paywall for unauthorized users (display-only access model)
PAYWALL = {
    "title": "Access Restricted",
    "product": "TeleAutomator Control Panel",
    "body": "This control panel belongs to a private automation project — your account isn't authorized to use it yet.",
    "contact": "@mkr_infinity",
    "contact_url": "https://t.me/mkr_infinity",
    "price_line": "100 Telegram Stars or 1 TON for 1 month",
    "how_line": "Pay to @mkr_infinity on Telegram, mention TeleAutomator, and your account will be authorized.",
}


def _format_ampm(time_str: str) -> str:
    try:
        parts = time_str.strip().split(":")
        h = int(parts[0])
        m = parts[1] if len(parts) > 1 else "00"
        ampm = "PM" if h >= 12 else "AM"
        h12 = h % 12 or 12
        return f"{h12:02d}:{m} {ampm}"
    except Exception:
        return time_str


def validate_init_data(init_data: str, bot_token: str) -> Optional[dict]:
    """Validate Telegram Mini App initData. Returns the user dict, or None when invalid."""
    if not init_data or not bot_token:
        return None
    try:
        from urllib.parse import parse_qsl, unquote
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed.pop("hash", "")
        if not received_hash:
            return None
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        computed = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed, received_hash):
            raw_pairs = dict(pair.split("=", 1) for pair in init_data.split("&") if "=" in pair)
            raw_hash = raw_pairs.pop("hash", "")
            if raw_hash:
                raw_data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(raw_pairs.items()))
                raw_computed = hmac.new(secret, raw_data_check_string.encode(), hashlib.sha256).hexdigest()
                if not hmac.compare_digest(raw_computed, raw_hash):
                    return None
            else:
                return None
        auth_date = float(parsed.get("auth_date", "0"))
        if auth_date <= 0 or (time.time() - auth_date) > INIT_DATA_MAX_AGE_SECONDS:
            return None
        user_val = parsed.get("user")
        if not user_val:
            return None
        if isinstance(user_val, str):
            if user_val.startswith("%"):
                user_val = unquote(user_val)
            user = json.loads(user_val)
        else:
            user = user_val
        if not isinstance(user, dict) or not user.get("id"):
            return None
        return user
    except Exception as e:
        logger.debug(f"initData validation failed: {e}")
        return None


class MiniAppContext:
    """Everything the API needs: the bot's own managers, shared with the GUI."""

    def __init__(self, db, safety, privacy, reply_manager, generator, bot_token: str, loop=None, bot_control=None):
        self.db = db
        self.safety = safety
        self.privacy = privacy
        self.reply_manager = reply_manager
        self.generator = generator
        self.bot_token = bot_token
        self.loop = loop
        self.bot_control = bot_control


def _authorized_user_ids(ctx: MiniAppContext) -> set[int]:
    """Same source of truth as the control bot: bot_authorized_users in DB + env seed."""
    ids: set[int] = set()
    try:
        raw = ctx.db.get_state("bot_authorized_users", "")
        if raw:
            ids.update(int(x) for x in json.loads(raw))
    except Exception:
        pass
    if ctx.bot_control and getattr(ctx.bot_control, "seed_user_ids", None):
        ids.update(int(x) for x in ctx.bot_control.seed_user_ids)
    if ctx.reply_manager and hasattr(ctx.reply_manager, "config") and getattr(ctx.reply_manager.config, "bot_authorized_users", None):
        ids.update(int(x) for x in ctx.reply_manager.config.bot_authorized_users)
    return ids


def _is_main_user(ctx: MiniAppContext, user_id: int) -> bool:
    if ctx.bot_control and hasattr(ctx.bot_control, "is_main_user"):
        return ctx.bot_control.is_main_user(user_id)
    try:
        saved_main = ctx.db.get_state("main_owner_id", "")
        if saved_main and int(saved_main) > 0:
            return int(saved_main) == int(user_id)
    except Exception:
        pass
    if ctx.reply_manager and hasattr(ctx.reply_manager, "config") and getattr(ctx.reply_manager.config, "bot_authorized_users", None):
        return sorted(ctx.reply_manager.config.bot_authorized_users)[0] == int(user_id)
    users = _authorized_user_ids(ctx)
    if users:
        first_user = min(users)
        try:
            ctx.db.set_state("main_owner_id", str(first_user))
        except Exception:
            pass
        return first_user == int(user_id)
    return False


class MiniAppAPI:
    """Route handlers, kept separate from the HTTP plumbing for testability."""

    def __init__(self, ctx: MiniAppContext):
        self.ctx = ctx

    # ------------------------------------------------------------- auth

    def handle_auth(self, user: Optional[dict]) -> dict:
        if user is None:
            return {"authorized": False, "paywall": PAYWALL, "version": APP_VERSION}
        user_id = int(user["id"])
        authorized = user_id in _authorized_user_ids(self.ctx)
        payload: dict[str, Any] = {
            "authorized": authorized,
            "user": {"id": user_id, "name": user.get("first_name") or user.get("username") or str(user_id)},
            "is_main": _is_main_user(self.ctx, user_id),
        }
        if not authorized:
            payload["paywall"] = PAYWALL
        return payload

    # ------------------------------------------------------------- state

    def handle_state(self) -> dict:
        ctx = self.ctx
        priv, grps = ctx.privacy.get_all_allowed_chats()
        paused = ctx.safety.get_remaining_pause_seconds()
        mode = ctx.db.get_state("reply_mode", getattr(ctx.reply_manager.config, "reply_mode", "restricted_auto"))
        emergency = ctx.safety.is_emergency_stopped
        in_quiet, _ = ctx.safety.is_in_quiet_hours()
        safe_mode = ctx.db.get_state("safe_mode_active", "0") == "1"
        try:
            chatty_global = float(ctx.db.get_state("chatty_probability", "0.15") or 0.15)
        except (ValueError, TypeError):
            chatty_global = 0.15
        try:
            tokens_today = int(ctx.db.get_daily_token_usage())
        except Exception:
            tokens_today = 0
        ai_model = ctx.db.get_state("ai_model", getattr(getattr(ctx, "reply_manager", None), "config", None) and getattr(ctx.reply_manager.config, "ai_model", "") or "")
        ai_base_url = ctx.db.get_state("ai_base_url", getattr(getattr(ctx, "reply_manager", None), "config", None) and getattr(ctx.reply_manager.config, "ai_base_url", "") or "")
        token_stats = {}
        if hasattr(ctx.db, "get_token_usage_stats"):
            try:
                token_stats = ctx.db.get_token_usage_stats()
            except Exception:
                pass
        qh_start = ctx.db.get_state("quiet_hours_start", getattr(ctx.reply_manager.config, "quiet_hours_start", "02:00"))
        qh_end = ctx.db.get_state("quiet_hours_end", getattr(ctx.reply_manager.config, "quiet_hours_end", "08:00"))
        auto_reactions = ctx.db.get_state("auto_reactions_enabled", "1") == "1"
        multibubble = ctx.db.get_state("multibubble_enabled", "1") == "1"
        typo = ctx.db.get_state("typo_correction_enabled", "1") == "1"
        debounce = ctx.db.get_state("debounce_enabled", "1") == "1"
        followup = ctx.db.get_state("spontaneous_followup_enabled", "1") == "1"
        mention_only = ctx.db.get_state("group_mention_only", "0") == "1"
        temp = ctx.db.get_state("ai_temperature", "0.6")
        thinking = ctx.db.get_state("ai_reasoning_effort", "default")
        lang = ctx.db.get_state("chat_language") or ctx.db.get_state("reply_language") or getattr(getattr(ctx, "generator", None), "language", "english") or "english"
        maxtokens = ctx.db.get_state("ai_max_tokens", "512")
        rules = ctx.db.list_keyword_rules() if hasattr(ctx.db, "list_keyword_rules") else []
        return {
            "mode": mode,
            "state": "stopped" if emergency else ("paused" if paused > 0 else "active"),
            "paused_remaining_sec": int(paused),
            "emergency": emergency,
            "quiet_hours": in_quiet,
            "quiet_hours_start": qh_start,
            "quiet_hours_end": qh_end,
            "quiet_hours_schedule": f"{_format_ampm(qh_start)} – {_format_ampm(qh_end)} IST",
            "safe_mode": safe_mode,
            "chatty_global": chatty_global,
            "style": ctx.generator.style,
            "prompt": ctx.generator.prompt_manager.custom_prompt,
            "owner_name": ctx.generator.prompt_manager.owner_name,
            "ai_engine": type(ctx.generator.provider).__name__.replace("Provider", ""),
            "ai_model": ai_model or "",
            "ai_base_url": ai_base_url or "",
            "auto_reactions": auto_reactions,
            "multibubble": multibubble,
            "typo": typo,
            "debounce": debounce,
            "followup": followup,
            "mention_only": mention_only,
            "temperature": temp,
            "thinking": thinking,
            "lang": lang,
            "max_tokens": maxtokens,
            "rules": rules,
            "chats_allowed": len(priv | grps),
            "pending_count": len(ctx.db.list_pending_approvals()),
            "replies_24h": ctx.db.get_recent_reply_count(86400.0),
            "tokens_today": tokens_today,
            "total_tokens": token_stats.get("total_tokens", 0),
            "token_requests": token_stats.get("request_count", 0),
            "version": APP_VERSION,
        }

    # ------------------------------------------------------------- chats

    def handle_chats(self) -> dict:
        ctx = self.ctx
        priv, grps = ctx.privacy.get_all_allowed_chats()
        blocked = set()
        if hasattr(ctx.privacy, "_get_dynamic_set"):
            blocked = set(ctx.privacy._get_dynamic_set("dynamic_blocked_chats"))
        chats = []
        all_cids = sorted((priv | grps) | blocked)
        import re
        gradients = [
            "linear-gradient(135deg, #153421 0%, #1E3F2A 100%)",
            "linear-gradient(135deg, #2e1065 0%, #581c87 100%)",
            "linear-gradient(135deg, #0f2c1f 0%, #1e40af 100%)",
            "linear-gradient(135deg, #3b0764 0%, #153421 100%)",
            "linear-gradient(135deg, #164e63 0%, #064e3b 100%)",
            "linear-gradient(135deg, #312e81 0%, #4c1d95 100%)",
        ]
        for cid in all_cids:
            meta = ctx.db.get_chat_metadata(cid) or {}
            perm = ctx.db.get_permanent_context(cid) if hasattr(ctx.db, "get_permanent_context") else {}
            title = meta.get("title") or f"Chat {cid}"
            username = meta.get("username") or ""

            clean_name = re.sub(r"[^\w\s]", "", title).strip()
            words = clean_name.split()
            if len(words) >= 2:
                initials = (words[0][0] + words[1][0]).upper()
            elif words:
                initials = words[0][:2].upper()
            else:
                initials = "GP" if cid < 0 else "DM"

            avatar_bg = gradients[abs(cid) % len(gradients)]
            clean_user = username.lstrip("@").strip()
            avatar_url = f"https://t.me/i/userpic/320/{clean_user}.jpg" if clean_user else ""

            chats.append({
                "id": cid,
                "name": title,
                "username": username,
                "initials": initials,
                "avatar_bg": avatar_bg,
                "avatar_url": avatar_url,
                "type": "Group" if cid < 0 else "Private",
                "chatty": ctx.db.get_state(f"chat_chatty_{cid}") or "",
                "style": ctx.db.get_state(f"chat_style_{cid}") or "",
                "prompt": ctx.db.get_state(f"chat_prompt_{cid}") or "",
                "context": perm.get("notes") or "",
                "voice_profile": bool(ctx.db.get_state(f"chat_voice_profile_{cid}")),
                "blocked": cid in blocked,
            })
        return {"chats": chats, "chatty_global": self.handle_state()["chatty_global"]}

    def handle_pending(self) -> dict:
        rows = self.ctx.db.list_pending_approvals()
        import re
        pending_list = []
        for r in rows:
            cid = r.get("chat_id")
            meta = self.ctx.db.get_chat_metadata(cid) or {} if hasattr(self.ctx.db, "get_chat_metadata") else {}
            title = r.get("chat_title") or meta.get("title") or f"Chat {cid}"
            username = meta.get("username") or ""
            clean_user = username.lstrip("@").strip()
            avatar_url = f"https://t.me/i/userpic/320/{clean_user}.jpg" if clean_user else ""
            clean_name = re.sub(r"[^\w\s]", "", title).strip()
            words = clean_name.split()
            initials = (words[0][0] + words[1][0]).upper() if len(words) >= 2 else (words[0][:2].upper() if words else "TG")
            pending_list.append({
                "id": r["id"],
                "chat_id": cid,
                "chat_title": title,
                "username": username,
                "avatar_url": avatar_url,
                "initials": initials,
                "sender_id": r.get("sender_id"),
                "incoming_text": r.get("incoming_text") or "",
                "text": r.get("draft_text") or r.get("incoming_text") or "",
                "created": r.get("created_at") or "",
            })
        return {"pending": pending_list}

    def handle_activity(self) -> dict:
        """Recent outgoing (automated + manual) messages across chats, newest first."""
        with self.ctx.db._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT m.chat_id, m.sender_name, m.text, m.created_at,
                       COALESCE(k.title, '') AS title
                FROM chat_messages m
                LEFT JOIN known_chats k ON k.chat_id = m.chat_id
                WHERE m.is_outgoing = 1
                ORDER BY m.id DESC
                LIMIT 25
                """
            ).fetchall()
        items = []
        for r in rows:
            items.append({
                "chat": r["title"] or f"Chat {r['chat_id']}",
                "chat_id": r["chat_id"],
                "text": r["text"] or "",
                "sender": r["sender_name"] or "",
                "ts": r["created_at"] or "",
            })
        return {"activity": items}

    def handle_access(self) -> dict:
        ids = sorted(_authorized_user_ids(self.ctx))
        main_id = min(ids) if ids else None
        users = []
        for uid in ids:
            meta = self.ctx.db.get_chat_metadata(uid) or {}
            username = meta.get("username") or ""
            clean_user = username.lstrip("@").strip()
            avatar_url = f"https://t.me/i/userpic/320/{clean_user}.jpg" if clean_user else ""
            users.append({
                "id": uid,
                "name": meta.get("title") or f"User {uid}",
                "username": username,
                "avatar_url": avatar_url,
                "main": uid == main_id,
                "perms": self.ctx.db.get_state(f"bot_granted_cmds_{uid}", "all"),
            })
        return {"users": users}

    # ------------------------------------------------------------- actions

    ACTION_TO_COMMAND = {
        "pause": "/pause {minutes}",
        "resume": "/resume",
        "stop": "/stop",
        "mode": "/mode {value}",
        "style": "/style {value}",
        "lang": "/lang {value}",
        "name": "/name {value}",
        "prompt": "/prompt {value}",
        "chatty_global": "/chatty {value}",
        "chatprompt": "/chatprompt {chat_id} {value}",
        "chatstyle": "/style {chat_id} {value}",
        "allow": "/allowchat {chat_id}",
        "remove": "/removechat {chat_id}",
        "block": "/blockchat {chat_id}",
        "clearcontext": "/clearcontext {chat_id}",
        "syncpins": "/syncpins {chat_id}",
        "setcontext": "/setcontext {chat_id} {value}",
        "delcontext": "/delcontext {chat_id}",
        "gencontext": "/gencontext {chat_id}",
        "approve": "/approve {id}",
        "reject": "/reject {id}",
        "setai": "/setai {provider} {value}",
        "apikey": "/apikey {value}",
        "baseurl": "/baseurl {value}",
        "model": "/model {value}",
        "provider": "/provider {value}",
        "temp": "/temp {value}",
        "maxtokens": "/maxtokens {value}",
        "thinking": "/thinking {value}",
        "chatcooldown": "/chatcooldown {value1} {value2}",
        "globalcooldown": "/globalcooldown {value1} {value2}",
        "ratelimit": "/ratelimit {value}",
        "quiethours": "/quiethours {value}",
        "reaction": "/reaction {value}",
        "mentiononly": "/mentiononly {value}",
        "debounce": "/debounce {value}",
        "multibubble": "/multibubble {value}",
        "typo": "/typo {value}",
        "editfix": "/editfix {value}",
        "followup": "/followup {value}",
        "addrule": "/addrule {value}",
        "delrule": "/delrule {value}",
        "sleep": "/sleep {value}",
        "backup": "/backup",
    }

    def map_action_to_command(self, action: str, params: dict) -> Optional[str]:
        template = self.ACTION_TO_COMMAND.get(action)
        if not template:
            return None
        filled = template.format(
            minutes=params.get("minutes", 30),
            value=str(params.get("value", "")),
            value1=str(params.get("value1", "")),
            value2=str(params.get("value2", "")),
            chat_id=params.get("chat_id", ""),
            provider=params.get("provider", ""),
            id=params.get("id", ""),
        ).strip()
        # Drop unpopulated placeholders while preserving multi-line user content
        import re
        cleaned = re.sub(r"\{[a-zA-Z0-9_]+\}", "", filled)
        cmd_name, _, rest = cleaned.partition(" ")
        return f"{cmd_name} {rest.strip()}".strip()

    def handle_action(self, user_id: int, action: str, params: dict) -> dict:
        """GUI buttons become real bot commands run through the same engine."""
        ctx = self.ctx
        if action in ("addauth", "removeauth"):
            return self._handle_access_change(user_id, action, params)
        if action == "chat_chatty":
            # Same state the bot's inline picker writes
            cid = int(params.get("chat_id", 0))
            value = str(params.get("value", "")).strip()
            if value.lower() in ("def", "default", ""):
                ctx.db.set_state(f"chat_chatty_{cid}", "")
                return {"ok": True, "response": f"Chatty for chat {cid} reset to the default 30-60% band."}
            pct = max(0, min(100, int(float(value))))
            ctx.db.set_state(f"chat_chatty_{cid}", str(pct / 100.0))
            return {"ok": True, "response": f"Chatty for chat {cid} set to {pct}%."}
        command = self.map_action_to_command(action, params)
        if not command:
            return {"ok": False, "response": f"Unknown action: {action}"}
        return self.run_command(command)

    def _handle_access_change(self, requester_id: int, action: str, params: dict) -> dict:
        """Add/remove authorized users — GUI equivalent of the bot's /addauth //removeauth."""
        ctx = self.ctx
        if not _is_main_user(ctx, requester_id):
            return {"ok": False, "response": "Only the main owner can manage authorized users."}
        try:
            target = int(params.get("user_id", 0))
        except (TypeError, ValueError):
            return {"ok": False, "response": "User ID must be an integer."}
        if target <= 0:
            return {"ok": False, "response": "Provide a valid Telegram user ID."}
        users = _authorized_user_ids(ctx)
        if action == "addauth":
            users.add(target)
            ctx.db.set_state("bot_authorized_users", json.dumps(sorted(users)))
            return {"ok": True, "response": f"User {target} added to authorized users."}
        if _is_main_user(ctx, target):
            return {"ok": False, "response": "The main owner cannot be removed."}
        users.discard(target)
        ctx.db.set_state("bot_authorized_users", json.dumps(sorted(users)))
        return {"ok": True, "response": f"User {target} removed from authorized users."}

    def run_command(self, command: str) -> dict:
        """Run a bot command through the shared engine on the main asyncio loop."""
        ctx = self.ctx
        if not command.startswith("/"):
            command = "/" + command
        if ctx.loop is None or ctx.loop.is_closed():
            # Headless (tests): run inline
            import asyncio
            response = asyncio.run(ctx.reply_manager.handle_control_command(command))
            return {"ok": response is not None, "response": response or "No response."}
        import asyncio

        async def _run():
            return await ctx.reply_manager.handle_control_command(command)

        future = asyncio.run_coroutine_threadsafe(_run(), ctx.loop)
        try:
            response = future.result(timeout=45.0)
        except Exception as e:
            logger.error(f"Mini app command '{command}' failed: {e}")
            return {"ok": False, "response": f"Command failed: {e}"}
        return {"ok": response is not None, "response": response or "No response."}

    def handle_fetch_models(self, base_url: str = "", api_key: Optional[str] = None) -> dict:
        """Fetch available models from an OpenAI-compatible /models endpoint."""
        raw_url = (base_url or "").strip().rstrip("/")
        if not raw_url:
            raw_url = (
                self.ctx.db.get_state("ai_base_url")
                or (getattr(getattr(self.ctx, "reply_manager", None), "config", None) and getattr(self.ctx.reply_manager.config, "ai_base_url", ""))
                or "https://api.openai.com/v1"
            )
        if raw_url.endswith("/chat/completions"):
            raw_url = raw_url[:-len("/chat/completions")].rstrip("/")
        models_url = raw_url if raw_url.endswith("/models") else f"{raw_url}/models"

        key = (
            api_key
            or self.ctx.db.get_state("ai_api_key")
            or (getattr(getattr(self.ctx, "reply_manager", None), "config", None) and getattr(self.ctx.reply_manager.config, "ai_api_key", ""))
            or ""
        )
        headers = {"Accept": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"

        req = urllib.request.Request(models_url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                raw_data = body.get("data") if isinstance(body, dict) else (body if isinstance(body, list) else [])
                if raw_data is None and isinstance(body, dict):
                    raw_data = body.get("models") or []
                models = []
                if isinstance(raw_data, list):
                    for item in raw_data:
                        if isinstance(item, dict) and "id" in item:
                            models.append(str(item["id"]))
                        elif isinstance(item, str):
                            models.append(item)
                models = sorted(list(dict.fromkeys(models)))
                return {"ok": True, "models": models, "url": models_url}
        except urllib.error.HTTPError as e:
            err_msg = f"HTTP {e.code}"
            try:
                eb = json.loads(e.read().decode("utf-8"))
                if isinstance(eb, dict) and "error" in eb:
                    err_msg = f"HTTP {e.code}: {eb['error'].get('message', eb['error'])}"
            except Exception:
                pass
            return {"ok": False, "error": err_msg, "url": models_url}
        except Exception as e:
            return {"ok": False, "error": str(e), "url": models_url}

    def handle_test_model(
        self,
        message: str = "hello",
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> dict:
        """Test chat message live in the GUI, test candidates, auto-prune dead models, and auto-save working rotation."""
        prompt = (message or "hello").strip()
        raw_base = (
            base_url
            or self.ctx.db.get_state("ai_base_url")
            or (getattr(getattr(self.ctx, "reply_manager", None), "config", None) and getattr(self.ctx.reply_manager.config, "ai_base_url", ""))
            or "https://api.openai.com/v1"
        ).strip()
        endpoint = raw_base.rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint = f"{endpoint}/chat/completions"

        key = (
            api_key
            or self.ctx.db.get_state("ai_api_key")
            or (getattr(getattr(self.ctx, "reply_manager", None), "config", None) and getattr(self.ctx.reply_manager.config, "ai_api_key", ""))
            or ""
        )

        model_param = (
            model
            or self.ctx.db.get_state("ai_model")
            or (getattr(getattr(self.ctx, "reply_manager", None), "config", None) and getattr(self.ctx.reply_manager.config, "ai_model", ""))
            or "gpt-4o-mini"
        )
        candidates = [m.strip() for m in model_param.replace(";", ",").split(",") if m.strip()]
        if not candidates:
            candidates = ["gpt-4o-mini"]

        results: list[dict] = []
        working_models: list[str] = []
        reply_text = ""
        first_working_model = ""

        for m in candidates:
            payload = {
                "model": m,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 150,
                "temperature": 0.7,
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                endpoint,
                data=data,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=12.0) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                    choices = body.get("choices", [])
                    if choices:
                        content = choices[0].get("message", {}).get("content") or ""
                        content = str(content).strip()
                        if content and content.lower() not in ("none", "null", "undefined"):
                            working_models.append(m)
                            results.append({"model": m, "ok": True, "detail": "Working"})
                            if not reply_text:
                                reply_text = content
                                first_working_model = m
                            continue
                    results.append({"model": m, "ok": False, "detail": "Empty response"})
            except urllib.error.HTTPError as e:
                detail = f"HTTP {e.code}"
                try:
                    eb = json.loads(e.read().decode("utf-8"))
                    if isinstance(eb, dict) and "error" in eb:
                        detail = f"HTTP {e.code}: {eb['error'].get('message', eb['error'])}"[:45]
                except Exception:
                    pass
                results.append({"model": m, "ok": False, "detail": detail})
            except Exception as e:
                results.append({"model": m, "ok": False, "detail": str(e)[:45]})

        updated_chain = ""
        if working_models:
            updated_chain = ",".join(working_models)
            self.ctx.db.set_state("ai_model", updated_chain)
            if hasattr(self.ctx.generator, "provider") and self.ctx.generator.provider:
                self.ctx.generator.provider.model = updated_chain
            if base_url:
                self.ctx.db.set_state("ai_base_url", base_url)
            if api_key:
                self.ctx.db.set_state("ai_api_key", api_key)

        return {
            "ok": len(working_models) > 0,
            "reply": reply_text or "No reply received.",
            "model_used": first_working_model,
            "working_models": working_models,
            "failed_models": [r["model"] for r in results if not r["ok"]],
            "results": results,
            "active_model": updated_chain or model_param,
        }


class MiniAppRequestHandler(BaseHTTPRequestHandler):
    api: MiniAppAPI = None  # injected at server construction
    static_dir: Path = MINIAPP_DIR

    # ---------------------------------------------------------------- utils

    def _init_user(self) -> Optional[dict]:
        init_data = self.headers.get("X-Telegram-Init-Data", "")
        if not init_data and "?" in self.path:
            try:
                from urllib.parse import parse_qs, urlparse
                qs = parse_qs(urlparse(self.path).query)
                init_data = qs.get("initData", [""])[0]
            except Exception:
                pass
        bot_token = self.api.ctx.bot_token if self.api else ""
        return validate_init_data(init_data, bot_token)

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _unauthorized_payload(self) -> dict:
        return {"authorized": False, "paywall": PAYWALL, "version": APP_VERSION}

    def log_message(self, fmt, *args):  # quiet default access logs
        logger.debug(f"miniapp http: {self.address_string()} {fmt % args}")

    # ---------------------------------------------------------------- routes

    def do_GET(self):  # noqa: N802 - stdlib naming
        path = self.path.split("?", 1)[0]
        if path == "/api/health":
            hs = getattr(self.api.ctx, "health_status", None)
            if hs and not hs.get("healthy", True):
                self._json(503, {"status": "error", "service": "teleautomator", "reason": hs.get("error") or "unhealthy"})
            else:
                self._json(200, {"status": "healthy", "service": "teleautomator"})
            return
        if path == "/api/version":
            self._json(200, {"version": APP_VERSION, "service": "teleautomator"})
            return
        # Static assets (index.html, style.css, app.js) are public: they carry no
        # data. Every /api/* route gates on initData; the page shows the paywall
        # client-side when auth fails, and Telegram fetches assets without initData.
        if not path.startswith("/api/"):
            try:
                self._serve_static(path)
            except Exception as e:
                logger.error(f"Mini app static error on {path}: {e}")
                self._json(500, {"ok": False, "response": f"Server error: {e}"})
            return
        user = self._init_user()
        if path == "/api/auth":
            # Auth works for everyone (browser visitors included): it answers the paywall
            self._json(200, self.api.handle_auth(user))
            return
        if user is None or int(user.get("id", 0)) not in _authorized_user_ids(self.api.ctx):
            self._json(401, self._unauthorized_payload())
            return
        if path == "/api/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                last_hash = None
                for _ in range(30):  # 30 * 2s = 60s stream window, client auto-reconnects
                    cur_state = self.api.handle_state()
                    h = (cur_state.get("mode"), cur_state.get("state"), cur_state.get("pending_count"), cur_state.get("chats_allowed"))
                    if h != last_hash:
                        last_hash = h
                        self.wfile.write(f"event: state\ndata: {json.dumps(cur_state)}\n\n".encode("utf-8"))
                        self.wfile.flush()
                    else:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                    time.sleep(2.0)
            except Exception:
                pass
            return
        try:
            if path == "/api/state":
                self._json(200, self.api.handle_state())
            elif path == "/api/chats":
                self._json(200, self.api.handle_chats())
            elif path == "/api/pending":
                self._json(200, self.api.handle_pending())
            elif path == "/api/activity":
                self._json(200, self.api.handle_activity())
            elif path == "/api/access":
                self._json(200, self.api.handle_access())
            elif path == "/api/commands":
                from app.bot_control import BOT_COMMAND_MENU
                self._json(200, {"commands": BOT_COMMAND_MENU})
            elif path in ("/api/models", "/api/fetch_models"):
                self._json(200, self.api.handle_fetch_models(""))
            else:
                self._serve_static(path)
        except Exception as e:
            logger.error(f"Mini app API error on {path}: {e}")
            self._json(500, {"ok": False, "response": f"Server error: {e}"})

    def do_POST(self):  # noqa: N802 - stdlib naming
        path = self.path.split("?", 1)[0]
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._json(400, {"ok": False, "response": "Invalid JSON body."})
            return
        user = self._init_user()
        if path == "/api/auth":
            # initData may also arrive in the POST body (browser builds it via Telegram widget)
            if user is None and isinstance(body.get("initData"), str):
                user = validate_init_data(body["initData"], self.api.ctx.bot_token)
            self._json(200, self.api.handle_auth(user))
            return
        if user is None or int(user.get("id", 0)) not in _authorized_user_ids(self.api.ctx):
            self._json(401, self._unauthorized_payload())
            return
        user_id = int(user["id"])
        try:
            if path == "/api/cmd":
                command = str(body.get("command", "")).strip()
                if not command or len(command) > 500:
                    self._json(400, {"ok": False, "response": "Provide a command."})
                    return
                self._json(200, self.api.run_command(command))
            elif path == "/api/action":
                action = str(body.get("action", "")).strip()
                params = body.get("params") or {}
                if not action:
                    self._json(400, {"ok": False, "response": "Provide an action."})
                    return
                self._json(200, self.api.handle_action(user_id, action, params))
            elif path == "/api/fetch_models":
                base_url = str(body.get("base_url") or "").strip()
                api_key = str(body.get("api_key") or "").strip() or None
                self._json(200, self.api.handle_fetch_models(base_url, api_key))
            elif path == "/api/test_model":
                message = str(body.get("message") or "hello").strip()
                model = str(body.get("model") or "").strip() or None
                base_url = str(body.get("base_url") or "").strip() or None
                api_key = str(body.get("api_key") or "").strip() or None
                self._json(200, self.api.handle_test_model(message, model, base_url, api_key))
            else:
                self._json(404, {"ok": False, "response": "Unknown endpoint."})
        except Exception as e:
            logger.error(f"Mini app API error on {path}: {e}")
            self._json(500, {"ok": False, "response": f"Server error: {e}"})

    # ---------------------------------------------------------------- static

    def _serve_static(self, path: str) -> None:
        if path in ("/", "/index.html"):
            file_path = self.static_dir / "index.html"
        else:
            safe = path.lstrip("/").replace("..", "").replace("\\", "")
            file_path = self.static_dir / safe
        if not file_path.is_file():
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
            return
        content_type = CONTENT_TYPES.get(file_path.suffix, "application/octet-stream")
        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)


def resolve_miniapp_url() -> str:
    """Resolve the public HTTPS URL for the Telegram Mini App.
    Auto-detects Railway (RAILWAY_PUBLIC_DOMAIN / RAILWAY_STATIC_URL), Render,
    or user-configured MINIAPP_URL / CUSTOM_DOMAIN.
    """
    import os
    # 1. Explicit user override (for custom domain in future)
    custom = (
        os.getenv("MINIAPP_URL")
        or os.getenv("CUSTOM_DOMAIN")
        or os.getenv("APP_URL")
        or ""
    ).strip()
    if custom:
        if not custom.startswith("http://") and not custom.startswith("https://"):
            custom = f"https://{custom}"
        return custom.rstrip("/")

    # 2. Railway auto-generated domain (all-in-one Railway style, zero extra domain needed)
    railway = (
        os.getenv("RAILWAY_PUBLIC_DOMAIN")
        or os.getenv("RAILWAY_STATIC_URL")
        or ""
    ).strip()
    if railway:
        if not railway.startswith("http://") and not railway.startswith("https://"):
            railway = f"https://{railway}"
        return railway.rstrip("/")

    # 3. Render auto-generated domain
    render = (os.getenv("RENDER_EXTERNAL_HOSTNAME") or "").strip()
    if render:
        return f"https://{render}".rstrip("/")

    return ""


def set_telegram_menu_button(
    bot_token: str,
    miniapp_url: str,
    button_text: str = "Open",
) -> bool:
    """Register the mini app as the bot's chat menu button (does NOT touch commands)."""
    if not bot_token or not miniapp_url:
        return False
    payload = json.dumps({
        "menu_button": {"type": "web_app", "text": button_text, "web_app": {"url": miniapp_url}},
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/setChatMenuButton",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            if result.get("ok"):
                logger.info(f"Mini app registered as the bot's menu button ('{button_text}'): {miniapp_url}")
                return True
            else:
                logger.warning(f"setChatMenuButton failed: {result}")
                return False
    except Exception as e:
        logger.warning(f"Could not set chat menu button ({miniapp_url}): {e}")
        return False


class MiniAppServer:
    """Owns the HTTP server thread."""

    def __init__(self, ctx: MiniAppContext, port: int = 8080):
        self.ctx = ctx
        self.port = port
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread = None

    def start(self) -> None:
        handler = type("BoundHandler", (MiniAppRequestHandler,), {"api": MiniAppAPI(self.ctx)})
        self._httpd = ThreadingHTTPServer(("0.0.0.0", self.port), handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True, name="miniapp-server")
        self._thread.start()
        logger.info(f"Mini app server listening on port {self.port} (GUI: miniapp/, API: /api/*)")

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()

    @property
    def is_running(self) -> bool:
        return self._httpd is not None
