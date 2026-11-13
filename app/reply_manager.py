"""Reply orchestration handling Draft, Approval, and Restricted Automation modes."""

from __future__ import annotations

import asyncio
import datetime
import json
import random
import re
import time
from typing import Any, Optional

from app.ai.reply_generator import ReplyGenerator
from app.config import AppConfig
from app.logger import setup_logger
from app.privacy_manager import PrivacyManager
from app.safety_manager import SafetyManager
from app.storage.database import Database

logger = setup_logger(__name__)

from app.command_router import CommandRouterMixin, _BOT_COMMAND_NAMES, _parse_time_str

try:
    from telethon.errors import FloodWaitError, PeerFloodError
except Exception:
    FloodWaitError = None  # type: ignore
    PeerFloodError = None  # type: ignore


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
            return True
        return False

    def set_telegram_client(self, client: Any) -> None:
        """Attach the active Telethon client."""
        self._client = client

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
        if not self._client:
            return None
        try:
            from telethon.tl.types import InputMessagesFilterPinned
            chat_title = str(chat_id)
            try:
                entity = await self._client.get_entity(chat_id)
                chat_title = getattr(entity, "title", "") or getattr(entity, "first_name", "") or str(chat_id)
            except Exception:
                pass

            pinned_msgs = await self._client.get_messages(chat_id, filter=InputMessagesFilterPinned, limit=5)
            if pinned_msgs:
                texts = [m.text.strip() for m in pinned_msgs if getattr(m, "text", None) and m.text.strip()]
                if texts:
                    raw_combined = "\n---\n".join(texts)
                    loop = asyncio.get_running_loop()
                    distilled = await loop.run_in_executor(
                        None, self.generator.distill_group_context, chat_title, raw_combined
                    )
                    pinned_content = distilled if distilled else raw_combined[:1500]
                    self.db.set_permanent_context(chat_id, pinned_text=pinned_content)
                    logger.info(f"AI-distilled permanent pinned context for '{chat_title}' ({chat_id}): {len(pinned_content)} chars")
                    return pinned_content
        except Exception as e:
            logger.debug(f"Could not fetch pinned messages for chat {chat_id}: {e}")
        return None

    async def generate_chat_voice_profile(self, chat_id: int, min_messages: int = 45) -> Optional[str]:
        """Fetch 40+ recent messages of a group, AI learns how its people talk, store permanently."""
        if not self._client or chat_id >= 0:
            logger.debug(f"Voice profile skipped for chat {chat_id}: client attached={bool(self._client)}, is_group={chat_id < 0}")
            return None
        try:
            entity = await self._client.get_entity(chat_id)
            chat_title = getattr(entity, "title", "") or str(chat_id)
            msgs = await self._client.get_messages(chat_id, limit=min_messages)
            lines: list[str] = []
            for m in msgs:
                txt = (getattr(m, "text", "") or "").strip()
                if not txt:
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
            profile = await loop.run_in_executor(
                None, self.generator.generate_voice_profile, chat_title, "\n".join(lines)
            )
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
    ) -> None:
        """Process an incoming message that has passed initial message filters."""
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
            "received_at": now,
        }

        if chat_id not in self._debounce_buffers:
            self._debounce_buffers[chat_id] = []
            self._debounce_first_time[chat_id] = now

        self._debounce_buffers[chat_id].append(msg_item)
        self._debounce_last_time[chat_id] = now

        if chat_id not in self._debounce_tasks or self._debounce_tasks[chat_id].done():
            self._debounce_tasks[chat_id] = asyncio.create_task(
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

            if len(items) == 1:
                stitched_text = items[0]["text"]
            else:
                stitched_text = "\n".join(m["text"].strip() for m in items if m["text"].strip())
                logger.info(
                    f"[MESSAGE STITCHING] Stitched {len(items)} rapid burst messages in chat {chat_id} "
                    f"into single cohesive thought: '{stitched_text[:60]}...'"
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
    ) -> None:
        """Process a single or stitched incoming message."""
        # Sanitize incoming text before passing to generator
        clean_text = self.privacy.sanitize_text(text)

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

        # Check for custom keyword trigger rule before calling AI
        matched_rule = self.db.match_keyword_rule(clean_text)
        if matched_rule:
            logger.info(f"[KEYWORD TRIGGER] Matched custom trigger rule for chat {chat_id}.")
            draft = matched_rule
        else:
            try:
                # Permanent chat context (pinned messages + important notes)
                perm_ctx = self.db.get_permanent_context(chat_id)
                pinned_text = perm_ctx.get("pinned_text", "")
                notes = perm_ctx.get("notes", "")

                # If this is a group and no pinned messages have been cached yet, auto-fetch
                if chat_id < 0 and not pinned_text:
                    fetched_pin = await self.sync_pinned_context_from_telegram(chat_id)
                    if fetched_pin:
                        pinned_text = fetched_pin

                perm_parts = []
                if pinned_text:
                    perm_parts.append(f"📌 Pinned message / group rules:\n{pinned_text}")
                if notes:
                    perm_parts.append(f"📝 Important chat notes & background:\n{notes}")
                # AI-generated voice profile for this group (how people talk, slang, lengths, topics)
                voice_profile = self.db.get_state(f"chat_voice_profile_{chat_id}")
                if voice_profile:
                    perm_parts.append(
                        f"🗣 HOW PEOPLE TALK IN THIS CHAT (AI-observed voice — mirror this tone, "
                        f"slang, message length and energy so you blend in like a regular here):\n{voice_profile}"
                    )
                # AI-generated rolling recap of recent chat context (refreshed by background job)
                ai_summary = self.db.get_chat_summary(chat_id)
                if ai_summary:
                    perm_parts.append(f"🧠 AI recap of this chat's recent conversations (so you remember older banter):\n{ai_summary}")
                permanent_context_str = "\n\n".join(perm_parts) if perm_parts else None

                # Check for per-chat style/persona overrides; fallback to global defaults
                chat_style = self.db.get_state(f"chat_style_{chat_id}")
                chat_persona = self.db.get_state(f"chat_prompt_{chat_id}")

                async def _do_generate():
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

                # Show typing indicator in chat or group while AI thinks/generates reply
                if self._client and self.current_mode == "restricted_auto":
                    try:
                        if hasattr(self._client, "action") and callable(self._client.action):
                            act = self._client.action(chat_id, "typing")
                            if hasattr(act, "__aenter__"):
                                async with act:
                                    draft = await _do_generate()
                            else:
                                if asyncio.iscoroutine(act):
                                    try:
                                        await act
                                    except Exception:
                                        pass
                                draft = await _do_generate()
                        else:
                            draft = await _do_generate()
                    except Exception:
                        draft = await _do_generate()
                else:
                    draft = await _do_generate()
            except Exception as e:
                logger.error(f"Failed to generate AI reply for chat {chat_id}: {e}")
                # AI provider/model/API-key failure: always alert Saved Messages so the owner can fix it fast.
                if not is_mention:
                    provider = getattr(self.generator.config, "ai_provider", "")
                    await self._notify_issue_to_saved_messages(
                        chat_id=chat_id,
                        chat_title=chat_title,
                        sender_name=sender_name,
                        error_msg=f"AI provider/model failed (provider='{provider}', all fallbacks exhausted): {e}",
                        incoming_text=clean_text,
                        force=True,
                    )
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
            # AI produced empty or null response: NEVER send hardcoded text to peer chats.
            if not is_mention:
                logger.warning(f"No valid draft generated for chat {chat_id}.")
                await self._notify_issue_to_saved_messages(
                    chat_id=chat_id,
                    chat_title=chat_title,
                    sender_name=sender_name,
                    error_msg="Empty or None response from AI engine; reply was dropped safely.",
                    incoming_text=clean_text,
                )
            return

        # Prevent repeating the same word or exact reply consecutively in this chat
        draft = self._prevent_duplicate_reply(chat_id, draft)

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
                    # NEVER skip mention messages: schedule deferred reply after cooldown/rate-limit!
                    if is_mention:
                        m = re.search(r"\((\d+)s remaining\)", reason)
                        wait_secs = float(m.group(1)) if m else 5.0
                        logger.info(
                            f"[MENTION QUEUED] Cooldown/rate-limit active for chat {chat_id} ({wait_secs}s). "
                            f"Scheduling deferred reply so mention is NEVER skipped."
                        )
                        asyncio.create_task(
                            self._schedule_deferred_reply(chat_id, message_id, draft, wait_secs)
                        )
                    return
                await self._notify_issue_to_saved_messages(
                    chat_id=chat_id,
                    chat_title=chat_title,
                    sender_name=sender_name,
                    error_msg=f"Auto-reply suppressed by safety guard: {reason}",
                    incoming_text=clean_text,
                )
                return

            sent = await self._send_reply(chat_id, message_id, draft, adaptive_delay=True, is_mention=is_mention)
            if sent:
                asyncio.create_task(self.refresh_single_chat_summary(chat_id))

    async def refresh_single_chat_summary(self, chat_id: int, min_new_messages: int = 4) -> None:
        """Dynamically update AI context memory for a single chat after recent messages."""
        try:
            marker = int(self.db.get_state(f"chat_summary_marker_{chat_id}", "0"))
            new_count = self.db.count_chat_messages_since(chat_id, marker)
            if new_count < min_new_messages:
                return
            raw = self.db.get_chat_messages_since_text(chat_id, marker, limit=40)
            if not raw:
                return
            meta = self.db.get_chat_metadata(chat_id) or {}
            title = meta.get("title") or ("this group" if chat_id < 0 else "this chat")
            summary = await asyncio.to_thread(
                self.generator.summarize_chat_history,
                title,
                self.db.get_chat_summary(chat_id),
                raw,
            )
            if summary:
                self.db.set_chat_summary(chat_id, summary)
                self.db.set_state(f"chat_summary_marker_{chat_id}", str(self.db.latest_chat_message_row_id(chat_id)))
                logger.info(f"[AI CHAT MEMORY] Auto-updated rolling context memory for chat {chat_id} ({new_count} new messages).")
        except Exception as e:
            logger.debug(f"[AI CHAT MEMORY] Could not update memory for chat {chat_id}: {e}")

    async def check_daily_quota_warning(self) -> None:
        """Daily quota threshold alerts have been disabled and removed."""
        return

    async def _schedule_deferred_reply(
        self,
        chat_id: int,
        message_id: int,
        draft: str,
        wait_seconds: float,
    ) -> None:
        """Queue and send a deferred reply after cooldown expires so mentions are never dropped."""
        try:
            await asyncio.sleep(max(1.0, wait_seconds + 1.0))
            if self.safety.is_emergency_stopped or self.safety.get_remaining_pause_seconds() > 0:
                logger.warning(f"Deferred mention reply to chat {chat_id} aborted: emergency stop or pause active.")
                return

            can_send, reason = self.safety.can_reply(chat_id, draft)
            if not can_send:
                if "cooldown" in reason.lower() or "limit" in reason.lower():
                    m = re.search(r"\((\d+)s remaining\)", reason)
                    retry_wait = float(m.group(1)) if m else 3.0
                    await asyncio.sleep(retry_wait + 1.0)
                    if self.safety.is_emergency_stopped or self.safety.get_remaining_pause_seconds() > 0:
                        return
                    can_send, reason = self.safety.can_reply(chat_id, draft)
                    if not can_send:
                        logger.warning(f"Deferred mention reply to chat {chat_id} aborted: {reason}")
                        return
                else:
                    logger.warning(f"Deferred mention reply to chat {chat_id} aborted: {reason}")
                    return

            sent = await self._send_reply(chat_id, message_id, draft, adaptive_delay=True, is_mention=True)
            if sent:
                asyncio.create_task(self.refresh_single_chat_summary(chat_id))
            logger.info(f"[DEFERRED MENTION SENT] Successfully replied to mention in chat {chat_id} after cooldown.")
        except Exception as e:
            logger.error(f"Error in deferred mention reply: {e}")

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
            if self.safety.is_emergency_stopped or self.safety.get_remaining_pause_seconds() > 0:
                return
            is_quiet, _ = self.safety.is_in_quiet_hours()
            if is_quiet:
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
            followup_raw = await asyncio.to_thread(
                self.generator.generate,
                sender_name="Contact",
                incoming_text=prompt_instruction,
                conversation_history=history,
                is_group=(chat_id < 0),
                is_mention=False,
            )

            followup_clean = self.generator.prompt_manager.clean_reply(followup_raw)
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

            sent_msg = await self._client.send_message(chat_id, followup_clean)
            self.safety.mark_reply_sent(chat_id)
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
            )
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

        notification = (
            f"📝 *Pending Approval #{approval_id}*\n"
            f"• *Chat:* {chat_title} (`{chat_id}`)\n"
            f"• *From:* {sender_name}\n"
            f"• *Incoming:* \"{incoming_text[:200]}\"\n"
            f"• *Suggested Reply:* \"{draft_text}\"\n\n"
            f"Send `/approve {approval_id}` to send, or `/reject {approval_id}` to discard."
        )
        try:
            # With the control bot active, approvals arrive as one-tap ✅/❌ inline buttons
            if self.bot_control is not None:
                try:
                    if await self.bot_control.send_approval_card(notification, approval_id):
                        return
                    logger.warning("Bot approval card failed; falling back to the control-alert path.")
                except Exception as e:
                    logger.warning(f"Bot approval card error ({e}); falling back to the control-alert path.")
            await self._send_control_alert(notification)
        except Exception as e:
            logger.error(f"Failed to send approval notification via control channel: {e}")

    async def _send_control_alert(self, text: str, parse_markdown: bool = True) -> bool:
        """Send a control-channel alert: to the bot's main user when the bot is active,
        otherwise (or if bot delivery fails) to Saved Messages as fallback."""
        if self.bot_control is not None:
            try:
                if await self.bot_control.send_alert(text):
                    return True
                logger.warning("Bot alert delivery failed; falling back to Saved Messages.")
            except Exception as e:
                logger.warning(f"Bot alert delivery error ({e}); falling back to Saved Messages.")
        if not self._client:
            return False
        try:
            # 'me' in Telethon resolves to the user's private Saved Messages
            await self._client.send_message("me", text, parse_mode="md" if parse_markdown else None)
            return True
        except Exception as e:
            logger.warning(f"Could not send control alert: {e}")
            return False

    async def _notify_issue_to_saved_messages(
        self,
        chat_id: int,
        chat_title: str,
        sender_name: str,
        error_msg: str,
        incoming_text: str = "",
        force: bool = False,
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
            alert = (
                f"⚠️ *TeleAutomator Alert* — _never sent to chat_\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• *Destination:* {target_name} (`{chat_id}`){sender}\n"
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
        if time.time() - since < recover_min * 60:
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
        """Calculate human-like randomized delay adapting to group vs DM, message complexity, and mentions."""
        if self.min_delay <= 0 and self.max_delay <= 0:
            return 0.0

        # When mentioned: randomized response cooldown strictly between 5 and 30 seconds
        if is_mention:
            delay = random.uniform(5.0, 30.0)
            return round(delay, 2)

        is_group = chat_id < 0

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
        """Add an emoji reaction to the message if reaction features and cooldown permit."""
        if not self._client:
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
        if any(w in lower for w in ("haha", "lol", "lmao", "rofl", "xd", "funny", "lmfao", "joke", "bruh", "meme", "comedy", "dead", "ded")):
            chosen = random.choice(["😂", "🤣", "💀", "😁", "🤡"])
        elif any(w in lower for w in ("congrats", "congratulations", "huge w", "promoted", "won", "awesome work", "let's go", "goat", "legend", "superb", "champion", "winner", "victory")):
            chosen = random.choice(["🔥", "⚡", "💯", "🏆", "🤩", "👏", "🎉", "🦄"])
        elif any(w in lower for w in ("thanks", "thank you", "tysm", "love you", "heart", "appreciate it", "grateful", "sweetest", "adorable")):
            chosen = random.choice(["❤️", "❤️‍🔥", "🥰", "😍", "🙏", "🤗", "😘", "💋"])
        elif any(w in lower for w in ("deal", "sounds good", "done deal", "agreed", "let's do it", "partner", "perfect", "done", "alright", "ok", "yep", "sure")):
            chosen = random.choice(["👍", "🤝", "🫡", "👌", "😎"])
        elif any(w in lower for w in ("wtf", "no way", "holy shit", "damn", "omg", "crazy", "wild", "insane", "unreal", "can't believe")):
            chosen = random.choice(["🤯", "😱", "👀", "😨", "🤨"])
        elif any(w in lower for w in ("rip", "sorry to hear", "unfortunate", "so sad", "pain", "hurts", "miss you", "tragic", "heartbroke")):
            chosen = random.choice(["😢", "😭", "💔"])
        elif any(w in lower for w in ("tired", "sleepy", "exhausted", "bored", "nap")):
            chosen = random.choice(["🥱", "😴"])
        elif any(w in lower for w in ("whatever", "meh", "sus", "mid", "boring")):
            chosen = random.choice(["🗿", "😐", "🥴"])
        elif any(w in lower for w in ("party", "birthday", "bday", "cheers", "celebrate")):
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
            await self._client(SendReactionRequest(peer=peer, msg_id=message_id, reaction=[ReactionEmoji(emoticon=chosen)]))
            now = time.time()
            self.db.record_reaction(now)
            self._last_reaction_time = now
            self._next_reaction_time_by_chat[chat_id] = now + random.uniform(120.0, 300.0)
            self._next_reaction_cooldown = random.uniform(min_react_cd, max_react_cd)
            logger.info(
                f"[REACTION] Reacted {chosen} to message {message_id} in chat {chat_id}. "
                f"Next reaction cooldown: {round(self._next_reaction_cooldown, 1)}s."
            )
            return True
        except Exception as e:
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
                logger.warning(f"Suppressed duplicate reply in chat {chat_id}: '{clean}' was sent recently.")
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

        if self.is_group_broadcast_or_greeting(clean_text):
            return True

        # 1. Check permanent context and pinned info
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

        # 2. Check if the message is a discussion prompt, question, or understandable topic statement
        discussion_keywords = (
            "how", "what", "why", "where", "who", "when", "can", "could", "should", "would",
            "anyone", "anybody", "someone", "think", "thought", "thoughts", "opinion", "idea",
            "solution", "issue", "error", "problem", "working", "tried", "tested", "project",
            "guys", "bro", "folks", "team", "people", "suggestion", "opinions", "batao",
            "kisi ko", "kaise", "kya", "kyun", "lagta", "sahi", "chal raha", "update"
        )
        words = clean_text.split()
        if len(words) >= 2 and any(kw in clean_text for kw in discussion_keywords):
            return True
        if len(words) >= 5:
            # Meaningful multi-word statement or conversation in the group
            return True

        return False

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

    async def refresh_group_summaries(self, min_new_messages: int = 15, max_payload: int = 40) -> None:
        """AI-generated rolling context recap per busy allowlisted group (saved for prompts).
        Busy chats (>=5 msgs/2min) summarize from ~8 new messages; quiet chats keep the 15-msg bar."""
        groups: set = set()
        try:
            private_set, group_set = self.privacy.get_all_allowed_chats()
            groups.update(group_set)
            groups.update(private_set)
        except Exception:
            pass
        if not groups:
            try:
                known = self.db.get_known_chats()
                groups = {c["chat_id"] for c in known if c.get("chat_id", 0) < 0 and self.privacy.is_chat_allowed(c["chat_id"], True)}
            except Exception:
                return
        # Also private chats are summarized when active
        for cid in list(groups):
            try:
                marker = int(self.db.get_state(f"chat_summary_marker_{cid}", "0"))
                new_count = self.db.count_chat_messages_since(cid, marker)
                # Busy community groups recap sooner: when the chat produced >=5 messages in the
                # last 2 minutes, summarize from ~8 new messages; quieter chats need the full 15.
                try:
                    threshold = 8 if self.db.get_recent_message_count(120.0, chat_id=cid) >= 5 else min_new_messages
                except Exception:
                    threshold = min_new_messages
                if new_count < threshold:
                    continue
                raw = self.db.get_chat_messages_since_text(cid, marker, limit=max_payload)
                if not raw:
                    continue
                meta = self.db.get_chat_metadata(cid) or {}
                title = meta.get("title") or ("this group" if cid < 0 else "this chat")
                summary = await asyncio.to_thread(
                    self.generator.summarize_chat_history,
                    title,
                    self.db.get_chat_summary(cid),
                    raw,
                )
                if not summary:
                    continue
                self.db.set_chat_summary(cid, summary)
                self.db.set_state(f"chat_summary_marker_{cid}", str(self.db.latest_chat_message_row_id(cid)))
                logger.info(f"[AI CONTEXT SUMMARY] Updated rolling recap for chat {cid} ({new_count} new messages).")
            except Exception as e:
                logger.debug(f"[AI CONTEXT SUMMARY] Could not summarize chat {cid}: {e}")

    async def maybe_send_quiet_hours_goodnight(self, force: bool = False) -> None:
        """Before or upon entering quiet hours (2:00 AM IST), write bye/goodnight to active allowlisted groups like a human."""
        if not self._client or (not self.safety.quiet_hours_enabled and not force):
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
                allowed_groups = list(allowed_groups)
            except Exception:
                allowed_groups = []
            if not allowed_groups:
                known = self.db.get_known_chats()
                allowed_groups = [c["chat_id"] for c in known if c.get("chat_id", 0) < 0 and self.privacy.is_chat_allowed(c["chat_id"], True)]

            if allowed_groups:
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
                        peer = await self._client.get_input_entity(gid)
                        await self._client.send_message(peer, text)
                        logger.info(f"[QUIET HOURS SIGN-OFF] Sent goodnight message to group {gid}: '{text}'")
                        await asyncio.sleep(random.uniform(2.0, 4.0))
                    except Exception as e:
                        logger.debug(f"Could not send goodnight to group {gid}: {e}")

                self.db.set_state("last_quiet_goodnight_date", today_str)

    async def _send_reply(
        self,
        chat_id: int,
        reply_to_msg_id: int,
        text: str,
        adaptive_delay: bool = True,
        is_mention: bool = False,
    ) -> bool:
        """Send message using Telethon client with adaptive human reading/typing delay and error handling."""
        if not self._client:
            logger.error("Cannot send reply: Telegram client is not attached.")
            return False

        # Human burst guard: never machine-gun >3 reply sequences into one chat within 10s.
        # Counts one sequence per _send_reply call (multi-bubble parts stay inside the same moment).
        burst_wait = self.safety.burst_wait_needed(chat_id)
        if burst_wait > 0:
            logger.info(f"[BURST GUARD] Pausing {burst_wait:.1f}s before next reply in chat {chat_id} (human burst cap {self.safety.burst_max_sends}/{self.safety.burst_window_seconds:.0f}s).")
            await asyncio.sleep(burst_wait)

        multibubble_enabled = self.db.get_state("multibubble_enabled", "1") == "1"
        msg_parts = self.split_reply_messages(text, enabled=multibubble_enabled)
        if not msg_parts:
            return False

        first_part = msg_parts[0]
        edit_fix_original: Optional[str] = None
        typo_enabled = (
            self.db.get_state("typo_correction_enabled", "1") == "1"
            or self.db.get_state("editfix_enabled", "1") == "1"
        )
        if typo_enabled and len(msg_parts) == 1 and not is_mention:
            # Human mobile texting simulation: occasionally sends a natural typo,
            # then edits the same message clean 1.5–3s later (never sends *correction as a separate message).
            typo_variant, _ = self.maybe_inject_typo_correction(first_part, probability=0.05)
            if typo_variant != first_part:
                edit_fix_original = first_part
                first_part = typo_variant

        try:
            # Calculate human-like delay adapting to group/DM environment and mentions (5-30s)
            if adaptive_delay and (self.min_delay > 0 or self.max_delay > 0):
                total_delay = self.calculate_adaptive_delay(chat_id, first_part, is_mention=is_mention)
            else:
                total_delay = self.typing_delay

            if adaptive_delay and (self.typing_delay > 0 or self.min_delay > 0 or self.max_delay > 0):
                # Human floor: never reply instantly — always at least a ~3-4.5s random thinking pause
                total_delay = max(total_delay, random.uniform(3.0, 4.5))

            if total_delay > 0:
                # Realistic human simulation: pause for reading/thinking, then show typing action
                # Dynamic typing delay scaling based on 1 to 5 word responses
                word_count = len(first_part.split())
                if word_count <= 2:
                    target_typing = random.uniform(1.2, 2.2)
                elif word_count <= 5:
                    target_typing = random.uniform(2.2, 3.8)
                else:
                    target_typing = random.uniform(3.8, 5.5)

                typing_duration = min(total_delay, target_typing) if total_delay > 1.5 else total_delay
                reading_delay = max(0.0, total_delay - typing_duration)

                env_type = "Group" if chat_id < 0 else "Private DM"
                mention_str = " (Mention 5-30s Delay)" if is_mention else ""
                logger.info(
                    f"[{env_type} Delay{mention_str}] Waiting {total_delay:.1f}s (reading: {reading_delay:.1f}s, typing: {typing_duration:.1f}s) before replying to chat {chat_id}."
                )

                # Phase 1: Reading/thinking pause
                if reading_delay > 0:
                    await asyncio.sleep(reading_delay)

                # Abort if emergency stop was triggered during reading delay
                if self.safety.is_emergency_stopped:
                    logger.warning(f"Reply to chat {chat_id} aborted: emergency stop triggered during delay.")
                    return False

                # Phase 2: Active typing indicator with realistic rhythm & pause bursts
                try:
                    if hasattr(self._client, "action") and callable(self._client.action):
                        if typing_duration >= 3.5:
                            burst1 = round(typing_duration * 0.5, 1)
                            pause = round(random.uniform(0.8, 1.4), 1)
                            burst2 = max(0.8, round(typing_duration - burst1, 1))

                            act1 = self._client.action(chat_id, "typing")
                            if hasattr(act1, "__aenter__"):
                                async with act1:
                                    await asyncio.sleep(burst1)
                            else:
                                if asyncio.iscoroutine(act1):
                                    act1.close()
                                await asyncio.sleep(burst1)

                            # Brief hesitation/thinking pause where user stops typing
                            await asyncio.sleep(pause)

                            act2 = self._client.action(chat_id, "typing")
                            if hasattr(act2, "__aenter__"):
                                async with act2:
                                    await asyncio.sleep(burst2)
                            else:
                                if asyncio.iscoroutine(act2):
                                    act2.close()
                                await asyncio.sleep(burst2)
                        else:
                            act = self._client.action(chat_id, "typing")
                            if hasattr(act, "__aenter__"):
                                async with act:
                                    await asyncio.sleep(typing_duration)
                            else:
                                if asyncio.iscoroutine(act):
                                    act.close()
                                await asyncio.sleep(typing_duration)
                    else:
                        await asyncio.sleep(typing_duration)
                except Exception:
                    await asyncio.sleep(typing_duration)

            # Send first message part
            # In groups, swipe-to-reply directly if mentioned; in DMs always reply_to; otherwise chime into stream
            actual_reply_to = reply_to_msg_id if (chat_id > 0 or is_mention) else None
            first_sent = await self._client.send_message(chat_id, first_part, reply_to=actual_reply_to)
            self.safety.mark_reply_sent(chat_id)
            self.safety.record_burst_send(chat_id)
            self._last_sent_reply_by_chat[chat_id] = first_part
            if chat_id not in self._recent_replies_history:
                self._recent_replies_history[chat_id] = []
            self._recent_replies_history[chat_id].append(first_part)
            while len(self._recent_replies_history[chat_id]) > 12:
                self._recent_replies_history[chat_id].pop(0)
            self._save_recent_replies_history()
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
            )
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
                self._last_sent_reply_by_chat[chat_id] = edit_fix_original
                if self._recent_replies_history.get(chat_id):
                    self._recent_replies_history[chat_id][-1] = edit_fix_original
                await asyncio.sleep(random.uniform(1.5, 3.0))
                try:
                    await self._client.edit_message(chat_id, first_msg_id, edit_fix_original)
                    logger.info(f"[SELF EDIT] Edited own message {first_msg_id} in chat {chat_id} to fix the typo.")
                    self.db.record_chat_message(
                        chat_id=chat_id,
                        message_id=first_msg_id,
                        sender_id=None,
                        sender_name=self.generator.prompt_manager.owner_name,
                        text=edit_fix_original,
                        is_outgoing=True,
                    )
                except Exception as e:
                    logger.debug(f"[SELF EDIT] Could not edit message {first_msg_id}: {e}")

            # Spontaneous Delayed Follow-Ups (10–20s later for 1–3 word single-message replies)
            followup_enabled = self.db.get_state("spontaneous_followup_enabled", "1") == "1"
            if (
                followup_enabled
                and len(msg_parts) == 1
                and edit_fix_original is None
                and not is_mention
                and len(first_part.split()) <= 3
                and self.current_mode == "restricted_auto"
            ):
                if random.random() < 0.18:
                    asyncio.create_task(
                        self._schedule_spontaneous_followup(
                            chat_id=chat_id,
                            sent_text=first_part,
                        )
                    )

            # Send subsequent message parts (2 or 3) with short natural typing pause
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

                try:
                    if hasattr(self._client, "action") and callable(self._client.action):
                        act = self._client.action(chat_id, "typing")
                        if hasattr(act, "__aenter__"):
                            async with act:
                                await asyncio.sleep(followup_typing)
                        else:
                            if asyncio.iscoroutine(act):
                                act.close()
                            await asyncio.sleep(followup_typing)
                    else:
                        await asyncio.sleep(followup_typing)
                except Exception:
                    await asyncio.sleep(followup_typing)

                sub_sent = await self._client.send_message(chat_id, part)
                self.safety.mark_reply_sent(chat_id)
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
                )
                logger.info(f"Successfully sent reply part {idx}/{len(msg_parts)} to chat {chat_id}.")

            return True
        except Exception as e:
            # Check for Telegram FloodWaitError
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
            )
            return False
