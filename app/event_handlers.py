"""Telethon event dispatchers and handlers."""

from __future__ import annotations

import re
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

        is_group = getattr(event, "is_group", False)
        message_obj = getattr(event, "message", None)
        message_id = getattr(event, "id", 0)

        # In groups with mention_only enabled, verify whether the reply or mention actually targets us
        reply_msg = None
        if is_group and reply_manager.db:
            mention_only = reply_manager.db.get_state("group_mention_only", "1") == "1"
            if mention_only:
                raw_text_lower = text.lower()
                my_username = (message_filter.my_username or "").lower()
                owner_name = (reply_manager.db.get_state("owner_name", "") or "").strip().lower()

                is_explicitly_mentioned = False
                if message_obj and getattr(message_obj, "mentioned", False):
                    is_explicitly_mentioned = True
                elif my_username and f"@{my_username}" in raw_text_lower:
                    is_explicitly_mentioned = True
                elif owner_name and len(owner_name) >= 3 and re.search(r"\b" + re.escape(owner_name) + r"\b", raw_text_lower):
                    is_explicitly_mentioned = True

                is_reply_to_me = False
                if getattr(event, "is_reply", False):
                    try:
                        reply_msg = await event.get_reply_message()
                        if reply_msg:
                            reply_sender_id = getattr(reply_msg, "sender_id", None)
                            reply_out = getattr(reply_msg, "out", False)
                            if reply_out or reply_sender_id == my_user_id:
                                is_reply_to_me = True
                    except Exception:
                        pass

                if not (is_explicitly_mentioned or is_reply_to_me):
                    logger.debug(f"Group message in {chat_id} ignored: not mentioned and not a reply to user.")
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

        # Extract recent conversation context (read recent chat messages before replying)
        conversation_history = []
        try:
            recent_msgs = await client.get_messages(chat_id, limit=6)
            if recent_msgs:
                for m in reversed(recent_msgs):
                    if getattr(m, "id", None) == message_id:
                        continue
                    m_text = getattr(m, "raw_text", "") or ""
                    m_text = m_text.strip()
                    if not m_text:
                        continue
                    m_sender_id = getattr(m, "sender_id", None)
                    m_out = getattr(m, "out", False)
                    if m_out or m_sender_id == my_user_id:
                        s_label = "You"
                    else:
                        s_label = "Contact"
                        try:
                            s_obj = await m.get_sender()
                            if s_obj and getattr(s_obj, "first_name", None):
                                s_label = s_obj.first_name
                        except Exception:
                            pass
                    conversation_history.append({"sender": s_label, "text": m_text})
        except Exception as e:
            logger.debug(f"Could not fetch recent chat history for context: {e}")

        # Ensure replied-to message is explicitly represented in context if not already fetched
        if reply_msg is None and getattr(event, "is_reply", False):
            try:
                reply_msg = await event.get_reply_message()
            except Exception:
                pass

        if reply_msg and getattr(reply_msg, "raw_text", None):
            r_text = reply_msg.raw_text.strip()
            if r_text and not any(h.get("text") == r_text for h in conversation_history):
                r_sender = "You" if (getattr(reply_msg, "out", False) or getattr(reply_msg, "sender_id", None) == my_user_id) else "Contact"
                conversation_history.append({"sender": f"{r_sender} (replied-to)", "text": r_text})

        # Optionally add a natural emoji reaction if allowed by reaction cooldown
        await reply_manager.maybe_send_reaction(chat_id, message_id, text)

        # Process reply generation and dispatch
        await reply_manager.handle_incoming_eligible_message(
            chat_id=chat_id,
            chat_title=chat_title,
            message_id=message_id,
            sender_id=sender_id,
            sender_name=sender_name,
            text=text,
            conversation_history=conversation_history,
        )
