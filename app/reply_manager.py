"""Reply orchestration handling Draft, Approval, and Restricted Automation modes."""

from __future__ import annotations

import asyncio
import datetime
import json
import math
import random
import re
import time
from typing import Any, Optional

from app.ai.reply_generator import ReplyGenerator
from app.ai.prompt_manager import outgoing_block_reason
from app.config import AppConfig
from app.logger import setup_logger
from app.privacy_manager import PrivacyManager
from app.safety_manager import SafetyManager
from app.storage.database import Database

logger = setup_logger(__name__)

from app.command_router import CommandRouterMixin, _BOT_COMMAND_NAMES, _parse_time_str
from app.ai.chat_context import ContextAgent

try:
    from telethon.errors import FloodWaitError, PeerFloodError
except Exception:
    FloodWaitError = None  # type: ignore
    PeerFloodError = None  # type: ignore


def capitalize_message(text: str) -> str:
    """Capitalize the first letter without lowercasing names, acronyms, or the rest of the message."""
    for index, character in enumerate(text):
        if character.isalpha():
            return text[:index] + character.upper() + text[index + 1:]
    return text


# Identity, model, and prompt-injection questions stay with the account owner (checked before any model call).
_IDENTITY_QUESTION = re.compile(
    r"\b(?:are|r)\s+(?:you|u)\s+(?:(?:an?|really|actually|just)\s+)*"
    r"(?:ai|bot|robot|human|real|automated|chatgpt|gpt|gemini|claude|llm)\b"
    r"|(?:^|[.!?,])\s*(?:you|u)\s+an?\s+(?:ai|bot|robot|llm)\b"
    r"|\bis\s+this\s+an?\s+(?:ai|bot|robot|llm)\b"
    r"|\b(?:what|which)\s+(?:ai|model|bot|llm)\s+(?:are|r)\s+(?:you|u)\b"
    r"|\bwhich\s+llm\b(?:\s+(?:is\s+(?:this|it)|do\s+(?:you|u)\s+use))?\s*(?:[?!.]|$)"
    r"|\bsystem\s+prompt\b"
    r"|\bignore\s+(?:all\s+)?(?:the\s+)?(?:previous|prior|above)\s+instructions\b",
    re.IGNORECASE | re.MULTILINE,
)
# Reply rates count only as explicit frequency phrases, so "100% certain" or "50% shorter" never set one.
_FREQUENCY_LEAD = r"\b(?:reply|respond|chime\s+in|participate|talk|join)\b[^.!?\n]{0,40}?\b(\d+(?:\.\d+)?)"
_FREQUENCY_RATIO = re.compile(_FREQUENCY_LEAD + r"\s+(?:times\s+)?(?:in|out\s+of)\s+(\d+)\s+(?:messages|texts|times|sends)\b", re.I)
_FREQUENCY_PERCENT = re.compile(_FREQUENCY_LEAD + r"\s*%\s*(?:of\s+the\s+time|of\s+(?:the\s+)?messages|chance)\b", re.I)


def _mentions_any(text: str, phrases) -> bool:
    """Whole word/phrase match; apostrophes count as letters so "won" never matches "won't" or "won’t"."""
    return re.search(r"(?<![\w'’])(?:" + "|".join(phrases) + r")(?![\w'’])", text) is not None


class ReplyManager(CommandRouterMixin):
    """Manages reply lifecycle across Draft, Approval Required, and Restricted Auto modes."""

    def __init__(
        self,
        config: AppConfig,
        database: Database,
        safety_manager: SafetyManager,
        privacy_manager: PrivacyManager,
        reply_generator: ReplyGenerator,
    ):
        self.config = config
        self.db = database
        self.safety = safety_manager
        self.privacy = privacy_manager
        self.generator = reply_generator
        self.context_agent = ContextAgent(database, privacy_manager, reply_generator, self.group_chatty_probability)
        self._approval_batch_task = None
        self._background_tasks = set()
        self._context_initializing = set()
        self._context_init_tasks = {}
        self._context_ready = set()
        self._own_sends: dict[int, list[tuple[str, float]]] = {}
        self._context_startup_enabled = False
        self._process_started_at = time.time()
        self._last_delivery_parts = {}
        self._closed = False
        self._client: Any = None
        # Optional Bot API control channel (set by main.py when BOT_API_KEY is configured).
        # When set: all alerts route to the bot's main user, Saved Messages stays as delivery fallback only.
        self.bot_control: Any = None
        self.typing_delay: float = getattr(config, "typing_delay_seconds", 2.0)
        self.min_delay: float = getattr(config, "min_delay_seconds", 5.0)
        self.max_delay: float = getattr(config, "max_delay_seconds", 60.0)
        self._last_reaction_time: float = 0.0
        self._next_reaction_time_by_chat: dict[int, float] = {}
        self._last_sent_reply_by_chat: dict[int, str] = {}
        # Persisted sent-reply history: survives restarts so no phrase is ever reused even days later
        self._recent_replies_history: dict[int, list[str]] = self._load_recent_replies_history()
        self._last_group_activity: dict[int, float] = {}
        # Suggestion 1: Incoming message burst debouncer state
        self._debounce_buffers: dict[int, list[dict[str, Any]]] = {}
        self._debounce_tasks: dict[int, asyncio.Task] = {}
        self._debounce_last_time: dict[int, float] = {}
        self._debounce_first_time: dict[int, float] = {}
        self._chat_send_locks: dict[int, asyncio.Lock] = {}
        self._outgoing_lock = asyncio.Lock()
        self._pending_deferred_replies: dict[int, asyncio.Task] = {}
        self._group_processing_locks: dict[int, asyncio.Lock] = {}
        self._alert_send_lock: asyncio.Lock = asyncio.Lock()
        self._last_alert_time: float = 0.0
        self._alert_min_cooldown: float = 4.0
        self._next_reaction_cooldown: float = random.uniform(
            float(self.db.get_state("reaction_min_cooldown_seconds", str(getattr(config, "reaction_min_cooldown_seconds", 15.0)))),
            float(self.db.get_state("reaction_max_cooldown_seconds", str(getattr(config, "reaction_max_cooldown_seconds", 60.0)))),
        )

        # Restore saved style if stored in DB
        saved_style = self.db.get_state("reply_style")
        if saved_style:
            self.generator.set_style(saved_style)

        # Restore saved language if stored in DB
        default_lang = getattr(config, "default_chat_language", "english")
        saved_lang = self.db.get_state("chat_language", default_lang)
        if saved_lang:
            self.generator.set_language(saved_lang)

        # Restore saved owner persona name if stored in DB
        saved_owner = self.db.get_state("owner_name")
        if saved_owner:
            self.generator.set_owner_name(saved_owner)

        # Wire token usage callback if provider supports it
        if hasattr(self.generator.provider, "usage_callback") and not self.generator.provider.usage_callback:
            self.generator.provider.usage_callback = self.db.record_token_usage

    @property
    def current_mode(self) -> str:
        """Active reply mode, prioritizing runtime database state over initial config."""
        saved_mode = self.db.get_state("reply_mode")
        if saved_mode in ("draft", "approval", "restricted_auto"):
            return saved_mode
        return self.config.reply_mode

    def set_mode(self, mode: str) -> bool:
        """Set and persist the active reply mode."""
        clean = mode.strip().lower()
        if clean in ("draft", "approval", "restricted_auto"):
            self.db.set_state("reply_mode", clean)
            self.db.set_state("safe_mode_active", "0")
            return True
        return False

    def set_telegram_client(self, client: Any) -> None:
        """Attach the active Telethon client."""
        self._client = client

    def schedule_chat_context(self, chat_id):
        task = self._context_init_tasks.get(chat_id)
        if task is None or task.done():
            self._context_ready.discard(chat_id)
            task = self.start_background(self.init_chat_context(chat_id))
            self._context_init_tasks[chat_id] = task
        return task

    async def ensure_chat_context(self, chat_id):
        if chat_id in self._context_ready or not self._client or self._closed:
            return
        task = self._context_init_tasks.get(chat_id)
        if task is None:
            task = self.schedule_chat_context(chat_id)
        if task is not asyncio.current_task():
            await asyncio.shield(task)

    def group_chatty_probability(self, chat_id):
        raw = self.db.get_state(f"chat_chatty_{chat_id}")
        if not raw:
            rules = self.db.get_chat_prompt(chat_id) + " " + self.db.get_permanent_context(chat_id).get("notes", "")
            ratio = _FREQUENCY_RATIO.search(rules)
            percent = _FREQUENCY_PERCENT.search(rules)
            if ratio and float(ratio[2]) > 0:
                raw = str(float(ratio[1]) / float(ratio[2]))
            elif percent:
                raw = str(float(percent[1]) / 100)
        if not raw:
            raw = self.db.get_state("chatty_probability", str(getattr(self.config, "chatty_probability", 0.15)))
        try:
            value = float(raw)
            return min(1.0, max(0.0, value)) if math.isfinite(value) else 0.0
        except (ValueError, TypeError):
            return 0.0

    def expect_own_send(self, chat_id: int, text: str) -> None:
        """Remember a message the automation is about to send so its echo is never taken for a manual one."""
        now = time.time()
        sends = [item for item in self._own_sends.get(chat_id, []) if now - item[1] < 120]
        sends.append((text.strip(), now))
        self._own_sends[chat_id] = sends

    def is_own_send(self, chat_id: int, text: str) -> bool:
        now = time.time()
        return any(sent == text.strip() and now - at < 120 for sent, at in self._own_sends.get(chat_id, []))

    def owner_recently_active(self, chat_id: int) -> bool:
        """The owner replied by hand lately: stay quiet so two voices never share one chat."""
        try:
            minutes = float(self.db.get_state("owner_active_minutes", "15"))
        except ValueError:
            minutes = 15.0
        return minutes > 0 and self.db.has_recent_manual_message(chat_id, minutes * 60)

    def _context_current(self, context, approved=False):
        if not approved and context is not None and self.owner_recently_active(context.chat_id):
            return False
        if not self.context_agent.is_current(context):
            return False
        if context is not None and context.chat_id < 0 and not approved and not getattr(context, "is_mention", False):
            probability = self.group_chatty_probability(context.chat_id)
            return (self.db.get_state("group_mention_only", "0") != "1"
                    and probability > 0 and probability >= context.chatty_probability)
        return True

    def start_background(self, coroutine):
        task = asyncio.create_task(coroutine)
        self._background_tasks.add(task)
        if self._closed:
            task.cancel()

        def finished(completed):
            self._background_tasks.discard(completed)
            if not completed.cancelled() and completed.exception():
                logger.error("Background reply task failed: %s", type(completed.exception()).__name__)

        task.add_done_callback(finished)
        return task

    async def close(self):
        self._closed = True
        tasks = self._background_tasks | set(self._debounce_tasks.values()) | set(self._pending_deferred_replies.values())
        if self._approval_batch_task:
            tasks.add(self._approval_batch_task)
        tasks.discard(asyncio.current_task())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._background_tasks.clear()
        self._debounce_tasks.clear()
        self._debounce_buffers.clear()
        self._debounce_first_time.clear()
        self._debounce_last_time.clear()
        self._pending_deferred_replies.clear()
        self._group_processing_locks.clear()
        self._context_init_tasks.clear()
        await self.context_agent.close()

    def _outgoing_text_reason(self, chat_id: int, text: str, names=()) -> str:
        normalized = " ".join(text.strip()[:300].casefold().split()).rstrip(".!?")
        if any(row["rating"] != "helpful" and " ".join(row["reply_text"].casefold().split()).rstrip(".!?") == normalized
               for row in self.db.list_reply_feedback([chat_id], limit=500)):
            return "Reply matches rejected feedback for this chat"
        participants = [*names, *[row["sender"] for row in self.db.get_recent_chat_messages(chat_id, limit=50) if not row["is_outgoing"]]]
        if chat_id > 0:
            metadata = self.db.get_chat_metadata(chat_id) or {}
            participants.extend([metadata.get("title", ""), metadata.get("username", "")])
        return outgoing_block_reason(text, participants)

    def _outgoing_allowed(self, chat_id: int, approved: bool = False, allow_quiet_hours: bool = False) -> bool:
        return (
            not self._closed and self.privacy.is_chat_allowed(chat_id, chat_id < 0)
            and not self.safety.action_block_reason(allow_quiet_hours)
            and (approved or (self.current_mode == "restricted_auto" and self.safety.is_auto_authorized
                              and self.db.get_state("safe_mode_active", "0") != "1"))
        )

    def _operator_allowed(self, operator_id):
        if operator_id is None:
            return True
        from app.bot_control import authorized_user_ids, can_run_command
        main_id = int(self.db.get_state("main_owner_id", "0") or 0) or min(self.config.bot_authorized_users or {0})
        return operator_id in authorized_user_ids(self.db, self.config.bot_authorized_users) and can_run_command(self.db, operator_id, "/approve", main_id)

    async def _typing_burst(self, chat_id, duration):
        if duration <= 0:
            return
        try:
            action = self._client.action(chat_id, "typing")
            if hasattr(action, "__aenter__"):
                async with action:
                    await asyncio.sleep(duration)
                return
            if asyncio.iscoroutine(action):
                await action
        except Exception:
            logger.debug("Typing indicator unavailable for chat %s", chat_id)
        await asyncio.sleep(duration)

    @staticmethod
    def _typing_window(text: str) -> float:
        """Seconds of typing indicator that end a reply wait, scaled 5-10 s by length."""
        words = len(text.split())
        if words <= 4:
            return random.uniform(5.0, 6.5)
        if words <= 12:
            return random.uniform(6.5, 8.5)
        return random.uniform(8.5, 10.0)

    async def _type_before_send(self, chat_id, duration):
        if duration < 3.5:
            await self._typing_burst(chat_id, duration)
            return
        first = duration / 2
        pause = random.uniform(0.8, 1.4)
        await self._typing_burst(chat_id, first)
        await asyncio.sleep(pause)
        # The pause is part of the total so typing ends exactly when the planned wait does.
        await self._typing_burst(chat_id, max(0.0, duration - first - pause))

    def _delivery_wait(self, chat_id, text, allow_quiet_hours=False, sequence_part=False):
        """Seconds until text may go out, or None when a non-cooldown safety rule blocks it."""
        can_send, reason = self.safety.can_reply(chat_id, text, allow_quiet_hours=allow_quiet_hours)
        if not can_send and "cooldown" not in reason.lower():
            return None
        if sequence_part:
            return 0.0  # Later bubbles belong to the reply whose first bubble already passed the cooldown.
        wait = self.safety.burst_wait_needed(chat_id)
        return wait if can_send else max(wait, self.safety.cooldown_remaining(chat_id)[0])

    async def _deliver_message(self, chat_id: int, text: str, reply_to=None, *, approved: bool = False, allow_quiet_hours: bool = False, context=None, operator_id=None, typing_seconds=None, sequence_part: bool = False):
        text = capitalize_message(text)
        if typing_seconds is None:
            typing_seconds = random.uniform(3.0, 7.0) if self.typing_delay > 0 else 0.0
        # Group messages go to the room without a quoted reply notification.
        reply_to = reply_to if chat_id > 0 and reply_to and reply_to > 0 else None
        if not self._outgoing_allowed(chat_id, approved, allow_quiet_hours):
            return None
        reason = self._outgoing_text_reason(chat_id, text)
        if reason:
            self.db.record_action("automation", "reply", "blocked", reason, chat_id=chat_id)
            return None
        typed = False
        while True:
            async with self._outgoing_lock:
                if not self._outgoing_allowed(chat_id, approved, allow_quiet_hours) or not self._context_current(context, approved) or not self._operator_allowed(operator_id):
                    return None
                if not self._prevent_duplicate_reply(chat_id, text):
                    return None
                wait = self._delivery_wait(chat_id, text, allow_quiet_hours, sequence_part)
                if wait is None:
                    return None
                if wait <= typing_seconds:
                    if typed:
                        # Clock rounding left a sliver of cooldown; the indicator from the last burst is still visible.
                        await asyncio.sleep(max(0.01, wait))
                    else:
                        # Typing covers the rest of the cooldown, so the message goes out as the wait ends.
                        await self._type_before_send(chat_id, typing_seconds)
                        typed = True
                    if (not self._outgoing_allowed(chat_id, approved, allow_quiet_hours)
                            or not self._context_current(context, approved) or not self._operator_allowed(operator_id)):
                        return None
                    if self._delivery_wait(chat_id, text, allow_quiet_hours, sequence_part) != 0:
                        continue
                    reason = self._outgoing_text_reason(chat_id, text)
                    if reason:
                        self.db.record_action("automation", "reply", "blocked", reason, chat_id=chat_id)
                        return None
                    try:
                        self.expect_own_send(chat_id, text)
                        message = await self._client.send_message(chat_id, text, reply_to=reply_to)
                    except Exception as e:
                        if not reply_to or "reply" not in str(e).lower() or not self._outgoing_allowed(chat_id, approved, allow_quiet_hours):
                            raise
                        if (not self._context_current(context, approved) or not self._operator_allowed(operator_id)
                                or self._outgoing_text_reason(chat_id, text)
                                or self._delivery_wait(chat_id, text, allow_quiet_hours, sequence_part) != 0):
                            return None
                        message = await self._client.send_message(chat_id, text)
                    self.safety.mark_reply_sent(chat_id)
                    if not sequence_part:
                        self.safety.record_burst_send(chat_id)
                    recent = self._recent_replies_history.setdefault(chat_id, [])
                    recent.append(text)
                    del recent[:-12]
                    self._save_recent_replies_history()
                    self.db.record_action("automation", "reply", "sent", "Message delivered", chat_id=chat_id)
                    return message
            typed = False
            # Release the account lock while waiting so another chat can proceed; typing starts when it fits the wait.
            await asyncio.sleep(min(1.0, max(0.01, wait - typing_seconds)))

    def _get_chat_send_lock(self, chat_id: int) -> asyncio.Lock:
        """Return a per-chat send lock ensuring sequential, non-overlapping message delivery."""
        if chat_id not in self._chat_send_locks:
            self._chat_send_locks[chat_id] = asyncio.Lock()
        return self._chat_send_locks[chat_id]

    def get_telegram_message_link(self, chat_id: int, message_id: int = 0) -> str:
        """Construct a direct Telegram message link for a chat and message ID."""
        if not message_id or message_id <= 0:
            return ""
        username = ""
        if self.db:
            try:
                meta = self.db.get_chat_metadata(chat_id) or {}
                username = meta.get("username", "")
            except Exception:
                pass
        if username:
            u = username.lstrip("@")
            return f"https://t.me/{u}/{message_id}"
        if chat_id < 0:
            s = str(chat_id)
            if s.startswith("-100"):
                clean_id = s[4:]
            else:
                clean_id = str(abs(chat_id))
            return f"https://t.me/c/{clean_id}/{message_id}"
        return f"tg://openmessage?user_id={chat_id}&message_id={message_id}"

    async def sync_owner_name_from_telegram(self) -> str:
        """Fetch current name from Telegram account and update owner persona name.
        Fallback hierarchy: first_name -> full name / last_name -> username -> user ID."""
        if not self._client:
            return self.generator.prompt_manager.owner_name
        try:
            me = await self._client.get_me()
            if me:
                first = (getattr(me, "first_name", "") or "").strip()
                last = (getattr(me, "last_name", "") or "").strip()
                full = f"{first} {last}".strip()
                username = (getattr(me, "username", "") or "").strip().lstrip("@")
                user_id_str = str(getattr(me, "id", "") or "").strip()
                resolved = first or full or username or user_id_str
                if resolved:
                    self.generator.set_owner_name(resolved)
                    self.db.set_state("owner_name", resolved)
                    return resolved
        except Exception as e:
            logger.debug(f"Could not auto-fetch name from Telegram: {e}")
        return self.generator.prompt_manager.owner_name

    async def sync_pinned_context_from_telegram(self, chat_id: int) -> Optional[str]:
        """Fetch pinned messages from Telegram for chat_id, distill with AI, and store permanently."""
        if not self._client or self._closed or not self.context_agent.allowed(chat_id):
            return None
        try:
            from telethon.tl.types import InputMessagesFilterPinned
            chat_title = str(chat_id)
            try:
                entity = await self._client.get_entity(chat_id)
                chat_title = getattr(entity, "title", "") or getattr(entity, "first_name", "") or str(chat_id)
            except Exception:
                pass

            if self._closed or not self.context_agent.allowed(chat_id):
                return None
            pinned_msgs = await self._client.get_messages(chat_id, filter=InputMessagesFilterPinned, limit=5)
            if self._closed or not self.context_agent.allowed(chat_id):
                return None
            # Lets incoming messages skip re-fetching a chat whose pins were just checked (even when empty).
            self.db.set_state(f"chat_pins_checked_{chat_id}", str(time.time()))
            if pinned_msgs:
                texts = [self.privacy.sanitize_text(m.text.strip()) for m in pinned_msgs
                         if getattr(m, "text", None) and m.text.strip() and not self.safety.is_sensitive(m.text)
                         and self.privacy.is_user_allowed(getattr(m, "sender_id", None))]
                if texts:
                    raw_combined = "\n---\n".join(texts)
                    loop = asyncio.get_running_loop()
                    distilled = await loop.run_in_executor(
                        None, self.generator.distill_group_context, chat_title, raw_combined
                    )
                    if self._closed or not self.context_agent.allowed(chat_id):
                        return None
                    pinned_content = distilled if distilled else raw_combined[:1500]
                    self.db.set_permanent_context(chat_id, pinned_text=pinned_content)
                    logger.info(f"AI-distilled permanent pinned context for '{chat_title}' ({chat_id}): {len(pinned_content)} chars")
                    return pinned_content
            # A successful empty fetch invalidates old announcements; failures retain them.
            self.db.set_permanent_context(chat_id, pinned_text="")
        except Exception as e:
            logger.debug(f"Could not fetch pinned messages for chat {chat_id}: {e}")
        return None

    async def generate_chat_voice_profile(self, chat_id: int, min_messages: int = 45) -> Optional[str]:
        """Fetch 40+ recent messages of a group, AI learns how its people talk, store permanently."""
        if not self._client or chat_id >= 0 or self._closed or not self.context_agent.allowed(chat_id):
            logger.debug(f"Voice profile skipped for chat {chat_id}: client attached={bool(self._client)}, is_group={chat_id < 0}")
            return None
        try:
            entity = await self._client.get_entity(chat_id)
            chat_title = getattr(entity, "title", "") or str(chat_id)
            if self._closed or not self.context_agent.allowed(chat_id):
                return None
            msgs = await self._client.get_messages(chat_id, limit=min_messages)
            lines: list[str] = []
            for m in msgs:
                txt = (getattr(m, "text", "") or "").strip()
                if not txt or self.safety.is_sensitive(txt) or not self.privacy.is_user_allowed(getattr(m, "sender_id", None)):
                    continue
                sender = "someone"
                try:
                    s = await m.get_sender()
                    if s:
                        sender = getattr(s, "first_name", None) or getattr(s, "username", None) or "someone"
                except Exception:
                    pass
                lines.append(f"{sender}: {txt}")
            if len(lines) < 10:
                logger.info(f"[VOICE PROFILE] Chat {chat_id}: only {len(lines)} text messages available (need 10+); skipping for now.")
                return None
            loop = asyncio.get_running_loop()
            if self._closed or not self.context_agent.allowed(chat_id):
                return None
            profile = await loop.run_in_executor(
                None, self.generator.generate_voice_profile, chat_title, "\n".join(lines)
            )
            if self._closed or not self.context_agent.allowed(chat_id):
                return None
            if profile:
                self.db.set_state(f"chat_voice_profile_{chat_id}", profile)
                logger.info(f"[VOICE PROFILE] Saved AI voice profile for '{chat_title}' ({chat_id}): {len(profile)} chars")
            return profile
        except Exception as e:
            logger.debug(f"Could not build voice profile for chat {chat_id}: {e}")
            return None

    async def handle_incoming_eligible_message(
        self,
        chat_id: int,
        chat_title: str,
        message_id: int,
        sender_id: Optional[int],
        sender_name: str,
        text: str,
        conversation_history: Optional[Any] = None,
        is_mention: bool = False,
        engagement: str = "",
    ) -> None:
        """Process an incoming message that has passed initial message filters."""
        if self._closed:
            return
        # Suggestion 1: Incoming message burst debouncer (message stitching)
        debounce_enabled = self.db.get_state("debounce_enabled", "1") == "1"
        raw_db_sec = self.db.get_state("debounce_seconds", "3.0")
        try:
            debounce_sec = float(raw_db_sec)
        except (ValueError, TypeError):
            debounce_sec = 3.0

        # In zero-delay environments (e.g. tests), bypass wait unless debounce_sec was explicitly configured
        if self.min_delay == 0 and self.max_delay == 0 and raw_db_sec == "3.0":
            debounce_sec = 0.0

        if self.current_mode != "restricted_auto" or not debounce_enabled or debounce_sec <= 0:
            await self._process_incoming_message(
                chat_id=chat_id,
                chat_title=chat_title,
                message_id=message_id,
                sender_id=sender_id,
                sender_name=sender_name,
                text=text,
                conversation_history=conversation_history,
                is_mention=is_mention,
                engagement=engagement,
            )
            return

        now = time.time()
        msg_item = {
            "chat_id": chat_id,
            "chat_title": chat_title,
            "message_id": message_id,
            "sender_id": sender_id,
            "sender_name": sender_name,
            "text": text,
            "is_mention": is_mention,
            "engagement": engagement,
            "received_at": now,
        }

        if chat_id not in self._debounce_buffers:
            self._debounce_buffers[chat_id] = []
            self._debounce_first_time[chat_id] = now

        self._debounce_buffers[chat_id].append(msg_item)
        self._debounce_last_time[chat_id] = now

        if chat_id not in self._debounce_tasks or self._debounce_tasks[chat_id].done():
            self._debounce_tasks[chat_id] = self.start_background(
                self._debounce_worker(chat_id, debounce_sec)
            )

        worker = self._debounce_tasks[chat_id]
        await asyncio.shield(worker)

    async def _debounce_worker(self, chat_id: int, debounce_sec: float) -> None:
        """Wait until incoming message burst ceases for chat_id, then stitch and execute."""
        try:
            while True:
                now = time.time()
                last_time = self._debounce_last_time.get(chat_id, now)
                first_time = self._debounce_first_time.get(chat_id, now)
                elapsed_since_last = now - last_time
                remaining = debounce_sec - elapsed_since_last
                total_burst = now - first_time
                buf_len = len(self._debounce_buffers.get(chat_id, []))

                # Contact paused typing (idle > debounce_sec), or burst cap reached (10s or 6 msgs)
                if remaining <= 0.05 or total_burst >= 10.0 or buf_len >= 6:
                    break

                await asyncio.sleep(min(max(0.05, remaining), 0.5))

            items = self._debounce_buffers.pop(chat_id, [])
            self._debounce_tasks.pop(chat_id, None)
            self._debounce_last_time.pop(chat_id, None)
            self._debounce_first_time.pop(chat_id, None)

            if not items:
                return

            latest_item = items[-1]
            latest_id = latest_item["message_id"]
            latest_sender_name = latest_item["sender_name"]
            latest_sender_id = latest_item["sender_id"]
            chat_title = latest_item["chat_title"]
            any_mention = any(m.get("is_mention", False) for m in items)
            engagement = next((m["engagement"] for m in reversed(items) if m.get("engagement")), "")

            if len(items) == 1:
                stitched_text = items[0]["text"]
            else:
                stitched_text = "\n".join(m["text"].strip() for m in items if m["text"].strip())
                logger.info(
                    "[MESSAGE STITCHING] Stitched %s rapid burst messages in chat %s", len(items), chat_id
                )

            ttl_hours = float(self.db.get_state("context_ttl_hours", "4.0"))
            max_age_secs = int(ttl_hours * 3600) if ttl_hours > 0 else None
            fresh_history = self.db.get_recent_chat_messages(
                chat_id, limit=15, max_age_seconds=max_age_secs
            )

            await self._process_incoming_message(
                chat_id=chat_id,
                chat_title=chat_title,
                message_id=latest_id,
                sender_id=latest_sender_id,
                sender_name=latest_sender_name,
                text=stitched_text,
                conversation_history=fresh_history,
                is_mention=any_mention,
                engagement=engagement,
            )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in debounce worker for chat {chat_id}: {e}")

    async def _process_incoming_message(
        self,
        chat_id: int,
        chat_title: str,
        message_id: int,
        sender_id: Optional[int],
        sender_name: str,
        text: str,
        conversation_history: Optional[Any] = None,
        is_mention: bool = False,
        engagement: str = "",
    ) -> None:
        """Serialize group work so a cooldown reply is sent before later messages are handled."""
        if chat_id >= 0:
            await self._process_incoming_message_now(
                chat_id, chat_title, message_id, sender_id, sender_name, text,
                conversation_history, is_mention, engagement,
            )
            return
        lock = self._group_processing_locks.setdefault(chat_id, asyncio.Lock())
        async with lock:
            await self._process_incoming_message_now(
                chat_id, chat_title, message_id, sender_id, sender_name, text,
                conversation_history, is_mention, engagement,
            )

    async def _process_incoming_message_now(
        self,
        chat_id: int,
        chat_title: str,
        message_id: int,
        sender_id: Optional[int],
        sender_name: str,
        text: str,
        conversation_history: Optional[Any] = None,
        is_mention: bool = False,
        engagement: str = "",
    ) -> None:
        """Process a single or stitched incoming message."""
        if self._closed or not self.privacy.is_chat_allowed(chat_id, chat_id < 0):
            return
        if self._context_startup_enabled or chat_id in self._context_init_tasks:
            await self.ensure_chat_context(chat_id)
            if self._closed or not self.privacy.is_chat_allowed(chat_id, chat_id < 0):
                return
        if not self.privacy.is_user_allowed(sender_id):
            return
        pending = self._pending_deferred_replies.get(chat_id)
        if pending and pending is not asyncio.current_task() and not pending.done():
            if chat_id < 0:
                # Deliver the already-written group reply first. Later work then sees the
                # updated history and can continue the conversation with the right context.
                await asyncio.shield(pending)
            else:
                self._pending_deferred_replies.pop(chat_id, None)
                pending.cancel()
        if self.current_mode == "restricted_auto" and self.safety.action_block_reason():
            return
        if self.current_mode == "restricted_auto" and self.owner_recently_active(chat_id):
            self.db.record_action("automation", "reply", "skipped", "Owner replied by hand recently; automation stays quiet in this chat", chat_id=chat_id)
            return
        # Sanitize incoming text before passing to generator
        clean_text = self.privacy.sanitize_text(text)

        age_question = re.search(r"\b(?:how old are you|(?:your|ur|tumhari|aapki)\s+(?:age|umar)|kitne saal ke)\b", text, re.IGNORECASE)
        if age_question and self.generator.prompt_manager.known_owner_age(self.db.get_chat_prompt(chat_id), is_group=chat_id < 0) is None:
            self.db.record_action("automation", "reply", "skipped", "Age is not configured; answer left to the account owner", chat_id=chat_id)
            return

        if _IDENTITY_QUESTION.search(text):
            self.db.record_action("automation", "reply", "skipped", "Identity question left for the account owner", chat_id=chat_id)
            return

        # Ensure recent chat context is always populated so AI is strictly on-topic in DMs & groups
        if not conversation_history:
            ttl_hours = float(self.db.get_state("context_ttl_hours", "4.0"))
            max_age_secs = int(ttl_hours * 3600) if ttl_hours > 0 else None
            conversation_history = self.db.get_recent_chat_messages(
                chat_id, limit=15, max_age_seconds=max_age_secs
            )

        # Record chat metadata for DataFrame display
        self.db.record_chat_metadata(
            chat_id=chat_id,
            title=chat_title,
            chat_type="Group" if chat_id < 0 else "Private",
        )
        if hasattr(self.db, "sync_chat_context_file"):
            self.db.sync_chat_context_file(chat_id)

        context = self.context_agent.snapshot(chat_id, conversation_history, is_mention=is_mention)
        if context is None:
            return
        conversation_history = context.history

        matched_rule = self.db.match_keyword_rule(clean_text)
        try:
            # Permanent chat context (pinned messages + important notes)
            perm_ctx = self.db.get_permanent_context(chat_id)
            pinned_text = perm_ctx.get("pinned_text", "")

            # If this is a group and no pinned messages have been cached yet, auto-fetch (at most every 6 hours)
            if chat_id < 0 and not pinned_text:
                try:
                    pins_checked = float(self.db.get_state(f"chat_pins_checked_{chat_id}") or "-inf")
                except ValueError:
                    pins_checked = float("-inf")
                if time.time() - pins_checked >= 6 * 3600:
                    fetched_pin = await self.sync_pinned_context_from_telegram(chat_id)
                    if fetched_pin:
                        pinned_text = fetched_pin

            # Rebuild after fetching pins; each stage receives the same chat snapshot.
            if not self._context_current(context):
                return
            context = self.context_agent.snapshot(chat_id, conversation_history, is_mention=is_mention)
            if context is None:
                return
            permanent_context_str = context.background or None
            if chat_id < 0:
                permanent_context_str = f"Group title: {chat_title}\n\n{context.background}"
            if matched_rule:
                permanent_context_str = ((permanent_context_str or "") + "\n\nOwner keyword reply intent (rewrite naturally for this conversation, never copy verbatim):\n" + matched_rule)
            chat_style, chat_persona = context.style, context.persona
            conversation_history = context.history

            async def _do_generate():
                if not self.privacy.is_chat_allowed(chat_id, chat_id < 0):
                    return ""
                return await asyncio.to_thread(
                    self.generator.generate,
                    sender_name=sender_name,
                    incoming_text=clean_text,
                    conversation_history=conversation_history,
                    style_override=chat_style or None,
                    persona_override=chat_persona or None,
                    permanent_context=permanent_context_str,
                    is_group=(chat_id < 0),
                    is_mention=is_mention,
                    engagement=engagement,
                )

            # Suggestion 1: Natural Read-Receipt Delay Simulation (2–4s hesitation before marking read)
            if self._client and self.current_mode == "restricted_auto" and (self.min_delay > 0 or self.max_delay > 0):
                read_hesitation = random.uniform(2.0, 4.0)
                await asyncio.sleep(read_hesitation)
                try:
                    if hasattr(self._client, "send_read_acknowledge"):
                        ack_res = self._client.send_read_acknowledge(chat_id, max_id=message_id)
                        if asyncio.iscoroutine(ack_res):
                            await ack_res
                        logger.debug(f"[READ RECEIPT] Marked message {message_id} as read in chat {chat_id}.")
                except Exception as e:
                    logger.debug(f"[READ RECEIPT] Could not send read acknowledgement: {e}")
                # Brief pause before starting to type
                await asyncio.sleep(random.uniform(0.8, 1.5))

            draft = await _do_generate()

        except Exception as e:
            logger.error(f"Failed to generate AI reply for chat {chat_id}: {e}")
            self.db.record_action("automation", "provider", "failed", "Reply generation failed; check provider credentials, endpoint, and model", chat_id=chat_id)
            # Model-failure alerts to authorized users are raised by the shared reporter in ReplyGenerator.
            return

        if not self._context_current(context):
            self.db.record_action("humanizer", "reply", "skipped", "Conversation changed while the reply was being written", chat_id=chat_id)
            return

        # Check if raw generated response was pure laughter (e.g. "haha", "lol")
        # In this case, send an emoji reaction (😂) instead of writing "haha" in a text message
        if draft:
            pure_laugh = re.sub(r"[^a-zA-Z]", "", draft).lower()
            if pure_laugh and re.match(r"^(?:[ae]*h+[ae]*|lol|lmao|rofl|xd|lmfao)+$", pure_laugh):
                logger.info(f"[LAUGHTER REACTION] AI generated laughter '{draft}'. Reacting with emoji instead of text.")
                await self.maybe_send_reaction(chat_id, message_id, "haha")
                return

        if not draft or draft.strip().lower() in ("none", "none.", "null", "null.", "undefined", ""):
            self.db.record_action("automation", "reply", "skipped", "No useful reply selected", chat_id=chat_id)
            return
        blocked = self._outgoing_text_reason(chat_id, draft, [sender_name])
        if blocked:
            self.db.record_action("automation", "reply", "blocked", blocked, chat_id=chat_id)
            return

        # Prevent repeating the same word or exact reply consecutively in this chat
        draft = self._prevent_duplicate_reply(chat_id, capitalize_message(draft))
        if not draft:
            return

        mode = self.current_mode

        # Mode 1: Draft Only (Default)
        if mode == "draft":
            logger.info(
                f"[DRAFT ONLY] Chat: '{chat_title}' ({chat_id}) | Sender: {sender_name}\n"
                f"  Draft: \"{draft}\""
            )
            # Store record for audit trail without sending
            self.db.add_approval(
                chat_id=chat_id,
                chat_title=chat_title,
                reply_to_msg_id=message_id,
                sender_id=sender_id,
                incoming_text=clean_text,
                draft_text=draft,
            )
            return

        # Mode 2: Approval Required
        if mode == "approval":
            approval_id = self.db.add_approval(
                chat_id=chat_id,
                chat_title=chat_title,
                reply_to_msg_id=message_id,
                sender_id=sender_id,
                incoming_text=clean_text,
                draft_text=draft,
            )
            logger.info(
                f"[APPROVAL REQUIRED] Created Draft #{approval_id} for Chat {chat_id} ('{chat_title}')."
            )
            await self._notify_approval_needed(
                approval_id=approval_id,
                chat_id=chat_id,
                chat_title=chat_title,
                sender_name=sender_name,
                incoming_text=clean_text,
                draft_text=draft,
                message_id=message_id,
            )
            return

        # Mode 3: Restricted Automation
        if mode == "restricted_auto":
            # Safety requirement: Restricted auto requires either explicit config or runtime authorization
            if not self.safety.is_auto_authorized:
                logger.warning(
                    f"[RESTRICTED AUTO BLOCKED] Mode is restricted_auto but explicit authorization is not granted. "
                    f"Drafting for approval instead."
                )
                approval_id = self.db.add_approval(
                    chat_id=chat_id,
                    chat_title=chat_title,
                    reply_to_msg_id=message_id,
                    sender_id=sender_id,
                    incoming_text=clean_text,
                    draft_text=draft,
                )
                await self._notify_approval_needed(
                    approval_id=approval_id,
                    chat_id=chat_id,
                    chat_title=chat_title,
                    sender_name=sender_name,
                    incoming_text=clean_text,
                    draft_text=draft,
                    message_id=message_id,
                )
                return

            # Validate safety constraints
            can_send, reason = self.safety.can_reply(chat_id, draft)
            if not can_send:
                logger.info(f"[AUTO REPLY SUPPRESSED] Chat {chat_id}: {reason}")
                if "quiet hours" in reason.lower():
                    # Sleep schedule active: quietly suppress auto-reply without disturbing Saved Messages
                    return
                if "cooldown" in reason.lower() or "limit" in reason.lower():
                    # Cancel any existing pending deferred reply for this chat to avoid double-sends
                    old_task = self._pending_deferred_replies.get(chat_id)
                    if old_task and not old_task.done():
                        old_task.cancel()
                        logger.info(
                            f"[DEFERRED SUPERSEDED] Cancelled previous pending reply for chat {chat_id} "
                            f"because a newer message arrived."
                        )

                    logger.info(
                        f"[REPLY QUEUED] Cooldown/rate-limit active for chat {chat_id}. "
                        f"Waiting for the current limits before sending."
                    )
                    task = self.start_background(
                        self._schedule_deferred_reply(chat_id, message_id, draft, is_mention=is_mention, context=context)
                    )
                    self._pending_deferred_replies[chat_id] = task
                    return
                await self._notify_issue_to_saved_messages(
                    chat_id=chat_id,
                    chat_title=chat_title,
                    sender_name=sender_name,
                    error_msg=f"Auto-reply suppressed by safety guard: {reason}",
                    incoming_text=clean_text,
                    message_id=message_id,
                )
                return

            # Cancel any pending deferred reply task for this chat before sending directly
            old_task = self._pending_deferred_replies.get(chat_id)
            if old_task and not old_task.done():
                old_task.cancel()
                self._pending_deferred_replies.pop(chat_id, None)

            sent = await self._send_reply(chat_id, message_id, draft, adaptive_delay=True, is_mention=is_mention, context=context)
            if sent:
                self.context_agent.observe(chat_id)

    async def refresh_single_chat_summary(self, chat_id: int, min_new_messages: int = 8, force: bool = False, max_payload: int = 50) -> None:
        """Delegate batched memory updates to the context stage."""
        await self.context_agent.refresh(chat_id, min_new_messages, force, max_payload)

    async def init_chat_context(self, chat_id: int) -> None:
        """Immediately initialize, fetch, and build the isolated context file for a newly added chat or group.
        Ensures AI has full context (pins, recent messages, voice profile, recap) before sending any message.
        """
        if self._closed or chat_id in self._context_initializing or not self.privacy.is_chat_allowed(chat_id, chat_id < 0):
            return
        self._context_initializing.add(chat_id)
        try:
            title = ""
            username = ""
            chat_type = "Group" if chat_id < 0 else "Private contact"
            if self._client:
                try:
                    entity = await self._client.get_entity(chat_id)
                    if hasattr(entity, "title") and entity.title:
                        title = entity.title
                    elif hasattr(entity, "first_name") and entity.first_name:
                        title = f"{entity.first_name} {getattr(entity, 'last_name', '') or ''}".strip()
                    if hasattr(entity, "username") and entity.username:
                        username = entity.username.lstrip("@")
                except Exception as e:
                    logger.debug(f"[INIT CONTEXT] Could not fetch entity for {chat_id}: {e}")

            if not title and self.db:
                meta = self.db.get_chat_metadata(chat_id) or {}
                title = meta.get("title") or (f"Group {chat_id}" if chat_id < 0 else f"Chat {chat_id}")
                username = username or meta.get("username", "")

            if self.db:
                self.db.record_chat_metadata(chat_id, title=title, username=username, chat_type=chat_type)

            # Fetch and summarize pins for private chats as well as groups.
            if self._client:
                try:
                    await self.sync_pinned_context_from_telegram(chat_id)
                except Exception as e:
                    logger.debug(f"[INIT CONTEXT] Sync pinned context failed for {chat_id}: {e}")

            # Fetch recent history from Telegram into local SQLite database if empty
            if self.db and self._client and hasattr(self._client, "get_messages"):
                existing_count = self.db.count_chat_messages(chat_id)
                memory_epoch = self.db.get_state(f"chat_memory_epoch_{chat_id}")
                if existing_count < 5 and not memory_epoch:
                    try:
                        recent_msgs = await self._client.get_messages(chat_id, limit=20)
                        for m in reversed(recent_msgs):
                            m_text = getattr(m, "message", None) or getattr(m, "text", None) or ""
                            if (not m_text.strip() or self.safety.is_sensitive(m_text)
                                    or not self.privacy.is_user_allowed(getattr(m, "sender_id", None))):
                                continue
                            sender_name = "Contact"
                            try:
                                s = await m.get_sender()
                                if s:
                                    sender_name = getattr(s, "first_name", "") or getattr(s, "title", "") or "Contact"
                            except Exception:
                                pass
                            if (not self.privacy.is_chat_allowed(chat_id, chat_id < 0)
                                    or self.db.get_state(f"chat_memory_epoch_{chat_id}") != memory_epoch):
                                break
                            self.db.record_chat_message(
                                chat_id=chat_id,
                                message_id=m.id,
                                sender_id=getattr(m, "sender_id", None),
                                sender_name=sender_name,
                                text=self.privacy.sanitize_text(m_text),
                                is_outgoing=bool(getattr(m, "out", False)),
                            )
                    except Exception as e:
                        logger.debug(f"[INIT CONTEXT] Backfilling recent messages for {chat_id}: {e}")

            # Generate AI voice profile and initial recap from the loaded history
            if chat_id < 0:
                await self.generate_chat_voice_profile(chat_id)
            await self.refresh_single_chat_summary(chat_id, min_new_messages=1, force=True)

            if self.db:
                self.db.sync_chat_context_file(chat_id)
            self._context_ready.add(chat_id)
            logger.info(f"[INIT CONTEXT] Successfully initialized permanent context for chat {chat_id} ({title}).")
        except Exception as e:
            logger.warning(f"[INIT CONTEXT] Error initializing context for chat {chat_id}: {e}")
        finally:
            self._context_initializing.discard(chat_id)

    async def check_daily_quota_warning(self) -> None:
        """Daily quota threshold alerts have been disabled and removed."""
        return

    async def _schedule_deferred_reply(
        self,
        chat_id: int,
        message_id: int,
        draft: str,
        is_mention: bool = False,
        context=None,
    ) -> None:
        """Queue and send a deferred reply after cooldown expires so no reply is sent prematurely or dropped."""
        delay_started_at = time.monotonic()
        try:
            while True:
                if not self._outgoing_allowed(chat_id) or not self._context_current(context):
                    return
                can_send, reason = self.safety.can_reply(chat_id, draft)
                # A cooldown within the longest typing window (10 s) is covered by typing in _send_reply.
                if can_send or ("cooldown" in reason.lower() and self.safety.cooldown_remaining(chat_id)[0] <= 10.0):
                    break
                if "cooldown" not in reason.lower() and "limit" not in reason.lower():
                    logger.warning(f"Deferred reply to chat {chat_id} aborted: {reason}")
                    return
                # Re-read live settings so a shortened or reset cooldown takes effect promptly.
                await asyncio.sleep(1.0)

            sent = await self._send_reply(chat_id, message_id, draft, adaptive_delay=True, is_mention=is_mention, context=context,
                                          delay_started_at=delay_started_at)
            if sent:
                self.start_background(self.refresh_single_chat_summary(chat_id))
                logger.info(f"[DEFERRED REPLY SENT] Successfully replied to chat {chat_id} after cooldown.")
        except asyncio.CancelledError:
            logger.debug(f"[DEFERRED REPLY CANCELLED] Deferred reply task for chat {chat_id} was cancelled.")
        except Exception as e:
            logger.error(f"Error in deferred reply: {e}")
        finally:
            if self._pending_deferred_replies.get(chat_id) is asyncio.current_task():
                self._pending_deferred_replies.pop(chat_id, None)

    async def _schedule_spontaneous_followup(
        self,
        chat_id: int,
        sent_text: str,
        delay_seconds: Optional[float] = None,
    ) -> None:
        """Schedule a contextual, delayed follow-up 10–20s after a 1–3 word reply to mimic human trains of thought."""
        try:
            delay = delay_seconds if delay_seconds is not None else random.uniform(10.0, 20.0)
            await asyncio.sleep(delay)

            # Safety checks
            if not self._outgoing_allowed(chat_id) or self.db.get_state("spontaneous_followup_enabled", "1") != "1":
                return

            # Check if contact messaged in the meantime; if so, never interrupt
            recent = self.db.get_recent_chat_messages(chat_id, limit=1)
            if not recent:
                return
            latest = recent[-1]
            if not latest.get("is_outgoing", False) or latest.get("text") != sent_text:
                logger.debug(f"[SPONTANEOUS FOLLOW-UP] Aborted: chat {chat_id} had intervening activity.")
                return

            # Call AI dynamically to generate an ultra-short follow-up thought
            prompt_instruction = (
                f"You just texted: \"{sent_text}\". "
                f"Send an ultra-short spontaneous follow-up thought (1 to 4 words). "
                f"Natural human texting, no names, no greetings, no code, no question marks."
            )

            history = self.db.get_recent_chat_messages(chat_id, limit=5)
            context = self.context_agent.snapshot(chat_id, history, require_latest=True)
            if context is None:
                return
            followup_raw = await asyncio.to_thread(
                self.generator.generate,
                sender_name="Contact",
                incoming_text=prompt_instruction,
                conversation_history=context.history,
                permanent_context=context.background or None,
                style_override=context.style or None,
                persona_override=context.persona or None,
                is_group=(chat_id < 0),
                is_mention=False,
            )

            followup_clean = capitalize_message(self.generator.prompt_manager.clean_reply(followup_raw))
            if not self.context_agent.is_current(context):
                return
            if not followup_clean or len(followup_clean.split()) > 8:
                return

            # Check duplicate
            followup_clean = self._prevent_duplicate_reply(chat_id, followup_clean)
            if not followup_clean:
                return

            can_send, reason = self.safety.can_reply(chat_id, followup_clean)
            if not can_send:
                logger.debug(f"[SPONTANEOUS FOLLOW-UP] Safety suppression: {reason}")
                return

            # Short typing burst (human takes at least 2.0s)
            typing_duration = random.uniform(2.0, 3.5)
            try:
                if hasattr(self._client, "action") and callable(self._client.action):
                    act = self._client.action(chat_id, "typing")
                    if hasattr(act, "__aenter__"):
                        async with act:
                            await asyncio.sleep(typing_duration)
                    else:
                        await asyncio.sleep(typing_duration)
                else:
                    await asyncio.sleep(typing_duration)
            except Exception:
                await asyncio.sleep(typing_duration)

            if self.safety.is_emergency_stopped:
                return

            sent_msg = await self._deliver_message(chat_id, followup_clean, context=context)
            if sent_msg is None:
                return
            sent_id = getattr(sent_msg, "id", 0)
            if not isinstance(sent_id, int):
                sent_id = 0
            self.db.record_chat_message(
                chat_id=chat_id,
                message_id=sent_id,
                sender_id=None,
                sender_name=self.generator.prompt_manager.owner_name,
                text=followup_clean,
                is_outgoing=True,
                is_automated=True,
            )
            self.context_agent.observe(chat_id)
            logger.info(f"[SPONTANEOUS FOLLOW-UP SENT] Sent follow-up '{followup_clean}' to chat {chat_id}.")
        except Exception as e:
            logger.debug(f"Error in spontaneous follow-up: {e}")

    async def _notify_approval_needed(
        self,
        approval_id: int,
        chat_id: int,
        chat_title: str,
        sender_name: str,
        incoming_text: str,
        draft_text: str,
        message_id: int = 0,
    ) -> None:
        """Notify the main user via the control channel (bot, fallback Saved Messages)."""
        if not self._client and self.bot_control is None:
            return

        # Suppress alerts when automation is paused, stopped, or in quiet hours
        if self.safety.is_emergency_stopped or self.safety.get_remaining_pause_seconds() > 0:
            return
        is_quiet, _ = self.safety.is_in_quiet_hours()
        if is_quiet:
            return

        msg_link = self.get_telegram_message_link(chat_id, message_id)
        link_line = f"\n• *Message Link:* [Open in Telegram]({msg_link})" if msg_link else ""
        notification = (
            f"📝 *Pending Approval #{approval_id}*\n"
            f"• *Chat:* {chat_title} (`{chat_id}`)\n"
            f"• *From:* {sender_name}{link_line}\n"
            f"• *Incoming:* \"{incoming_text[:200]}\"\n"
            f"• *Suggested Reply:* \"{draft_text}\"\n\n"
            f"Send `/approve {approval_id}` to send, or `/reject {approval_id}` to discard."
        )
        try:
            async with self._alert_send_lock:
                now = time.time()
                elapsed = now - self._last_alert_time
                if self._last_alert_time > 0 and elapsed < self._alert_min_cooldown:
                    wait_s = self._alert_min_cooldown - elapsed
                    logger.info(f"[ALERT COOLDOWN] Waiting {wait_s:.1f}s before sending next approval card.")
                    await asyncio.sleep(wait_s)

                sent_ok = False
                # With the control bot active, approvals arrive as one-tap ✅/❌ inline buttons
                if self.bot_control is not None:
                    try:
                        sent_ok = await self.bot_control.send_approval_card(notification, approval_id)
                    except Exception as e:
                        logger.warning(f"Bot approval card error ({e}); falling back to the control-alert path.")
                        sent_ok = False
                if not sent_ok:
                    sent_ok = await self._send_control_alert_unlocked(notification)
                if sent_ok:
                    self._last_alert_time = time.time()
        except Exception as e:
            logger.error(f"Failed to send approval notification via control channel: {e}")

    async def _send_control_alert_unlocked(self, text: str, parse_markdown: bool = True) -> bool:
        """Internal worker to dispatch alert message without re-acquiring alert lock."""
        if self.bot_control is not None:
            try:
                return await self.bot_control.send_alert(text)
            except Exception as e:
                logger.warning(f"Bot alert delivery error: {e}")
                return False
        # Headless testing fallback only when running without bot credentials
        if self._client and not getattr(self.config, "bot_api_key", None):
            try:
                await self._client.send_message("me", text, parse_mode="md" if parse_markdown else None)
                return True
            except Exception as e:
                logger.warning(f"Could not send control alert: {e}")
                return False
        return False

    async def _send_control_alert(self, text: str, parse_markdown: bool = True) -> bool:
        """Send a control-channel alert strictly through the bot control channel with lock & cooldown."""
        async with self._alert_send_lock:
            now = time.time()
            elapsed = now - self._last_alert_time
            if self._last_alert_time > 0 and elapsed < self._alert_min_cooldown:
                wait_s = self._alert_min_cooldown - elapsed
                logger.info(f"[ALERT COOLDOWN] Waiting {wait_s:.1f}s before sending next alert to avoid rapid bursts.")
                await asyncio.sleep(wait_s)

            res = await self._send_control_alert_unlocked(text, parse_markdown=parse_markdown)
            if res:
                self._last_alert_time = time.time()
            return res

    async def _notify_issue_to_saved_messages(
        self,
        chat_id: int,
        chat_title: str,
        sender_name: str,
        error_msg: str,
        incoming_text: str = "",
        force: bool = False,
        message_id: int = 0,
    ) -> None:
        """Send internal error/issue alerts to the control channel (bot main user, fallback Saved Messages)."""
        if not self._client and self.bot_control is None:
            return

        if force:
            # AI provider/key failures must ALWAYS reach Saved Messages (throttled to one per 10 minutes)
            now_ts = time.time()
            last_ts = float(self.db.get_state("last_ai_failure_alert_ts", "0") or 0)
            if (now_ts - last_ts) < 600.0:
                return
            self.db.set_state("last_ai_failure_alert_ts", str(now_ts))
        # Otherwise suppress alerts if automation is paused, emergency stopped, in quiet hours, or in draft mode
        elif self.safety.is_emergency_stopped or self.safety.get_remaining_pause_seconds() > 0:
            return
        else:
            is_quiet, _ = self.safety.is_in_quiet_hours()
            if is_quiet:
                return
            if self.current_mode == "draft":
                return

        try:
            target_name = chat_title or f"Chat {chat_id}"
            sender = f" from *{sender_name}*" if sender_name else ""
            incoming_snippet = f"\n• *Incoming:* \"{incoming_text[:120]}\"" if incoming_text else ""
            msg_link = self.get_telegram_message_link(chat_id, message_id)
            link_line = f"\n• *Message Link:* [Open in Telegram]({msg_link})" if msg_link else ""
            alert = (
                f"⚠️ *TeleAutomator Alert* — _never sent to chat_\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• *Destination:* {target_name} (`{chat_id}`){sender}{link_line}\n"
                f"• *Issue:* `{error_msg}`{incoming_snippet}\n"
                f"• *Safety:* Suppressed safely — zero error text or fallbacks reached the recipient."
            )
            await self._send_control_alert(alert)
        except Exception as e:
            logger.error(f"Failed to deliver issue alert via control channel: {e}")

    async def check_pause_expiry(self) -> None:
        """When a timed pause (from /pause or a flood-wait nap) ends naturally, clear it and
        notify the control channel so automation visibly resumes in the group."""
        try:
            until = float(self.db.get_state("pause_until", "0") or 0)
        except ValueError:
            until = 0.0
        if until <= 0 or time.time() < until:
            return
        self.db.set_state("pause_until", "0")
        self.db.set_state("sleep_now", "0")  # a finished /sleep must not let a later /resume disable quiet hours
        logger.info("SAFETY: Timed pause expired. Automation resumed automatically.")
        if not self.safety.is_emergency_stopped:
            await self._send_control_alert(
                "▶️ *Timed pause ended*\nAutomation is active again — replies, reactions & engagement resume in allowlisted chats."
            )

    async def maybe_recover_safe_mode(self) -> None:
        """Auto-recover from safe-mode boot guard: after calm uptime, restore the real mode."""
        if self.db.get_state("safe_mode_active", "0") != "1":
            return
        try:
            since = float(self.db.get_state("safe_mode_since", "0"))
            recover_min = max(1, int(self.db.get_state("safe_mode_recover_minutes", "15")))
        except ValueError:
            return
        if time.time() - max(since, self._process_started_at) < recover_min * 60:
            return
        prev = self.db.get_state("safe_mode_prev_mode", "restricted_auto")
        self.db.set_state("reply_mode", prev)
        self.db.set_state("safe_mode_active", "0")
        if prev == "restricted_auto" and getattr(self.config, "auto_authorize", False):
            self.safety.set_auto_authorization(True)
        logger.info(f"SAFE MODE recovered after {recover_min} min of stable uptime. Mode restored to '{prev}'.")
        await self._send_control_alert(
            f"🛡️ *Safe mode recovered*\nThe process stayed stable for {recover_min} min — automation restored to *{prev}* automatically."
        )

    def _parse_duration(self, raw: str) -> Optional[float]:
        """Parse duration strings like '2h', '30m', '90s', '30 min', '2 hours', '1d 2h'.
        A bare number is interpreted as MINUTES (e.g. '/pause 45' = 45 minutes)."""
        s = raw.strip().lower()
        if not s:
            return None
        factors = {
            "d": 86400.0, "day": 86400.0, "days": 86400.0,
            "h": 3600.0, "hr": 3600.0, "hrs": 3600.0, "hour": 3600.0, "hours": 3600.0,
            "m": 60.0, "min": 60.0, "mins": 60.0, "minute": 60.0, "minutes": 60.0,
            "s": 1.0, "sec": 1.0, "secs": 1.0, "second": 1.0, "seconds": 1.0,
        }
        total = 0.0
        seen = False
        for num_str, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([a-zA-Z]+)?", s):
            unit = (unit or "").strip().lower()
            if unit:
                factor = factors.get(unit)
                if factor is None:
                    return None  # unknown unit word
            else:
                factor = 60.0  # bare number: intuitive minutes
            total += float(num_str) * factor
            seen = True
        return total if seen and total > 0 else None

    async def get_allowed_chats_dataframe(self) -> str:
        """Format all allowlisted groups and chats as an aligned DataFrame table with numbering, name, and username/ID."""
        priv, grps = self.privacy.get_all_allowed_chats()
        all_ids = sorted(list(priv | grps))
        if not all_ids:
            return "_No allowed chats or groups configured. Use `/allowchat <id>` to add._"

        rows: list[list[str]] = []
        for idx, cid in enumerate(all_ids, 1):
            meta = self.db.get_chat_metadata(cid) or {}
            c_type = str(meta.get("chat_type") or ("Group" if cid < 0 else "Private"))
            c_title = str(meta.get("title") or "")
            c_user = str(meta.get("username") or "")

            if self._client and (not c_title or not c_user):
                try:
                    entity = await self._client.get_entity(cid)
                    if hasattr(entity, "title") and isinstance(entity.title, str) and entity.title:
                        c_title = entity.title
                    elif hasattr(entity, "first_name") and isinstance(entity.first_name, str):
                        fn = entity.first_name or ""
                        ln = getattr(entity, "last_name", "") or ""
                        c_title = f"{fn} {ln}".strip()
                    if hasattr(entity, "username") and isinstance(entity.username, str) and entity.username:
                        c_user = entity.username
                    if isinstance(c_title, str) and isinstance(c_user, str):
                        self.db.record_chat_metadata(cid, title=c_title, username=c_user, chat_type=c_type)
                except Exception:
                    pass

            name_display = str(c_title) if (c_title and isinstance(c_title, str)) else f"Chat {cid}"
            user_display = f"@{c_user}" if (c_user and isinstance(c_user, str)) else str(cid)
            rows.append([str(idx), str(c_type), str(name_display), str(user_display)])

        headers = ["#", "Type", "Name / Title", "Username / ID"]
        col_widths = [len(h) for h in headers]
        for row in rows:
            for i, val in enumerate(row):
                col_widths[i] = max(col_widths[i], len(val))

        header_str = " | ".join(headers[i].ljust(col_widths[i]) for i in range(len(headers)))
        sep_str = "-+-".join("-" * col_widths[i] for i in range(len(headers)))
        body_strs = [
            " | ".join(row[i].ljust(col_widths[i]) for i in range(len(headers)))
            for row in rows
        ]
        return f"```\n{header_str}\n{sep_str}\n" + "\n".join(body_strs) + "\n```"

    def _safe_mode_status_inline(self) -> str:
        """One-line safe-mode guard status for the /status card."""
        try:
            threshold = self.db.get_state("safe_mode_restarts", "3")
            recover = self.db.get_state("safe_mode_recover_minutes", "15")
        except ValueError:
            threshold, recover = "3", "15"
        if self.db.get_state("safe_mode_active", "0") == "1":
            try:
                since = float(self.db.get_state("safe_mode_since", "0"))
                waited = max(0, int((time.time() - since) / 60))
            except ValueError:
                waited = 0
            return f"🛡️ *ACTIVE* — draft mode, stable {waited}/{recover} min"
        return f"ready ✅ (trips at {threshold} rapid restarts / 10 min)"

    def calculate_adaptive_delay(
        self,
        chat_id: int,
        reply_text: str = "",
        incoming_text: str = "",
        is_mention: bool = False,
    ) -> float:
        """Calculate human-like randomized delay adapting to per-chat cooldown, group vs DM, and mentions."""
        chat_min, chat_max = self.safety._get_chat_cooldown_range(chat_id)
        if chat_min <= 0.0 and chat_max <= 0.0:
            return 0.0

        if self.min_delay <= 0 and self.max_delay <= 0 and chat_min <= 0:
            return 0.0

        has_custom_chat_cd = (
            self.db
            and hasattr(self.db, "get_state")
            and (self.db.get_state(f"chat_cooldown_min_{chat_id}") != "" or self.db.get_state(f"chat_cooldown_max_{chat_id}") != "")
        )

        # When mentioned: randomized response cooldown strictly between 5 and 30 seconds (or custom chat cooldown if configured)
        if is_mention:
            if has_custom_chat_cd:
                delay = random.uniform(chat_min, max(chat_min, chat_max))
            else:
                delay = random.uniform(5.0, 30.0)
            return round(delay, 2)

        is_group = chat_id < 0

        if has_custom_chat_cd:
            low = chat_min
            high = max(chat_min, chat_max)
            delay = random.uniform(low, high) if high > low else low
            return round(delay, 2)

        # Group chats move quickly in public channels: tighter delay window (5-25s)
        # 1-on-1 private DMs are relaxed personal chats: broader delay window (10-60s)
        if is_group:
            low = max(self.min_delay, 5.0)
            high = min(self.max_delay, 25.0)
            if low > high:
                low = high
        else:
            low = max(self.min_delay, 10.0)
            high = max(low, self.max_delay)

        delay = random.uniform(low, high)

        # Content length adaptation
        content_len = len(reply_text)
        if content_len < 25:
            # Short punchy responses skew faster
            delay = max(self.min_delay, delay - random.uniform(2.0, 5.0))
        elif content_len > 100:
            # Longer thoughtful responses take more formulation time
            delay = min(self.max_delay, delay + random.uniform(3.0, 8.0))

        # Smart Typing Speed Modulation (Suggestion 5)
        combo_text = (reply_text + " " + incoming_text).lower()
        if any(w in combo_text for w in ("haha", "lol", "lmao", "rofl", "xd", "yo", "sup", "nice", "cool", "yeah", "yea")):
            # Fast casual banter: 30% faster response
            delay = max(self.min_delay, delay * 0.70)
        elif any(w in combo_text for w in ("why", "how", "explain", "think", "what do you", "opinion", "serious")):
            # Thoughtful inquiry: 25% longer pause
            delay = min(self.max_delay, delay * 1.25)

        # Add human typing speed jitter (±15% randomized variation)
        jitter = random.uniform(-0.15, 0.15) * delay
        delay = delay + jitter

        cap_max = min(self.max_delay, 25.0) if is_group else self.max_delay
        hard_floor = 5.0 if (self.min_delay > 0 or self.max_delay > 0) else 0.0
        return round(max(hard_floor, self.min_delay, min(cap_max, delay)), 2)

    @staticmethod
    def split_reply_messages(text: str, enabled: bool = True) -> list[str]:
        """Split a multi-thought reply into 2 or 3 natural messages without breaking word or clause meaning."""
        text = text.strip()
        if not text or not enabled:
            return [text] if text else []

        # If already separated by newlines, split by line
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if len(lines) > 1:
            return lines[:3]

        # Natural multi-bubble splits on ellipsis "... "
        if "... " in text:
            parts = [p.strip() for p in text.split("... ") if p.strip()]
            if 1 < len(parts) <= 3 and all(len(p.split()) >= 1 for p in parts):
                return parts

        # If a single line, check for clean sentence boundaries
        sentences = re.split(r"(?<=[.!?])\s+", text)
        sentences = [s.strip() for s in sentences if s.strip()]
        if 1 < len(sentences) <= 3 and len(text) >= 10:
            # Ensure every sentence is a real thought (at least 2 chars), not broken words
            if all(len(s) >= 2 for s in sentences):
                return sentences

        # Natural follow-up split thoughts with clause connectors (e.g. ", btw ", ", also ", ", and ", ", but ", ", let ")
        for conn in (", btw ", ", also ", ", and ", ", but ", ", let "):
            if conn in text.lower():
                idx = text.lower().find(conn)
                part1 = text[:idx].strip()
                part2 = text[idx + 2:].strip()
                if len(part1.split()) >= 2 and len(part2.split()) >= 2 and len(part1) >= 5 and len(part2) >= 5:
                    return [part1, part2]

        return [text]

    @staticmethod
    def maybe_inject_typo_correction(text: str, probability: float = 0.04) -> tuple[str, Optional[str]]:
        """Occasionally simulate a realistic touchscreen fat-finger typo and its immediate *correction follow-up.

        Returns:
            (modified_text, correction_word) or (text, None)
        """
        if probability <= 0 or random.random() > probability:
            return text, None

        words = text.split()
        if len(words) < 3:
            return text, None

        # Eligible casual words (4 to 8 letters, strictly alphabetic)
        eligible_indices = [
            i for i, w in enumerate(words)
            if re.fullmatch(r"[a-zA-Z]{4,8}", w)
            and w.lower() not in ("what", "when", "with", "from", "that", "this", "they", "http", "https")
        ]
        if not eligible_indices:
            return text, None

        target_idx = random.choice(eligible_indices)
        orig_word = words[target_idx]
        w_lower = orig_word.lower()

        if len(w_lower) >= 4:
            # Pick an adjacent-char swap that visually changes the word (avoids identical-char swaps producing no typo)
            chars = list(w_lower)
            swap_candidates = [i for i in range(1, len(w_lower) - 1) if chars[i] != chars[i + 1]]
            if not swap_candidates:
                return text, None
            pos = random.choice(swap_candidates)
            chars[pos], chars[pos + 1] = chars[pos + 1], chars[pos]
            typo_word = "".join(chars)
            if typo_word == orig_word.lower():
                return text, None
            if orig_word.istitle():
                typo_word = typo_word.capitalize()
            elif orig_word.isupper():
                typo_word = typo_word.upper()

            words[target_idx] = typo_word
            return " ".join(words), f"*{orig_word}"

        return text, None

    def _load_recent_replies_history(self) -> dict[int, list[str]]:
        """Restore the persisted per-chat sent-reply history (anti-repetition across restarts)."""
        data = self.db.get_state("recent_replies_by_chat", "")
        if not data:
            return {}
        try:
            parsed = json.loads(data)
            return {int(chat_id): list(texts) for chat_id, texts in parsed.items()}
        except Exception:
            return {}

    def _save_recent_replies_history(self) -> None:
        try:
            self.db.set_state("recent_replies_by_chat", json.dumps(self._recent_replies_history))
        except Exception as e:
            logger.debug(f"Could not persist recent replies history: {e}")

    async def maybe_send_reaction(
        self, chat_id: int, message_id: int, text: str, allow_any_emoji: bool = False
    ) -> bool:
        async with self._outgoing_lock:
            return await self._send_reaction_unlocked(chat_id, message_id, text, allow_any_emoji)

    async def _send_reaction_unlocked(self, chat_id: int, message_id: int, text: str, allow_any_emoji: bool) -> bool:
        """Add an emoji reaction to the message if reaction features and cooldown permit."""
        if not self._client or not self._outgoing_allowed(chat_id):
            return False
        if not allow_any_emoji and self.owner_recently_active(chat_id):
            return False

        # Check if reactions are enabled
        enabled = self.db.get_state(
            "reaction_enabled",
            "1" if getattr(self.config, "reaction_enabled", True) else "0"
        ) == "1"
        if not enabled:
            return False

        # Check quiet hours (sleep schedule)
        is_quiet, _ = self.safety.is_in_quiet_hours()
        if is_quiet:
            logger.debug("[REACTION] Suppressed reaction: quiet hours sleep schedule active.")
            return False

        # Check randomized interval cooldown
        now = time.time()
        min_react_cd = float(self.db.get_state(
            "reaction_min_cooldown_seconds",
            str(getattr(self.config, "reaction_min_cooldown_seconds", 15.0))
        ))
        max_react_cd = float(self.db.get_state(
            "reaction_max_cooldown_seconds",
            str(getattr(self.config, "reaction_max_cooldown_seconds", 60.0))
        ))
        if (now - self._last_reaction_time) < self._next_reaction_cooldown:
            wait_rem = round(self._next_reaction_cooldown - (now - self._last_reaction_time), 1)
            logger.debug(f"[REACTION] Cooldown active ({wait_rem}s remaining before next reaction).")
            return False

        # Human-style per-chat gap: randomized 2–5 minutes between reactions in the same chat
        next_chat_react = self._next_reaction_time_by_chat.get(chat_id, 0.0)
        if now < next_chat_react:
            logger.debug(f"[REACTION] Per-chat reaction cooldown active for {chat_id}.")
            return False

        # Check rolling rate limit
        max_reactions = int(self.db.get_state(
            "reaction_max_per_window",
            str(getattr(self.config, "reaction_max_per_window", 4))
        ))
        window_seconds = float(self.db.get_state(
            "reaction_window_seconds",
            str(getattr(self.config, "reaction_window_seconds", 600.0))
        ))

        recent_count = self.db.get_recent_reaction_count(window_seconds)
        if recent_count >= max_reactions:
            logger.debug(
                f"[REACTION] Rate limit reached: {recent_count}/{max_reactions} reactions used in last {int(window_seconds // 60)}m."
            )
            return False

        # Complete Telegram reaction emoji catalogue
        all_telegram_reactions = [
            "👍", "👎", "❤️", "🔥", "🥰", "👏", "😁", "🤔", "🤯", "😱", "🤬", "😢", "🎉", "🤩",
            "🤮", "💩", "🙏", "👌", "🕊️", "🤡", "🥱", "🥴", "😍", "🐳", "❤️‍🔥", "🌚", "🌭", "💯",
            "🤣", "😂", "💀", "⚡", "🍌", "🏆", "💔", "🤨", "😐", "🍓", "🍾", "💋", "🖕", "😈", "😴", "😭",
            "🤓", "👻", "👨‍💻", "👀", "🎃", "🙈", "😇", "😨", "🤝", "✍️", "🤗", "🫡", "🎅", "🎄",
            "☃️", "💅", "🤪", "🗿", "🆒", "💘", "🙉", "🦄", "😘", "💊", "🙊", "😎", "👾", "🤷‍♂️",
            "🤷", "🤷‍♀️", "😡"
        ]

        # Natural sentiment & tone mapping with full emoji variety (selective, thoughtful, non-spammy).
        # shortcut: pools must stay a subset of `all_telegram_reactions` below (only valid Telegram reaction emojis)
        lower = text.lower()
        has_sentiment = True
        # Entries are regex fragments matched as whole words (laughter may be stretched, e.g. "hahaha", "lmaooo").
        if _mentions_any(lower, ("ha(?:ha)+h?", "lo+l+", "lmao+", "rofl", "xd", "funny", "lmfao+", "joke", "bruh", "meme", "comedy", "dead", "ded")):
            chosen = random.choice(["😂", "🤣", "💀", "😁", "🤡"])
        elif _mentions_any(lower, ("congrats", "congratulations", "huge w", "promoted", "won", "awesome work", "let's go", "goat", "legend", "superb", "champion", "winner", "victory")):
            chosen = random.choice(["🔥", "⚡", "💯", "🏆", "🤩", "👏", "🎉", "🦄"])
        elif _mentions_any(lower, ("thanks", "thank you", "tysm", "love you", "heart", "appreciate it", "grateful", "sweetest", "adorable")):
            chosen = random.choice(["❤️", "❤️‍🔥", "🥰", "😍", "🙏", "🤗", "😘", "💋"])
        elif _mentions_any(lower, ("deal", "sounds good", "done deal", "agreed", "let's do it", "partner", "perfect", "done", "alright", "ok", "yep", "sure")):
            chosen = random.choice(["👍", "🤝", "🫡", "👌", "😎"])
        elif _mentions_any(lower, ("wtf", "no way", "holy shit", "damn", "omg", "crazy", "wild", "insane", "unreal", "can't believe")):
            chosen = random.choice(["🤯", "😱", "👀", "😨", "🤨"])
        elif _mentions_any(lower, ("rip", "sorry to hear", "unfortunate", "so sad", "pain", "hurts", "miss you", "tragic", "heartbroke")):
            chosen = random.choice(["😢", "😭", "💔"])
        elif _mentions_any(lower, ("tired", "sleepy", "exhausted", "bored", "nap")):
            chosen = random.choice(["🥱", "😴"])
        elif _mentions_any(lower, ("whatever", "meh", "sus", "mid", "boring")):
            chosen = random.choice(["🗿", "😐", "🥴"])
        elif _mentions_any(lower, ("party", "birthday", "bday", "cheers", "celebrate")):
            chosen = random.choice(["🎉", "🍾"])
        else:
            has_sentiment = False
            chosen = ""

        # Only react when there is clear, relative sentiment to the message; never react unnecessarily.
        # Own-reply reactions (allow_any_emoji=True) fall back to a vibe-appropriate choice drawn ONLY from
        # the valid Telegram reaction catalogue above (non-catalogue emojis are rejected by Telegram).
        if (not has_sentiment or not chosen) and allow_any_emoji:
            chosen = random.choice(["👍", "🔥", "😂", "🤣", "💯", "🎉", "❤️", "😍", "😎", "🤩", "⚡", "👏", "👀", "🗿", "🆒", "❤️‍🔥", "😈", "💅", "👻", "🤪"])
            has_sentiment = True
        if not has_sentiment or not chosen:
            return False

        try:
            from telethon.tl.functions.messages import SendReactionRequest
            from telethon.tl.types import ReactionEmoji

            peer = await self._client.get_input_entity(chat_id)
            if not self._outgoing_allowed(chat_id):
                return False
            await self._client(SendReactionRequest(peer=peer, msg_id=message_id, reaction=[ReactionEmoji(emoticon=chosen)]))
            now = time.time()
            self.db.record_reaction(now)
            self.db.record_action("automation", "reaction", "sent", "Reaction delivered", chat_id=chat_id)
            self._last_reaction_time = now
            self._next_reaction_time_by_chat[chat_id] = now + random.uniform(120.0, 300.0)
            self._next_reaction_cooldown = random.uniform(min_react_cd, max_react_cd)
            logger.info(
                f"[REACTION] Reacted {chosen} to message {message_id} in chat {chat_id}. "
                f"Next reaction cooldown: {round(self._next_reaction_cooldown, 1)}s."
            )
            return True
        except Exception as e:
            self.db.record_action("automation", "reaction", "failed", "Telegram could not deliver the reaction", chat_id=chat_id)
            if (FloodWaitError and isinstance(e, FloodWaitError)) or "floodwait" in e.__class__.__name__.lower():
                wait_time = getattr(e, "seconds", 30)
                self.safety.set_timed_pause(wait_time + 2.0)
                logger.warning(f"[REACTION FLOODWAIT] Reaction triggered Telegram FloodWait ({wait_time}s). Paused automated actions.")
            else:
                logger.debug(f"[REACTION] Could not send reaction {chosen} to chat {chat_id}: {e}")
            return False

    def _prevent_duplicate_reply(self, chat_id: int, text: str) -> str:
        """Prevent repeating the same exact reply or canned phrase in this chat."""
        clean = text.strip()
        if not clean:
            return ""

        recent = self._recent_replies_history.get(chat_id, [])
        clean_lower = clean.lower()

        for past in recent:
            if clean_lower == past.lower():
                logger.warning("Suppressed duplicate reply in chat %s: reply was sent recently", chat_id)
                return ""
        return clean

    @staticmethod
    def is_group_broadcast_or_greeting(text: str) -> bool:
        """Detect greetings, announcements, or messages addressing the entire group."""
        clean = text.strip().lower()
        if not clean:
            return False
        broadcast_patterns = [
            r"\b(?:hi|hello|hey|yo|sup|hola|namaste|salaam)\b.*\b(?:guys|everyone|all|folks|people|team|friends|bhai|gang|group)\b",
            r"\b(?:guys|everyone|all|folks|team|bhai log|sab|sabhi)\b.*\b(?:hi|hello|hey|sup|kya haal|kaise ho)\b",
            r"\b(?:good morning|good evening|good afternoon|good night|gm|ge|gn)\b(?:\s+(?:all|everyone|guys|team|folks|gang|bhai log|friends))?",
            r"\b(?:anyone|anybody|someone|kisi ko)\b",
            r"\b(?:what's up|whats up|kya chal raha|kya haal|sab kaisa)\b",
            r"\b(?:who is here|anyone here|anybody active|kya scene)\b",
            r"^(?:hi|hello|hey|yo|gm|gn)[!.]*$",
        ]
        return any(re.search(pat, clean) for pat in broadcast_patterns)

    def is_group_message_relevant(self, chat_id: int, text: str, chat_title: str = "") -> bool:
        """Check if an incoming group message is relevant to the group's topic, context, or active discussion."""
        clean_text = text.strip().lower()
        if not clean_text:
            return False

        if self.is_group_broadcast_or_greeting(clean_text) and not re.search(r"\?|\b(?:anyone|anybody|thoughts|opinions)\b", clean_text):
            return False

        if self._matches_group_context(chat_id, clean_text, chat_title):
            return True

        # Open questions can invite the room; message length alone never does.
        return len(clean_text.split()) >= 4 and bool(re.search(
            r"[?？]|\b(?:anyone|anybody|thoughts|opinions|suggestions)\b|^(?:how|what|which|why|where|when|can|could|does|has|have)\b", clean_text
        ))

    def _matches_group_context(self, chat_id: int, clean_text: str, chat_title: str = "") -> bool:
        """True when the message shares meaningful words with the group's own notes, pins or title."""
        ctx = self.db.get_permanent_context(chat_id)
        context_corpus = ""
        if ctx:
            context_corpus += f" {ctx.get('notes', '')} {ctx.get('pinned_text', '')} {ctx.get('pinned_summary', '')}"
        if chat_title:
            context_corpus += f" {chat_title}"

        if context_corpus.strip():
            keywords = set(re.findall(r"\b[a-zA-Z]{4,}\b", context_corpus.lower()))
            stopwords = {"group", "chat", "rules", "always", "this", "that", "with", "from", "have", "will", "what", "here"}
            meaningful_kw = keywords - stopwords
            if meaningful_kw:
                msg_words = set(re.findall(r"\b[a-zA-Z]{4,}\b", clean_text))
                if msg_words.intersection(meaningful_kw):
                    return True
        return False

    # A greeting to everyone, an open question or someone starting a conversation is a natural chance to
    # join in, even with the default chatty rate: such messages get at least this chance to be answered.
    OPEN_INVITE_MIN_CHANCE = 0.6

    def is_open_group_invite(self, text: str) -> bool:
        """The message is for the whole room: a hello to everyone or a general question."""
        clean = text.strip().lower()
        if not clean:
            return False
        if self.is_group_broadcast_or_greeting(clean):
            return True
        return len(clean.split()) >= 2 and bool(re.search(
            r"[?？]|\b(?:anyone|anybody|everyone|guys|thoughts|opinions|suggestions)\b|^(?:how|what|which|why|where|when|who|can|could|does|has|have|is|are|any)\b", clean
        ))

    def plan_group_engagement(self, chat_id: int, text: str, chat_title: str = "", *, is_reply_to_other: bool = False,
                              recent_active: int = 3, idle_before: bool = False) -> tuple[float, str, str]:
        """Decide how an unaddressed group message is treated: (chance 0..1, engagement mode, skip reason).

        Modes: "open" (for the whole room), "thread" (members talking to each other about the group's own
        topics) or "" (ordinary relevant message). A chance of 0 means skip, with the reason.
        """
        base = self.group_chatty_probability(chat_id)
        if base <= 0:
            return 0.0, "", "Chatty is off for this chat"
        if re.match(r"\s*@\w+", text):
            return 0.0, "", "Message is addressed to a specific member"
        full = base >= 1.0
        clean = text.strip().lower()
        invite = self.is_open_group_invite(clean) or idle_before
        if is_reply_to_other:
            # The existing writer judges semantic relevance using this chat's context in any language.
            context = self.db.get_permanent_context(chat_id)
            if not (context.get("notes") or context.get("pinned_text") or self.db.get_chat_summary(chat_id)
                    or len(self.db.get_recent_chat_messages(chat_id, limit=2, max_age_seconds=1200)) > 1):
                return 0.0, "", "No group context available to judge a thread between other members"
            mode, chance = "thread", base
        elif invite:
            mode, chance = "open", max(base, self.OPEN_INVITE_MIN_CHANCE)
        elif full or self.is_group_message_relevant(chat_id, text, chat_title):
            mode, chance = "active" if full else "", base
        else:
            return 0.0, "", "No relevant contribution requested"
        if not full and mode != "open":
            from app.event_handlers import adjust_engagement_for_room_heat
            chance = adjust_engagement_for_room_heat(chance, recent_active)
        return chance, mode, ""

    def check_group_20m_idle(self, chat_id: int) -> bool:
        """Check if 20 minutes (1200s) have passed without any reply or engagement in this group."""
        now = time.time()
        last_time = self._last_group_activity.get(chat_id)
        if last_time is None:
            self._last_group_activity[chat_id] = now
            return False
        return (now - last_time) >= 1200.0

    def mark_group_activity(self, chat_id: int) -> None:
        """Update last activity timestamp for group."""
        self._last_group_activity[chat_id] = time.time()

    async def refresh_group_summaries(self, min_new_messages: int = 15, max_payload: int = 50) -> None:
        """AI-generated rolling context recap per busy allowlisted group (saved for prompts).
        Busy chats (>=5 msgs/2min) summarize from ~8 new messages; quiet chats keep the 15-msg bar."""
        groups: set = set()
        try:
            private_set, group_set = self.privacy.get_all_allowed_chats()
            groups.update(group_set)
            groups.update(private_set)
        except Exception:
            pass
        # Also private chats are summarized when active
        for cid in list(groups):
            try:
                # Busy community groups recap sooner: when the chat produced >=5 messages in the
                # last 2 minutes, summarize from ~8 new messages; quieter chats need the full 15.
                try:
                    threshold = 8 if self.db.get_recent_message_count(120.0, chat_id=cid) >= 5 else min_new_messages
                except Exception:
                    threshold = min_new_messages
                await self.refresh_single_chat_summary(cid, min_new_messages=threshold, max_payload=max_payload)
            except Exception as e:
                logger.debug(f"[AI CONTEXT SUMMARY] Could not summarize chat {cid}: {e}")

    async def maybe_send_quiet_hours_goodnight(self, force: bool = False) -> None:
        """Before or upon entering quiet hours (2:00 AM IST), write bye/goodnight to active allowlisted groups like a human."""
        if not self._client or self.current_mode != "restricted_auto" or (not self.safety.quiet_hours_enabled and not force):
            return

        ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        now_ist = datetime.datetime.now(ist_tz)
        today_str = now_ist.strftime("%Y-%m-%d")

        last_goodnight = self.db.get_state("last_quiet_goodnight_date", "")
        if last_goodnight == today_str and not force:
            return

        start_str, _ = self.safety.quiet_hours_window
        try:
            sh, sm = map(int, start_str.strip().split(":"))
        except Exception:
            return

        target_mins = sh * 60 + sm
        curr_mins = now_ist.hour * 60 + now_ist.minute
        # Trigger window: 15 minutes before start up to 15 minutes after (e.g. 01:45 to 02:15 IST)
        diff = (curr_mins - target_mins) % 1440
        should_send = force or (diff <= 15 or (1440 - diff) <= 15)

        if should_send:
            try:
                _, allowed_groups = self.privacy.get_all_allowed_chats()
                # Mention-only rooms and rooms set to never chime in get no unprompted sign-off.
                mention_only = self.db.get_state("group_mention_only", "0") == "1"
                allowed_groups = [gid for gid in allowed_groups
                                  if not mention_only and self.group_chatty_probability(gid) > 0
                                  and time.time() - self.db.get_last_reply_timestamp(gid) < 900]
            except Exception:
                allowed_groups = []
            if allowed_groups:
                if not any(self._outgoing_allowed(gid, allow_quiet_hours=True) for gid in allowed_groups):
                    return
                # One attempt per night: a failed or empty model sign-off is not retried by the heartbeat.
                self.db.set_state("last_quiet_goodnight_date", today_str)
                # Goodnight text is AI-generated (never hardcoded); skip if the AI fails
                try:
                    text = await asyncio.to_thread(self.generator.generate_goodnight_signoff)
                except Exception as e:
                    logger.warning(f"[QUIET HOURS SIGN-OFF] AI sign-off generation failed, not sending canned text: {e}")
                    text = ""
                if not text:
                    return
                for gid in allowed_groups:
                    try:
                        await self._send_reply(gid, 0, text, allow_quiet_hours=True)
                    except Exception as e:
                        logger.debug(f"Could not send goodnight to group {gid}: {e}")

    async def _send_reply(
        self,
        chat_id: int,
        reply_to_msg_id: int,
        text: str,
        adaptive_delay: bool = True,
        is_mention: bool = False,
        approved: bool = False,
        allow_quiet_hours: bool = False,
        context=None,
        operator_id=None,
        delay_started_at: Optional[float] = None,
    ) -> bool:
        """Send message using Telethon client with adaptive human reading/typing delay and error handling."""
        if delay_started_at is None:
            delay_started_at = time.monotonic()
        if not self._client:
            logger.error("Cannot send reply: Telegram client is not attached.")
            return False
        self._last_delivery_parts[chat_id] = 0
        if not self._outgoing_allowed(chat_id, approved, allow_quiet_hours) or not self._context_current(context, approved):
            return False
        if self.safety.is_sensitive(text):
            return False
        blocked = self._outgoing_text_reason(chat_id, text)
        if blocked:
            self.db.record_action("automation", "reply", "blocked", blocked, chat_id=chat_id)
            return False

        async with self._get_chat_send_lock(chat_id):
            self._last_delivery_parts[chat_id] = 0
            # Private drafts are superseded; group replies remain queued behind this send.
            curr_task = asyncio.current_task()
            old_task = self._pending_deferred_replies.get(chat_id)
            if chat_id > 0 and old_task and old_task is not curr_task and not old_task.done():
                old_task.cancel()
                self._pending_deferred_replies.pop(chat_id, None)

            # Anti-Flooding: In group chats (chat_id < 0), NEVER send multiple message bubbles simultaneously.
            # Multi-bubble splitting is strictly restricted to private 1-on-1 DMs (chat_id > 0).
            multibubble_enabled = (self.db.get_state("multibubble_enabled", "1") == "1") and (chat_id > 0)
            msg_parts = [capitalize_message(part) for part in self.split_reply_messages(text, enabled=multibubble_enabled)]
            if not msg_parts:
                return False

            first_part = msg_parts[0]
            edit_fix_original: Optional[str] = None
            typo_enabled = (
                self.db.get_state("typo_correction_enabled", "1") == "1"
                and self.db.get_state("editfix_enabled", "1") == "1"
            )
            if typo_enabled and len(msg_parts) == 1 and not is_mention:
                # Human mobile texting simulation: occasionally sends a natural typo,
                # then edits the same message clean 1.5–3s later (never sends *correction as a separate message).
                typo_variant, _ = self.maybe_inject_typo_correction(first_part, probability=0.05)
                if typo_variant != first_part:
                    edit_fix_original = first_part
                    first_part = capitalize_message(typo_variant)

            sent_any = False
            try:
                chat_min, _ = self.safety._get_chat_cooldown_range(chat_id)
                initial_range = self.safety._get_chat_cooldown_range(chat_id)

                # Strict per-chat minimum cooldown check
                now_check = time.time()
                last_reply_t = self.safety._last_chat_reply_time.get(chat_id)
                if last_reply_t is None:
                    last_reply_t = (
                        self.db.get_last_reply_timestamp(chat_id)
                        if (self.db and hasattr(self.db, "get_last_reply_timestamp"))
                        else 0.0
                    )
                    self.safety._last_chat_reply_time[chat_id] = last_reply_t

                time_since_last = (now_check - last_reply_t) if last_reply_t > 0 else 999999.0
                needed_cooldown_wait = max(0.0, chat_min - time_since_last) if (last_reply_t > 0 and chat_min > 0) else 0.0

                is_zero_delay = (
                    (self.min_delay <= 0 and self.max_delay <= 0 and chat_min <= 0)
                    or (not adaptive_delay and self.typing_delay <= 0 and needed_cooldown_wait <= 0)
                )

                if is_zero_delay:
                    typing_duration = 0.0
                else:
                    human_wait = self.calculate_adaptive_delay(chat_id, first_part, is_mention=is_mention) if adaptive_delay else 0.0
                    window = self._typing_window(first_part)
                    # Queue/lock time already spent counts toward the human wait only, never toward safety limits.
                    waited = elapsed_wait = max(0.0, time.monotonic() - delay_started_at)

                    def plan():
                        remaining = max(human_wait - waited, self.safety.cooldown_remaining(chat_id)[0],
                                        self.safety.burst_wait_needed(chat_id), 0.0)
                        # Typing fills the end of the wait; only a wait-free send adds a short configured burst.
                        return remaining, (min(window, remaining) if remaining > 0 else min(window, self.typing_delay))

                    remaining, typing_duration = plan()
                    total_delay = max(remaining, typing_duration)
                    if total_delay > 0:
                        env_type = "Group" if chat_id < 0 else "Private DM"
                        mention_str = " (Mention)" if is_mention else ""
                        logger.info(
                            f"[{env_type} Delay{mention_str}] Total delay: {total_delay:.1f}s "
                            f"(reading: {total_delay - typing_duration:.1f}s, typing indicator: {typing_duration:.1f}s) "
                            f"for chat {chat_id} (chat_min={chat_min}s, already_waited={elapsed_wait:.1f}s)."
                        )

                    # Phase 1: reading/thinking until only the typing window is left; live limits are re-read each step.
                    while remaining > typing_duration:
                        if not self._outgoing_allowed(chat_id, approved, allow_quiet_hours) or not self._context_current(context, approved):
                            return False
                        current_range = self.safety._get_chat_cooldown_range(chat_id)
                        if current_range != initial_range:
                            initial_range = current_range
                            if adaptive_delay:
                                human_wait = min(human_wait, self.calculate_adaptive_delay(chat_id, first_part, is_mention=is_mention))
                        step = min(1.0, max(0.01, remaining - typing_duration))
                        await asyncio.sleep(step)
                        waited += step
                        remaining, typing_duration = plan()

                    # Abort if emergency stop was triggered during reading delay
                    if self.safety.is_emergency_stopped:
                        logger.warning(f"Reply to chat {chat_id} aborted: emergency stop triggered during delay.")
                        return False

                # Send first message part
                first_sent = await self._deliver_message(chat_id, first_part, reply_to_msg_id, approved=approved, allow_quiet_hours=allow_quiet_hours, context=context, operator_id=operator_id, typing_seconds=typing_duration)
                if first_sent is None:
                    return False
                sent_any = True
                self._last_delivery_parts[chat_id] = 1
                self._last_sent_reply_by_chat[chat_id] = first_part
                if chat_id < 0:
                    self.mark_group_activity(chat_id)
                first_msg_id = getattr(first_sent, "id", 0)
                if not isinstance(first_msg_id, int):
                    first_msg_id = 0
                self.db.record_chat_message(
                    chat_id=chat_id,
                    message_id=first_msg_id,
                    sender_id=None,
                    sender_name=self.generator.prompt_manager.owner_name,
                    text=first_part,
                    is_outgoing=True,
                    is_automated=True,
                )
                self.context_agent.observe(chat_id)
                logger.info(f"Successfully sent reply part 1/{len(msg_parts)} to chat {chat_id}.")

                # Human touch: occasionally react to your own message just like a real person (20%)
                if (first_msg_id and self.current_mode == "restricted_auto" and not self.safety.is_emergency_stopped
                        and self.db.get_state("ownreact_enabled", "1") == "1"
                        and random.random() < 0.20):
                    try:
                        reacted = await self.maybe_send_reaction(chat_id, first_msg_id, first_part, allow_any_emoji=True)
                        if reacted:
                            logger.info(f"[OWN-REPLY REACTION] Reacted to own message {first_msg_id} in chat {chat_id}.")
                    except Exception as e:
                        logger.debug(f"[OWN-REPLY REACTION] Could not react to own message: {e}")

                # Quick-fire typo self-edit: seamlessly edit the sent message clean ~1.5-3s later (human in-place edit)
                if edit_fix_original is not None and first_msg_id and not self.safety.is_emergency_stopped:
                    await asyncio.sleep(random.uniform(1.5, 3.0))
                    if (not self._outgoing_allowed(chat_id, approved, allow_quiet_hours)
                            or not self._operator_allowed(operator_id) or not self._context_current(context, approved)
                            or self._outgoing_text_reason(chat_id, edit_fix_original)):
                        return True
                    try:
                        await self._client.edit_message(chat_id, first_msg_id, edit_fix_original)
                        self._last_sent_reply_by_chat[chat_id] = edit_fix_original
                        self._recent_replies_history[chat_id] = [edit_fix_original if text == first_part else text
                                                                for text in self._recent_replies_history.get(chat_id, [])]
                        self._save_recent_replies_history()
                        logger.info(f"[SELF EDIT] Edited own message {first_msg_id} in chat {chat_id} to fix the typo.")
                        self.db.record_chat_message(
                            chat_id=chat_id,
                            message_id=first_msg_id,
                            sender_id=None,
                            sender_name=self.generator.prompt_manager.owner_name,
                            text=edit_fix_original,
                            is_outgoing=True,
                            is_automated=True,
                        )
                    except Exception as e:
                        logger.debug(f"[SELF EDIT] Could not edit message {first_msg_id}: {e}")

                # Spontaneous Delayed Follow-Ups (10–20s later for 1–3 word single-message replies in private DMs only)
                followup_enabled = (
                    self.db.get_state("spontaneous_followup_enabled", "1") == "1"
                    and (chat_id > 0)
                )
                if (
                    followup_enabled
                    and len(msg_parts) == 1
                    and edit_fix_original is None
                    and not is_mention
                    and len(first_part.split()) <= 3
                    and self.current_mode == "restricted_auto"
                ):
                    if random.random() < 0.18:
                        self.start_background(
                            self._schedule_spontaneous_followup(
                                chat_id=chat_id,
                                sent_text=first_part,
                            )
                        )

                # Send subsequent message parts (2 or 3) with short natural typing pause (DMs only)
                for idx, part in enumerate(msg_parts[1:], start=2):
                    if self.safety.is_emergency_stopped:
                        logger.warning(f"Follow-up message to chat {chat_id} aborted: emergency stop triggered.")
                        break

                    # Multi-bubble human typing pause (minimum 2.0s) between bubbles - humans take minimum 2 seconds
                    if self.min_delay == 0 and self.max_delay == 0:
                        followup_delay = 0.0
                        followup_typing = 0.0
                        followup_pause = 0.0
                    else:
                        followup_delay = random.uniform(2.5, 4.0)
                        followup_typing = min(followup_delay, max(2.0, min(3.5, len(part.split()) * 0.4)))
                        followup_pause = max(0.0, followup_delay - followup_typing)

                    if followup_pause > 0:
                        await asyncio.sleep(followup_pause)


                    sub_sent = await self._deliver_message(chat_id, part, approved=approved, allow_quiet_hours=allow_quiet_hours, context=context, operator_id=operator_id, typing_seconds=followup_typing, sequence_part=True)
                    if sub_sent is None:
                        break
                    self._last_delivery_parts[chat_id] = idx
                    sub_msg_id = getattr(sub_sent, "id", 0)
                    if not isinstance(sub_msg_id, int):
                        sub_msg_id = 0
                    self.db.record_chat_message(
                        chat_id=chat_id,
                        message_id=sub_msg_id,
                        sender_id=None,
                        sender_name=self.generator.prompt_manager.owner_name,
                        text=part,
                        is_outgoing=True,
                        is_automated=True,
                    )
                    logger.info(f"Successfully sent reply part {idx}/{len(msg_parts)} to chat {chat_id}.")

                complete = self._last_delivery_parts[chat_id] == len(msg_parts)
                if not complete:
                    self.db.record_action("automation", "reply", "failed", f"Partial delivery: {self._last_delivery_parts[chat_id]}/{len(msg_parts)} parts sent; not retried automatically", chat_id=chat_id)
                return complete
            except Exception as e:
                # Check for Telegram FloodWaitError
                self.db.record_action("automation", "reply", "failed", "Telegram delivery failed: " + type(e).__name__, chat_id=chat_id)
                if (FloodWaitError and isinstance(e, FloodWaitError)) or "floodwait" in e.__class__.__name__.lower():
                    wait_time = getattr(e, "seconds", 60)
                    self.safety.set_timed_pause(wait_time + 5.0)
                    logger.warning(
                        f"[TELEGRAM FLOODWAIT] Telegram anti-spam FloodWait triggered! "
                        f"Pausing all automated actions for {wait_time + 5}s."
                    )
                    await self._notify_issue_to_saved_messages(
                        chat_id=chat_id,
                        chat_title="",
                        sender_name="",
                        error_msg=f"Telegram FloodWaitError: Pausing automated replies for {wait_time}s as required by Telegram anti-spam guidelines.",
                        incoming_text=text,
                        message_id=reply_to_msg_id,
                    )
                    return False

                # Check for Telegram PeerFloodError (account restricted by Telegram anti-spam)
                if (PeerFloodError and isinstance(e, PeerFloodError)) or "peerflood" in e.__class__.__name__.lower():
                    self.safety.set_emergency_stop(True)
                    logger.critical(
                        f"[TELEGRAM PEERFLOOD] Telegram anti-spam restriction triggered (PeerFloodError)! "
                        f"Emergency stop activated to protect account from ban."
                    )
                    await self._notify_issue_to_saved_messages(
                        chat_id=chat_id,
                        chat_title="",
                        sender_name="",
                        error_msg="Telegram PeerFloodError: Account was restricted by Telegram anti-spam (@SpamBot). All automated actions stopped safely.",
                        incoming_text=text,
                        message_id=reply_to_msg_id,
                    )
                    return False

                self.safety.record_error()
                logger.error(f"Failed to send message to chat {chat_id}: {e}")
                await self._notify_issue_to_saved_messages(
                    chat_id=chat_id,
                    chat_title="",
                    sender_name="",
                    error_msg=f"Message delivery error: {e}",
                    incoming_text=text,
                    message_id=reply_to_msg_id,
                )
                return False
