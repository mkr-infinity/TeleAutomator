"""Export Telethon StringSession from existing local session file for cloud deployment."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telethon import TelegramClient
from telethon.sessions import StringSession

from app.config import load_config
from app.session_manager import get_local_session_path


async def export_session() -> None:
    try:
        config = load_config()
    except Exception as e:
        print(f"[ERROR] Configuration error: {e}")
        sys.exit(1)

    session_path = get_local_session_path(config.data_dir, config.session_name)
    session_file = session_path.with_suffix(".session")

    if not session_file.exists():
        print(f"[ERROR] Session file not found: {session_file}")
        print("Please authenticate first by running ./authenticate.sh (or: python3 run.py --auth)")
        sys.exit(1)

    client = TelegramClient(str(session_path), config.api_id, config.api_hash)
    await client.connect()

    if not await client.is_user_authorized():
        print("[ERROR] Session is not authorized. Please run ./authenticate.sh (or: python3 run.py --auth)")
        await client.disconnect()
        sys.exit(1)

    cloud_session = StringSession.save(client.session)
    await client.disconnect()

    print("\n" + "=" * 60)
    print(" EXPORTED STRING SESSION (TG_SESSION_STRING)")
    print("=" * 60)
    print("\n" + cloud_session + "\n")
    print("=" * 60)
    print("Copy this value into .env as TG_SESSION_STRING if deploying to Docker or cloud VPS.")
    print("NEVER commit or share this string.\n")


if __name__ == "__main__":
    asyncio.run(export_session())
