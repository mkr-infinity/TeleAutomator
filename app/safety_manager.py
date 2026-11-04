"""Safety and rate limiting controls to prevent spam, loops, and sensitive data leakage."""

from __future__ import annotations

import hashlib
import re
import time
from typing import Dict, Optional

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
        self._last_global_reply_time: float = 0.0
        self._last_chat_reply_time: Dict[int, float] = {}
        self._consecutive_errors: int = 0
        self._error_pause_until: float = 0.0

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

    def can_reply(self, chat_id: int, text: str) -> tuple[bool, str]:
        """Verify whether an outgoing reply is safe and permitted."""
        if self.is_emergency_stopped:
            return False, "Emergency stop active"

        remaining_pause = self.get_remaining_pause_seconds()
        if remaining_pause > 0:
            mins = int(remaining_pause // 60)
            secs = int(remaining_pause % 60)
            return False, f"Client is paused ({mins}m {secs}s remaining)"

        now = time.time()
        if now < self._error_pause_until:
            return False, f"Safety pause active for {int(self._error_pause_until - now)}s"

        if self.is_sensitive(text):
            return False, "Message matches sensitive/OTP content pattern"

        if len(text) > self.config.max_message_length:
            return False, f"Message length ({len(text)}) exceeds maximum allowed ({self.config.max_message_length})"

        # Global cooldown check
        time_since_global = now - self._last_global_reply_time
        if time_since_global < self.config.global_cooldown_seconds:
            wait_time = int(self.config.global_cooldown_seconds - time_since_global)
            return False, f"Global cooldown active ({wait_time}s remaining)"

        # Per-chat cooldown check
        last_chat_time = self._last_chat_reply_time.get(chat_id, 0.0)
        time_since_chat = now - last_chat_time
        if time_since_chat < self.config.per_chat_cooldown_seconds:
            wait_time = int(self.config.per_chat_cooldown_seconds - time_since_chat)
            return False, f"Per-chat cooldown active for chat {chat_id} ({wait_time}s remaining)"

        return True, "OK"

    def mark_reply_sent(self, chat_id: int) -> None:
        """Update cooldown timestamps after sending a reply."""
        now = time.time()
        self._last_global_reply_time = now
        self._last_chat_reply_time[chat_id] = now
        self.record_success()
