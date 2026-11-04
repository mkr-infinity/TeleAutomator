"""Main entrypoint for the Personal Telegram Client."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path

from app.ai.reply_generator import ReplyGenerator
from app.config import load_config
from app.health import HealthMonitor
from app.logger import setup_logger
from app.privacy_manager import PrivacyManager
from app.reply_manager import ReplyManager
from app.safety_manager import SafetyManager
from app.storage.database import Database
from app.telegram_client import TelegramService

logger = setup_logger(__name__)


def run_health_check() -> int:
    """Execute health check and return exit code for Docker/monitoring."""
    data_dir = Path(os.getenv("DATA_DIR", "data"))
    monitor = HealthMonitor(data_dir)
    if monitor.is_healthy():
        sys.stdout.write("HEALTHY: Client is connected and active.\n")
        return 0
    sys.stderr.write("UNHEALTHY: Client is not connected or heartbeat is stale.\n")
    return 1


async def run_app() -> None:
    """Load configuration and run the Telegram client with graceful signal handling."""
    config = load_config()
    setup_logger(level_name=config.log_level)
    logger.info("Initializing Telegram Personal Client application...")

    # Initialize storage & managers
    db = Database(config.data_dir / "app.db")
    safety = SafetyManager(config, db)
    if config.auto_authorize:
        safety.set_auto_authorization(True)
    privacy = PrivacyManager(config)
    generator = ReplyGenerator(config)
    reply_mgr = ReplyManager(config, db, safety, privacy, generator)
    health = HealthMonitor(config.data_dir)

    service = TelegramService(
        config=config,
        database=db,
        safety_manager=safety,
        privacy_manager=privacy,
        reply_manager=reply_mgr,
        health_monitor=health,
    )

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Received termination signal. Initiating shutdown...")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass  # Windows or restricted environments

    # Run service as a background task and wait for stop_event
    run_task = asyncio.create_task(service.run())

    try:
        # Wait until run_task finishes or stop_event is fired
        wait_stop = asyncio.create_task(stop_event.wait())
        done, _ = await asyncio.wait([run_task, wait_stop], return_when=asyncio.FIRST_COMPLETED)

        if wait_stop in done:
            await service.stop()
            run_task.cancel()
        elif run_task in done:
            # Service completed or failed
            run_task.result()
    finally:
        await service.stop()


def main() -> None:
    if "--health" in sys.argv:
        sys.exit(run_health_check())

    try:
        asyncio.run(run_app())
    except KeyboardInterrupt:
        logger.info("Process interrupted by user. Exiting.")
    except Exception as e:
        logger.critical(f"Application terminated with fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
