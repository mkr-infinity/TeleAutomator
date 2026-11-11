"""Safe-mode boot guard.

If the process boots repeatedly in a short window (crash loop: bad config, revoked
session, failing provider), automation is held in draft mode so a broken deploy can
never spam real chats. After the process stays up for a calm period, the previous
mode is restored automatically and the owner is alerted via the control channel.
"""

from __future__ import annotations

import json
import time
from typing import Optional

from app.logger import setup_logger
from app.storage.database import Database

logger = setup_logger(__name__)

DEFAULT_WINDOW_SECONDS = 600.0      # crash window: 10 minutes
DEFAULT_RESTARTS = 3                # boots needed inside the window to trigger safe mode
DEFAULT_RECOVER_MINUTES = 15        # calm uptime required before restoring the real mode


def record_boot_and_maybe_safe_mode(db: Database, config) -> Optional[str]:
    """Record this boot; if too many boots happened recently while automation is in
    restricted_auto, force draft mode (safe mode). Returns a status string or None."""
    now = time.time()
    try:
        history = json.loads(db.get_state("boot_history", "[]") or "[]")
    except Exception:
        history = []
    history = [float(t) for t in history if float(t) > now - DEFAULT_WINDOW_SECONDS]
    history.append(now)
    db.set_state("boot_history", json.dumps(history))

    try:
        threshold = max(2, int(db.get_state("safe_mode_restarts", str(DEFAULT_RESTARTS))))
    except ValueError:
        threshold = DEFAULT_RESTARTS

    active = db.get_state("safe_mode_active", "0") == "1"
    rapid_boots = len([t for t in history if t > now - DEFAULT_WINDOW_SECONDS]) >= threshold

    if active:
        return "already-safe"

    if rapid_boots and config.reply_mode == "restricted_auto":
        current = db.get_state("reply_mode", config.reply_mode)
        if current == "restricted_auto":
            db.set_state("safe_mode_prev_mode", "restricted_auto")
            db.set_state("reply_mode", "draft")
            db.set_state("safe_mode_active", "1")
            db.set_state("safe_mode_since", str(now))
            logger.warning(
                f"SAFE MODE: {len(history)} boots in {int(DEFAULT_WINDOW_SECONDS / 60)} minutes "
                f"(threshold {threshold}). Automation held in DRAFT mode — nothing will be sent to chats. "
                f"Auto-recovers after {int(db.get_state('safe_mode_recover_minutes', str(DEFAULT_RECOVER_MINUTES)))} min of calm uptime."
            )
            return "safe-mode"

    return None
