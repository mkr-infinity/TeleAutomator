"""Verify Telegram connection and personal account status without performing actions."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telethon import TelegramClient

from app.config import load_config
from app.session_manager import get_telethon_session


async def check() -> None:
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
            print("[FAIL] Session exists but is NOT authorized. Please run ./local/authenticate.sh.")
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

    except Exception as e:
        print(f"[FAIL] Connection error: {e}")
        sys.exit(1)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(check())
