"""Health tracking and status file management for Docker and local checks."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from app.logger import setup_logger

logger = setup_logger(__name__)


class HealthMonitor:
    """Manages periodic health heartbeats without exposing private account information."""

    def __init__(self, data_dir: Path):
        self.health_file = data_dir / "health.json"
        self.start_time = time.time()
        self.is_connected = False
        self.emergency_stop = False

    def update_heartbeat(self, is_connected: bool, emergency_stop: bool = False) -> None:
        """Write sanitized health status to JSON file."""
        self.is_connected = is_connected
        self.emergency_stop = emergency_stop
        uptime = int(time.time() - self.start_time)
        status = {
            "status": "healthy" if is_connected else "disconnected",
            "connected": is_connected,
            "emergency_stop": emergency_stop,
            "uptime_seconds": uptime,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self.health_file.parent.mkdir(parents=True, exist_ok=True)
            self.health_file.write_text(json.dumps(status, indent=2))
        except Exception as e:
            logger.warning(f"Could not write health heartbeat: {e}")

    def is_healthy(self, max_stale_seconds: int = 120) -> bool:
        """Check if health file exists, is connected, and was updated recently."""
        if not self.health_file.exists():
            return False
        try:
            data = json.loads(self.health_file.read_text())
            if not data.get("connected", False):
                return False
            # Check file modification time freshness
            mtime = self.health_file.stat().st_mtime
            if (time.time() - mtime) > max_stale_seconds:
                return False
            return True
        except Exception:
            return False
