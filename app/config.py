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
    ai_provider: str = "local"  # "local", "gemini", "openai"
    ai_api_key: str = ""
    ai_model: str = ""

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

    # Language & Reactions
    default_chat_language: str = "dynamic"
    reaction_enabled: bool = True
    reaction_max_per_window: int = 4
    reaction_window_seconds: int = 600

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
    session_mode = os.getenv("TG_SESSION_MODE", "local").strip().lower()
    if session_mode not in ("local", "string"):
        raise ValueError(f"Invalid TG_SESSION_MODE: '{session_mode}'. Must be 'local' or 'string'.")

    session_name = os.getenv("TG_SESSION_NAME", "telegram_client").strip()
    session_string = "".join(os.getenv("TG_SESSION_STRING", "").split()).strip("\"'")
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
    ai_enabled = _parse_bool(os.getenv("AI_ENABLED"), default=False)
    ai_provider = os.getenv("AI_PROVIDER", "local").strip().lower()
    if ai_provider not in ("local", "gemini", "openai"):
        raise ValueError(f"Invalid AI_PROVIDER: '{ai_provider}'. Must be 'local', 'gemini', or 'openai'.")

    ai_api_key = os.getenv("AI_API_KEY", "").strip()
    if ai_enabled and ai_provider != "local":
        if not ai_api_key or ai_api_key == "your_gemini_api_key_here":
            raise ValueError(
                f"AI_ENABLED is true with provider '{ai_provider}', but AI_API_KEY is not set. "
                "Please add your Gemini API key from https://aistudio.google.com/app/apikey into .env."
            )
    if ai_api_key:
        register_secret(ai_api_key)

    ai_model = os.getenv("AI_MODEL", "").strip()

    # Rate limits and bounds
    try:
        global_cooldown = max(0, int(os.getenv("GLOBAL_COOLDOWN_SECONDS", "30")))
        per_chat_cooldown = max(0, int(os.getenv("PER_CHAT_COOLDOWN_SECONDS", "60")))
        max_length = max(10, int(os.getenv("MAX_MESSAGE_LENGTH", "1000")))
        typing_delay = max(0.0, float(os.getenv("TYPING_DELAY_SECONDS", "2.0")))
        min_delay = max(0.0, float(os.getenv("MIN_REPLY_DELAY_SECONDS", "5.0")))
        max_delay = max(min_delay, float(os.getenv("MAX_REPLY_DELAY_SECONDS", "60.0")))
        default_chat_language = os.getenv("DEFAULT_CHAT_LANGUAGE", "dynamic").strip().lower() or "dynamic"
        reaction_enabled = _parse_bool(os.getenv("REACTION_ENABLED"), default=True)
        reaction_max_per_window = max(1, int(os.getenv("REACTION_MAX_PER_WINDOW", "4")))
        reaction_window_seconds = max(10, int(os.getenv("REACTION_WINDOW_SECONDS", "600")))
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
        data_dir=data_dir,
    )
