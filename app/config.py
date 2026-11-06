"""Application configuration loading and validation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Set

from dotenv import load_dotenv

from app.logger import register_secret


def _parse_id_set(value: str | None) -> Set[int]:
    """Parse comma-separated Telegram IDs into an integer set.
    
    Users can enter single or multiple IDs separated by commas in .env:
      - Private chat: ALLOWED_PRIVATE_CHATS=123456789,987654321
      - Group/Supergroup: ALLOWED_GROUPS=-1001234567890
    """
    if not value or not value.strip():
        return set()
    result: Set[int] = set()
    for item in value.split(","):
        cleaned = item.strip()
        if cleaned:
            try:
                result.add(int(cleaned))
            except ValueError:
                raise ValueError(
                    f"Invalid Telegram ID in configuration: '{cleaned}' must be an integer. "
                    "Make sure to separate multiple IDs with commas (e.g. 123456, 789012)."
                )
    return result


def _parse_bool(value: str | None, default: bool = False) -> bool:
    """Parse boolean from string."""
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class AppConfig:
    # Telegram Credentials
    api_id: int
    api_hash: str
    session_mode: str = "local"  # "local" or "string"
    session_name: str = "telegram_client"
    session_string: str = ""

    # Runtime Environment
    app_env: str = "development"
    log_level: str = "INFO"

    # Reply Mode: "draft" (default), "approval", "restricted_auto"
    reply_mode: str = "draft"
    auto_authorize: bool = False

    # AI Configuration
    ai_enabled: bool = False
    ai_provider: str = "local"  # "local", "gemini", "openai", "custom", "nvidia"
    ai_api_key: str = ""
    ai_model: str = ""
    ai_base_url: str = ""
    ai_reasoning_effort: str = "default"

    # Chat & User Filtering
    allowed_private_chats: Set[int] = field(default_factory=set)
    allowed_groups: Set[int] = field(default_factory=set)
    blocked_chats: Set[int] = field(default_factory=set)
    ignored_users: Set[int] = field(default_factory=set)

    # Safety & Rate Limits
    global_cooldown_seconds: int = 30
    per_chat_cooldown_seconds: int = 60
    max_message_length: int = 1000
    typing_delay_seconds: float = 2.0
    min_delay_seconds: float = 5.0
    max_delay_seconds: float = 60.0
    min_chat_cooldown_seconds: float = 5.0
    max_chat_cooldown_seconds: float = 60.0
    min_global_cooldown_seconds: float = 5.0
    max_global_cooldown_seconds: float = 60.0
    max_replies_per_minute: int = 5
    max_replies_per_hour: int = 30

    # Language & Reactions
    default_chat_language: str = "english"
    reaction_enabled: bool = True
    reaction_max_per_window: int = 4
    reaction_window_seconds: int = 600
    reaction_min_cooldown_seconds: float = 3.0
    reaction_max_cooldown_seconds: float = 9.0

    # Group Dynamics & Participation
    chatty_probability: float = 0.15
    react_only_probability: float = 0.25

    # Quiet Hours (Sleep Schedule Simulation - default 02:00 to 08:00 IST)
    quiet_hours_enabled: bool = True
    quiet_hours_start: str = "02:00"
    quiet_hours_end: str = "08:00"

    # Paths
    data_dir: Path = Path("data")

    def __repr__(self) -> str:
        """Safe representation without secret values."""
        return (
            f"AppConfig("
            f"api_id={self.api_id}, "
            f"session_mode='{self.session_mode}', "
            f"reply_mode='{self.reply_mode}', "
            f"ai_enabled={self.ai_enabled}, "
            f"ai_provider='{self.ai_provider}', "
            f"allowed_private_chats={sorted(self.allowed_private_chats)}, "
            f"allowed_groups={sorted(self.allowed_groups)}, "
            f"blocked_chats={sorted(self.blocked_chats)}, "
            f"data_dir='{self.data_dir}')"
        )


def load_config(env_path: Path | str | None = None) -> AppConfig:
    """Load configuration from environment or optional .env file and validate."""
    if env_path:
        load_dotenv(dotenv_path=env_path, override=True)
    else:
        load_dotenv(override=False)

    # API ID validation
    raw_api_id = os.getenv("TG_API_ID", "").strip()
    if not raw_api_id or raw_api_id == "your_api_id_here":
        raise ValueError("Missing required configuration: TG_API_ID must be set.")
    try:
        api_id = int(raw_api_id)
    except ValueError:
        raise ValueError(f"Invalid TG_API_ID: '{raw_api_id}' must be an integer.")

    # API Hash validation
    api_hash = os.getenv("TG_API_HASH", "").strip()
    if not api_hash or api_hash == "your_api_hash_here":
        raise ValueError("Missing required configuration: TG_API_HASH must be set.")
    if len(api_hash) < 10:
        raise ValueError("Invalid TG_API_HASH: value is too short to be a valid Telegram API hash.")
    register_secret(api_hash)

    # Session handling
    session_string = "".join(os.getenv("TG_SESSION_STRING", "").split()).strip("\"'")
    raw_mode = os.getenv("TG_SESSION_MODE", "").strip().lower()
    if not raw_mode:
        # Auto-detect: if TG_SESSION_STRING is set, auto-switch to "string" mode (Cloud/Railway/Docker)
        session_mode = "string" if session_string else "local"
    else:
        session_mode = raw_mode

    if session_mode not in ("local", "string"):
        raise ValueError(f"Invalid TG_SESSION_MODE: '{session_mode}'. Must be 'local' or 'string'.")

    session_name = os.getenv("TG_SESSION_NAME", "telegram_client").strip()
    if session_mode == "string":
        if not session_string:
            raise ValueError("TG_SESSION_MODE is set to 'string', but TG_SESSION_STRING is empty.")
        register_secret(session_string)

    # Reply Mode validation
    reply_mode = os.getenv("REPLY_MODE", "draft").strip().lower()
    if reply_mode not in ("draft", "approval", "restricted_auto"):
        raise ValueError(
            f"Invalid REPLY_MODE: '{reply_mode}'. Must be 'draft', 'approval', or 'restricted_auto'."
        )
    auto_authorize = _parse_bool(os.getenv("AUTO_AUTHORIZE"), default=False)

    # AI Configuration
    ai_provider = os.getenv("AI_PROVIDER", "local").strip().lower()
    valid_providers = ("local", "gemini", "openai", "custom", "nvidia", "groq", "together", "deepseek", "inception")
    if ai_provider not in valid_providers:
        raise ValueError(f"Invalid AI_PROVIDER: '{ai_provider}'. Must be one of: {', '.join(valid_providers)}.")

    raw_ai_enabled = os.getenv("AI_ENABLED")
    if raw_ai_enabled is None:
        # Auto-enable if external provider is selected
        ai_enabled = (ai_provider != "local")
    else:
        ai_enabled = _parse_bool(raw_ai_enabled, default=False)

    ai_api_key = (os.getenv("AI_API_KEY") or os.getenv("CUSTOM_API_KEY") or "").strip()
    if ai_enabled and ai_provider != "local":
        if not ai_api_key or ai_api_key in ("your_gemini_api_key_here", "your_openai_api_key_here"):
            raise ValueError(
                f"AI_ENABLED is true with provider '{ai_provider}', but AI_API_KEY is not set. "
                "Please add your API key into .env or Railway environment variables."
            )
    if ai_api_key:
        register_secret(ai_api_key)

    ai_model = (os.getenv("AI_MODEL") or os.getenv("CUSTOM_MODEL") or "").strip()
    ai_base_url = (os.getenv("AI_BASE_URL") or os.getenv("CUSTOM_BASE_URL") or "").strip()

    # Rate limits and bounds
    try:
        global_cooldown = max(0, int(os.getenv("GLOBAL_COOLDOWN_SECONDS", "30")))
        per_chat_cooldown = max(0, int(os.getenv("PER_CHAT_COOLDOWN_SECONDS", "60")))
        max_length = max(10, int(os.getenv("MAX_MESSAGE_LENGTH", "1000")))
        typing_delay = max(0.0, float(os.getenv("TYPING_DELAY_SECONDS", "2.0")))
        min_delay = max(0.0, float(os.getenv("MIN_REPLY_DELAY_SECONDS", "5.0")))
        max_delay = max(min_delay, float(os.getenv("MAX_REPLY_DELAY_SECONDS", "60.0")))
        default_chat_language = os.getenv("DEFAULT_CHAT_LANGUAGE", "english").strip().lower() or "english"
        reaction_enabled = _parse_bool(os.getenv("REACTION_ENABLED"), default=True)
        reaction_max_per_window = max(1, int(os.getenv("REACTION_MAX_PER_WINDOW", "4")))
        reaction_window_seconds = max(10, int(os.getenv("REACTION_WINDOW_SECONDS", "600")))
        chatty_probability = max(0.0, min(1.0, float(os.getenv("CHATTY_PROBABILITY", "0.15"))))
        react_only_probability = max(0.0, min(1.0, float(os.getenv("REACT_ONLY_PROBABILITY", "0.25"))))
        min_chat_cd = max(0.0, float(os.getenv("MIN_CHAT_COOLDOWN_SECONDS", "5.0")))
        max_chat_cd = max(min_chat_cd, float(os.getenv("MAX_CHAT_COOLDOWN_SECONDS", "60.0")))
        min_global_cd = max(0.0, float(os.getenv("MIN_GLOBAL_COOLDOWN_SECONDS", "5.0")))
        max_global_cd = max(min_global_cd, float(os.getenv("MAX_GLOBAL_COOLDOWN_SECONDS", "60.0")))
        reaction_min_cd = max(0.0, float(os.getenv("REACTION_MIN_COOLDOWN_SECONDS", "3.0")))
        reaction_max_cd = max(reaction_min_cd, float(os.getenv("REACTION_MAX_COOLDOWN_SECONDS", "9.0")))
        max_replies_per_minute = max(1, int(os.getenv("MAX_REPLIES_PER_MINUTE", "5")))
        max_replies_per_hour = max(1, int(os.getenv("MAX_REPLIES_PER_HOUR", "30")))
        quiet_hours_enabled = _parse_bool(os.getenv("QUIET_HOURS_ENABLED"), default=True)
        quiet_hours_start = os.getenv("QUIET_HOURS_START", "02:00").strip() or "02:00"
        quiet_hours_end = os.getenv("QUIET_HOURS_END", "08:00").strip() or "08:00"
    except ValueError as e:
        raise ValueError(f"Invalid rate limit or message delay configuration: {e}")

    data_dir = Path(os.getenv("DATA_DIR", "data"))

    return AppConfig(
        api_id=api_id,
        api_hash=api_hash,
        session_mode=session_mode,
        session_name=session_name,
        session_string=session_string,
        app_env=os.getenv("APP_ENV", "development").strip().lower(),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
        reply_mode=reply_mode,
        auto_authorize=auto_authorize,
        ai_enabled=ai_enabled,
        ai_provider=ai_provider,
        ai_api_key=ai_api_key,
        ai_model=ai_model,
        ai_base_url=ai_base_url,
        ai_reasoning_effort=os.getenv("AI_REASONING_EFFORT", "default").strip().lower(),
        allowed_private_chats=_parse_id_set(os.getenv("ALLOWED_PRIVATE_CHATS")),
        allowed_groups=_parse_id_set(os.getenv("ALLOWED_GROUPS")),
        blocked_chats=_parse_id_set(os.getenv("BLOCKED_CHATS")),
        ignored_users=_parse_id_set(os.getenv("IGNORED_USERS")),
        global_cooldown_seconds=global_cooldown,
        per_chat_cooldown_seconds=per_chat_cooldown,
        max_message_length=max_length,
        typing_delay_seconds=typing_delay,
        min_delay_seconds=min_delay,
        max_delay_seconds=max_delay,
        default_chat_language=default_chat_language,
        reaction_enabled=reaction_enabled,
        reaction_max_per_window=reaction_max_per_window,
        reaction_window_seconds=reaction_window_seconds,
        chatty_probability=chatty_probability,
        react_only_probability=react_only_probability,
        min_chat_cooldown_seconds=min_chat_cd,
        max_chat_cooldown_seconds=max_chat_cd,
        min_global_cooldown_seconds=min_global_cd,
        max_global_cooldown_seconds=max_global_cd,
        max_replies_per_minute=max_replies_per_minute,
        max_replies_per_hour=max_replies_per_hour,
        reaction_min_cooldown_seconds=reaction_min_cd,
        reaction_max_cooldown_seconds=reaction_max_cd,
        quiet_hours_enabled=quiet_hours_enabled,
        quiet_hours_start=quiet_hours_start,
        quiet_hours_end=quiet_hours_end,
        data_dir=data_dir,
    )
