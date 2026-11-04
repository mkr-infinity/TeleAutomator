"""Main entrypoint for the Personal Telegram Client."""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
from pathlib import Path
from typing import Optional

from app.ai.reply_generator import ReplyGenerator
from app.banner import print_banner
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


async def run_app(mode_override: Optional[str] = None, style_override: Optional[str] = None) -> None:
    """Load configuration and run the Telegram client with graceful signal handling."""
    config = load_config()
    setup_logger(level_name=config.log_level)
    logger.info("Initializing TeleAutomator personal client application...")

    # Initialize storage & managers
    db = Database(config.data_dir / "app.db")

    # Apply runtime CLI overrides if provided
    if mode_override:
        config.reply_mode = mode_override
        db.set_state("reply_mode", mode_override)
        logger.info(f"CLI mode override active: {mode_override}")

    safety = SafetyManager(config, db)
    if config.auto_authorize or config.reply_mode == "restricted_auto":
        safety.set_auto_authorization(True)

    privacy = PrivacyManager(config, database=db)
    generator = ReplyGenerator(config)
    if style_override:
        generator.set_style(style_override)
        db.set_state("reply_style", style_override)
        logger.info(f"CLI style override active: {style_override}")

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

    parser = argparse.ArgumentParser(
        description="TeleAutomator - Personal Telegram AI Assistant",
        add_help=True,
    )
    parser.add_argument(
        "--mode",
        choices=["draft", "approval", "restricted_auto"],
        help="Override automation mode (draft, approval, restricted_auto)",
    )
    parser.add_argument(
        "--draft",
        action="store_true",
        help="Run strictly in Draft-only mode (generates and logs drafts; never sends)",
    )
    parser.add_argument(
        "--style",
        choices=["casual", "concise", "formal", "humorous"],
        help="Override AI reply style",
    )

    args, _ = parser.parse_known_args()

    mode = "draft" if args.draft else args.mode
    style = args.style

    print_banner()

    try:
        asyncio.run(run_app(mode_override=mode, style_override=style))
    except KeyboardInterrupt:
        logger.info("Process interrupted by user. Exiting.")
    except Exception as e:
        logger.critical(f"Application terminated with fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
