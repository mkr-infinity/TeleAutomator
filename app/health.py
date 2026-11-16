"""Health tracking and status file management for Docker and local checks."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from app.logger import setup_logger

logger = setup_logger(__name__)


class HealthMonitor:
    """Manages periodic health heartbeats without exposing private account information."""

    def __init__(self, data_dir: Path):
        self.health_file = data_dir / "health.json"
        self.start_time = time.time()
        self.is_connected = False
        self.emergency_stop = False
        self.ready = False
        self._last_heartbeat = None
        self.connection_probe = None

    def update_heartbeat(self, is_connected: bool, emergency_stop: bool = False, ready: bool | None = None) -> None:
        """Write sanitized health status to JSON file."""
        self.is_connected = is_connected
        self.emergency_stop = emergency_stop
        self.ready = is_connected and (ready if ready is not None else True)
        self._last_heartbeat = time.monotonic()
        uptime = int(time.time() - self.start_time)
        status = {
            "status": "healthy" if self.ready else "disconnected",
            "ready": self.ready,
            "connected": is_connected,
            "emergency_stop": emergency_stop,
            "uptime_seconds": uptime,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self.health_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.health_file.with_suffix(".tmp")
            temporary.write_text(json.dumps(status, indent=2))
            temporary.replace(self.health_file)
        except Exception as e:
            logger.warning(f"Could not write health heartbeat: {e}")

    def get_status(self, max_stale_seconds: int = 120) -> dict:
        """Live sanitized readiness for HTTP handlers; startup is never ready."""
        fresh = self._last_heartbeat is not None and 0 <= time.monotonic() - self._last_heartbeat <= max_stale_seconds
        connected = self.is_connected
        if self.connection_probe is not None:
            try:
                connected = bool(self.connection_probe())
            except Exception:
                connected = False
        ready = bool(self.ready and connected and fresh)
        return {"status": "healthy" if ready else "unavailable", "ready": ready,
                "connected": connected, "emergency_stop": self.emergency_stop}

    def is_healthy(self, max_stale_seconds: int = 120) -> bool:
        """Check if health file exists, is connected, and was updated recently."""
        if not self.health_file.exists():
            return False
        try:
            data = json.loads(self.health_file.read_text())
            if not data.get("connected", False) or not data.get("ready", False):
                return False
            # Check file modification time freshness
            mtime = self.health_file.stat().st_mtime
            if not 0 <= time.time() - mtime <= max_stale_seconds:
                return False
            return True
        except Exception:
            return False
