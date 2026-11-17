"""Versioned preference files. Credentials, access grants, and conversation history are excluded."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone

from app.ai.prompt_manager import VALID_STYLES

MAX_BACKUP_BYTES = 1_000_000
MAX_CONTEXT_NOTES = 8000
BOOL_KEYS = {
    "group_mention_only", "reaction_enabled", "ownreact_enabled", "multibubble_enabled",
    "typo_correction_enabled", "editfix_enabled", "debounce_enabled", "spontaneous_followup_enabled",
    "quiet_hours_enabled",
}
NUMBER_KEYS = {
    "chatty_probability": (0, 1), "ai_temperature": (0, 2), "debounce_seconds": (0, 30),
    "min_chat_cooldown_seconds": (0, 86400), "max_chat_cooldown_seconds": (0, 86400),
    "min_global_cooldown_seconds": (0, 86400), "max_global_cooldown_seconds": (0, 86400),
    "max_replies_per_minute": (1, 1000), "max_chat_replies_per_minute": (1, 1000),
}
TEXT_KEYS = {"reply_style", "chat_language", "custom_system_prompt", "owner_name",
             "quiet_hours_start", "quiet_hours_end", "ai_reasoning_effort", "ai_max_tokens"}
CHAT_STATES = {
    "prompt": "chat_prompt_", "style": "chat_style_", "chatty": "chat_chatty_",
    "cooldown_min": "chat_cooldown_min_", "cooldown_max": "chat_cooldown_max_",
    "voice_profile": "chat_voice_profile_",
}


def _text(value, label, maximum=8000):
    if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
        raise ValueError(f"{label} must be text up to {maximum} characters")
    return value


def _number(value, label, low, high, integer=False):
    value = _text(value, label, 32)
    try:
        number = float(value)
    except ValueError:
        raise ValueError(f"{label} must be numeric") from None
    if not math.isfinite(number) or not low <= number <= high or (integer and not number.is_integer()):
        raise ValueError(f"{label} must be between {low} and {high}")
    return str(int(number)) if integer else str(number)


def export_preferences(ctx):
    db, config, safety = ctx.db, ctx.reply_manager.config, ctx.safety
    defaults = {
        "reply_style": ctx.generator.style, "chat_language": ctx.generator.language,
        "custom_system_prompt": ctx.generator.prompt_manager.custom_prompt,
        "owner_name": ctx.generator.prompt_manager.owner_name,
        "chatty_probability": str(getattr(config, "chatty_probability", 0.15)),
        "ai_temperature": "0.6", "ai_reasoning_effort": getattr(config, "ai_reasoning_effort", "default"), "ai_max_tokens": "",
        "debounce_seconds": "3.0", "quiet_hours_start": getattr(config, "quiet_hours_start", "02:00"), "quiet_hours_end": getattr(config, "quiet_hours_end", "08:00"),
    }
    for key in BOOL_KEYS:
        defaults[key] = "1" if key not in ("group_mention_only",) else "0"
    defaults["reaction_enabled"] = "1" if getattr(config, "reaction_enabled", True) else "0"
    defaults["quiet_hours_enabled"] = "1" if getattr(config, "quiet_hours_enabled", True) else "0"
    for key, attr, fallback in (
        ("min_chat_cooldown_seconds", "min_chat_cooldown", 5), ("max_chat_cooldown_seconds", "max_chat_cooldown", 60),
        ("min_global_cooldown_seconds", "min_global_cooldown", 5), ("max_global_cooldown_seconds", "max_global_cooldown", 60),
        ("max_replies_per_minute", "max_replies_per_minute", 5), ("max_chat_replies_per_minute", "max_chat_replies_per_minute", 3),
    ):
        defaults[key] = str(getattr(safety, attr, fallback))
    chats = []
    private, groups = ctx.privacy.get_all_allowed_chats()
    for cid in sorted(private | groups):
        permanent = db.get_permanent_context(cid)
        chats.append({"id": cid, "title": (db.get_chat_metadata(cid) or {}).get("title", ""),
                      **{field: db.get_state(prefix + str(cid)) for field, prefix in CHAT_STATES.items()},
                      "notes": permanent.get("notes", ""), "pinned_text": permanent.get("pinned_text", "")})
    return {"format": "teleautomator-preferences", "version": 1,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "settings": {key: db.get_state(key, value) for key, value in defaults.items()},
            "chats": chats, "keyword_rules": db.list_keyword_rules()}


def validate_preferences(payload, db):
    if not isinstance(payload, dict) or payload.get("format") != "teleautomator-preferences" or type(payload.get("version")) is not int or payload["version"] != 1:
        raise ValueError("Choose a version 1 TeleAutomator preference backup")
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > MAX_BACKUP_BYTES:
        raise ValueError("Preference backups must be smaller than 1 MB")
    if set(payload) - {"format", "version", "exported_at", "settings", "chats", "keyword_rules"}:
        raise ValueError("The backup contains unsupported sections")
    settings = payload.get("settings", {})
    chats, rules = payload.get("chats", []), payload.get("keyword_rules", [])
    if not isinstance(settings, dict) or not isinstance(chats, list) or not isinstance(rules, list) or len(chats) > 500 or len(rules) > 200:
        raise ValueError("Invalid preference sections or too many profiles/rules")
    if set(settings) - BOOL_KEYS - NUMBER_KEYS.keys() - TEXT_KEYS:
        raise ValueError("The backup contains unsupported settings; credentials and access controls cannot be imported")
    states, contexts, clean_rules, chat_ids = {}, [], [], set()
    for key, raw in settings.items():
        value = _text(raw, key)
        if key in BOOL_KEYS and value not in ("0", "1"):
            raise ValueError(f"{key} must be 0 or 1")
        if key in NUMBER_KEYS:
            value = _number(value, key, *NUMBER_KEYS[key], integer=key.startswith("max_replies") or key.startswith("max_chat_replies"))
        if key == "reply_style" and value not in VALID_STYLES:
            raise ValueError("Invalid reply style")
        if key == "chat_language" and not re.fullmatch(r"[a-zA-Z][a-zA-Z -]{0,39}", value):
            raise ValueError("Invalid reply language")
        if key == "owner_name" and (not value.strip() or len(value) > 200):
            raise ValueError("Owner names must contain 1–200 characters")
        if key in ("quiet_hours_start", "quiet_hours_end") and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("Quiet hours must use HH:MM")
        if key == "ai_reasoning_effort" and value not in ("default", "off", "none", "instant", "low", "medium", "high"):
            raise ValueError("Invalid reasoning setting")
        if key == "ai_max_tokens" and value:
            value = _number(value, key, 1, 1000000, integer=True)
        states[key] = value
    for prefix in ("chat", "global"):
        low, high = f"min_{prefix}_cooldown_seconds", f"max_{prefix}_cooldown_seconds"
        if (low in states) != (high in states) or (low in states and float(states[low]) > float(states[high])):
            raise ValueError("Each default cooldown needs a valid minimum and maximum")
    for chat in chats:
        if not isinstance(chat, dict) or set(chat) - {"id", "title", "notes", "pinned_text", *CHAT_STATES}:
            raise ValueError("Invalid chat profile")
        cid = chat.get("id")
        if type(cid) is not int or not 0 < abs(cid) < 2**63 or cid in chat_ids:
            raise ValueError("Chat IDs must be unique nonzero integers")
        chat_ids.add(cid)
        _text(chat.get("title", ""), "Chat title", 300)
        for field, prefix in CHAT_STATES.items():
            if field not in chat:
                continue
            value = _text(chat[field], field)
            if field == "style" and value and value not in VALID_STYLES:
                raise ValueError("Invalid chat reply style")
            if field in ("chatty", "cooldown_min", "cooldown_max") and value:
                value = _number(value, field, 0, 1 if field == "chatty" else 86400)
            states[prefix + str(cid)] = value
        low, high = chat.get("cooldown_min", ""), chat.get("cooldown_max", "")
        if ("cooldown_min" in chat) != ("cooldown_max" in chat) or bool(low) != bool(high) or (low and float(low) > float(high)):
            raise ValueError("Each chat cooldown needs a valid minimum and maximum")
        current = db.get_permanent_context(cid)
        contexts.append({"id": cid, "notes": _text(chat.get("notes", current.get("notes", "")), "Chat notes", MAX_CONTEXT_NOTES),
                         "pinned_text": _text(chat.get("pinned_text", current.get("pinned_text", "")), "Pinned context")})
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) != {"keyword", "reply"}:
            raise ValueError("Invalid keyword rule")
        keyword = _text(rule["keyword"], "Keyword", 100).strip().lower()
        if not keyword:
            raise ValueError("Keyword rules need a trigger")
        clean_rules.append({"keyword": keyword, "reply": _text(rule["reply"], "Keyword reply", 2000)})
    return {"states": states, "contexts": contexts, "rules": clean_rules, "chat_ids": sorted(chat_ids),
            "summary": {"settings": len(settings), "chats": len(chats), "rules": len(rules)}}
