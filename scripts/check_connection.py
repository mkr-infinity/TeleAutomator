"""Verify Telegram connection and personal account status without performing actions."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telethon import TelegramClient
from telethon.errors import (
    AuthKeyDuplicatedError,
    AuthKeyUnregisteredError,
    SessionExpiredError,
    SessionRevokedError,
)

from app.banner import print_banner
from app.config import load_config
from app.session_manager import get_telethon_session


async def check() -> None:
    print_banner()
    print("Testing Telegram MTProto connection...")
    try:
        config = load_config()
    except Exception as e:
        print(f"[FAIL] Configuration error: {e}")
        sys.exit(1)

    session = get_telethon_session(config)
    client = TelegramClient(session, config.api_id, config.api_hash)

    try:
        await client.connect()
        if not await client.is_user_authorized():
            print("[FAIL] Session exists but is NOT authorized. Please run ./authenticate.sh (or: python3 run.py --auth).")
            sys.exit(1)

        me = await client.get_me()
        print("[SUCCESS] Connected to Telegram MTProto successfully!")
        print(f" Account ID   : {me.id}")
        print(f" Account Name : {me.first_name or ''} {me.last_name or ''}".strip())
        print(f" Username     : @{me.username}" if me.username else " Username     : (none)")
        print(f" Account Type : {'Bot' if me.bot else 'Personal User Account'}")
        print(f" Phone        : {me.phone[:4]}***" if me.phone else " Phone        : Hidden")

        if me.bot:
            print("[WARNING] Account is marked as a Bot. This application expects a personal account.")
            sys.exit(1)

        print("\nTip: To allow the client to reply to specific contacts, put their Chat IDs in .env:")
        print("  ALLOWED_PRIVATE_CHATS=123456789,987654321")
        print("When anyone sends you a message while the client runs, its Chat ID is printed in the terminal.\n")

    except (AuthKeyDuplicatedError, AuthKeyUnregisteredError, SessionRevokedError, SessionExpiredError) as e:
        print("\n" + "=" * 60)
        print(" [FAIL] TELEGRAM SESSION REVOKED (AuthKeyDuplicatedError)")
        print("=" * 60)
        print("The authorization key was invalidated by Telegram.")
        print("CAUSE: The session was used under two different IP addresses simultaneously")
        print("(e.g. running locally and on Railway at the same time), or revoked in Devices.")
        print("\nHOW TO FIX:")
        print("1. Re-authenticate: run ./authenticate.sh (or: python run.py --auth)")
        print("2. If using Railway: export the new session string with ./session.sh")
        print("   and update TG_SESSION_STRING in your Railway dashboard.")
        print("=" * 60 + "\n")
        sys.exit(1)
    except Exception as e:
        print(f"[FAIL] Connection error: {e}")
        sys.exit(1)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(check())
