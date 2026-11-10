"""Safety and rate limiting controls to prevent spam, loops, and sensitive data leakage."""

from __future__ import annotations

import datetime
import hashlib
import random
import re
import time
from typing import Dict, Optional, Tuple

from app.config import AppConfig
from app.logger import setup_logger
from app.storage.database import Database

logger = setup_logger(__name__)

# Patterns that indicate OTPs, financial transactions, or sensitive security messages
SENSITIVE_CONTENT_PATTERNS = [
    re.compile(r"\b(?:otp|one-time password|verification code|auth code|login code)\b", re.IGNORECASE),
    re.compile(r"\b(?:credit card|cvv|bank account|wire transfer|routing number)\b", re.IGNORECASE),
    re.compile(r"\b(?:private key|seed phrase|wallet address)\b", re.IGNORECASE),
    re.compile(r"\b(?:your code is|security code is)\b", re.IGNORECASE),
]

# Patterns matching scammer links, crypto traps, and suspicious URL shorteners
SCAM_AND_SPAM_PATTERNS = [
    re.compile(r"t\.me\/(?:\+|joinchat\/)", re.IGNORECASE),
    re.compile(r"\b(?:airdrop|crypto bonus|free usdt|claim reward|investment opportunity|profit guaranteed|binance bonus|free btc|doubler|fast profit|earn \$)\b", re.IGNORECASE),
    re.compile(r"https?:\/\/(?:bit\.ly|tinyurl|t\.co|goo\.gl|cutt\.ly|rb\.gy|is\.gd|shorturl\.at)\b", re.IGNORECASE),
    re.compile(r"(?:https?:\/\/|www\.)\S+.*?\b(?:win|claim|free|bonus|reward|investment|crypto|earn)\b", re.IGNORECASE),
]


class SafetyManager:
    """Enforces cooldowns, rate limits, sensitive message detection, and emergency stop."""

    def __init__(self, config: AppConfig, database: Database):
        self.config = config
        self.db = database
        self._last_global_reply_time: float = (
            self.db.get_last_reply_timestamp() if (self.db and hasattr(self.db, "get_last_reply_timestamp")) else 0.0
        )
        self._last_chat_reply_time: Dict[int, float] = {}
        self._next_global_cooldown: float = 0.0
        self._next_chat_cooldown: Dict[int, float] = {}
        self._consecutive_errors: int = 0
        self._error_pause_until: float = 0.0
        self._minute_cap: int = self.max_replies_per_minute
        self._minute_cap_ts: float = 0.0

    @property
    def is_emergency_stopped(self) -> bool:
        """Check if emergency stop is currently active."""
        return self.db.get_state("emergency_stop", "0") == "1"

    def set_emergency_stop(self, stop: bool) -> None:
        """Enable or disable emergency stop."""
        self.db.set_state("emergency_stop", "1" if stop else "0")
        if stop:
            logger.warning("SAFETY: Emergency stop ACTIVATED. All automated actions halted.")
        else:
            logger.info("SAFETY: Emergency stop deactivated.")

    def set_timed_pause(self, seconds: float) -> float:
        """Pause automated replies for a specific duration in seconds."""
        until = time.time() + max(0.0, seconds)
        self.db.set_state("pause_until", str(until))
        logger.warning(f"SAFETY: Client paused for {int(seconds)}s (until timestamp {int(until)}).")
        return until

    def clear_pause(self) -> None:
        """Clear both timed pause and emergency stop."""
        self.db.set_state("pause_until", "0")
        self.db.set_state("emergency_stop", "0")
        logger.info("SAFETY: Pause and emergency stop cleared.")

    def get_remaining_pause_seconds(self) -> float:
        """Return remaining seconds if client is in a timed pause."""
        try:
            until = float(self.db.get_state("pause_until", "0"))
            return max(0.0, until - time.time())
        except ValueError:
            return 0.0

    @property
    def is_auto_authorized(self) -> bool:
        """Check if Mode 3 (Restricted Automation) has been explicitly authorized."""
        return self.db.get_state("auto_authorized", "0") == "1"

    def set_auto_authorization(self, authorized: bool) -> None:
        """Explicitly authorize or revoke restricted auto mode."""
        self.db.set_state("auto_authorized", "1" if authorized else "0")
        if authorized:
            logger.warning("SAFETY: Mode 3 Restricted Automation explicitly AUTHORIZED.")
        else:
            logger.info("SAFETY: Mode 3 Restricted Automation authorization REVOKED.")

    def record_error(self) -> None:
        """Increment consecutive error count and apply safety pause if threshold met."""
        self._consecutive_errors += 1
        if self._consecutive_errors >= 5:
            pause_seconds = 300  # 5 minutes pause
            self._error_pause_until = time.time() + pause_seconds
            logger.error(
                f"SAFETY: 5 consecutive errors detected! Pausing automated replies for {pause_seconds}s."
            )

    def record_success(self) -> None:
        """Reset consecutive error count on successful operation."""
        self._consecutive_errors = 0

    def compute_message_hash(self, chat_id: int, message_id: int, text: str) -> str:
        """Generate unique hash for message deduplication."""
        raw = f"{chat_id}:{message_id}:{text.strip()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def is_duplicate(self, chat_id: int, message_id: int, text: str) -> bool:
        """Check if message event has already been processed."""
        msg_hash = self.compute_message_hash(chat_id, message_id, text)
        if self.db.is_duplicate_message(msg_hash):
            return True
        self.db.record_message(msg_hash, chat_id)
        return False

    def is_sensitive(self, text: str) -> bool:
        """Check if message contains OTPs, passwords, or financial information."""
        if not text:
            return False
        for pattern in SENSITIVE_CONTENT_PATTERNS:
            if pattern.search(text):
                return True
        return False

    def is_scam_or_suspicious(self, text: str) -> bool:
        """Check if message contains scam invite links, crypto bait, or phishing patterns."""
        if not text:
            return False
        for pattern in SCAM_AND_SPAM_PATTERNS:
            if pattern.search(text):
                return True
        return False

    @property
    def min_chat_cooldown(self) -> float:
        db_val = self.db.get_state("min_chat_cooldown_seconds")
        if db_val:
            try:
                return max(0.0, float(db_val))
            except ValueError:
                pass
        base = getattr(self.config, "min_chat_cooldown_seconds", 5.0)
        if self.config.per_chat_cooldown_seconds < base:
            return float(self.config.per_chat_cooldown_seconds)
        return float(base)

    @property
    def max_chat_cooldown(self) -> float:
        db_val = self.db.get_state("max_chat_cooldown_seconds")
        if db_val:
            try:
                return max(self.min_chat_cooldown, float(db_val))
            except ValueError:
                pass
        base = getattr(self.config, "max_chat_cooldown_seconds", 60.0)
        if self.config.per_chat_cooldown_seconds < 5.0:
            return float(self.config.per_chat_cooldown_seconds)
        return max(self.min_chat_cooldown, float(base))

    @property
    def min_global_cooldown(self) -> float:
        db_val = self.db.get_state("min_global_cooldown_seconds")
        if db_val:
            try:
                return max(0.0, float(db_val))
            except ValueError:
                pass
        base = getattr(self.config, "min_global_cooldown_seconds", 5.0)
        if self.config.global_cooldown_seconds < base:
            return float(self.config.global_cooldown_seconds)
        return float(base)

    @property
    def max_global_cooldown(self) -> float:
        db_val = self.db.get_state("max_global_cooldown_seconds")
        if db_val:
            try:
                return max(self.min_global_cooldown, float(db_val))
            except ValueError:
                pass
        base = getattr(self.config, "max_global_cooldown_seconds", 60.0)
        if self.config.global_cooldown_seconds < 5.0:
            return float(self.config.global_cooldown_seconds)
        return max(self.min_global_cooldown, float(base))

    def _pick_random_chat_cooldown(self) -> float:
        """Choose a random cooldown between min (default 5s) and max (default 60s)."""
        lo = self.min_chat_cooldown
        hi = self.max_chat_cooldown
        return random.uniform(lo, hi) if hi >= lo else lo

    def _pick_random_global_cooldown(self) -> float:
        """Choose a random global cooldown between min (default 5s) and max (default 60s)."""
        lo = self.min_global_cooldown
        hi = self.max_global_cooldown
        return random.uniform(lo, hi) if hi >= lo else lo

    @property
    def global_cooldown_seconds(self) -> int:
        """Effective global cooldown in seconds (display/target)."""
        db_val = self.db.get_state("global_cooldown_seconds")
        if db_val:
            try:
                return max(0, int(db_val))
            except ValueError:
                pass
        return int(self.max_global_cooldown)

    @property
    def per_chat_cooldown_seconds(self) -> int:
        """Effective per-chat cooldown in seconds (display/target)."""
        db_val = self.db.get_state("per_chat_cooldown_seconds")
        if db_val:
            try:
                return max(0, int(db_val))
            except ValueError:
                pass
        return int(self.max_chat_cooldown)

    @property
    def max_replies_per_minute(self) -> int:
        """Base maximum automated replies allowed per rolling 60-second window across all chats."""
        db_val = self.db.get_state("max_replies_per_minute")
        if db_val:
            try:
                return max(1, int(db_val))
            except ValueError:
                pass
        return getattr(self.config, "max_replies_per_minute", 5)

    def _pick_dynamic_minute_limit(self, chat_id: int) -> int:
        """Human-like fluctuating burst cap: re-rolled around the base each minute,
        auto-boosted when the chat is busy (many incoming messages recently)."""
        base = self.max_replies_per_minute
        busy = False
        if self.db and hasattr(self.db, "get_recent_message_count"):
            busy = self.db.get_recent_message_count(120.0, chat_id=chat_id) >= 5
        jitter = random.randint(0, 3)
        boost = 4 if busy else 0
        return base + jitter + boost

    @property
    def max_chat_replies_per_minute(self) -> int:
        """Maximum automated replies allowed to the same individual chat in 60 seconds."""
        db_val = self.db.get_state("max_chat_replies_per_minute")
        if db_val:
            try:
                return max(1, int(db_val))
            except ValueError:
                pass
        return 3

    @property
    def quiet_hours_enabled(self) -> bool:
        """Whether quiet hours / sleep schedule is active."""
        return self.db.get_state(
            "quiet_hours_enabled",
            "1" if getattr(self.config, "quiet_hours_enabled", True) else "0",
        ) == "1"

    @property
    def quiet_hours_window(self) -> tuple[str, str]:
        """Configured (start, end) time strings in HH:MM format."""
        start = self.db.get_state("quiet_hours_start", getattr(self.config, "quiet_hours_start", "02:00"))
        end = self.db.get_state("quiet_hours_end", getattr(self.config, "quiet_hours_end", "08:00"))
        return start, end

    def set_quiet_hours(self, enabled: bool, start: Optional[str] = None, end: Optional[str] = None) -> None:
        """Update quiet hours enablement and optional schedule window."""
        self.db.set_state("quiet_hours_enabled", "1" if enabled else "0")
        if start:
            self.db.set_state("quiet_hours_start", start)
        if end:
            self.db.set_state("quiet_hours_end", end)
        logger.info(f"SAFETY: Quiet hours set to enabled={enabled}, start={start}, end={end}")

    def is_in_quiet_hours(self, now_time: Optional[datetime.time] = None) -> tuple[bool, str]:
        """
        Check if the current time falls inside the configured Quiet Hours (sleep schedule).
        Evaluated in Indian Standard Time (IST, UTC+05:30) by default.
        Returns (is_active, status_message).
        """
        if not self.quiet_hours_enabled:
            return False, "Quiet hours disabled"

        start_str, end_str = self.quiet_hours_window
        try:
            sh, sm = map(int, start_str.strip().split(":"))
            eh, em = map(int, end_str.strip().split(":"))
            start_t = datetime.time(sh, sm)
            end_t = datetime.time(eh, em)
        except Exception:
            return False, f"Invalid quiet hours format ({start_str}-{end_str})"

        # Default to Indian Standard Time (IST, UTC+05:30) for reliable 2am-8am sleep schedule across clouds
        ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        cur_t = now_time if now_time is not None else datetime.datetime.now(ist_tz).time()

        if start_t <= end_t:
            in_window = start_t <= cur_t < end_t
        else:
            # Crosses midnight (e.g. 23:00 to 07:00)
            in_window = cur_t >= start_t or cur_t < end_t

        if in_window:
            return True, f"Quiet hours active (sleep schedule {start_str} - {end_str})"
        return False, f"Outside quiet hours ({start_str} - {end_str})"

    def can_reply(self, chat_id: int, text: str) -> tuple[bool, str]:
        """Verify whether an outgoing reply is safe and permitted."""
        if self.is_emergency_stopped:
            return False, "Emergency stop active"

        remaining_pause = self.get_remaining_pause_seconds()
        if remaining_pause > 0:
            mins = int(remaining_pause // 60)
            secs = int(remaining_pause % 60)
            return False, f"Client is paused ({mins}m {secs}s remaining)"

        # Quiet hours (sleep schedule)
        is_quiet, quiet_reason = self.is_in_quiet_hours()
        if is_quiet:
            return False, quiet_reason

        now = time.time()
        if now < self._error_pause_until:
            return False, f"Safety pause active for {int(self._error_pause_until - now)}s"

        if self.is_sensitive(text):
            return False, "Message matches sensitive/OTP content pattern"

        if len(text) > self.config.max_message_length:
            return False, f"Message length ({len(text)}) exceeds maximum allowed ({self.config.max_message_length})"

        # Telegram Anti-Spam Guidelines: dynamically fluctuating rolling-minute burst limit
        if self.config.global_cooldown_seconds > 0 and self.db and hasattr(self.db, "get_recent_reply_count"):
            if self.max_replies_per_minute > 0:
                if now - self._minute_cap_ts >= 60.0:
                    self._minute_cap_ts = now
                    self._minute_cap = self._pick_dynamic_minute_limit(chat_id)
                recent_min_count = self.db.get_recent_reply_count(60.0)
                if recent_min_count >= self._minute_cap:
                    return False, f"Anti-spam burst limit reached ({recent_min_count}/{self._minute_cap} replies in last 60s)"

            if self.max_chat_replies_per_minute > 0:
                recent_chat_min = self.db.get_recent_reply_count(60.0, chat_id=chat_id)
                if recent_chat_min >= self.max_chat_replies_per_minute:
                    return False, f"Anti-spam chat burst limit reached ({recent_chat_min}/{self.max_chat_replies_per_minute} replies in last 60s for chat {chat_id})"

        # Global cooldown check (minimum 5s hard floor + randomized interval)
        time_since_global = now - self._last_global_reply_time
        floor_global = min(5.0, self.min_global_cooldown)
        if time_since_global < floor_global:
            wait_time = max(1, int(round(floor_global - time_since_global)))
            return False, f"Global cooldown active ({wait_time}s remaining)"

        global_cd = max(floor_global, self._next_global_cooldown or self._pick_random_global_cooldown())
        if time_since_global < global_cd:
            wait_time = max(1, int(round(global_cd - time_since_global)))
            return False, f"Global cooldown active ({wait_time}s remaining)"

        # Per-chat cooldown check (minimum 5s hard floor + randomized interval)
        last_chat_time = self._last_chat_reply_time.get(chat_id)
        if last_chat_time is None:
            last_chat_time = (
                self.db.get_last_reply_timestamp(chat_id)
                if (self.db and hasattr(self.db, "get_last_reply_timestamp"))
                else 0.0
            )
            self._last_chat_reply_time[chat_id] = last_chat_time
        time_since_chat = now - last_chat_time
        floor_chat = min(5.0, self.min_chat_cooldown)
        if time_since_chat < floor_chat:
            wait_time = max(1, int(round(floor_chat - time_since_chat)))
            return False, f"Per-chat cooldown active for chat {chat_id} ({wait_time}s remaining)"

        chat_cd = max(floor_chat, self._next_chat_cooldown.get(chat_id) or self._pick_random_chat_cooldown())
        if time_since_chat < chat_cd:
            wait_time = max(1, int(round(chat_cd - time_since_chat)))
            return False, f"Per-chat cooldown active for chat {chat_id} ({wait_time}s remaining)"

        return True, "OK"

    def mark_reply_sent(self, chat_id: int) -> None:
        """Update cooldown timestamps after sending a reply and pick next randomized interval."""
        now = time.time()
        self._last_global_reply_time = now
        self._last_chat_reply_time[chat_id] = now
        self._next_global_cooldown = self._pick_random_global_cooldown()
        self._next_chat_cooldown[chat_id] = self._pick_random_chat_cooldown()
        if self.db and hasattr(self.db, "record_reply_event"):
            try:
                self.db.record_reply_event(chat_id, now)
            except Exception as e:
                logger.debug(f"Could not record reply event: {e}")
        self.record_success()
