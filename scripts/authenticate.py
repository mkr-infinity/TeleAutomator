"""Interactive first-time authentication for personal Telegram MTProto account."""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

from app.config import load_config
from app.logger import setup_logger
from app.session_manager import ensure_secure_file, get_local_session_path

logger = setup_logger("authenticator")


async def authenticate() -> None:
    print("=" * 60)
    print(" Telegram Personal MTProto Account Authentication")
    print("=" * 60)

    try:
        config = load_config()
    except Exception as e:
        print(f"\n[ERROR] Configuration error: {e}")
        print("Please check your .env file or environment variables.\n")
        sys.exit(1)

    session_path = get_local_session_path(config.data_dir, config.session_name)
    session_file = session_path.with_suffix(".session")

    if session_file.exists():
        print(f"\nFound existing session file: {session_file}")
        confirm = input("A session already exists. Re-authenticate and overwrite? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Aborted. Existing session kept.")
            return

    # Use StringSession during interactive login to easily generate both local file and string export
    client = TelegramClient(str(session_path), config.api_id, config.api_hash)
    await client.connect()

    if await client.is_user_authorized():
        print("\nSession is already authorized!")
    else:
        phone = input("\nEnter your phone number (with country code, e.g., +1234567890): ").strip()
        if not phone:
            print("[ERROR] Phone number cannot be empty.")
            sys.exit(1)

        print(f"Requesting verification code for {phone[:4]}***...")
        await client.send_code_request(phone)

        code = input("Enter the 5-digit verification code received in Telegram: ").strip()
        try:
            await client.sign_in(phone=phone, code=code)
        except SessionPasswordNeededError:
            print("\nTwo-step verification (2FA) is enabled on this account.")
            password = getpass.getpass("Enter your 2FA password: ")
            await client.sign_in(password=password)

    # Secure local session file
    if session_file.exists():
        ensure_secure_file(session_file)

    me = await client.get_me()
    if getattr(me, "bot", False):
        print("\n[ERROR] Connected account is a BOT, not a personal user account!")
        print("This application requires your actual personal Telegram account.")
        await client.disconnect()
        sys.exit(1)

    print("\n" + "=" * 60)
    print(" Authentication Successful!")
    print(f" Account Name : {me.first_name or ''} {me.last_name or ''}".strip())
    print(f" Username     : @{me.username}" if me.username else " Username     : (none)")
    print(f" User ID      : {me.id}")
    print(f" Session File : {session_file}")
    print("=" * 60)

    # Export StringSession for cloud deployment
    # Load session string using StringSession
    string_client = TelegramClient(StringSession(), config.api_id, config.api_hash)
    await string_client.connect()
    # Telethon allows exporting session string
    # We export directly from client session
    cloud_session_str = StringSession.save(client.session)

    print("\n" + "#" * 60)
    print(" CLOUD DEPLOYMENT SESSION STRING (TG_SESSION_STRING)")
    print("#" * 60)
    print("\nIf you deploy this client to a cloud server or Docker VPS,")
    print("use the following session string as the value for TG_SESSION_STRING:")
    print("\n" + cloud_session_str + "\n")
    print("⚠️  SECURITY WARNING:")
    print("1. Keep this string completely private. Treat it like a password.")
    print("2. NEVER commit it to git or paste it in public channels.")
    print("3. Do not run local and cloud instances at the exact same time.")
    print("4. Revoke anytime in Telegram: Settings -> Devices.")
    print("#" * 60 + "\n")

    await client.disconnect()


if __name__ == "__main__":
    import asyncio
    asyncio.run(authenticate())
