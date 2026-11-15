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
import gzip
import json
import math
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

from app import __version__ as APP_VERSION
from app.ai.provider import normalize_base_url
from app.ai.reply_generator import create_ai_provider
from app.bot_control import authorized_user_ids, can_run_command, save_authorized_users
from app.logger import setup_logger
from app.settings_transfer import MAX_BACKUP_BYTES, export_preferences, validate_preferences

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
        if not math.isfinite(auth_date) or auth_date <= 0 or auth_date > time.time() + 300 or (time.time() - auth_date) > INIT_DATA_MAX_AGE_SECONDS:
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
        self.settings_downloads = {}
        self.settings_download_lock = threading.Lock()


def _seed_user_ids(ctx: MiniAppContext) -> set[int]:
    ids: set[int] = set()
    if ctx.bot_control and getattr(ctx.bot_control, "seed_user_ids", None):
        ids.update(int(x) for x in ctx.bot_control.seed_user_ids)
    if ctx.reply_manager and hasattr(ctx.reply_manager, "config") and getattr(ctx.reply_manager.config, "bot_authorized_users", None):
        ids.update(int(x) for x in ctx.reply_manager.config.bot_authorized_users)
    return ids


def _authorized_user_ids(ctx: MiniAppContext) -> set[int]:
    ids = authorized_user_ids(ctx.db, _seed_user_ids(ctx))
    saved_main = ctx.db.get_state("main_owner_id", "")
    if saved_main.isdigit() and int(saved_main) > 0:
        ids.add(int(saved_main))
    return ids


def _is_main_user(ctx: MiniAppContext, user_id: int) -> bool:
    return _main_user_id(ctx) == int(user_id)


def _main_user_id(ctx: MiniAppContext) -> Optional[int]:
    if ctx.bot_control and hasattr(ctx.bot_control, "main_user_id"):
        return ctx.bot_control.main_user_id
    try:
        saved_main = ctx.db.get_state("main_owner_id", "")
        if saved_main and int(saved_main) > 0:
            return int(saved_main)
    except Exception:
        pass
    if ctx.reply_manager and hasattr(ctx.reply_manager, "config") and getattr(ctx.reply_manager.config, "bot_authorized_users", None):
        return sorted(ctx.reply_manager.config.bot_authorized_users)[0]
    users = _authorized_user_ids(ctx)
    if users:
        owner = min(users)
        ctx.db.set_state("main_owner_id", str(owner))
        return owner
    return None


class MiniAppAPI:
    """Route handlers, kept separate from the HTTP plumbing for testability."""

    def __init__(self, ctx: MiniAppContext):
        self.ctx = ctx

    def command_denial(self, user_id: int, command: str) -> Optional[dict]:
        if user_id not in _authorized_user_ids(self.ctx):
            return {"ok": False, "response": "This account is not authorized."}
        if not can_run_command(self.ctx.db, user_id, command, _main_user_id(self.ctx)):
            return {"ok": False, "response": f"Permission denied for {command.split()[0]}. Ask the owner to grant this command."}
        return None

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
            "can_feedback": authorized and can_run_command(self.ctx.db, user_id, "/feedback", _main_user_id(self.ctx)),
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
        configured_chatty = getattr(ctx.reply_manager.config, "chatty_probability", 0.15)
        try:
            chatty_global = float(ctx.db.get_state("chatty_probability", str(configured_chatty)))
            if not math.isfinite(chatty_global):
                chatty_global = configured_chatty
        except (ValueError, TypeError):
            chatty_global = configured_chatty
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
        auto_reactions = ctx.db.get_state("reaction_enabled", "1" if getattr(ctx.reply_manager.config, "reaction_enabled", True) else "0") == "1"
        ownreact = ctx.db.get_state("ownreact_enabled", "1") == "1"
        multibubble = ctx.db.get_state("multibubble_enabled", "1") == "1"
        typo = ctx.db.get_state("typo_correction_enabled", "1") == "1"
        debounce = ctx.db.get_state("debounce_enabled", "1") == "1"
        followup = ctx.db.get_state("spontaneous_followup_enabled", "1") == "1"
        mention_only = ctx.db.get_state("group_mention_only", "0") == "1"
        temp = ctx.db.get_state("ai_temperature", "0.6")
        thinking = ctx.db.get_state("ai_reasoning_effort", "default")
        lang = ctx.db.get_state("chat_language") or ctx.db.get_state("reply_language") or getattr(getattr(ctx, "generator", None), "language", "english") or "english"
        maxtokens = ctx.db.get_state("ai_max_tokens", "") or "default"
        rules = ctx.db.list_keyword_rules() if hasattr(ctx.db, "list_keyword_rules") else []

        # Available models list (custom/endpoint or defaults)
        raw_avail = ctx.db.get_state("available_models", "")
        avail_models: list[str] = []
        if raw_avail:
            try:
                avail_models = json.loads(raw_avail)
            except Exception:
                pass
        if not avail_models:
            configured = ai_model or getattr(ctx.generator.provider, "model", "")
            avail_models = [m.strip() for m in configured.replace(";", ",").split(",") if m.strip()]

        return {
            "revision": ctx.db.get_state("state_revision", "0"),
            "history_revision": ctx.db.latest_action_id(),
            "pipeline": {"context": "Per-chat files and batched summaries", "writer": "Selected model", "humanizer": "Local checks; no extra model call",
                         "context_jobs": len(getattr(getattr(ctx.reply_manager, "context_agent", None), "busy", ()))},
            "mode": mode,
            "state": "stopped" if emergency else ("paused" if paused > 0 else "active"),
            "paused_remaining_sec": int(paused),
            "emergency": emergency,
            "quiet_hours": in_quiet,
            "quiet_hours_enabled": getattr(ctx.safety, "quiet_hours_enabled", ctx.db.get_state("quiet_hours_enabled", "1") == "1"),
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
            "available_models": avail_models,
            "models_manually_set": ctx.db.get_state("models_manually_set", "0") == "1",
            "auto_reactions": auto_reactions,
            "ownreact": ownreact,
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
            "pending_count": ctx.db.count_pending_approvals(),
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
        default_min = getattr(ctx.safety, "min_chat_cooldown", 5.0)
        default_max = getattr(ctx.safety, "max_chat_cooldown", 60.0)
        all_cids = sorted((priv | grps) | blocked)
        metadata, contexts, settings = ctx.db.get_chat_panel_data(all_cids)
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
            meta = metadata.get(cid, {})
            perm = contexts.get(cid, {})
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

            c_min_str = settings.get(f"chat_cooldown_min_{cid}") or ""
            c_max_str = settings.get(f"chat_cooldown_max_{cid}") or ""
            cooldown_min = None
            cooldown_max = None
            cooldown_str = ""
            if c_min_str != "" and c_max_str != "":
                try:
                    cooldown_min = float(c_min_str)
                    cooldown_max = float(c_max_str)
                    if not (math.isfinite(cooldown_min) and math.isfinite(cooldown_max) and 0 <= cooldown_min <= cooldown_max):
                        raise ValueError("Invalid saved cooldown")
                    if cooldown_min == 0.0 and cooldown_max == 0.0:
                        cooldown_str = "0s (No chat wait; global cooldown applies)"
                    else:
                        cooldown_str = f"{int(cooldown_min)}s - {int(cooldown_max)}s"
                except (ValueError, TypeError, OverflowError):
                    cooldown_min = cooldown_max = None
                    cooldown_str = ""

            chats.append({
                "id": cid,
                "name": title,
                "username": username,
                "initials": initials,
                "avatar_bg": avatar_bg,
                "avatar_url": avatar_url,
                "type": "Group" if cid < 0 else "Private",
                "chatty": settings.get(f"chat_chatty_{cid}") or "",
                "style": settings.get(f"chat_style_{cid}") or "",
                "prompt": settings.get(f"chat_prompt_{cid}") or "",
                "context": perm.get("notes") or "",
                "cooldown_min": cooldown_min,
                "cooldown_max": cooldown_max,
                "cooldown_default_min": default_min,
                "cooldown_default_max": default_max,
                "cooldown_str": cooldown_str,
                "voice_profile": bool(settings.get(f"chat_voice_profile_{cid}")),
                "blocked": cid in blocked,
            })
        try:
            chatty_global = float(ctx.db.get_state("chatty_probability", str(getattr(ctx.reply_manager.config, "chatty_probability", 0.15))))
            if not math.isfinite(chatty_global):
                chatty_global = getattr(ctx.reply_manager.config, "chatty_probability", 0.15)
        except (ValueError, TypeError):
            chatty_global = 0.15
        return {"chats": chats, "chatty_global": chatty_global}

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
        return {"pending": pending_list, "total": self.ctx.db.count_pending_approvals(),
                "batch_running": bool(getattr(self.ctx.reply_manager, "_approval_batch_task", None) and not self.ctx.reply_manager._approval_batch_task.done())}

    def handle_activity(self) -> dict:
        """Recent outgoing (automated + manual) messages across chats, newest first."""
        with self.ctx.db._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT m.chat_id, m.message_id, m.sender_name, m.text, m.created_at, m.is_automated,
                       COALESCE(f.rating,'') AS feedback,
                       COALESCE(k.title, '') AS title,
                       COALESCE(k.username, '') AS username
                FROM chat_messages m
                LEFT JOIN known_chats k ON k.chat_id = m.chat_id
                LEFT JOIN reply_feedback f ON f.chat_id=m.chat_id AND f.message_id=m.message_id
                WHERE m.is_outgoing = 1
                ORDER BY m.id DESC
                LIMIT 25
                """
            ).fetchall()
        items = []
        private, groups = self.ctx.privacy.get_all_allowed_chats()
        allowed = private | groups
        for r in rows:
            cid = r["chat_id"]
            if cid not in allowed:
                continue
            mid = r["message_id"]
            username = (r["username"] or "").lstrip("@").strip()
            msg_url = ""
            if mid and mid > 0:
                if username:
                    msg_url = f"https://t.me/{username}/{mid}"
                elif str(cid).startswith("-100"):
                    clean_cid = str(cid)[4:]
                    msg_url = f"https://t.me/c/{clean_cid}/{mid}"
                elif cid > 0:
                    msg_url = f"https://t.me/c/{cid}/{mid}"

            items.append({
                "chat": r["title"] or f"Chat {cid}",
                "chat_id": cid,
                "message_id": mid,
                "is_automated": bool(r["is_automated"]),
                "feedback": r["feedback"],
                "msg_url": msg_url,
                "text": r["text"] or "",
                "sender": r["sender_name"] or "",
                "ts": r["created_at"] or "",
            })
        return {"activity": items}

    def handle_feedback(self, rating="") -> dict:
        if rating not in ("", "helpful", "unnecessary", "off_topic", "style"):
            return {"ok": False, "response": "Choose a valid feedback filter"}
        private, groups = self.ctx.privacy.get_all_allowed_chats()
        rows = self.ctx.db.list_reply_feedback(private | groups, limit=500)
        counts = {key: sum(row["rating"] == key for row in rows) for key in ("helpful", "unnecessary", "off_topic", "style")}
        return {"ok": True, "feedback": [row for row in rows if not rating or row["rating"] == rating][:40], "counts": counts}

    def handle_access(self) -> dict:
        ids = sorted(_authorized_user_ids(self.ctx))
        main_id = _main_user_id(self.ctx)
        if main_id and main_id not in ids:
            ids.append(main_id)
            ids.sort()

        gradients = [
            "linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%)",
            "linear-gradient(135deg, #065f46 0%, #10b981 100%)",
            "linear-gradient(135deg, #701a75 0%, #d946ef 100%)",
            "linear-gradient(135deg, #831843 0%, #f43f5e 100%)",
            "linear-gradient(135deg, #1e293b 0%, #64748b 100%)",
            "linear-gradient(135deg, #0f2c1f 0%, #1e40af 100%)",
        ]

        users = []
        for uid in ids:
            meta = self.ctx.db.get_chat_metadata(uid) or {} if hasattr(self.ctx.db, "get_chat_metadata") else {}
            username = meta.get("username") or ""
            clean_user = username.lstrip("@").strip()
            avatar_url = f"https://t.me/i/userpic/320/{clean_user}.jpg" if clean_user else ""
            title = meta.get("title") or ("Main Owner" if uid == main_id else f"User {uid}")
            clean_name = re.sub(r"[^\w\s]", "", title).strip()
            words = clean_name.split()
            if len(words) >= 2:
                initials = (words[0][0] + words[1][0]).upper()
            elif words:
                initials = words[0][:2].upper()
            else:
                initials = "OW" if uid == main_id else "US"

            avatar_bg = gradients[abs(uid) % len(gradients)]
            users.append({
                "id": uid,
                "name": title,
                "username": username,
                "avatar_url": avatar_url,
                "avatar_bg": avatar_bg,
                "initials": initials,
                "main": uid == main_id,
                "perms": self.ctx.db.get_state(f"bot_granted_cmds_{uid}", "all"),
            })
        return {"users": users}

    # ------------------------------------------------------------- actions

    ACTION_TO_COMMAND = {
        "feedback": "/feedback {chat_id} {id} {value}",
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
        "approve_all": "/approve all",
        "reject": "/reject {id}",
        "reject_all": "/reject all",
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
        "ownreact": "/ownreact {value}",
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
        "safemode": "/safemode {value}",
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
        if not isinstance(params, dict):
            return {"ok": False, "response": "Action parameters must be an object"}
        known = action in self.ACTION_TO_COMMAND or action in {"chat_chatty", "chat_cooldown", "save_available_models", "safemode_reset", "emergencystop", "addauth", "removeauth"}
        label = action if known else "unknown_action"
        try:
            result = self._perform_action(user_id, action, params)
        except (ValueError, TypeError, OverflowError):
            self.ctx.db.record_action("miniapp", label, "failed", "Invalid action parameters", actor_id=user_id)
            return {"ok": False, "response": "Invalid action parameters. Review the values and try again."}
        except Exception:
            self.ctx.db.record_action("miniapp", label, "failed", "Action failed; review its inputs", actor_id=user_id)
            raise
        self.ctx.db.record_action("miniapp", label, "success" if result.get("ok") else "failed",
                                  "Action completed" if result.get("ok") else "Action rejected; check permissions, inputs, or safety controls", actor_id=user_id)
        return result

    def _perform_action(self, user_id: int, action: str, params: dict) -> dict:
        """GUI buttons become real bot commands run through the same engine."""
        ctx = self.ctx
        permission = {
            "save_available_models": "/model", "chat_chatty": "/chatty",
            "chat_cooldown": "/chatcooldown", "safemode_reset": "/safemode",
            "emergencystop": "/stop" if str(params.get("value", "")).lower() in ("1", "true", "on", "yes", "stop") else "/resume",
            "addauth": "/addauth", "removeauth": "/removeauth",
        }.get(action) or self.ACTION_TO_COMMAND.get(action, "").split(" ")[0]
        if not permission:
            return {"ok": False, "response": f"Unknown action: {action}"}
        denial = self.command_denial(user_id, permission)
        if denial:
            return denial
        if action in ("addauth", "removeauth"):
            return self._handle_access_change(user_id, action, params)
        if action == "save_available_models":
            models = params.get("models") or []
            if isinstance(models, list):
                cleaned = [str(m).strip() for m in models if str(m).strip()]
                ctx.db.set_state("available_models", json.dumps(cleaned))
                return {"ok": True, "response": f"Saved {len(cleaned)} available model(s)."}
            return {"ok": False, "response": "Invalid models list."}
        if action == "model":
            ctx.db.set_state("models_manually_set", "1")
        if action == "chat_chatty":
            # Same state the bot's inline picker writes
            cid = int(params.get("chat_id", 0))
            value = str(params.get("value", "")).strip()
            if value.lower() in ("def", "default", ""):
                ctx.db.set_state(f"chat_chatty_{cid}", "")
                return {"ok": True, "response": f"Chatty for chat {cid} reset to the global default."}
            pct = max(0, min(100, int(float(value))))
            ctx.db.set_state(f"chat_chatty_{cid}", str(pct / 100.0))
            return {"ok": True, "response": f"Chatty for chat {cid} set to {pct}%."}
        if action == "chat_cooldown":
            cid = int(params.get("chat_id", 0))
            is_reset = str(params.get("reset", "")).lower() in ("1", "true", "yes") or "reset" in str(params.get("min", "")).lower()
            if is_reset:
                ctx.db.set_state(f"chat_cooldown_min_{cid}", "")
                ctx.db.set_state(f"chat_cooldown_max_{cid}", "")
                if hasattr(ctx, "safety") and ctx.safety and hasattr(ctx.safety, "reset_chat_cooldown"):
                    ctx.safety.reset_chat_cooldown(cid)
                return {"ok": True, "response": f"Cooldown for chat {cid} reset to global default."}
            try:
                c_min = float(params.get("min", 5))
                c_max = float(params.get("max", 60))
                if not (math.isfinite(c_min) and math.isfinite(c_max) and 0 <= c_min <= c_max <= 86400):
                    return {"ok": False, "response": "Cooldowns must be finite numbers from 0 to 86400 seconds, with maximum at least minimum."}
                ctx.db.set_state(f"chat_cooldown_min_{cid}", str(round(c_min, 1)))
                ctx.db.set_state(f"chat_cooldown_max_{cid}", str(round(c_max, 1)))
                if hasattr(ctx, "safety") and ctx.safety and hasattr(ctx.safety, "set_chat_cooldown"):
                    ctx.safety.set_chat_cooldown(cid, c_min, c_max)
                if c_min == 0.0 and c_max == 0.0:
                    return {"ok": True, "response": f"Cooldown for chat {cid} set to 0s (Instant - No Wait)."}
                return {"ok": True, "response": f"Cooldown for chat {cid} set to {int(c_min)}s - {int(c_max)}s."}
            except (ValueError, TypeError) as e:
                return {"ok": False, "response": f"Invalid cooldown values: {e}"}
        if action == "chatprompt":
            cid = int(params.get("chat_id", 0))
            val = str(params.get("value", "")).strip()
            if val.lower() in ("default", "clear", "reset", "none", ""):
                ctx.db.set_state(f"chat_prompt_{cid}", "")
                if hasattr(ctx.db, "sync_chat_context_file"):
                    ctx.db.sync_chat_context_file(cid)
                return {"ok": True, "response": f"Chat {cid} reset to default prompt."}
            ctx.db.set_state(f"chat_prompt_{cid}", val)
            if hasattr(ctx.db, "sync_chat_context_file"):
                ctx.db.sync_chat_context_file(cid)
            return {"ok": True, "response": f"Custom prompt saved for chat {cid}."}
        if action == "setcontext":
            cid = int(params.get("chat_id", 0))
            val = str(params.get("value", "")).strip()
            if hasattr(ctx.db, "set_permanent_context"):
                ctx.db.set_permanent_context(cid, notes=val)
            if hasattr(ctx.db, "sync_chat_context_file"):
                ctx.db.sync_chat_context_file(cid)
            return {"ok": True, "response": f"Context notes saved for chat {cid}."}
        if action == "delcontext":
            cid = int(params.get("chat_id", 0))
            if hasattr(ctx.db, "delete_permanent_context"):
                ctx.db.delete_permanent_context(cid)
            if hasattr(ctx.db, "sync_chat_context_file"):
                ctx.db.sync_chat_context_file(cid)
            return {"ok": True, "response": f"Context notes cleared for chat {cid}."}
        if action == "chatstyle":
            cid = int(params.get("chat_id", 0))
            val = str(params.get("value", "")).strip().lower()
            if val in ("default", "clear", "reset", "none", ""):
                ctx.db.set_state(f"chat_style_{cid}", "")
                if hasattr(ctx.db, "sync_chat_context_file"):
                    ctx.db.sync_chat_context_file(cid)
                return {"ok": True, "response": f"Chat {cid} reset to default style."}
            ctx.db.set_state(f"chat_style_{cid}", val)
            if hasattr(ctx.db, "sync_chat_context_file"):
                ctx.db.sync_chat_context_file(cid)
            return {"ok": True, "response": f"Style set to {val} for chat {cid}."}
        if action == "ownreact":
            val = str(params.get("value", "")).lower().strip()
            is_on = val in ("1", "true", "on", "yes", "enable")
            ctx.db.set_state("ownreact_enabled", "1" if is_on else "0")
            return {"ok": True, "response": f"Own-reply reactions turned {'ON' if is_on else 'OFF'}."}
        if action == "clearcontext":
            cid = str(params.get("chat_id", "all")).strip().lower()
            if cid in ("all", "*", ""):
                count = ctx.db.clear_all_chat_context()
                return {"ok": True, "response": f"Cleared {count} cached AI context messages across all chats."}
            try:
                target_cid = int(cid)
                count = ctx.db.clear_chat_context(target_cid)
                return {"ok": True, "response": f"Cleared {count} cached context messages for chat {target_cid}."}
            except ValueError:
                return {"ok": False, "response": "Invalid chat ID for clearcontext."}
        if action == "safemode_reset":
            ctx.db.set_state("safe_mode_active", "0")
            ctx.db.set_state("safe_mode_restarts", "0")
            return {"ok": True, "response": "Safe Mode reset. Crash-loop guard is in Protected state."}
        if action == "emergencystop":
            val = str(params.get("value", "")).lower().strip()
            is_stop = val in ("1", "true", "on", "yes", "stop")
            if hasattr(ctx, "reply_manager") and hasattr(ctx.reply_manager, "safety"):
                ctx.reply_manager.safety.set_emergency_stop(is_stop)
            return {"ok": True, "response": f"Emergency stop {'activated' if is_stop else 'cleared'}."}
        command = self.map_action_to_command(action, params)
        if not command:
            return {"ok": False, "response": f"Unknown action: {action}"}
        return self.run_command(command, user_id, audit=False)

    def _resolve_user_target(self, raw_target: str) -> tuple[Optional[int], Optional[dict], Optional[str]]:
        """Resolve a username or ID string for owners."""
        clean = str(raw_target or "").strip()
        for prefix in ("https://t.me/", "http://t.me/", "t.me/", "@"):
            if clean.startswith(prefix):
                clean = clean[len(prefix):]
        clean = clean.strip("/").strip()

        # 1. Check known_chats in DB
        if self.ctx.db and hasattr(self.ctx.db, "find_chat_by_username"):
            meta = self.ctx.db.find_chat_by_username(clean)
            if meta:
                return meta["chat_id"], meta, None

        # 2. Try CommandRouter's _resolve_chat_id
        cmd_router = self.ctx.reply_manager
        if cmd_router and hasattr(cmd_router, "_resolve_chat_id"):
            import asyncio
            try:
                if self.ctx.loop and not self.ctx.loop.is_closed():
                    fut = asyncio.run_coroutine_threadsafe(cmd_router._resolve_chat_id(clean), self.ctx.loop)
                    cid, meta, err = fut.result(timeout=10.0)
                else:
                    cid, meta, err = asyncio.run(cmd_router._resolve_chat_id(clean))
                if cid is not None:
                    return cid, meta, None
                return None, None, err
            except Exception as e:
                logger.debug(f"Async resolve failed for {clean}: {e}")

        err_msg = (
            f"Unable to resolve '{raw_target}'.\n"
            f"• Issue: Telegram cannot locate a user with handle '{clean}'.\n"
            f"• How to fix: Verify username spelling, or use the numeric User ID."
        )
        return None, None, err_msg

    def _handle_access_change(self, requester_id: int, action: str, params: dict) -> dict:
        """Add/remove authorized users — GUI equivalent of the bot's /addauth //removeauth."""
        ctx = self.ctx
        if not _is_main_user(ctx, requester_id):
            return {"ok": False, "response": "Only the main owner can manage authorized users."}

        raw_target = str(params.get("user_id") or params.get("target") or "").strip()
        if not raw_target:
            return {"ok": False, "response": "Provide a valid Telegram user ID or @username."}

        target: Optional[int] = None
        try:
            target = int(raw_target)
        except ValueError:
            pass

        meta: Optional[dict] = None
        if target is None:
            resolved_id, resolved_meta, err = self._resolve_user_target(raw_target)
            if err or resolved_id is None:
                return {"ok": False, "response": err or f"Could not resolve '{raw_target}'."}
            target = resolved_id
            meta = resolved_meta
        else:
            if self.ctx.db and hasattr(self.ctx.db, "get_chat_metadata"):
                meta = self.ctx.db.get_chat_metadata(target)
            if not meta or not meta.get("username"):
                _, resolved_meta, _ = self._resolve_user_target(str(target))
                if resolved_meta:
                    meta = resolved_meta

        if target <= 0:
            return {"ok": False, "response": "Authorized owners must be Telegram user accounts, not groups or channels."}

        users = _authorized_user_ids(ctx)
        if action == "addauth":
            users.add(target)
            save_authorized_users(ctx.db, users, _seed_user_ids(ctx))
            if meta and hasattr(ctx.db, "record_chat_metadata"):
                ctx.db.record_chat_metadata(
                    target,
                    title=meta.get("title") or f"User {target}",
                    username=meta.get("username") or "",
                    chat_type="Owner",
                )
            name_display = (meta.get("title") if meta else "") or f"User {target}"
            return {"ok": True, "response": f"Owner {name_display} ({target}) added to authorized users."}

        if _is_main_user(ctx, target):
            return {"ok": False, "response": "The main owner cannot be removed."}
        users.discard(target)
        save_authorized_users(ctx.db, users, _seed_user_ids(ctx))
        return {"ok": True, "response": f"User {target} removed from authorized users."}

    def run_command(self, command: str, user_id: int, audit: bool = True) -> dict:
        """Run a bot command through the shared engine on the main asyncio loop."""
        ctx = self.ctx
        if not command.startswith("/"):
            command = "/" + command
        denial = self.command_denial(user_id, command)
        if denial:
            if audit:
                ctx.db.record_action("miniapp", "command", "blocked", "Command permission denied", actor_id=user_id)
            return denial
        if ctx.loop is None or ctx.loop.is_closed():
            # Headless (tests): run inline
            import asyncio
            async def execute_inline():
                result = await ctx.reply_manager.handle_control_command(command, audit_source="miniapp" if audit else None, actor_id=user_id)
                task = getattr(ctx.reply_manager, "_approval_batch_task", None)
                if command.strip().lower() == "/approve all" and task and not task.done():
                    await task
                return result
            response = asyncio.run(execute_inline())
        else:
            import asyncio
            future = asyncio.run_coroutine_threadsafe(ctx.reply_manager.handle_control_command(command, audit_source="miniapp" if audit else None, actor_id=user_id), ctx.loop)
            try:
                response = future.result(timeout=45.0)
            except Exception as e:
                future.cancel()
                logger.error(f"Mini app command '{command.split()[0]}' failed: {e}")
                return {"ok": False, "response": f"Command failed: {e}"}
        ok = bool(response) and not response.startswith(("❌", "⚠️", "❓", "Usage:"))
        return {"ok": ok, "response": response or "No response."}

    def handle_history(self, status="", before=0, limit=40) -> dict:
        if status not in ("", "success", "failed", "blocked", "sent", "skipped"):
            return {"ok": False, "response": "Choose a valid history status"}
        rows = self.ctx.db.list_actions(status, before, limit)
        state = self.handle_state()
        return {"ok": True, "events": rows, "next_before": rows[-1]["id"] if len(rows) == limit else None,
                "diagnostics": {key: state[key] for key in ("state", "mode", "ai_engine", "ai_model", "safe_mode", "quiet_hours", "pending_count", "chats_allowed", "version", "pipeline")}}

    def _settings_denial(self, user_id):
        if user_id not in _authorized_user_ids(self.ctx) or not _is_main_user(self.ctx, user_id):
            return {"ok": False, "response": "Only the main owner can export or import preferences"}
        return None

    def handle_settings_export(self, user_id) -> dict:
        denial = self._settings_denial(user_id)
        if denial:
            return denial
        backup = export_preferences(self.ctx)
        validate_preferences(backup, self.ctx.db)
        content = json.dumps(backup, ensure_ascii=False, indent=2).encode("utf-8")
        if len(content) > MAX_BACKUP_BYTES:
            return {"ok": False, "response": "The preference backup exceeds the 1 MB limit"}
        token = secrets.token_urlsafe(32)
        filename = "teleautomator-preferences.json"
        with self.ctx.settings_download_lock:
            now = time.monotonic()
            self.ctx.settings_downloads = {key: value for key, value in self.ctx.settings_downloads.items() if value[0] > now}
            while len(self.ctx.settings_downloads) >= 5:
                self.ctx.settings_downloads.pop(next(iter(self.ctx.settings_downloads)))
            self.ctx.settings_downloads[token] = (now + 300, content, filename)
        self.ctx.db.record_action("miniapp", "settings_export", "success", "Private preference download prepared", actor_id=user_id)
        return {"ok": True, "download_url": "/api/settings/download?token=" + token, "file_name": filename}

    def settings_download(self, token):
        with self.ctx.settings_download_lock:
            entry = self.ctx.settings_downloads.get(token)
            if entry and entry[0] > time.monotonic():
                return entry[1:]
            self.ctx.settings_downloads.pop(token, None)
        return None

    def handle_settings_import(self, user_id, backup, *, preview=True) -> dict:
        denial = self._settings_denial(user_id)
        if denial:
            return denial
        try:
            plan = validate_preferences(backup, self.ctx.db)
        except (ValueError, TypeError) as error:
            self.ctx.db.record_action("miniapp", "settings_import", "failed", "Preference file validation failed", actor_id=user_id)
            return {"ok": False, "response": str(error)}
        if preview:
            return {"ok": True, "summary": plan["summary"], "chat_ids": plan["chat_ids"],
                    "setting_keys": sorted(backup.get("settings", {})), "rule_keywords": [rule["keyword"] for rule in plan["rules"]]}
        generator, db, safety = self.ctx.generator, self.ctx.db, self.ctx.safety
        try:
            planned_db = SimpleNamespace(get_state=lambda key, default="": plan["states"].get(key, db.get_state(key, default)),
                                         record_token_usage=db.record_token_usage)
            provider = create_ai_provider(generator.config, database=planned_db)
        except Exception:
            db.record_action("miniapp", "settings_import", "failed", "Provider could not load the proposed preferences", actor_id=user_id)
            return {"ok": False, "response": "The provider could not load these preferences. Nothing was changed."}
        db.apply_preferences(plan["states"], plan["contexts"], plan["rules"])
        generator.set_style(db.get_state("reply_style", generator.style))
        generator.set_language(db.get_state("chat_language", generator.language))
        generator.prompt_manager.custom_prompt = db.get_state("custom_system_prompt", generator.prompt_manager.custom_prompt)
        generator.set_owner_name(db.get_state("owner_name", generator.prompt_manager.owner_name))
        generator.provider = provider
        safety._next_chat_cooldown.clear()
        safety._next_global_cooldown = 0.0
        safety._minute_cap = safety.max_replies_per_minute
        self.ctx.db.record_action("miniapp", "settings_import", "success", "Preferences applied; access controls and conversation memory preserved", actor_id=user_id)
        return {"ok": True, "summary": plan["summary"], "response": "Preferences restored"}

    def handle_fetch_models(self, base_url: str = "", api_key: Optional[str] = None) -> dict:
        """Fetch available models from Gemini or OpenAI-compatible endpoint."""
        provider = (
            self.ctx.db.get_state("ai_provider")
            or (getattr(getattr(self.ctx, "reply_manager", None), "config", None) and getattr(self.ctx.reply_manager.config, "ai_provider", "gemini"))
            or "gemini"
        ).strip().lower()

        key = (
            api_key
            or self.ctx.db.get_state("ai_api_key")
            or (getattr(getattr(self.ctx, "reply_manager", None), "config", None) and getattr(self.ctx.reply_manager.config, "ai_api_key", ""))
            or ""
        ).strip()

        user_base = (base_url or "").strip().rstrip("/")
        db_base = (self.ctx.db.get_state("ai_base_url") or "").strip().rstrip("/")
        config_base = (getattr(getattr(self.ctx, "reply_manager", None), "config", None) and getattr(self.ctx.reply_manager.config, "ai_base_url", "") or "").strip().rstrip("/")
        effective_base = user_base or db_base or config_base
        if effective_base:
            try:
                effective_base = normalize_base_url(effective_base)
            except ValueError as e:
                return {"ok": False, "error": str(e)}

        if effective_base:
            is_gemini = "googleapis.com" in effective_base
        else:
            is_gemini = (provider == "gemini" or key.startswith("AIzaSy") or not provider)

        if is_gemini:
            if not key:
                return {
                    "ok": True,
                    "models": [
                        "gemini-2.5-flash-lite",
                        "gemini-2.5-flash",
                        "gemini-2.5-pro",
                        "gemini-1.5-flash",
                        "gemini-1.5-pro",
                    ],
                    "url": "https://generativelanguage.googleapis.com/v1beta/models",
                }
            models_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
            headers = {"Accept": "application/json", "x-goog-api-key": key}
            req = urllib.request.Request(models_url, headers=headers, method="GET")
            try:
                with urllib.request.urlopen(req, timeout=10.0) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                    raw_models = body.get("models") or []
                    models: list[str] = []
                    for item in raw_models:
                        if isinstance(item, dict):
                            methods = item.get("supportedGenerationMethods") or []
                            name = str(item.get("name") or "")
                            if "generateContent" in methods or not methods:
                                clean_name = name.removeprefix("models/").strip()
                                if clean_name and not any(bad in clean_name.lower() for bad in ("embedding", "aqa", "imagen")):
                                    models.append(clean_name)
                        elif isinstance(item, str):
                            clean_name = item.removeprefix("models/").strip()
                            if clean_name:
                                models.append(clean_name)

                    def _sort_gemini(m: str):
                        ml = m.lower()
                        if "flash-lite" in ml:
                            return (0, ml)
                        if "flash" in ml:
                            return (1, ml)
                        if "pro" in ml:
                            return (2, ml)
                        return (3, ml)

                    models = sorted(list(dict.fromkeys(models)), key=_sort_gemini)
                    if not models:
                        models = ["gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-1.5-flash"]
                    return {"ok": True, "models": models, "url": "https://generativelanguage.googleapis.com/v1beta/models"}
            except urllib.error.HTTPError as e:
                err_msg = f"HTTP {e.code}"
                try:
                    eb = json.loads(e.read().decode("utf-8"))
                    if isinstance(eb, dict):
                        if "error" in eb:
                            err_obj = eb["error"]
                            err_msg = f"HTTP {e.code}: {err_obj.get('message', err_obj) if isinstance(err_obj, dict) else err_obj}"
                        elif "message" in eb:
                            err_msg = f"HTTP {e.code}: {eb['message']}"
                except Exception:
                    pass
                if e.code == 400 and "api_key_invalid" in err_msg.lower():
                    err_msg = "Invalid Gemini API Key"
                elif e.code == 401:
                    err_msg += " (Unauthorized: check your Gemini API key)"
                return {"ok": False, "error": err_msg, "url": "https://generativelanguage.googleapis.com/v1beta/models"}
            except urllib.error.URLError as e:
                reason = getattr(e, "reason", str(e))
                return {"ok": False, "error": f"Connection error: {reason}. Check your internet connection.", "url": "https://generativelanguage.googleapis.com/v1beta/models"}
            except Exception as e:
                return {"ok": False, "error": str(e), "url": "https://generativelanguage.googleapis.com/v1beta/models"}

        raw_url = (effective_base or "https://api.openai.com/v1").rstrip("/")
        if not raw_url.startswith(("http://", "https://")):
            raw_url = f"https://{raw_url}"
        if raw_url.endswith("/chat/completions"):
            raw_url = raw_url[:-len("/chat/completions")].rstrip("/")
        models_url = raw_url if raw_url.endswith("/models") else f"{raw_url}/models"

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
                is_inception = "inceptionlabs" in (effective_base or "").lower()
                if isinstance(raw_data, list):
                    for item in raw_data:
                        if isinstance(item, dict):
                            supported = item.get("supported_endpoints") or []
                            if supported and not any("chat" in ep for ep in supported):
                                continue
                            mid = str(item.get("id", "")).strip()
                            if is_inception and mid in ("mercury-2", "mercury-2.5", "mercury-small"):
                                continue
                            if mid:
                                models.append(mid)
                        elif isinstance(item, str):
                            mid = item.strip()
                            if is_inception and mid in ("mercury-2", "mercury-2.5", "mercury-small"):
                                continue
                            if mid:
                                models.append(mid)
                if is_inception:
                    for extra in ("mercury-3", "mercury-3-preview-1014", "mercury-3-preview-1002"):
                        if extra not in models:
                            models.append(extra)
                models = sorted(list(dict.fromkeys(models)))
                return {"ok": True, "models": models, "url": models_url}
        except urllib.error.HTTPError as e:
            err_msg = f"HTTP {e.code}"
            try:
                eb = json.loads(e.read().decode("utf-8"))
                if isinstance(eb, dict):
                    if "error" in eb:
                        err_obj = eb["error"]
                        err_msg = f"HTTP {e.code}: {err_obj.get('message', err_obj) if isinstance(err_obj, dict) else err_obj}"
                    elif "message" in eb:
                        err_msg = f"HTTP {e.code}: {eb['message']}"
            except Exception:
                pass
            if e.code == 401:
                err_msg += " (Unauthorized: check API key)"
            elif e.code == 404:
                err_msg += f" (Not Found: verify Base URL '{models_url}')"
            elif e.code == 429:
                err_msg += " (Quota or Rate Limit Exceeded)"
            return {"ok": False, "error": err_msg, "url": models_url}
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", str(e))
            return {
                "ok": False,
                "error": f"Connection error: {reason}. Verify that Base URL '{models_url}' is correct and reachable.",
                "url": models_url,
            }
        except Exception as e:
            return {"ok": False, "error": f"Failed to fetch models: {e}", "url": models_url}

    def handle_test_model(
        self,
        message: str = "hello",
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        auto_apply: bool = False,
    ) -> dict:
        """Test chat message live in the GUI, test candidates, auto-prune dead models, and auto-save working rotation."""
        expected_settings = {key: self.ctx.db.get_state(key) for key in
                             ("ai_model", "ai_base_url", "ai_api_key", "ai_provider", "ai_enabled", "models_manually_set",
                              "ai_temperature", "ai_max_tokens", "ai_reasoning_effort")}
        prompt = (message or "hello").strip()
        provider = (
            self.ctx.db.get_state("ai_provider")
            or (getattr(getattr(self.ctx, "reply_manager", None), "config", None) and getattr(self.ctx.reply_manager.config, "ai_provider", "gemini"))
            or "gemini"
        ).strip().lower()

        key = (
            api_key
            or self.ctx.db.get_state("ai_api_key")
            or (getattr(getattr(self.ctx, "reply_manager", None), "config", None) and getattr(self.ctx.reply_manager.config, "ai_api_key", ""))
            or ""
        ).strip()

        user_base = (base_url or "").strip().rstrip("/")
        db_base = (self.ctx.db.get_state("ai_base_url") or "").strip().rstrip("/")
        config_base = (getattr(getattr(self.ctx, "reply_manager", None), "config", None) and getattr(self.ctx.reply_manager.config, "ai_base_url", "") or "").strip().rstrip("/")
        effective_base = user_base or db_base or config_base
        if effective_base:
            try:
                effective_base = normalize_base_url(effective_base)
            except ValueError as e:
                return {"ok": False, "error": str(e)}

        if effective_base:
            is_gemini = "googleapis.com" in effective_base
        else:
            is_gemini = (provider == "gemini" or key.startswith("AIzaSy") or not provider)

        default_model = "gemini-2.5-flash-lite,gemini-2.5-flash" if is_gemini else "gpt-4o-mini"
        model_param = (
            model
            or self.ctx.db.get_state("ai_model")
            or (getattr(getattr(self.ctx, "reply_manager", None), "config", None) and getattr(self.ctx.reply_manager.config, "ai_model", ""))
            or default_model
        )
        candidates = list(dict.fromkeys(m.strip().removeprefix("models/") for m in model_param.replace(";", ",").split(",") if m.strip()))
        if not candidates:
            candidates = ["gemini-2.5-flash-lite"] if is_gemini else ["gpt-4o-mini"]

        results: list[dict] = []
        working_models: list[str] = []
        reply_text = ""
        first_working_model = ""
        deadline = time.monotonic() + 30.0

        if is_gemini:
            for m in candidates:
                clean_m = m.removeprefix("models/").strip()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    results.append({"model": clean_m, "ok": False, "detail": "Not tested: request time budget exhausted. Retry a smaller selection."})
                    continue
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_m}:generateContent?key={key}"
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.7, "maxOutputTokens": 200},
                }
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    url,
                    data=data,
                    headers={"Content-Type": "application/json", "x-goog-api-key": key},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(req, timeout=min(12.0, remaining)) as resp:
                        body = json.loads(resp.read().decode("utf-8"))
                        choices = body.get("candidates", [])
                        if choices:
                            parts = choices[0].get("content", {}).get("parts", [])
                            if parts:
                                raw_text = parts[0].get("text")
                                if raw_text is not None and str(raw_text).strip().lower() not in ("none", "null", "undefined", ""):
                                    working_models.append(clean_m)
                                    results.append({"model": clean_m, "ok": True, "detail": "Working"})
                                    if not reply_text:
                                        reply_text = str(raw_text).strip().strip('"')
                                        first_working_model = clean_m
                                    continue
                        results.append({"model": clean_m, "ok": False, "detail": "Empty response from Gemini"})
                except urllib.error.HTTPError as e:
                    detail = f"HTTP {e.code}"
                    try:
                        eb = json.loads(e.read().decode("utf-8"))
                        if isinstance(eb, dict) and "error" in eb:
                            err_obj = eb["error"]
                            detail = f"HTTP {e.code}: {err_obj.get('message', err_obj) if isinstance(err_obj, dict) else err_obj}"
                    except Exception:
                        pass
                    if e.code == 400 and "api_key_invalid" in detail.lower():
                        detail = "Invalid Gemini API Key"
                    elif e.code == 404:
                        detail = f"Model '{clean_m}' not found for key"
                    results.append({"model": clean_m, "ok": False, "detail": detail[:120]})
                except urllib.error.URLError as e:
                    reason = getattr(e, "reason", str(e))
                    results.append({"model": clean_m, "ok": False, "detail": f"Network error: {reason}"[:120]})
                except Exception as e:
                    results.append({"model": clean_m, "ok": False, "detail": str(e)[:120]})
        else:
            raw_endpoint = (effective_base or "https://api.openai.com/v1").rstrip("/")
            if raw_endpoint.endswith("/models"):
                raw_endpoint = raw_endpoint[:-len("/models")].rstrip("/")
            if not raw_endpoint.endswith("/chat/completions"):
                endpoint = f"{raw_endpoint}/chat/completions"
            else:
                endpoint = raw_endpoint

            for m in candidates:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    results.append({"model": m, "ok": False, "detail": "Not tested: request time budget exhausted. Retry a smaller selection."})
                    continue
                payload = {
                    "model": m,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 300,
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
                    with urllib.request.urlopen(req, timeout=min(12.0, remaining)) as resp:
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
                        results.append({"model": m, "ok": False, "detail": "Empty choices response"})
                except urllib.error.HTTPError as e:
                    detail = f"HTTP {e.code}"
                    try:
                        eb = json.loads(e.read().decode("utf-8"))
                        if isinstance(eb, dict):
                            if "error" in eb:
                                err_obj = eb["error"]
                                detail = f"HTTP {e.code}: {err_obj.get('message', err_obj) if isinstance(err_obj, dict) else err_obj}"
                            elif "message" in eb:
                                detail = f"HTTP {e.code}: {eb['message']}"
                    except Exception:
                        pass
                    if e.code == 401 and "unauthorized" not in detail.lower():
                        detail += " (Invalid API key)"
                    elif e.code == 404 and "not found" not in detail.lower():
                        detail += f" (Endpoint '{endpoint}' or model not found)"
                    elif e.code == 429 and "quota" not in detail.lower():
                        detail += " (Quota or Rate Limit)"
                    results.append({"model": m, "ok": False, "detail": detail[:120]})
                except urllib.error.URLError as e:
                    reason = getattr(e, "reason", str(e))
                    results.append({"model": m, "ok": False, "detail": f"Network error: {reason}. Check Base URL '{endpoint}'"[:120]})
                except Exception as e:
                    results.append({"model": m, "ok": False, "detail": str(e)[:120]})

        manually_set = self.ctx.db.get_state("models_manually_set", "0") == "1"
        should_auto_apply = not manually_set or bool(auto_apply)

        updated_chain = ""
        if working_models:
            updated_chain = ",".join(working_models)
            if should_auto_apply:
                states = {"ai_model": updated_chain, "ai_enabled": "1"}
                if base_url:
                    states["ai_base_url"] = effective_base
                if api_key:
                    states["ai_api_key"] = api_key
                active_provider = "gemini" if is_gemini else (provider if provider not in ("local", "gemini") else "custom")
                states["ai_provider"] = active_provider
                from app.ai.reply_generator import create_ai_provider
                planned_db = SimpleNamespace(get_state=lambda key, default="": states.get(key, self.ctx.db.get_state(key, default)),
                                             record_token_usage=self.ctx.db.record_token_usage)
                try:
                    new_provider = create_ai_provider(self.ctx.reply_manager.config, database=planned_db)
                except Exception:
                    return {"ok": False, "error": "The provider could not load this rotation. Saved settings were preserved.",
                            "auto_applied": False, "working_models": working_models, "results": results}
                if self.ctx.db.apply_preferences(states, [], [], expected_states=expected_settings):
                    self.ctx.generator.provider = new_provider
                else:
                    should_auto_apply = False

        primary_err = results[0]["detail"] if results else "All candidate models failed."
        return {
            "ok": len(working_models) > 0,
            "reply": reply_text or "No reply received.",
            "error": "" if working_models else primary_err,
            "model_used": first_working_model,
            "working_models": working_models,
            "failed_models": [r["model"] for r in results if not r["ok"]],
            "results": results,
            "active_model": (updated_chain if should_auto_apply else self.ctx.db.get_state("ai_model")) or model_param,
            "auto_applied": should_auto_apply and len(working_models) > 0,
        }


@lru_cache(maxsize=16)
def _static_bytes(path: Path, _modified_ns: int):
    body = path.read_bytes()
    return body, gzip.compress(body, mtime=0)


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
        body, compressed = self._encode_body(body)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Vary", "Accept-Encoding")
        if compressed:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        self.wfile.write(body)

    def _encode_body(self, body, compressed_body=None):
        accepts_gzip = any(part.strip() == "gzip" for part in self.headers.get("Accept-Encoding", "").split(","))
        return ((compressed_body if compressed_body is not None else gzip.compress(body, mtime=0)), True) if accepts_gzip and len(body) >= 512 else (body, False)

    def _unauthorized_payload(self) -> dict:
        return {"authorized": False, "paywall": PAYWALL, "version": APP_VERSION}

    def log_message(self, fmt, *args):  # quiet default access logs
        logger.debug("miniapp http: %s %s %s", self.address_string(), self.command, self.path.split("?", 1)[0])

    def _serve_settings_download(self, head_only=False):
        from urllib.parse import parse_qs, urlsplit
        token = parse_qs(urlsplit(self.path).query).get("token", [""])[0]
        entry = self.api.settings_download(token)
        if entry is None:
            self.send_response(404)
            self.end_headers()
            return
        content, filename = entry
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Access-Control-Allow-Origin", "https://web.telegram.org")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if not head_only:
            self.wfile.write(content)

    def do_HEAD(self):
        if self.path.split("?", 1)[0] == "/api/settings/download":
            return self._serve_settings_download(head_only=True)
        self.send_response(404)
        self.end_headers()

    # ---------------------------------------------------------------- routes

    def do_GET(self):  # noqa: N802 - stdlib naming
        path = self.path.split("?", 1)[0]
        if path == "/api/settings/download":
            return self._serve_settings_download()
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
        permission = {
            "/api/events": "/status", "/api/state": "/status", "/api/chats": "/chats",
            "/api/pending": "/pending", "/api/activity": "/chats", "/api/access": "/authlist",
            "/api/models": "/checkmodels", "/api/fetch_models": "/checkmodels",
            "/api/history": "/status", "/api/settings/export": "/backup",
            "/api/feedback": "/feedback",
        }.get(path)
        if permission:
            denial = self.api.command_denial(int(user["id"]), permission)
            if denial:
                self._json(403, denial)
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
                    if self.api.command_denial(int(user["id"]), "/status"):
                        break
                    cur_state = self.api.handle_state()
                    h = json.dumps(cur_state, sort_keys=True)
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
            elif path == "/api/feedback":
                from urllib.parse import parse_qs, urlsplit
                rating = parse_qs(urlsplit(self.path).query).get("rating", [""])[0]
                result = self.api.handle_feedback(rating)
                self._json(200 if result.get("ok") else 400, result)
            elif path == "/api/access":
                self._json(200, self.api.handle_access())
            elif path == "/api/history":
                from urllib.parse import parse_qs, urlsplit
                query = parse_qs(urlsplit(self.path).query)
                try:
                    before = max(0, int(query.get("before", ["0"])[0]))
                    limit = max(1, min(100, int(query.get("limit", ["40"])[0])))
                except ValueError:
                    self._json(400, {"ok": False, "response": "Invalid history page"})
                    return
                result = self.api.handle_history(query.get("status", [""])[0], before, limit)
                self._json(200 if result.get("ok") else 400, result)
            elif path == "/api/settings/export":
                denial = self.api._settings_denial(int(user["id"]))
                self._json(403, denial) if denial else self._json(200, self.api.handle_settings_export(int(user["id"])))
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
            if not 0 <= length <= MAX_BACKUP_BYTES + 10000:
                raise ValueError("Request too large")
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("Expected a JSON object")
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
                self._json(200, self.api.run_command(command, user_id))
            elif path in ("/api/settings/preview", "/api/settings/import"):
                denial = self.api._settings_denial(user_id)
                if denial:
                    self._json(403, denial)
                    return
                result = self.api.handle_settings_import(user_id, body.get("backup"), preview=path.endswith("preview"))
                self._json(200 if result.get("ok") else 400, result)
            elif path == "/api/action":
                action = str(body.get("action", "")).strip()
                params = body.get("params") or {}
                if not action or not isinstance(params, dict):
                    self._json(400, {"ok": False, "response": "Provide an action."})
                    return
                self._json(200, self.api.handle_action(user_id, action, params))
            elif path == "/api/fetch_models":
                for command in ("/checkmodels", "/baseurl" if body.get("base_url") else "/checkmodels", "/apikey" if body.get("api_key") else "/checkmodels"):
                    denial = self.api.command_denial(user_id, command)
                    if denial:
                        self._json(403, denial)
                        return
                base_url = str(body.get("base_url") or "").strip()
                api_key = str(body.get("api_key") or "").strip() or None
                result = self.api.handle_fetch_models(base_url, api_key)
                self.api.ctx.db.record_action("miniapp", "fetch_models", "success" if result.get("ok") else "failed", "Model list request completed", actor_id=user_id)
                self._json(200, result)
            elif path == "/api/test_model":
                required = ("/checkmodels", "/model", "/baseurl", "/apikey", "/provider")
                for command in required:
                    denial = self.api.command_denial(user_id, command)
                    if denial:
                        self._json(403, denial)
                        return
                message = str(body.get("message") or "hello").strip()
                model = str(body.get("model") or "").strip() or None
                base_url = str(body.get("base_url") or "").strip() or None
                api_key = str(body.get("api_key") or "").strip() or None
                auto_apply = body.get("auto_apply", False)
                if type(auto_apply) is not bool:
                    self._json(400, {"ok": False, "response": "auto_apply must be true or false"})
                    return
                result = self.api.handle_test_model(message, model, base_url, api_key, auto_apply=auto_apply)
                self.api.ctx.db.record_action("miniapp", "model_test", "success" if result.get("ok") else "failed", "Provider and model check completed", actor_id=user_id)
                self._json(200, result)
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
        body, compressed_body = _static_bytes(file_path, file_path.stat().st_mtime_ns)
        body, compressed = self._encode_body(body, compressed_body)
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Vary", "Accept-Encoding")
        if compressed:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        if file_path.name == "sw.js":
            self.send_header("Service-Worker-Allowed", "/")
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
