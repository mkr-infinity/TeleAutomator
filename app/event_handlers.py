"""Telethon event dispatchers and handlers."""

from __future__ import annotations

from typing import Any

from telethon import events

from app.logger import setup_logger
from app.message_filter import MessageFilter
from app.reply_manager import ReplyManager

logger = setup_logger(__name__)


def register_handlers(
    client: Any,
    my_user_id: int,
    message_filter: MessageFilter,
    reply_manager: ReplyManager,
) -> None:
    """Register incoming message and control command handlers with the Telethon client."""

    @client.on(events.NewMessage)
    async def on_new_message(event: Any) -> None:
        chat_id = getattr(event, "chat_id", None)
        text = getattr(event, "raw_text", "") or ""

        # Check for control commands sent in private 'Saved Messages' (chat with self)
        # In Telethon, private chat with oneself has chat_id == my_user_id
        if chat_id == my_user_id and text.startswith("/"):
            logger.info("Received control command in Saved Messages.")
            response = await reply_manager.handle_control_command(text)
            if response:
                await client.send_message("me", response, parse_mode="md")
            return

        # Regular incoming message handling
        is_eligible, reason = message_filter.evaluate(event)
        if not is_eligible:
            # Helper log for users: shows the Chat ID so they can easily copy it into .env
            if "not allowlisted" in reason and chat_id:
                logger.info(
                    f"[CHAT DETECTED] Received message from Chat ID: {chat_id}. "
                    f"To allow replies for this contact/group, add {chat_id} to ALLOWED_PRIVATE_CHATS in .env"
                )
            else:
                logger.debug(f"Message ignored: {reason}")
            return

        # Resolve chat title and sender name safely
        chat_title = f"Chat {chat_id}"
        try:
            chat = await event.get_chat()
            if hasattr(chat, "title") and chat.title:
                chat_title = chat.title
            elif hasattr(chat, "first_name") and chat.first_name:
                chat_title = chat.first_name
        except Exception:
            pass

        sender_name = "User"
        sender_id = getattr(event, "sender_id", None)
        try:
            sender = await event.get_sender()
            if hasattr(sender, "first_name") and sender.first_name:
                sender_name = sender.first_name
            elif hasattr(sender, "username") and sender.username:
                sender_name = f"@{sender.username}"
        except Exception:
            pass

        message_id = getattr(event, "id", 0)

        await reply_manager.handle_incoming_eligible_message(
            chat_id=chat_id,
            chat_title=chat_title,
            message_id=message_id,
            sender_id=sender_id,
            sender_name=sender_name,
            text=text,
        )
