"""Telethon event dispatchers and handlers."""

from __future__ import annotations

import random
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
        # In Telethon, private chat with oneself has chat_id == my_user_id or private out message to self
        is_saved_messages = (chat_id == my_user_id) or (
            getattr(event, "is_private", False)
            and getattr(event, "out", False)
            and (getattr(event, "sender_id", None) == my_user_id or chat_id is None)
        )
        clean_text = text.strip()
        if is_saved_messages and clean_text.startswith("/"):
            logger.info(f"Received control command in Saved Messages: {clean_text.split()[0]}")
            response = await reply_manager.handle_control_command(clean_text)
            if response:
                try:
                    await client.send_message("me", response, parse_mode="md")
                except Exception as e:
                    logger.warning(f"Could not deliver command response with markdown: {e}. Falling back to plain text.")
                    try:
                        await client.send_message("me", response, parse_mode=None)
                    except Exception as e2:
                        logger.error(f"Failed to deliver command response to Saved Messages: {e2}")
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

        # In groups, verify who is replying to whom
        reply_msg = None
        is_explicitly_mentioned = False
        is_reply_to_me = False
        is_reply_to_other = False
        reply_target_name = ""

        if is_group and reply_manager.db:
            raw_text_lower = text.lower()
            my_username = (message_filter.my_username or "").lower()
            owner_name = (reply_manager.db.get_state("owner_name", "") or "").strip().lower()

            if message_obj and getattr(message_obj, "mentioned", False):
                is_explicitly_mentioned = True
            elif my_username and f"@{my_username}" in raw_text_lower:
                is_explicitly_mentioned = True
            elif owner_name and len(owner_name) >= 3 and re.search(r"\b" + re.escape(owner_name) + r"\b", raw_text_lower):
                is_explicitly_mentioned = True

            if getattr(event, "is_reply", False):
                try:
                    reply_msg = await event.get_reply_message()
                    if reply_msg:
                        reply_sender_id = getattr(reply_msg, "sender_id", None)
                        reply_out = getattr(reply_msg, "out", False)
                        if reply_out or reply_sender_id == my_user_id:
                            is_reply_to_me = True
                        else:
                            is_reply_to_other = True
                            try:
                                r_sender_obj = await reply_msg.get_sender()
                                if r_sender_obj and getattr(r_sender_obj, "first_name", None):
                                    reply_target_name = r_sender_obj.first_name
                            except Exception:
                                reply_target_name = "User"
                except Exception:
                    pass

        is_mention = not is_group or (is_explicitly_mentioned or is_reply_to_me)

        # Resolve chat title and sender name safely
        chat_title = f"Chat {chat_id}"
        chat_username = ""
        try:
            chat = await event.get_chat()
            if hasattr(chat, "title") and chat.title:
                chat_title = chat.title
            elif hasattr(chat, "first_name") and chat.first_name:
                chat_title = chat.first_name
            if hasattr(chat, "username") and chat.username:
                chat_username = chat.username
        except Exception:
            pass

        if reply_manager.db:
            try:
                reply_manager.db.record_chat_metadata(
                    chat_id=chat_id,
                    title=chat_title,
                    username=chat_username,
                    chat_type="group" if is_group else "user",
                )
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

        # Cache current incoming message into local SQLite database with reply target context
        recorded_sender = f"{sender_name} (to {reply_target_name})" if reply_target_name else sender_name
        reply_manager.db.record_chat_message(
            chat_id=chat_id,
            message_id=message_id,
            sender_id=sender_id,
            sender_name=recorded_sender,
            text=text,
            is_outgoing=False,
        )

        # Group smart engagement decision
        if is_group and reply_manager.db:
            # Mention-only filter (default: OFF / "0" so account actively engages in group)
            strict_mention = reply_manager.db.get_state("group_mention_only", "0") == "1"
            if strict_mention and not is_mention:
                logger.debug(f"Group message in {chat_id} ignored: strict mention-only active.")
                return

            is_broadcast_or_greeting = reply_manager.is_group_broadcast_or_greeting(text)

            if is_mention:
                # Direct mention or reply to our account: always reply
                reply_manager.mark_group_activity(chat_id)
            elif is_broadcast_or_greeting:
                # Group-wide greeting or open callout (e.g. "hi guys", "hello everyone", "gm all", "anyone free"):
                # Active human engagement: acknowledge group greetings (~85% reply, ~10% emoji reaction)
                roll = random.random()
                if roll < 0.85:
                    logger.info(f"[GROUP GREETING ENGAGEMENT] Message in {chat_id} addressed the group ('{text[:30]}'). Replying as human.")
                    reply_manager.mark_group_activity(chat_id)
                elif roll < 0.95:
                    logger.info(f"[GROUP GREETING REACTION] Reacting with emoji to group greeting in chat {chat_id}.")
                    await reply_manager.maybe_send_reaction(chat_id, message_id, text)
                    reply_manager.mark_group_activity(chat_id)
                    return
                else:
                    logger.debug(f"Group broadcast message in {chat_id} acknowledged silently.")
                    return
            else:
                # Active group conversation (even when replying to another member or sending into group stream):
                # Engages dynamically based on chatty rate without waiting 20 minutes!
                chatty_prob = float(reply_manager.db.get_state(
                    "chatty_probability",
                    str(getattr(reply_manager.config, "chatty_probability", 0.20))
                ))
                is_relevant = reply_manager.is_group_message_relevant(chat_id, text, chat_title)
                # If message is relevant to group topic or discussion, boost engagement
                effective_prob = max(chatty_prob, 0.40) if is_relevant else chatty_prob

                # If replying to another member specifically, slightly moderate chime-in rate unless relevant
                if is_reply_to_other and not is_relevant:
                    effective_prob = effective_prob * 0.70

                if effective_prob > 0.0 and random.random() < effective_prob:
                    # Decide between text reply (~80%) and emoji reaction (~20%)
                    if random.random() < 0.80:
                        logger.info(f"[GROUP ENGAGEMENT] Active chime-in in group {chat_id} (prob: {effective_prob:.2f}). Replying as human.")
                        reply_manager.mark_group_activity(chat_id)
                    else:
                        logger.info(f"[GROUP REACTION] Chime-in with emoji reaction in group {chat_id}.")
                        await reply_manager.maybe_send_reaction(chat_id, message_id, text)
                        reply_manager.mark_group_activity(chat_id)
                        return
                else:
                    logger.debug(f"Group message in {chat_id} read silently (prob: {effective_prob:.2f}).")
                    return

        # Natural emoji reaction across sentiment spectrum (humor, excitement, agreement, surprise, warmth)
        if not is_group or not is_reply_to_other:
            reacted = await reply_manager.maybe_send_reaction(chat_id, message_id, text)
            if reacted and not is_mention:
                react_only_prob = float(reply_manager.db.get_state("react_only_probability", str(getattr(reply_manager.config, "react_only_probability", 0.25))))
                pure_laugh_text = re.sub(r"[^a-zA-Z]", "", text).lower()
                is_pure_laughter = bool(pure_laugh_text and re.match(r"^(?:[ae]*h+[ae]*|lol|lmao|rofl|xd|lmfao)+$", pure_laugh_text))
                words = text.strip().split()
                if is_pure_laughter or (len(words) <= 3 and random.random() < react_only_prob):
                    logger.info(f"[SENTIMENT REACTION ONLY] Reacted with emoji to sentiment in chat {chat_id}; completed interaction.")
                    return

        # Retrieve recent conversation context with aging window (default: 2 hours TTL)
        ttl_hours = float(reply_manager.db.get_state("context_ttl_hours", "2.0"))
        max_age_secs = int(ttl_hours * 3600) if ttl_hours > 0 else None
        conversation_history = reply_manager.db.get_recent_chat_messages(chat_id, limit=15, max_age_seconds=max_age_secs)
        if len(conversation_history) <= 2:
            try:
                recent_msgs = await client.get_messages(chat_id, limit=15)
                if recent_msgs:
                    for m in reversed(recent_msgs):
                        m_id = getattr(m, "id", None)
                        m_text = (getattr(m, "raw_text", "") or "").strip()
                        if not m_text:
                            continue
                        m_out = getattr(m, "out", False)
                        m_sender_id = getattr(m, "sender_id", None)
                        s_name = "You" if (m_out or m_sender_id == my_user_id) else "Contact"
                        if not m_out:
                            try:
                                s_obj = await m.get_sender()
                                if s_obj and getattr(s_obj, "first_name", None):
                                    s_name = s_obj.first_name
                            except Exception:
                                pass
                        reply_manager.db.record_chat_message(
                            chat_id=chat_id,
                            message_id=m_id,
                            sender_id=m_sender_id,
                            sender_name=s_name,
                            text=m_text,
                            is_outgoing=m_out,
                        )
                    conversation_history = reply_manager.db.get_recent_chat_messages(chat_id, limit=15, max_age_seconds=max_age_secs)
            except Exception as e:
                logger.debug(f"Could not seed chat history from network: {e}")

        # Ensure replied-to message is explicitly represented in context if not already fetched
        if reply_msg is None and getattr(event, "is_reply", False):
            try:
                reply_msg = await event.get_reply_message()
            except Exception:
                pass

        if reply_msg and getattr(reply_msg, "raw_text", None):
            r_text = reply_msg.raw_text.strip()
            if r_text and not any(h.get("text") == r_text for h in conversation_history):
                r_sender = "You" if (getattr(reply_msg, "out", False) or getattr(reply_msg, "sender_id", None) == my_user_id) else (reply_target_name or "Contact")
                conversation_history.append({"sender": f"{r_sender} (in reply to)", "text": r_text})

        # Process reply generation and dispatch
        await reply_manager.handle_incoming_eligible_message(
            chat_id=chat_id,
            chat_title=chat_title,
            message_id=message_id,
            sender_id=sender_id,
            sender_name=sender_name,
            text=text,
            conversation_history=conversation_history,
            is_mention=is_mention,
        )
