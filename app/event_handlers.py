"""Telethon event dispatchers and handlers."""

from __future__ import annotations

import random
import re
from typing import Any

from telethon import events

from app.logger import setup_logger
from app.message_filter import MessageFilter, is_account_addressed
from app.reply_manager import ReplyManager

logger = setup_logger(__name__)


def adjust_engagement_for_room_heat(base_prob: float, recent_messages: int) -> float:
    """Scale group chime-in probability by how active the room is (5-minute window).

    Busy rooms never increase the configured chance; quiet rooms dampen it.
    A zero setting always remains zero.
    """
    if base_prob <= 0:
        return 0.0
    if recent_messages >= 3:
        return min(1.0, base_prob)
    if recent_messages <= 1:
        return base_prob * 0.6
    return base_prob


# Words that close a conversation loop: farewells, acknowledgments, agreements, fillers.
# When someone sends these, a real human reacts with an emoji or goes quiet — they do not
# force another line to keep a finished conversation alive.
_THREAD_ENDER_WORDS = frozenset((
    # farewells / sign-offs
    "gn", "goodnight", "good", "night", "bye", "goodbye", "tc", "take", "care", "see", "you",
    "ya", "cya", "seeya", "later", "laters", "ttyl", "gtg", "g2g", "brb", "bbl", "sleep", "well",
    # acknowledgments / agreements
    "ok", "okay", "k", "kk", "thx", "thanks", "thank", "ty", "tysm", "welcome", "yep", "yeah",
    "yes", "yup", "nop", "nope", "sure", "fine", "alright", "aight", "ight", "done", "same",
    "true", "fr", "frfr", "real", "fact", "facts", "great", "nice", "cool", "swell", "fair",
    "enough", "got", "gotcha", "aight", "sir", "bro", "bruh", "bhai", "yaar", "boss", "dude",
    # filler closures
    "hm", "hmm", "hmmm", "mm", "huh", "oh", "ooh", "welp", "lol", "lmao", "hehe", "haha",
))


def is_thread_ender(text: str) -> bool:
    """True when the message closes the conversation loop — short acknowledgment, farewell,
    pure laughter, or emoji-only. Questions and real statements are never thread enders."""
    t = (text or "").strip().lower()
    if not t:
        return False
    if "?" in t or "？" in t:
        return False
    words = re.findall(r"[^\W\d_]+", t)
    if not words:
        # emoji-only or punctuation-only message: a reaction, not an opening
        return True
    if len(words) > 3:
        return False
    if all(w in _THREAD_ENDER_WORDS for w in words):
        return True
    # pure laughter ("hahaha", "lolll") closes the loop
    letters = "".join(words)
    return bool(letters) and re.match(r"^(?:[ae]*h+[ae]*|lol|lmao|rofl|xd|lmfao)+$", letters) is not None


def decide_thread_end_action(is_group: bool, roll: float) -> str:
    """Conversation closers never trigger another text reply."""
    if is_group:
        return "reaction" if roll < 0.20 else "silent"
    if roll < 0.65:
        return "reaction"
    return "silent"


def record_own_outgoing_message(reply_manager: ReplyManager, event: Any, my_user_id: int) -> None:
    """Record the owner's own manually-typed messages into chat history so the AI always
    knows what they personally said. The automation's own replies are already recorded by
    ReplyManager with proper attribution — those are skipped via the (chat_id, message_id)
    existence check so the event handler never overwrites them with generic data."""
    chat_id = getattr(event, "chat_id", None)
    text = (getattr(event, "raw_text", "") or "").strip()
    if chat_id is None or not text:
        return
    if not reply_manager.privacy.is_chat_allowed(chat_id, chat_id < 0) or reply_manager.safety.is_sensitive(text):
        return
    text = reply_manager.privacy.sanitize_text(text)
    if reply_manager.db.has_chat_message(chat_id, getattr(event, "id", None)):
        return
    if getattr(reply_manager, "is_own_send", lambda *_: False)(chat_id, text) is True:
        return  # echo of an automated message, not something the owner typed
    try:
        reply_manager.db.record_chat_message(
            chat_id=chat_id,
            message_id=getattr(event, "id", None) or 0,
            sender_id=my_user_id,
            sender_name="You",
            text=text,
            is_outgoing=True,
        )
        reply_manager.context_agent.observe(chat_id)
    except Exception:
        pass


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

        # Saved Messages (chat with self): completely ignored. All commands and messaging
        # are handled strictly in the Telegram control bot.
        is_saved_messages = (chat_id == my_user_id) or (
            getattr(event, "is_private", False)
            and getattr(event, "out", False)
            and (chat_id is None or chat_id == my_user_id)
            and getattr(event, "sender_id", None) == my_user_id
        )
        if is_saved_messages:
            return
        if chat_id is None or not reply_manager.privacy.is_chat_allowed(chat_id, getattr(event, "is_group", False)):
            return

        # Context continuity: always record the owner's own manually-typed outgoing messages
        # so the AI remembers what the account itself said (not just what it received).
        if getattr(event, "out", False) and not is_saved_messages:
            record_own_outgoing_message(reply_manager, event, my_user_id)

        # Regular incoming message handling
        is_eligible, reason = message_filter.evaluate_context(event)
        if not is_eligible:
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
        owner_name = reply_manager.db.get_state("owner_name", "") or ""
        my_username = message_filter.my_username or ""

        if is_group and reply_manager.db:
            my_username = (message_filter.my_username or "").lower()
            owner_name = (reply_manager.db.get_state("owner_name", "") or "").strip().lower()

            is_explicitly_mentioned = is_account_addressed(text, my_username, owner_name,
                                                          bool(message_obj and getattr(message_obj, "mentioned", False)))

            if getattr(event, "is_reply", False):
                # An unresolved quote must not be treated as an open room invitation.
                is_reply_to_other = True
                try:
                    reply_msg = await event.get_reply_message()
                    if reply_msg:
                        reply_sender_id = getattr(reply_msg, "sender_id", None)
                        reply_out = getattr(reply_msg, "out", False)
                        if reply_out or reply_sender_id == my_user_id:
                            is_reply_to_me = True
                            is_reply_to_other = False
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
        addressless_text = re.sub(r"@\w+", "", text)
        if owner_name:
            addressless_text = re.sub(r"\b" + re.escape(owner_name) + r"\b", "", addressless_text, flags=re.IGNORECASE)

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
        sender_label = sender_name
        sender_id = getattr(event, "sender_id", None)
        try:
            sender = await event.get_sender()
            full_name = " ".join(value for value in (getattr(sender, "first_name", ""), getattr(sender, "last_name", "")) if isinstance(value, str) and value)
            username = getattr(sender, "username", "")
            username = username if isinstance(username, str) else ""
            sender_name = full_name or (f"@{username}" if username else "User")
            sender_label = f"{sender_name} (@{username})" if full_name and username else sender_name
        except Exception:
            pass

        # Cache current incoming message into local SQLite database with reply target context
        if not reply_manager.privacy.is_chat_allowed(chat_id, is_group):
            return
        recorded_sender = f"{sender_label} (to {reply_target_name})" if reply_target_name else sender_label
        reply_manager.db.record_chat_message(
            chat_id=chat_id,
            message_id=message_id,
            sender_id=sender_id,
            sender_name=recorded_sender,
            text=reply_manager.privacy.sanitize_text(text),
            is_outgoing=False,
        )
        reply_manager.context_agent.observe(chat_id)

        # Group smart engagement decision
        if is_group and reply_manager.db:
            # Mention-only filter (default: OFF / "0" so account actively engages in group)
            strict_mention = reply_manager.db.get_state("group_mention_only", "0") == "1"
            if strict_mention and not is_mention:
                logger.debug(f"Group message in {chat_id} ignored: strict mention-only active.")
                return

            if not is_mention and (is_reply_to_other or re.search(r"@\w+", text)):
                reply_manager.db.record_action("automation", "reply", "skipped", "Message addresses another participant", chat_id=chat_id)
                return

            if is_thread_ender(addressless_text):
                reply_manager.db.record_action("automation", "reply", "skipped", "Conversation already ended", chat_id=chat_id)
                return

            if is_mention:
                # Addressed messages can proceed; the model may still choose NONE.
                reply_manager.mark_group_activity(chat_id)
            else:
                if not reply_manager.is_group_message_relevant(chat_id, text, chat_title):
                    reply_manager.db.record_action("automation", "reply", "skipped", "No relevant contribution requested", chat_id=chat_id)
                    return
                # Frequencies are ceilings for relevant messages, not permission to interrupt other threads.
                effective_prob = reply_manager.group_chatty_probability(chat_id)

                # Quiet rooms can reduce the configured chance, never increase it.
                try:
                    recent_active = len(reply_manager.db.get_recent_chat_messages(
                        chat_id, limit=6, max_age_seconds=300
                    ))
                except Exception:
                    recent_active = 0
                effective_prob = adjust_engagement_for_room_heat(effective_prob, recent_active)

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
                    reply_manager.db.record_action("automation", "reply", "skipped", "Occasional participation limit", chat_id=chat_id)
                    logger.debug(f"Group message in {chat_id} read silently (prob: {effective_prob:.2f}).")
                    return

        # Natural conversation endings (DMs & direct replies): when the other person closes the
        # loop ("gn", "ok cool", "thanks bro", laughter, emoji-only), a real human mostly reacts
        # or goes quiet instead of forcing another line. Real questions are never thread enders.
        if not is_group and is_thread_ender(addressless_text):
            action = decide_thread_end_action(is_group=False, roll=random.random())
            if action == "reaction":
                logger.info(f"[THREAD END] Reacting with emoji to conversation closer in chat {chat_id}.")
                await reply_manager.maybe_send_reaction(chat_id, message_id, text)
                return
            if action == "silent":
                logger.info(f"[THREAD END] Left on read — conversation closed naturally in chat {chat_id}.")
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

        # Retrieve recent conversation context with aging window (default: 4 hours TTL).
        # Groups get a wider window (30 msgs) so constant chatter keeps full context.
        ttl_hours = float(reply_manager.db.get_state("context_ttl_hours", "4.0"))
        max_age_secs = int(ttl_hours * 3600) if ttl_hours > 0 else None
        history_limit = 40 if getattr(event, "is_group", False) else 15
        conversation_history = reply_manager.db.get_recent_chat_messages(chat_id, limit=history_limit, max_age_seconds=max_age_secs)
        memory_epoch = reply_manager.db.get_state(f"chat_memory_epoch_{chat_id}")
        if len(conversation_history) <= 2 and not memory_epoch:
            try:
                recent_msgs = await client.get_messages(chat_id, limit=15)
                if recent_msgs:
                    for m in reversed(recent_msgs):
                        m_id = getattr(m, "id", None)
                        m_text = (getattr(m, "raw_text", "") or "").strip()
                        if (not m_text or reply_manager.safety.is_sensitive(m_text)
                                or not reply_manager.privacy.is_user_allowed(getattr(m, "sender_id", None))):
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
                        if (not reply_manager.privacy.is_chat_allowed(chat_id, is_group)
                                or reply_manager.db.get_state(f"chat_memory_epoch_{chat_id}") != memory_epoch):
                            break
                        reply_manager.db.record_chat_message(
                            chat_id=chat_id,
                            message_id=m_id,
                            sender_id=m_sender_id,
                            sender_name=s_name,
                            text=reply_manager.privacy.sanitize_text(m_text),
                            is_outgoing=m_out,
                        )
                    conversation_history = reply_manager.db.get_recent_chat_messages(chat_id, limit=history_limit, max_age_seconds=max_age_secs)
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
            if (r_text and reply_manager.privacy.is_user_allowed(getattr(reply_msg, "sender_id", None))
                    and not reply_manager.safety.is_sensitive(r_text)
                    and not any(h.get("text") == r_text for h in conversation_history)):
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
