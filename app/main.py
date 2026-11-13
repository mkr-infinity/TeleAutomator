"""Main entrypoint for the Personal Telegram Client."""

from __future__ import annotations

import argparse
import asyncio
import json
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

    # Safe-mode boot guard: hold automation in draft if the process is crash-looping
    try:
        from app.boot_guard import record_boot_and_maybe_safe_mode
        boot_status = record_boot_and_maybe_safe_mode(db, config)
        if boot_status == "safe-mode":
            logger.warning("Safe mode engaged: starting in draft mode until the process proves stable.")
    except Exception as e:
        logger.warning(f"Boot guard error (continuing normally): {e}")

    # Apply runtime CLI overrides if provided
    if mode_override:
        config.reply_mode = mode_override
        db.set_state("reply_mode", mode_override)
        logger.info(f"CLI mode override active: {mode_override}")

    safety = SafetyManager(config, db)
    if config.auto_authorize or config.reply_mode == "restricted_auto":
        safety.set_auto_authorization(True)

    privacy = PrivacyManager(config, database=db)
    generator = ReplyGenerator(config, database=db)
    if style_override:
        generator.set_style(style_override)
        db.set_state("reply_style", style_override)
        logger.info(f"CLI style override active: {style_override}")

    reply_mgr = ReplyManager(config, db, safety, privacy, generator)
    health = HealthMonitor(config.data_dir)

    # Bot control channel: replaces Saved Messages as the command + alert surface when configured
    bot_task: Optional[asyncio.Task] = None
    if config.bot_api_key:
        if not config.bot_authorized_users:
            logger.warning("BOT_API_KEY is set but BOT_AUTHORIZED_USERS is empty; "
                           "add your Telegram user ID to BOT_AUTHORIZED_USERS to control the project.")
        try:
            from app.bot_control import BotControl
            bot_control = BotControl(
                api_key=config.bot_api_key,
                db=db,
                reply_manager=reply_mgr,
                seed_user_ids=config.bot_authorized_users,
                health_file=config.data_dir / "health.json",
            )
            reply_mgr.bot_control = bot_control
            logger.info("Bot control channel enabled (Saved Messages commands disabled; alerts route to bot).")
        except Exception as e:
            logger.warning(f"Could not initialize bot control channel: {e}")
            reply_mgr.bot_control = None

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

    # Start the bot control long-poll loop alongside the main service
    if reply_mgr.bot_control is not None:
        bot_task = asyncio.create_task(reply_mgr.bot_control.run())

    # HTTP server for cloud platforms (Railway / Render) and local Mini App GUI.
    # Defaults to port 8080 so the Mini App server and health checks always start automatically.
    port_env = os.getenv("PORT", "8080")
    http_server = None
    miniapp_server = None
    server_status = {"healthy": True, "error": None}

    try:
        from app.miniapp_server import MiniAppContext, MiniAppServer, resolve_miniapp_url, set_telegram_menu_button
        miniapp_ctx = MiniAppContext(
            db=db,
            safety=safety,
            privacy=privacy,
            reply_manager=reply_mgr,
            generator=generator,
            bot_token=config.bot_api_key or "",
            loop=loop,
            bot_control=reply_mgr.bot_control,
        )
        miniapp_ctx.health_status = server_status
        miniapp_server = MiniAppServer(miniapp_ctx, port=int(port_env))
        miniapp_server.start()
        logger.info(f"TeleAutomator Mini App running on port {port_env}")

        miniapp_url = resolve_miniapp_url()
        if miniapp_url and config.bot_api_key:
            logger.info(f"Auto-registering Telegram Mini App menu button: {miniapp_url}")
            await loop.run_in_executor(None, set_telegram_menu_button, config.bot_api_key, miniapp_url)
    except Exception as e:
        logger.warning(f"Could not start mini app server on port {port_env}: {e}")
        miniapp_server = None

    if port_env and miniapp_server is None:
        try:
            port = int(port_env)
            async def _handle_http(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
                try:
                    await reader.read(1024)
                    if not server_status["healthy"]:
                        body = json.dumps({
                            "status": "error",
                            "service": "teleautomator",
                            "reason": "session_invalid_or_revoked",
                            "detail": server_status["error"] or "Telegram session revoked",
                        }).encode("utf-8") + b"\n"
                        header = (
                            b"HTTP/1.1 503 Service Unavailable\r\n"
                            b"Content-Type: application/json\r\n"
                            b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
                            b"Connection: close\r\n\r\n"
                        )
                    else:
                        body = b'{"status":"healthy","service":"teleautomator"}\n'
                        header = (
                            b"HTTP/1.1 200 OK\r\n"
                            b"Content-Type: application/json\r\n"
                            b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
                            b"Connection: close\r\n\r\n"
                        )
                    writer.write(header + body)
                    await writer.drain()
                except Exception:
                    pass
                finally:
                    try:
                        writer.close()
                        await writer.wait_closed()
                    except Exception:
                        pass

            http_server = await asyncio.start_server(_handle_http, "0.0.0.0", port)
            logger.info(f"Render / Cloud PaaS HTTP health server listening on port {port}.")
        except Exception as e:
            logger.warning(f"Could not start HTTP health server on port {port_env}: {e}")

    try:
        # Wait until run_task finishes or stop_event is fired
        wait_stop = asyncio.create_task(stop_event.wait())
        done, _ = await asyncio.wait([run_task, wait_stop], return_when=asyncio.FIRST_COMPLETED)

        if wait_stop in done:
            await service.stop()
            run_task.cancel()
        elif run_task in done:
            # Service completed or failed
            exc = run_task.exception()
            if exc:
                server_status["healthy"] = False
                server_status["error"] = str(exc)
                is_cloud = bool(port_env or os.getenv("RAILWAY_STATIC_URL") or os.getenv("RENDER") or os.getenv("TG_SESSION_STRING"))
                if is_cloud and ("AuthKeyDuplicatedError" in str(exc) or "REVOKED" in str(exc)):
                    logger.critical(
                        "Cloud deployment halted due to revoked Telegram session. "
                        "Backing off for 60 seconds to prevent rapid crash-restart loops on Railway..."
                    )
                    try:
                        await asyncio.sleep(60)
                    except asyncio.CancelledError:
                        pass
                raise exc
    finally:
        if miniapp_server:
            miniapp_server.stop()
        if http_server:
            http_server.close()
            await http_server.wait_closed()
        await service.stop()
        if bot_task is not None and not bot_task.done():
            bot_task.cancel()
            try:
                await bot_task
            except (asyncio.CancelledError, Exception):
                pass


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
