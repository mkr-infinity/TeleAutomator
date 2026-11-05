"""Export or generate Telethon StringSession for cloud deployment."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telethon import TelegramClient
from telethon.errors import (
    AuthKeyDuplicatedError,
    AuthKeyUnregisteredError,
    SessionExpiredError,
    SessionPasswordNeededError,
    SessionRevokedError,
)
from telethon.sessions import StringSession

from app.config import AppConfig, load_config
from app.session_manager import get_local_session_path


async def generate_new_cloud_session(config: AppConfig) -> None:
    """Generate a dedicated, isolated StringSession via interactive MTProto sign-in."""
    print("\n" + "=" * 60)
    print(" Generate Dedicated Cloud StringSession")
    print("=" * 60)
    print("This creates a distinct MTProto session for Railway/Render/Docker.")
    print("Because it is registered as an independent device, it will NOT")
    print("conflict with your local desktop session.\n")

    client = TelegramClient(StringSession(), config.api_id, config.api_hash)
    await client.connect()

    phone = input("Enter your phone number (with country code, e.g. +1234567890): ").strip()
    if not phone:
        print("[ERROR] Phone number cannot be empty.")
        await client.disconnect()
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

    me = await client.get_me()
    cloud_session = StringSession.save(client.session)
    await client.disconnect()

    print("\n" + "=" * 60)
    print(" DEDICATED CLOUD STRING SESSION (TG_SESSION_STRING)")
    print("=" * 60)
    print("\n" + cloud_session + "\n")
    print("=" * 60)
    print(f"Account Connected : {me.first_name or ''} {me.last_name or ''}".strip())
    print(f"Username          : @{me.username}" if me.username else "Username          : (none)")
    print(f"User ID           : {me.id}")
    print("\n✅ This session is dedicated for cloud deployment.")
    print("You can run TeleAutomator locally AND on Railway simultaneously without conflict!")
    print("Copy this value into Railway dashboard as TG_SESSION_STRING.\n")


async def export_existing_session(config: AppConfig) -> None:
    """Export the StringSession from an authorized local .session file."""
    session_path = get_local_session_path(config.data_dir, config.session_name)
    session_file = session_path.with_suffix(".session")

    if not session_file.exists():
        print(f"\n[ERROR] Local session file not found: {session_file}")
        print("Choose an option:")
        print("  1. Run ./authenticate.sh to create a local session.")
        print("  2. Run ./session.sh --new to generate a dedicated cloud session directly.\n")
        sys.exit(1)

    client = TelegramClient(str(session_path), config.api_id, config.api_hash)
    try:
        await client.connect()
    except (AuthKeyDuplicatedError, AuthKeyUnregisteredError, SessionRevokedError, SessionExpiredError):
        print("\n" + "=" * 60)
        print(" [ERROR] LOCAL SESSION REVOKED BY TELEGRAM (AuthKeyDuplicatedError)")
        print("=" * 60)
        print("Your local session was invalidated because it was used simultaneously from")
        print("two different IP addresses (e.g. running locally and on Railway at the same time),")
        print("or terminated in Telegram Settings > Devices.")
        print("\nTo fix this:")
        print("1. Re-authenticate locally: ./authenticate.sh (or: python run.py --auth)")
        print("2. Or generate a dedicated cloud session: ./session.sh --new")
        print("=" * 60 + "\n")
        sys.exit(1)

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
    print("Copy this value into Railway or .env as TG_SESSION_STRING.")
    print("\n⚠️  IMPORTANT RULE:")
    print("Do NOT run TeleAutomator locally and on Railway simultaneously with this same session!")
    print("Telegram will invalidate it if connected from two IP addresses at once.")
    print("To run both concurrently, generate a separate session: ./session.sh --new\n")


async def main_async() -> None:
    parser = argparse.ArgumentParser(description="Export or generate Telethon StringSession for cloud deployment")
    parser.add_argument(
        "--new", "-n", action="store_true", help="Generate a fresh, dedicated cloud StringSession via phone/OTP login"
    )
    args, _ = parser.parse_known_args()

    try:
        config = load_config()
    except Exception as e:
        print(f"[ERROR] Configuration error: {e}")
        sys.exit(1)

    if args.new:
        await generate_new_cloud_session(config)
    else:
        await export_existing_session(config)


if __name__ == "__main__":
    asyncio.run(main_async())
