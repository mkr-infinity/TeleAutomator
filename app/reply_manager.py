"""Reply orchestration handling Draft, Approval, and Restricted Automation modes."""

from __future__ import annotations

import asyncio
import datetime
import random
import re
import shutil
import time
from typing import Any, Optional

from app.ai.reply_generator import ReplyGenerator
from app.config import AppConfig
from app.logger import setup_logger
from app.privacy_manager import PrivacyManager
from app.safety_manager import SafetyManager
from app.storage.database import Database

logger = setup_logger(__name__)


def _parse_time_str(val: str) -> Optional[str]:
    """Parse and normalize HH:MM string."""
    m = re.match(r"^(\d{1,2}):(\d{2})$", val.strip())
    if not m:
        return None
    h, mins = int(m.group(1)), int(m.group(2))
    if 0 <= h <= 23 and 0 <= mins <= 59:
        return f"{h:02d}:{mins:02d}"
    return None


class ReplyManager:
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
        self.typing_delay: float = getattr(config, "typing_delay_seconds", 2.0)
        self.min_delay: float = getattr(config, "min_delay_seconds", 5.0)
        self.max_delay: float = getattr(config, "max_delay_seconds", 60.0)
        self._last_reaction_time: float = 0.0
        self._last_sent_reply_by_chat: dict[int, str] = {}
        self._last_group_activity: dict[int, float] = {}
        self._next_reaction_cooldown: float = random.uniform(
            float(self.db.get_state("reaction_min_cooldown_seconds", str(getattr(config, "reaction_min_cooldown_seconds", 3.0)))),
            float(self.db.get_state("reaction_max_cooldown_seconds", str(getattr(config, "reaction_max_cooldown_seconds", 9.0)))),
        )

        # Restore saved style if stored in DB
        saved_style = self.db.get_state("reply_style")
        if saved_style:
            self.generator.set_style(saved_style)

        # Restore saved language if stored in DB
        default_lang = getattr(config, "default_chat_language", "dynamic")
        saved_lang = self.db.get_state("chat_language", default_lang)
        if saved_lang:
            self.generator.set_language(saved_lang)

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
        # Sanitize incoming text before passing to generator
        clean_text = self.privacy.sanitize_text(text)

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
                permanent_context_str = "\n\n".join(perm_parts) if perm_parts else None

                # Check for per-chat style/persona override; fallback to global default
                chat_style = self.db.get_state(f"chat_style_{chat_id}")
                draft = self.generator.generate(
                    sender_name=sender_name,
                    incoming_text=clean_text,
                    conversation_history=conversation_history,
                    style_override=chat_style or None,
                    permanent_context=permanent_context_str,
                    is_group=(chat_id < 0),
                )
            except Exception as e:
                logger.error(f"Failed to generate AI reply for chat {chat_id}: {e}")
                if is_mention:
                    # For mentions, NEVER drop or send error to Saved Messages! Use human fallback reply
                    logger.info(f"[MENTION FALLBACK] Using natural human fallback for mention in chat {chat_id}.")
                    draft = self.generator.prompt_manager.get_fallback_reply(clean_text)
                else:
                    # Strictly send issue/error to Saved Messages only; never leak to peer chat or group
                    await self._notify_issue_to_saved_messages(
                        chat_id=chat_id,
                        chat_title=chat_title,
                        sender_name=sender_name,
                        error_msg=f"AI generation failed: {e}",
                        incoming_text=clean_text,
                    )
                    return

        if not draft or draft.strip().lower() in ("none", "none.", "null", "null.", "undefined", ""):
            if is_mention:
                logger.info(f"[MENTION FALLBACK] Empty or None AI draft, using natural human fallback for mention in chat {chat_id}.")
                draft = self.generator.prompt_manager.get_fallback_reply(clean_text)
            else:
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
                if "cooldown" in reason.lower():
                    # NEVER skip mention messages: schedule deferred reply after cooldown!
                    if is_mention:
                        import re
                        m = re.search(r"\((\d+)s remaining\)", reason)
                        wait_secs = float(m.group(1)) if m else 5.0
                        logger.info(
                            f"[MENTION QUEUED] Cooldown active for chat {chat_id} ({wait_secs}s). "
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

            sent = await self._send_reply(chat_id, message_id, draft, adaptive_delay=True)
            if sent:
                asyncio.create_task(self.check_daily_quota_warning())

    async def check_daily_quota_warning(self) -> None:
        """Check if 24-hour token consumption exceeded user-defined threshold and alert Saved Messages."""
        if not self._client or not self.db:
            return
        enabled = self.db.get_state("quota_alert_enabled", "1") == "1"
        if not enabled:
            return
        try:
            threshold = int(self.db.get_state("quota_threshold_tokens", "100000"))
            daily_tokens = self.db.get_daily_token_usage()
            if daily_tokens >= threshold:
                last_alert = float(self.db.get_state("last_quota_alert_timestamp", "0"))
                now = time.time()
                # Alert once per 24 hours
                if (now - last_alert) >= 86400:
                    self.db.set_state("last_quota_alert_timestamp", str(now))
                    rem = max(0, 100_000_000 - daily_tokens)
                    alert_text = (
                        f"⚠️ *Daily Token Quota Threshold Alert:*\n\n"
                        f"• 24h Consumed: *{daily_tokens:,}* tokens\n"
                        f"• Warning Threshold: `{threshold:,}` tokens\n"
                        f"• Remaining Free Pool: *{rem:,}* tokens\n\n"
                        f"_Adjust threshold via `/quotathreshold <tokens>` or toggle via `/quotaalert off`._"
                    )
                    await self._client.send_message("me", alert_text, parse_mode="md")
                    logger.info(f"[QUOTA ALERT] Sent 24h threshold warning ({daily_tokens:,} tokens) to Saved Messages.")
        except Exception as e:
            logger.debug(f"Could not execute quota warning check: {e}")

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
                if "cooldown" in reason.lower():
                    import re
                    m = re.search(r"\((\d+)s remaining\)", reason)
                    retry_wait = float(m.group(1)) if m else 3.0
                    await asyncio.sleep(retry_wait + 1.0)
                    if self.safety.is_emergency_stopped:
                        return

            sent = await self._send_reply(chat_id, message_id, draft, adaptive_delay=True)
            if sent:
                asyncio.create_task(self.check_daily_quota_warning())
            logger.info(f"[DEFERRED MENTION SENT] Successfully replied to mention in chat {chat_id} after cooldown.")
        except Exception as e:
            logger.error(f"Error in deferred mention reply: {e}")

    async def _notify_approval_needed(
        self,
        approval_id: int,
        chat_id: int,
        chat_title: str,
        sender_name: str,
        incoming_text: str,
        draft_text: str,
    ) -> None:
        """Notify the user in their private Saved Messages control channel."""
        if not self._client:
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
            # 'me' in Telethon resolves to the user's private Saved Messages
            await self._client.send_message("me", notification, parse_mode="md")
        except Exception as e:
            logger.error(f"Failed to send approval notification to Saved Messages: {e}")

    async def _notify_issue_to_saved_messages(
        self,
        chat_id: int,
        chat_title: str,
        sender_name: str,
        error_msg: str,
        incoming_text: str = "",
    ) -> None:
        """Send internal error/issue alerts exclusively to user's private Saved Messages."""
        if not self._client:
            return

        # Suppress alerts if automation is paused, emergency stopped, in quiet hours, or in draft mode
        if self.safety.is_emergency_stopped or self.safety.get_remaining_pause_seconds() > 0:
            return
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
                f"⚠️ *TeleAutomator Alert (Never Sent to Chat)*\n"
                f"• *Destination:* {target_name} (`{chat_id}`){sender}\n"
                f"• *Issue/Error:* `{error_msg}`{incoming_snippet}\n"
                f"• *Safety Status:* Suppressed safely. Zero error text or fallbacks sent to recipient."
            )
            await self._client.send_message("me", alert, parse_mode="md")
        except Exception as e:
            logger.error(f"Failed to deliver issue alert to Saved Messages: {e}")

    def _parse_duration(self, raw: str) -> Optional[float]:
        """Parse duration strings like '2h', '30m', '1d', or '2' (hours)."""
        import re
        s = raw.strip().lower()
        if not s:
            return None
        try:
            if s.endswith(("m", "min", "mins")):
                num = re.sub(r"[^\d.]", "", s)
                return float(num) * 60
            elif s.endswith(("h", "hr", "hrs", "hour", "hours")):
                num = re.sub(r"[^\d.]", "", s)
                return float(num) * 3600
            elif s.endswith(("d", "day", "days")):
                num = re.sub(r"[^\d.]", "", s)
                return float(num) * 86400
            elif re.match(r"^\d+(?:\.\d+)?$", s):
                # Default bare number to hours
                return float(s) * 3600
        except ValueError:
            pass
        return None

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

    async def handle_control_command(self, text: str) -> Optional[str]:
        """Handle control commands sent to Saved Messages (e.g., /approve, /reject, /status, /pause, /setprompt)."""
        cmd_parts = text.strip().split()
        if not cmd_parts:
            return None

        cmd = cmd_parts[0].lower()

        if cmd in ("/help", "/start"):
            return (
                "🤖 *TeleAutomator Commands:*\n\n"
                "*Core Controls:*\n"
                "• `/status` - Health, active identity, pause timer, & mode\n"
                "• `/mode <draft|approval|auto>` - Switch automation mode on the fly\n"
                "• `/style <casual|concise|formal|humorous>` - Change AI reply style\n"
                "• `/lang <dynamic|english|hindi|...>` - Chat language selection\n"
                "• `/auto on` / `/auto off` - Authorize or revoke automated replies\n"
                "• `/pause <time>` - Snooze replies (e.g. `/pause 2h`, `/pause 30m`)\n"
                "• `/resume` - Resume operations (clears pause & stop)\n"
                "• `/stop` - Emergency stop switch (halts all replies)\n\n"
                "*Reactions & Cooldowns:*\n"
                "• `/reaction on` / `/reaction off` - Enable or disable auto-reactions\n"
                "• `/reactioncooldown <min> <max>` - Set random reaction cooldown (e.g. `3 9` seconds)\n"
                "• `/chatcooldown <min> <max>` - Custom per-chat reply cooldown (e.g. `5 60`)\n"
                "• `/globalcooldown <min> <max>` - Custom global reply cooldown (e.g. `5 60`)\n\n"
                "*Quiet Hours (Sleep Schedule):*\n"
                "• `/quiethours on [start] [end]` - Turn ON sleep schedule (e.g. `/quiethours on 23:00 07:00`)\n"
                "• `/quiethours off` - Turn OFF sleep schedule\n"
                "• `/quiethours` - Check current quiet hours status\n\n"
                "*AI Tuning, Usage & Personas:*\n"
                "• `/aiconfig` - View provider, base URL, temperature, and reasoning parameters\n"
                "• `/setai` - Custom AI dashboard & 1-step setup (e.g. `/setai mercury <key>`)\n"
                "• `/apikey <key>` - Set/update AI API key directly from Telegram\n"
                "• `/usage` - Live token tracker & remaining free 100M quota\n"
                "• `/checkmodels` - Ping and verify candidate models in real time\n"
                "• `/reasoning <low|medium|high|off>` - Adjust discrete reasoning effort\n"
                "• `/temp <0.0-1.0>` - Adjust AI randomness/creativity\n"
                "• `/maxtokens <tokens>` - Maximum output tokens per response\n"
                "• `/model <name>` - Set model name or comma-separated fallback chain\n"
                "• `/baseurl <url>` - Set custom API endpoint/base URL\n"
                "• `/provider <name>` - Switch AI engine (custom, gemini, openai, nvidia, local)\n"
                "• `/style [chat_id] <style>` - Global or per-chat persona override\n"
                "• `/styles` - List all per-chat persona overrides\n"
                "• `/quotathreshold <tokens>` - Set daily token warning limit\n"
                "• `/quotaalert <on|off>` - Toggle daily quota warning alerts\n\n"
                "*Custom Keyword Auto-Replies:*\n"
                "• `/addrule <word> => <reply>` - Auto-reply when a word is detected\n"
                "• `/delrule <word>` - Delete keyword trigger\n"
                "• `/rules` - List all active custom keyword triggers\n\n"
                "*Chat & Group Management:*\n"
                "• `/chats` - View all allowlisted private contacts & groups\n"
                "• `/allowchat <id>` - Allow a contact or group directly from Telegram\n"
                "• `/removechat <id>` - Remove chat from allowlist\n"
                "• `/blockchat <id>` - Block a chat ID\n"
                "• `/mentiononly on|off` - Group safety: reply only when mentioned/replied to\n"
                "• `/contextttl <hours>` - Set context auto-aging window (e.g. `/contextttl 2.0`)\n"
                "• `/clearcontext <chat_id>` - Reset cached AI context for a chat (never deletes Telegram messages)\n"
                "• `/syncpins [chat_id]` - Sync pinned message(s) into permanent chat context\n"
                "• `/setcontext <chat_id> <notes>` - Save permanent notes/guidelines for a group\n"
                "• `/showcontext <chat_id>` - View permanent background context for a group\n"
                "• `/delcontext <chat_id>` - Delete permanent context for a group\n"
                "• `/backup` - Create database snapshot & send directly to Saved Messages\n\n"
                "*Approvals & Drafts:*\n"
                "• `/pending` - List drafts waiting for review\n"
                "• `/approve <id>` - Approve & send pending draft\n"
                "• `/reject <id>` - Discard pending draft\n\n"
                "*Identity & Persona:*\n"
                "• `/name <name>` - Set your display name for AI persona\n"
                "• `/prompt` - View active system prompt\n"
                "• `/setprompt <text>` - Update system prompt on the fly\n"
                "• `/model <name>` - Switch AI model (e.g. `gemini-2.5-flash-lite`)\n"
                "• `/baseurl <url>` - Set custom base URL for NVIDIA/Groq/Ollama\n"
                "• `/provider <gemini|openai|nvidia|custom>` - Switch AI backend\n"
                "• `/chatty <0-100>` - Set group banter participation %"
            )

        if cmd in ("/rules", "/listrules"):
            rules = self.db.list_keyword_rules()
            if not rules:
                return "📋 *Custom Keyword Triggers:* (none configured)\nUse `/addrule <word> => <reply>` to create one!"
            lines = ["📋 *Custom Keyword Triggers:*"]
            for r in rules:
                lines.append(f"• If text contains *'{r['keyword']}'* ➜ \"{r['reply']}\"")
            lines.append("\n_Use `/delrule <word>` to remove a trigger._")
            return "\n".join(lines)

        if cmd == "/addrule":
            raw_args = text[len(cmd_parts[0]):].strip()
            # Support formats: <keyword> => <reply> or <keyword> : <reply>
            sep = "=>" if "=>" in raw_args else (":" if ":" in raw_args else None)
            if not sep:
                return (
                    "Usage: `/addrule <keyword> => <reply>`\n"
                    "Example: `/addrule pricing => We are updating our packages, will send details soon!`"
                )
            kw, reply = raw_args.split(sep, 1)
            kw, reply = kw.strip(), reply.strip()
            if not kw or not reply:
                return "Error: Both keyword and reply must be non-empty."
            self.db.add_keyword_rule(kw, reply)
            return f"✅ Keyword rule added!\n• When message contains: *'{kw}'*\n• Client will reply: \"{reply}\""

        if cmd == "/delrule":
            if len(cmd_parts) < 2:
                return "Usage: `/delrule <keyword>`"
            kw = " ".join(cmd_parts[1:]).strip()
            ok = self.db.delete_keyword_rule(kw)
            if ok:
                return f"🗑️ Keyword trigger rule for *'{kw}'* has been deleted."
            return f"Rule for *'{kw}'* not found."

        if cmd in ("/chats", "/allowlist", "/listchats"):
            chats_df = await self.get_allowed_chats_dataframe()
            mention_only = self.db.get_state("group_mention_only", "0") == "1"
            filter_str = "@Mentions / Replies Only" if mention_only else "Smart Human Engagement (Relevant Topics & 20m Idle)"
            return (
                f"📋 *Active Allowlisted Chats (DataFrame):*\n"
                f"{chats_df}\n\n"
                f"• *Group Filter:* {filter_str}\n"
                f"_Use `/allowchat <id>` to add, or `/removechat <id>` to remove._"
            )

        if cmd == "/allowchat":
            if len(cmd_parts) < 2:
                return "Usage: `/allowchat <chat_id>` (e.g. `/allowchat 123456789` or `/allowchat -1001234567890`)"
            try:
                cid = int(cmd_parts[1])
                self.privacy.allow_chat(cid)
                target = "Group" if cid < 0 else "Private contact"
                return f"✅ {target} `{cid}` has been added to the allowlist!"
            except ValueError:
                return "Error: Chat ID must be an integer."

        if cmd == "/removechat":
            if len(cmd_parts) < 2:
                return "Usage: `/removechat <chat_id>`"
            try:
                cid = int(cmd_parts[1])
                self.privacy.remove_chat(cid)
                return f"🗑️ Chat `{cid}` removed from allowlist."
            except ValueError:
                return "Error: Chat ID must be an integer."

        if cmd == "/blockchat":
            if len(cmd_parts) < 2:
                return "Usage: `/blockchat <chat_id>`"
            try:
                cid = int(cmd_parts[1])
                self.privacy.block_chat(cid)
                return f"🚫 Chat `{cid}` is now blocked."
            except ValueError:
                return "Error: Chat ID must be an integer."

        if cmd in ("/mentiononly", "/mentions"):
            if len(cmd_parts) < 2 or cmd_parts[1].lower() not in ("on", "off"):
                current = "ON (strict: only replies when mentioned/replied to)" if self.db.get_state("group_mention_only", "0") == "1" else "OFF (natural human engagement: replies/reacts to relevant topics, mentions, or after 20m idle)"
                return f"Group mention filter is currently: *{current}*\nUsage: `/mentiononly on` or `/mentiononly off`"
            val = "1" if cmd_parts[1].lower() == "on" else "0"
            self.db.set_state("group_mention_only", val)
            if val == "1":
                return "🛡️ Group automation: *Mentions Only* activated. The client will only reply in groups when someone mentions your @username or replies directly to your message."
            else:
                return "🌟 Group automation: *Smart Human Engagement* activated. The client will naturally reply or react to relevant group topics, answer mentions, and chime in after 20 minutes of idle time."

        if cmd in ("/mode", "/setmode"):
            if len(cmd_parts) < 2:
                curr = self.current_mode
                return (
                    f"⚙️ *Current Reply Mode:* `{curr}`\n\n"
                    f"*Available Modes:*\n"
                    f"• `/mode draft` - Suggests drafts in terminal/logs; NEVER sends.\n"
                    f"• `/mode approval` - Sends drafts to Saved Messages for `/approve <id>`.\n"
                    f"• `/mode auto` - Directly replies to allowlisted chats without manual approval."
                )
            target = cmd_parts[1].lower().strip()
            if target in ("draft", "draft_only", "drafts"):
                self.set_mode("draft")
                return "📝 Mode switched to *Draft Only*. Replies will be generated and logged, but never sent to recipients."
            elif target in ("approval", "pending", "review"):
                self.set_mode("approval")
                return "📋 Mode switched to *Approval Required*. Every draft will be sent to your Saved Messages for review."
            elif target in ("auto", "restricted_auto", "automatic"):
                self.set_mode("restricted_auto")
                self.safety.set_auto_authorization(True)
                return "⚡ Mode switched to *Restricted Auto*. Allowlisted chats will receive automated replies directly."
            else:
                return "Invalid mode. Use `/mode draft`, `/mode approval`, or `/mode auto`."

        if cmd in ("/style", "/setstyle"):
            if len(cmd_parts) < 2:
                curr = self.generator.style
                return (
                    f"🎨 *Current AI Style:* `{curr}`\n\n"
                    f"*Available Styles:*\n"
                    f"• `/style casual` - Friendly, relaxed texting tone.\n"
                    f"• `/style concise` - Minimal, brief, straight to the point.\n"
                    f"• `/style formal` - Polite, structured, professional.\n"
                    f"• `/style humorous` - Witty, playful banter.\n\n"
                    f"*Per-Chat Persona Override:*\n"
                    f"• `/style <chat_id> <style>` - Assign custom style to specific chat (e.g. `/style 123456 formal`)\n"
                    f"• `/style <chat_id> default` - Reset chat to default global persona\n"
                    f"• `/styles` - View all active per-chat style overrides"
                )

            if len(cmd_parts) >= 3:
                try:
                    target_cid = int(cmd_parts[1])
                except ValueError:
                    return "Error: First argument must be an integer chat ID. Usage: `/style <chat_id> <style>`"
                target_style = cmd_parts[2].lower().strip()
                if target_style in ("default", "clear", "reset", "none"):
                    self.db.set_state(f"chat_style_{target_cid}", "")
                    return f"🔄 Chat `{target_cid}` reset to default global style (*{self.generator.style}*)."
                if target_style not in ("casual", "concise", "formal", "humorous"):
                    return "Invalid style. Available: `casual`, `concise`, `formal`, `humorous`, `default`."
                self.db.set_state(f"chat_style_{target_cid}", target_style)
                return f"🎨 Chat `{target_cid}` custom AI persona set to *{target_style}*."

            target_style = cmd_parts[1].lower().strip()
            ok = self.generator.set_style(target_style)
            if ok:
                self.db.set_state("reply_style", target_style)
                return f"🎨 Global AI response style switched to *{target_style}*."
            return "Invalid style. Available: `/style casual`, `/style concise`, `/style formal`, `/style humorous`."

        if cmd == "/styles":
            priv, grps = self.privacy.get_all_allowed_chats()
            all_ids = sorted(list(priv | grps))
            lines = [f"🎨 *AI Styles & Personas (Global Default: `{self.generator.style}`):*"]
            overrides_found = 0
            for cid in all_ids:
                s = self.db.get_state(f"chat_style_{cid}")
                if s:
                    overrides_found += 1
                    meta = self.db.get_chat_metadata(cid) or {}
                    name = meta.get("title") or f"Chat {cid}"
                    lines.append(f"• {name} (`{cid}`): *{s}*")
            if not overrides_found:
                lines.append("• _All chats currently use the default global persona._")
            lines.append("\n_Customize per chat with `/style <chat_id> <style>` or `/style <chat_id> default`._")
            return "\n".join(lines)

        if cmd in ("/contextttl", "/aging"):
            if len(cmd_parts) < 2:
                curr = self.db.get_state("context_ttl_hours", "2.0")
                return (
                    f"⏳ *Conversation Context Auto-Aging:* `{curr} hours`\n"
                    "After this period of inactivity, older conversation context expires so the AI starts fresh.\n"
                    "Usage: `/contextttl <hours>` (e.g. `/contextttl 2.0`)"
                )
            try:
                val = max(0.1, float(cmd_parts[1]))
                self.db.set_state("context_ttl_hours", str(val))
                return f"⏳ Context aging window set to *{val} hours*. Messages older than this will expire from AI prompt memory."
            except ValueError:
                return "Error: Hours must be a positive number."

        if cmd in ("/clearcontext", "/resetcontext"):
            if len(cmd_parts) < 2:
                return (
                    "Usage: `/clearcontext <chat_id>`\n"
                    "_Safely clears local AI context cache for the chat so the next reply starts fresh._\n"
                    "_CRITICAL SAFETY: This NEVER deletes any Telegram messages._"
                )
            try:
                target_cid = int(cmd_parts[1])
                count = self.db.clear_chat_context(target_cid)
                return (
                    f"🧹 Cleared {count} cached context messages for chat `{target_cid}`.\n"
                    "The AI will start fresh on the next message without referencing older context.\n"
                    "_(Zero Telegram messages were touched or deleted)._"
                )
            except ValueError:
                return "Error: Chat ID must be an integer."

        if cmd in ("/syncpin", "/syncpins"):
            if len(cmd_parts) >= 2:
                try:
                    target_cid = int(cmd_parts[1])
                    pin_res = await self.sync_pinned_context_from_telegram(target_cid)
                    if pin_res:
                        preview = pin_res[:200] + ("..." if len(pin_res) > 200 else "")
                        return f"📌 *Synced pinned context for chat `{target_cid}`:*\n_{preview}_\n\nThis is saved permanently and will never be deleted."
                    return f"ℹ️ No pinned messages found or accessible for chat `{target_cid}`."
                except ValueError:
                    return "Error: Chat ID must be an integer."
            groups = list(self.privacy.allowed_groups)
            if not groups:
                return "No allowlisted groups found. Usage: `/syncpins <chat_id>`"
            synced_count = 0
            for gid in groups:
                res = await self.sync_pinned_context_from_telegram(gid)
                if res:
                    synced_count += 1
            return f"📌 Synced pinned messages for {synced_count}/{len(groups)} allowlisted groups into permanent context."

        if cmd == "/setcontext":
            if len(cmd_parts) < 3:
                return (
                    "Usage: `/setcontext <chat_id> <important details / rules>`\n"
                    "Example: `/setcontext -1001234567890 Solana trading group, focus on meme coins, keep replies brief.`\n"
                    "_Permanently saves chat context and guidelines so the AI never replies with senseless answers._"
                )
            try:
                target_cid = int(cmd_parts[1])
                notes_text = " ".join(cmd_parts[2:]).strip()
                self.db.set_permanent_context(target_cid, notes=notes_text)
                return f"📌 Permanent context saved for chat `{target_cid}`:\n_{notes_text}_\n\nThis will be remembered permanently across all conversations."
            except ValueError:
                return "Error: Chat ID must be an integer."

        if cmd == "/showcontext":
            if len(cmd_parts) < 2:
                return "Usage: `/showcontext <chat_id>`"
            try:
                target_cid = int(cmd_parts[1])
                ctx = self.db.get_permanent_context(target_cid)
                pinned = ctx.get("pinned_text") or "(No pinned message cached)"
                notes = ctx.get("notes") or "(No custom notes set)"
                return (
                    f"📌 *Permanent Context for Chat `{target_cid}`:*\n\n"
                    f"*Pinned Info / Rules:*\n{pinned}\n\n"
                    f"*Custom Notes:*\n{notes}\n\n"
                    f"_Use `/setcontext {target_cid} <notes>` to update notes, or `/syncpin {target_cid}` to refresh pins._"
                )
            except ValueError:
                return "Error: Chat ID must be an integer."

        if cmd == "/delcontext":
            if len(cmd_parts) < 2:
                return "Usage: `/delcontext <chat_id>`"
            try:
                target_cid = int(cmd_parts[1])
                ok = self.db.delete_permanent_context(target_cid)
                if ok:
                    return f"🗑️ Permanent context for chat `{target_cid}` has been removed."
                return f"No permanent context found for chat `{target_cid}`."
            except ValueError:
                return "Error: Chat ID must be an integer."

        if cmd in ("/backup", "/exportdb"):
            db_path = getattr(self.db, "db_path", None)
            if not db_path or not db_path.exists():
                return "❌ Database file not found."
            backup_dir = db_path.parent / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = backup_dir / f"teleautomator_backup_{ts}.db"
            try:
                with self.db._get_connection() as conn:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                shutil.copy2(db_path, backup_file)
                if self._client:
                    await self._client.send_file(
                        "me",
                        str(backup_file),
                        caption=f"📦 *TeleAutomator Database Backup*\n_Created:_ `{ts}`\n_Contains:_ Permanent contexts, rules, and AI configurations.",
                    )
                    return f"✅ Database backup `{backup_file.name}` created and sent directly to your Saved Messages!"
                return f"✅ Database backup saved locally to `{backup_file}`."
            except Exception as e:
                logger.error(f"Backup failed: {e}")
                return f"❌ Backup failed: {e}"

        if cmd in ("/usage", "/tokens", "/quota"):
            stats = self.db.get_token_usage_stats()
            reqs = stats["request_count"]
            tot_tokens = stats["total_tokens"]
            p_tokens = stats["total_prompt"]
            c_tokens = stats["total_completion"]
            FREE_POOL = 100_000_000
            rem_tokens = max(0, FREE_POOL - tot_tokens)
            used_pct = (tot_tokens / FREE_POOL) * 100

            daily_tokens = self.db.get_daily_token_usage()
            thresh = int(self.db.get_state("quota_threshold_tokens", "100000"))
            alert_on = self.db.get_state("quota_alert_enabled", "1") == "1"
            alert_status = f"ON (alert at {thresh:,} tokens)" if alert_on else "OFF"

            model_lines = []
            for bm in stats["by_model"]:
                model_lines.append(f"• `{bm['model']}`: {bm['tokens']:,} tokens ({bm['calls']} requests)")
            by_model_str = "\n".join(model_lines) if model_lines else "• _No API requests logged yet._"

            return (
                f"📊 *Inception Labs / AI Token Tracker:*\n\n"
                f"• Total AI Requests: `{reqs:,}`\n"
                f"• Total Tokens Used: *{tot_tokens:,}* / 100,000,000 ({used_pct:.4f}%)\n"
                f"• 24h Daily Consumption: *{daily_tokens:,}* tokens (Alert: `{alert_status}`)\n"
                f"• Prompt Tokens: `{p_tokens:,}`\n"
                f"• Completion Tokens: `{c_tokens:,}`\n"
                f"• Remaining Free Quota: *{rem_tokens:,}* tokens\n\n"
                f"*Breakdown by Model:*\n{by_model_str}"
            )

        if cmd in ("/quotathreshold", "/threshold"):
            if len(cmd_parts) < 2:
                curr = self.db.get_state("quota_threshold_tokens", "100000")
                return f"⚠️ *Daily Quota Warning Threshold:* `{int(curr):,} tokens`\nUsage: `/quotathreshold <tokens>` (e.g. `/quotathreshold 150000`)"
            try:
                val = max(1000, int(cmd_parts[1]))
                self.db.set_state("quota_threshold_tokens", str(val))
                return f"⚠️ Daily quota warning threshold set to *{val:,} tokens*."
            except ValueError:
                return "Error: Threshold must be a valid integer number of tokens."

        if cmd in ("/quotaalert", "/thresholdalert"):
            if len(cmd_parts) < 2 or cmd_parts[1].lower() not in ("on", "off"):
                curr = "ON" if self.db.get_state("quota_alert_enabled", "1") == "1" else "OFF"
                return f"Daily quota warning alerts are currently: *{curr}*\nUsage: `/quotaalert on` or `/quotaalert off`"
            val = "1" if cmd_parts[1].lower() == "on" else "0"
            self.db.set_state("quota_alert_enabled", val)
            status_str = "ENABLED" if val == "1" else "DISABLED"
            return f"⚠️ Daily quota warning alerts are now *{status_str}*."

        if cmd in ("/reasoning", "/effort"):
            if len(cmd_parts) < 2:
                curr = self.db.get_state("ai_reasoning_effort", "low")
                return (
                    f"🧠 *Current Reasoning Effort:* `{curr}`\n\n"
                    f"*Options:*\n"
                    f"• `/reasoning low` - Ultra-fast discrete diffusion generation (Default)\n"
                    f"• `/reasoning medium` - Balanced reasoning depth\n"
                    f"• `/reasoning high` - In-depth logical analysis\n"
                    f"• `/reasoning off` - Disable explicit reasoning effort parameter"
                )
            target = cmd_parts[1].lower().strip()
            if target not in ("low", "medium", "high", "off", "none"):
                return "Invalid reasoning effort. Choose `low`, `medium`, `high`, or `off`."
            self.db.set_state("ai_reasoning_effort", target)
            if hasattr(self.generator.provider, "reasoning_effort"):
                self.generator.provider.reasoning_effort = target
            return f"🧠 AI reasoning effort set to *{target}*."

        if cmd in ("/temp", "/temperature"):
            if len(cmd_parts) < 2:
                curr = self.db.get_state("ai_temperature", "0.6")
                return f"🌡️ *Current AI Temperature:* `{curr}`\nUsage: `/temp <0.0 - 1.0>` (e.g. `/temp 0.7`)"
            try:
                val = max(0.0, min(1.0, float(cmd_parts[1])))
                self.db.set_state("ai_temperature", str(val))
                if hasattr(self.generator.provider, "temperature"):
                    self.generator.provider.temperature = val
                return f"🌡️ AI temperature set to *{val}*."
            except ValueError:
                return "Error: Temperature must be a number between 0.0 and 1.0."

        if cmd in ("/maxtokens", "/maxoutput"):
            if len(cmd_parts) < 2:
                curr = self.db.get_state("ai_max_tokens", "200")
                return f"📝 *Current Max Output Tokens:* `{curr}`\nUsage: `/maxtokens <tokens>` (e.g. `/maxtokens 250`)"
            try:
                val = max(10, int(cmd_parts[1]))
                self.db.set_state("ai_max_tokens", str(val))
                if hasattr(self.generator.provider, "max_tokens"):
                    self.generator.provider.max_tokens = val
                return f"📝 AI max output tokens set to *{val}*."
            except ValueError:
                return "Error: Max tokens must be a valid integer."

        if cmd in ("/aiconfig", "/aisettings"):
            prov = self.db.get_state("ai_provider", self.config.ai_provider)
            mod = self.db.get_state("ai_model", self.config.ai_model or "mercury-3")
            url = self.db.get_state("ai_base_url", self.config.ai_base_url or "https://api.inceptionlabs.ai/v1")
            eff = self.db.get_state("ai_reasoning_effort", "low")
            temp = self.db.get_state("ai_temperature", "0.6")
            mtok = self.db.get_state("ai_max_tokens", "200")
            curr_key = self.db.get_state("ai_api_key", self.config.ai_api_key or "")
            masked_key = f"`{curr_key[:7]}...{curr_key[-4:]}`" if len(curr_key) > 11 else ("`Configured`" if curr_key else "`Missing`")
            cands = []
            if hasattr(self.generator.provider, "get_candidate_models"):
                cands = self.generator.provider.get_candidate_models()
            cand_str = ", ".join(f"`{c}`" for c in cands) if cands else f"`{mod}`"

            return (
                f"🤖 *AI Engine Configuration:*\n\n"
                f"• Provider: `{prov.upper()}`\n"
                f"• Base URL: `{url}`\n"
                f"• Active Model: `{getattr(self.generator.provider, 'model', mod)}`\n"
                f"• Fallback Sequence: {cand_str}\n"
                f"• API Key: {masked_key} (change via `/apikey <key>`)\n"
                f"• Reasoning Effort: `{eff}` (change via `/reasoning <effort>`)\n"
                f"• Temperature: `{temp}` (change via `/temp <0.0-1.0>`)\n"
                f"• Max Output Tokens: `{mtok}` (change via `/maxtokens <tokens>`)\n\n"
                f"_Quick Setup:_ `/setai <provider> <api_key> <endpoint> [model]` or `/setai mercury <key>`\n"
                f"_Send `/checkmodels` to ping and verify candidate models in real-time._"
            )

        if cmd in ("/checkmodels", "/testmodels"):
            if not hasattr(self.generator.provider, "check_working_models"):
                return "Live model verification is supported on OpenAI and Inception Labs custom providers."
            results = self.generator.provider.check_working_models()
            lines = ["🔍 *Model Live Health Check:*"]
            for m, ok, detail in results:
                icon = "✅" if ok else "❌"
                lines.append(f"{icon} `{m}`: {detail}")
            active = getattr(self.generator.provider, "model", "")
            lines.append(f"\n🎯 Active working model set to: *{active}*")
            self.db.set_state("ai_model", active)
            return "\n".join(lines)

        if cmd == "/status":
            auto_status = "AUTHORIZED" if self.safety.is_auto_authorized else "DISABLED"
            stop_status = "ACTIVE" if self.safety.is_emergency_stopped else "NORMAL"
            remaining = self.safety.get_remaining_pause_seconds()
            pause_str = f"PAUSED ({int(remaining // 60)}m left)" if remaining > 0 else "ACTIVE"
            pending_count = len(self.db.list_pending_approvals())
            owner = self.generator.prompt_manager.owner_name
            mode_display = self.current_mode
            style_display = self.generator.style
            lang_display = self.generator.language
            react_enabled = self.db.get_state(
                "reaction_enabled",
                "1" if getattr(self.config, "reaction_enabled", True) else "0"
            ) == "1"
            react_status = "ON" if react_enabled else "OFF"
            max_r = self.db.get_state("reaction_max_per_window", str(getattr(self.config, "reaction_max_per_window", 4)))
            win_m = int(float(self.db.get_state("reaction_window_seconds", str(getattr(self.config, "reaction_window_seconds", 600.0)))) // 60)
            active_prov = self.db.get_state("ai_provider", self.config.ai_provider)
            active_mod = self.db.get_state("ai_model", self.config.ai_model or "default")
            active_url = self.db.get_state("ai_base_url", self.config.ai_base_url or "")
            url_str = f" [Base: {active_url}]" if active_url else ""
            chatty_prob = float(self.db.get_state(
                "chatty_probability",
                str(getattr(self.config, "chatty_probability", 0.15))
            ))
            qh_enabled = self.safety.quiet_hours_enabled
            qh_start, qh_end = self.safety.quiet_hours_window
            is_quiet, _ = self.safety.is_in_quiet_hours()
            qh_desc = f"ON ({qh_start}–{qh_end}, {'Sleeping 💤' if is_quiet else 'Awake ☀️'})" if qh_enabled else "OFF"
            min_r_sec = float(self.db.get_state("reaction_min_cooldown_seconds", str(getattr(self.config, "reaction_min_cooldown_seconds", 3.0))))
            max_r_sec = float(self.db.get_state("reaction_max_cooldown_seconds", str(getattr(self.config, "reaction_max_cooldown_seconds", 9.0))))
            chat_cd_range = f"{int(self.safety.min_chat_cooldown)}s–{int(self.safety.max_chat_cooldown)}s"
            global_cd_range = f"{int(self.safety.min_global_cooldown)}s–{int(self.safety.max_global_cooldown)}s"
            chats_df = await self.get_allowed_chats_dataframe()
            return (
                f"📊 *TeleAutomator v2.0.5 Status:*\n"
                f"• Identity Name: `{owner}`\n"
                f"• Automation: *{pause_str}*\n"
                f"• Reply Mode: `{mode_display}` (change with `/mode <draft|approval|auto>`)\n"
                f"• AI Style: `{style_display}` (change with `/style <casual|concise|formal|humorous>`)\n"
                f"• Language: `{lang_display}` (change with `/lang <dynamic|english|hindi|...>`)\n"
                f"• Reactions: *{react_status}* ({int(min_r_sec)}s–{int(max_r_sec)}s interval, max {max_r} in {win_m}m)\n"
                f"• Quiet Hours: *{qh_desc}* (change with `/quiethours <on|off|start end>`)\n"
                f"• Group Banter: `{int(chatty_prob * 100)}%` (change with `/chatty <0-100>`)\n"
                f"• Cooldowns: Chat=`{chat_cd_range}`, Global=`{global_cd_range}`\n"
                f"• Auto Authorized: *{auto_status}*\n"
                f"• Emergency Stop: *{stop_status}*\n"
                f"• Pending Approvals: `{pending_count}`\n"
                f"• AI Provider: `{active_prov.upper()}` (model=`{active_mod}`{url_str})\n\n"
                f"📋 *Target Chats & Groups (DataFrame):*\n{chats_df}"
            )

        if cmd in ("/lang", "/language", "/setlang"):
            if len(cmd_parts) < 2:
                curr = self.generator.language
                return (
                    f"🌐 *Current Reply Language:* `{curr}`\n\n"
                    f"*Available Options:*\n"
                    f"• `/lang dynamic` - Automatically detects sender's language (English, Hinglish, Hindi, etc.) and replies in the same language.\n"
                    f"• `/lang english` - Forces AI to reply ONLY in English.\n"
                    f"• `/lang hindi` - Forces AI to reply in Hindi / Hinglish.\n"
                    f"• `/lang <language>` - Set to any language (e.g. `/lang spanish`, `/lang french`)"
                )
            target_lang = cmd_parts[1].lower().strip()
            self.generator.set_language(target_lang)
            self.db.set_state("chat_language", target_lang)
            return f"🌐 Chat language set to *{target_lang}*."

        if cmd in ("/reaction", "/reactions"):
            if len(cmd_parts) < 2:
                enabled = self.db.get_state(
                    "reaction_enabled",
                    "1" if getattr(self.config, "reaction_enabled", True) else "0"
                ) == "1"
                status_str = "ON" if enabled else "OFF"
                max_r = self.db.get_state("reaction_max_per_window", str(getattr(self.config, "reaction_max_per_window", 4)))
                win_m = int(float(self.db.get_state("reaction_window_seconds", str(getattr(self.config, "reaction_window_seconds", 600.0)))) // 60)
                return (
                    f"⚡ *Auto-Reactions:* *{status_str}*\n"
                    f"• Rate Limit: Max {max_r} reactions per {win_m} minutes\n\n"
                    f"*Commands:*\n"
                    f"• `/reaction on` - Enable natural reactions\n"
                    f"• `/reaction off` - Disable reactions\n"
                    f"• `/reactioncooldown <max_count> <minutes>` - Customize reaction cooldown (e.g. `/reactioncooldown 4 10`)"
                )
            target = cmd_parts[1].lower().strip()
            if target == "on":
                self.db.set_state("reaction_enabled", "1")
                return "⚡ Auto-reactions *ENABLED*. Natural emoji reactions will be added within cooldown limits."
            elif target == "off":
                self.db.set_state("reaction_enabled", "0")
                return "🔒 Auto-reactions *DISABLED*."
            return "Usage: `/reaction on` or `/reaction off`"

        if cmd in ("/quiethours", "/quiet", "/sleep"):
            if len(cmd_parts) < 2:
                qh_enabled = self.safety.quiet_hours_enabled
                qh_start, qh_end = self.safety.quiet_hours_window
                is_quiet, _ = self.safety.is_in_quiet_hours()
                now_str = datetime.datetime.now().strftime("%H:%M")
                status_title = "ON" if qh_enabled else "OFF (Default)"
                sleep_state = "Sleeping 💤 (Auto-replies & reactions paused)" if is_quiet else "Awake ☀️ (Active)"
                return (
                    f"🌙 *Quiet Hours (Sleep Schedule):* *{status_title}*\n"
                    f"• Schedule: `{qh_start}` to `{qh_end}`\n"
                    f"• Current Local Time: `{now_str}`\n"
                    f"• Current State: *{sleep_state}*\n\n"
                    f"*Commands:*\n"
                    f"• `/quiethours on [start] [end]` - Turn ON (e.g. `/quiethours on 23:00 07:00`)\n"
                    f"• `/quiethours off` - Turn OFF sleep schedule\n"
                    f"• `/quiethours <start> <end>` - Update schedule & enable (e.g. `/quiethours 01:00 08:00`)"
                )

            sub = cmd_parts[1].lower().strip()
            if sub == "off":
                self.safety.set_quiet_hours(False)
                return "☀️ Quiet hours *DISABLED*. Automated replies and reactions are now active 24/7."

            if sub == "on":
                if len(cmd_parts) >= 4:
                    t_start = _parse_time_str(cmd_parts[2])
                    t_end = _parse_time_str(cmd_parts[3])
                    if not t_start or not t_end:
                        return "Error: Times must be in valid 24h format HH:MM (e.g. `23:00 07:00` or `01:00 08:00`)."
                    self.safety.set_quiet_hours(True, t_start, t_end)
                    return f"🌙 Quiet hours *ENABLED* from *{t_start}* to *{t_end}*. Automated replies & reactions will pause during this sleep window."
                else:
                    self.safety.set_quiet_hours(True)
                    s, e = self.safety.quiet_hours_window
                    return f"🌙 Quiet hours *ENABLED* with schedule *{s}* to *{e}*. Automated replies & reactions will pause during sleep hours."

            # Direct schedule update: e.g. /quiethours 23:00 07:00 or /quiethours set 23:00 07:00
            time_args = cmd_parts[2:] if sub == "set" else cmd_parts[1:]
            if len(time_args) >= 2:
                t_start = _parse_time_str(time_args[0])
                t_end = _parse_time_str(time_args[1])
                if not t_start or not t_end:
                    return "Error: Times must be in valid 24h format HH:MM (e.g. `23:00 07:00` or `01:00 08:00`)."
                self.safety.set_quiet_hours(True, t_start, t_end)
                return f"🌙 Quiet hours schedule set to *{t_start}* – *{t_end}* and *ENABLED*."

            return "Usage: `/quiethours on [start] [end]`, `/quiethours off`, or `/quiethours <start> <end>`"

        if cmd in ("/reactioncooldown", "/reactcd", "/reactionlimit", "/reactioninterval"):
            min_react = float(self.db.get_state(
                "reaction_min_cooldown_seconds",
                str(getattr(self.config, "reaction_min_cooldown_seconds", 3.0))
            ))
            max_react = float(self.db.get_state(
                "reaction_max_cooldown_seconds",
                str(getattr(self.config, "reaction_max_cooldown_seconds", 9.0))
            ))
            max_r = self.db.get_state("reaction_max_per_window", str(getattr(self.config, "reaction_max_per_window", 4)))
            win_m = int(float(self.db.get_state("reaction_window_seconds", str(getattr(self.config, "reaction_window_seconds", 600.0)))) // 60)

            if len(cmd_parts) < 2:
                return (
                    f"⚡ *Reaction Cooldown Settings:*\n"
                    f"• Interval: Random `{int(min_react)}s` to `{int(max_react)}s` between reactions\n"
                    f"• Rolling Rate Limit: Max *{max_r}* reactions per *{win_m}* minutes\n\n"
                    f"*Commands:*\n"
                    f"• `/reactioncooldown <min_sec> <max_sec>` - Set random interval (e.g. `/reactioncooldown 3 9`)\n"
                    f"• `/reactioncooldown limit <max_count> <window_mins>` - Set rolling limit (e.g. `/reactioncooldown limit 4 10`)"
                )

            if cmd_parts[1].lower() == "limit" and len(cmd_parts) >= 4:
                try:
                    max_cnt = max(1, int(cmd_parts[2]))
                    win_mins = max(1, float(cmd_parts[3]))
                    self.db.set_state("reaction_max_per_window", str(max_cnt))
                    self.db.set_state("reaction_window_seconds", str(win_mins * 60.0))
                    return f"✅ Reaction rolling limit updated: Max *{max_cnt}* reactions per *{win_mins:.0f}* minute(s)."
                except ValueError:
                    return "Error: Both count and minutes must be valid numbers."

            # Check if 2 numbers provided (e.g. /reactioncooldown 4 10 or /reactioncooldown 3 9)
            if len(cmd_parts) >= 3:
                try:
                    v1 = float(cmd_parts[1])
                    v2 = float(cmd_parts[2])
                    min_sec = max(1.0, min(v1, v2))
                    max_sec = max(min_sec, max(v1, v2))
                    self.db.set_state("reaction_min_cooldown_seconds", str(min_sec))
                    self.db.set_state("reaction_max_cooldown_seconds", str(max_sec))
                    self._next_reaction_cooldown = random.uniform(min_sec, max_sec)

                    # Also update window limit
                    max_cnt = max(1, int(v1))
                    win_mins = max(1.0, float(v2))
                    self.db.set_state("reaction_max_per_window", str(max_cnt))
                    self.db.set_state("reaction_window_seconds", str(win_mins * 60.0))
                    return (
                        f"✅ Reaction rate limit updated: Max *{max_cnt}* reactions per *{win_mins:.0f}* minute(s) "
                        f"(Random interval: *{int(min_sec)}s*–*{int(max_sec)}s*)."
                    )
                except ValueError:
                    return "Error: Cooldown values must be valid numbers."

            return "Usage: `/reactioncooldown 3 9` (seconds) or `/reactioncooldown limit 4 10` (rolling limit)"

        if cmd in ("/chatcooldown", "/chatcd"):
            if len(cmd_parts) < 2:
                min_cd = self.safety.min_chat_cooldown
                max_cd = self.safety.max_chat_cooldown
                return (
                    f"⏱️ *Current Chat Reply Cooldown:* Random `{int(min_cd)}s` – `{int(max_cd)}s`\n\n"
                    f"Usage:\n"
                    f"• `/chatcooldown <min> <max>` - Set random cooldown range (e.g. `/chatcooldown 5 60`)\n"
                    f"• `/chatcooldown <seconds>` - Set cooldown (e.g. `/chatcooldown 30`)"
                )
            try:
                if len(cmd_parts) >= 3:
                    min_val = max(1, int(cmd_parts[1]))
                    max_val = max(min_val, int(cmd_parts[2]))
                    self.db.set_state("min_chat_cooldown_seconds", str(min_val))
                    self.db.set_state("max_chat_cooldown_seconds", str(max_val))
                    self.db.set_state("per_chat_cooldown_seconds", str(max_val))
                    return f"✅ Chat reply cooldown randomized range set to *{min_val}s* – *{max_val}s*."
                else:
                    secs = max(1, int(cmd_parts[1]))
                    min_val = min(5, secs)
                    self.db.set_state("min_chat_cooldown_seconds", str(min_val))
                    self.db.set_state("max_chat_cooldown_seconds", str(secs))
                    self.db.set_state("per_chat_cooldown_seconds", str(secs))
                    return f"✅ Chat reply cooldown updated to *{secs}s*."
            except ValueError:
                return "Error: Cooldown seconds must be valid integers."

        if cmd in ("/globalcooldown", "/globalcd"):
            if len(cmd_parts) < 2:
                min_cd = self.safety.min_global_cooldown
                max_cd = self.safety.max_global_cooldown
                return (
                    f"⏱️ *Current Global Cooldown:* Random `{int(min_cd)}s` – `{int(max_cd)}s`\n\n"
                    f"Usage:\n"
                    f"• `/globalcooldown <min> <max>` - Set random range (e.g. `/globalcooldown 5 60`)\n"
                    f"• `/globalcooldown <seconds>` - Set cooldown (e.g. `/globalcooldown 15`)"
                )
            try:
                if len(cmd_parts) >= 3:
                    min_val = max(1, int(cmd_parts[1]))
                    max_val = max(min_val, int(cmd_parts[2]))
                    self.db.set_state("min_global_cooldown_seconds", str(min_val))
                    self.db.set_state("max_global_cooldown_seconds", str(max_val))
                    self.db.set_state("global_cooldown_seconds", str(max_val))
                    return f"✅ Global cooldown randomized range set to *{min_val}s* – *{max_val}s*."
                else:
                    secs = max(1, int(cmd_parts[1]))
                    min_val = min(5, secs)
                    self.db.set_state("min_global_cooldown_seconds", str(min_val))
                    self.db.set_state("max_global_cooldown_seconds", str(secs))
                    self.db.set_state("global_cooldown_seconds", str(secs))
                    return f"✅ Global cooldown updated to *{secs}s*."
            except ValueError:
                return "Error: Cooldown seconds must be valid integers."

        if cmd in ("/model", "/setmodel", "/custommodel"):
            if len(cmd_parts) < 2:
                curr = self.db.get_state("ai_model", self.config.ai_model or "default")
                return (
                    f"🤖 *Current AI Model:* `{curr}`\n\n"
                    f"*Recommended Models:*\n"
                    f"• Inception Labs: `/model mercury-3,mercury-3-preview-1014,mercury-3-preview-1002`\n"
                    f"• Google Gemini: `/model gemini-2.5-flash-lite`\n"
                    f"• OpenAI: `/model gpt-4o-mini`\n"
                    f"• NVIDIA: `/model meta/llama-3.1-70b-instruct`\n\n"
                    f"Usage: `/model <model_name(s)>` (supports comma-separated fallback chain)"
                )
            new_model = cmd_parts[1].strip()
            self.db.set_state("ai_model", new_model)
            self.generator.reload_provider()
            return f"✅ AI model switched to *{new_model}* (provider reloaded)."

        if cmd in ("/baseurl", "/setbaseurl", "/endpoint"):
            if len(cmd_parts) < 2:
                curr = self.db.get_state("ai_base_url", self.config.ai_base_url or "(default API)")
                return (
                    f"🔗 *Current AI Base URL / Endpoint:* `{curr}`\n\n"
                    f"*Custom API Endpoints:*\n"
                    f"• Inception Labs: `/baseurl https://api.inceptionlabs.ai/v1`\n"
                    f"• Groq: `/baseurl https://api.groq.com/openai/v1`\n"
                    f"• NVIDIA: `/baseurl https://integrate.api.nvidia.com/v1`\n"
                    f"• DeepSeek: `/baseurl https://api.deepseek.com/v1`\n"
                    f"• Local Ollama: `/baseurl http://localhost:11434/v1`\n"
                    f"• Reset: `/baseurl default`"
                )
            raw_url = " ".join(cmd_parts[1:]).strip()
            target_url = "" if raw_url.lower() == "default" else raw_url
            self.db.set_state("ai_base_url", target_url)
            self.generator.reload_provider()
            return f"✅ AI base URL updated to: `{target_url or 'default'}` (provider reloaded)."

        if cmd in ("/provider", "/setprovider"):
            if len(cmd_parts) < 2:
                curr = self.db.get_state("ai_provider", self.config.ai_provider)
                return (
                    f"🧠 *Current AI Provider:* `{curr}`\n\n"
                    f"*Available Options:*\n"
                    f"• `/provider custom` - Generic / Inception Labs OpenAI-compatible\n"
                    f"• `/provider gemini` - Google Gemini (Flash & Lite)\n"
                    f"• `/provider openai` - OpenAI (GPT-4o-mini)\n"
                    f"• `/provider nvidia` - NVIDIA API (via custom base URL)\n"
                    f"• `/provider local` - Offline rule-based (zero credit cost)"
                )
            target = cmd_parts[1].lower().strip()
            if target in ("gemini", "openai", "nvidia", "custom", "groq", "together", "deepseek", "local", "inception"):
                self.db.set_state("ai_provider", target)
                self.generator.reload_provider()
                return f"🧠 AI provider switched to *{target.upper()}* (provider reloaded)."
            return "Invalid provider. Available: custom, gemini, openai, nvidia, groq, local."

        if cmd in ("/apikey", "/setkey", "/setapikey"):
            if len(cmd_parts) < 2:
                curr_key = self.db.get_state("ai_api_key", self.config.ai_api_key or "")
                masked = f"`{curr_key[:7]}...{curr_key[-4:]}`" if len(curr_key) > 11 else ("`Set`" if curr_key else "`Not Configured`")
                return (
                    f"🔑 *Current AI API Key:* {masked}\n\n"
                    f"Usage: `/apikey <your_api_key>`\n"
                    f"_Example:_ `/apikey sk_your_api_key_here`\n\n"
                    f"_Updates your active AI key instantly on both local and cloud deployments without server restarts._"
                )
            new_key = cmd_parts[1].strip()
            self.db.set_state("ai_api_key", new_key)
            self.generator.reload_provider()
            masked = f"`{new_key[:7]}...{new_key[-4:]}`" if len(new_key) > 11 else "`Set`"
            return f"✅ AI API key updated to {masked} and provider reloaded."

        if cmd in ("/setai", "/customai"):
            if len(cmd_parts) < 2:
                prov = self.db.get_state("ai_provider", self.config.ai_provider)
                url = self.db.get_state("ai_base_url", self.config.ai_base_url or "(default API)")
                mod = self.db.get_state("ai_model", self.config.ai_model or "(default model)")
                curr_key = self.db.get_state("ai_api_key", self.config.ai_api_key or "")
                masked_key = f"`{curr_key[:7]}...{curr_key[-4:]}`" if len(curr_key) > 11 else ("`Configured`" if curr_key else "`Missing`")
                return (
                    f"🛠️ *Custom AI Setup Dashboard:*\n\n"
                    f"• **Provider:** `{prov.upper()}`\n"
                    f"• **Endpoint URL:** `{url}`\n"
                    f"• **Active Model(s):** `{mod}`\n"
                    f"• **API Key:** {masked_key}\n\n"
                    f"*Commands to customize from Telegram:*\n"
                    f"• `/setai <provider> <api_key> <endpoint_url> [models]`\n"
                    f"  _Example:_ `/setai custom sk_... https://api.your-provider.com/v1 model-name`\n"
                    f"• `/setai mercury <api_key>` (one-step Inception Labs Mercury setup)\n"
                    f"• `/apikey <key>` — Update API key directly\n"
                    f"• `/baseurl <url>` — Update endpoint URL\n"
                    f"• `/model <name>` — Update model name(s)\n"
                    f"• `/provider <name>` — Switch provider"
                )
            p = cmd_parts[1].lower().strip()
            if p in ("mercury", "inception") and len(cmd_parts) >= 3:
                k = cmd_parts[2].strip()
                self.db.set_state("ai_provider", "custom")
                self.db.set_state("ai_api_key", k)
                self.db.set_state("ai_base_url", "https://api.inceptionlabs.ai/v1")
                self.db.set_state("ai_model", "mercury-3,mercury-3-preview-1014,mercury-3-preview-1002")
                self.generator.reload_provider()
                return (
                    f"✅ *Inception Labs Mercury Configured & Activated!*\n\n"
                    f"• Provider: `CUSTOM`\n"
                    f"• Base URL: `https://api.inceptionlabs.ai/v1`\n"
                    f"• Models: `mercury-3, mercury-3-preview-1014, mercury-3-preview-1002`\n"
                    f"• Provider reloaded and active."
                )
            elif len(cmd_parts) >= 4:
                k = cmd_parts[2].strip()
                u = cmd_parts[3].strip()
                m = cmd_parts[4].strip() if len(cmd_parts) >= 5 else ""
                self.db.set_state("ai_provider", p)
                self.db.set_state("ai_api_key", k)
                self.db.set_state("ai_base_url", u)
                if m:
                    self.db.set_state("ai_model", m)
                self.generator.reload_provider()
                return (
                    f"✅ *Custom AI Configured & Activated!*\n\n"
                    f"• Provider: `{p.upper()}`\n"
                    f"• Endpoint: `{u}`\n"
                    f"• Model: `{m or 'default'}`\n"
                    f"• Provider reloaded and active."
                )
            else:
                return (
                    "Usage:\n"
                    "• `/setai <provider> <api_key> <endpoint_url> [models]`\n"
                    "• Or one-step Mercury setup: `/setai mercury <api_key>`"
                )

        if cmd in ("/chatty", "/banter"):
            if len(cmd_parts) < 2:
                curr_prob = float(self.db.get_state(
                    "chatty_probability",
                    str(getattr(self.config, "chatty_probability", 0.15))
                ))
                return (
                    f"💬 *Group Banter Participation:* `{int(curr_prob * 100)}%`\n"
                    f"Chance of casually chiming in on group conversation even when not directly mentioned.\n\n"
                    f"*Commands:*\n"
                    f"• `/chatty off` - Strictly reply only when mentioned (0%)\n"
                    f"• `/chatty on` - Enable natural 15% group banter\n"
                    f"• `/chatty <0-100>` - Set custom percentage (e.g. `/chatty 25`)"
                )
            arg = cmd_parts[1].lower().strip()
            if arg == "off":
                self.db.set_state("chatty_probability", "0.0")
                return "🔒 Group banter *DISABLED*. Client will strictly reply only when mentioned."
            elif arg == "on":
                self.db.set_state("chatty_probability", "0.15")
                return "💬 Group banter *ENABLED* (15% natural reply rate in allowlisted groups)."
            else:
                try:
                    pct = float(arg.rstrip("%"))
                    prob = max(0.0, min(1.0, pct / 100.0 if pct > 1.0 else pct))
                    self.db.set_state("chatty_probability", str(prob))
                    return f"💬 Group banter probability set to *{int(prob * 100)}%*."
                except ValueError:
                    return "Usage: `/chatty on`, `/chatty off`, or `/chatty <0-100>`"

        if cmd in ("/pause", "/off", "/sleep"):
            if len(cmd_parts) < 2:
                return "Usage: `/pause <duration>` (e.g. `/pause 2h`, `/pause 30m`, `/pause 45m`)"
            seconds = self._parse_duration(cmd_parts[1])
            if not seconds:
                return "Invalid duration format. Use e.g. `/pause 2h` or `/pause 30m`."
            self.safety.set_timed_pause(seconds)
            mins = int(seconds // 60)
            hours = round(seconds / 3600, 1)
            display = f"{hours} hour(s)" if seconds >= 3600 else f"{mins} minute(s)"
            return f"⏸️ Automation PAUSED for {display}. All auto-replies are paused.\nSend `/resume` anytime to reactivate early."

        if cmd in ("/stop", "/halt"):
            self.safety.set_emergency_stop(True)
            return "🛑 Emergency stop ACTIVATED. All automated actions halted."

        if cmd in ("/resume", "/start", "/unpause"):
            self.safety.clear_pause()
            return "▶️ Automation RESUMED. Emergency stop and timed pauses cleared."

        if cmd == "/name":
            if len(cmd_parts) < 2 or cmd_parts[1].lower() in ("sync", "fetch", "auto"):
                synced = await self.sync_owner_name_from_telegram()
                return f"✅ Identity name: *'{synced}'* (synced directly from Telegram profile).\nUsage: `/name <CustomName>` or `/name sync`"
            new_name = " ".join(cmd_parts[1:]).strip()
            self.generator.set_owner_name(new_name)
            self.db.set_state("owner_name", new_name)
            return f"✅ Identity updated! The AI will now reply as '{new_name}'."

        if cmd == "/prompt":
            custom = self.generator.prompt_manager.custom_prompt
            mode_str = f"Custom Persona ({len(custom.split())} words)" if custom else "Default Persona"
            full_inst = self.generator.prompt_manager.system_instructions
            custom_display = f'"{custom}"' if custom else "None (using default instructions)"
            return (
                f"📜 *Active System Instructions ({mode_str}):*\n\n"
                f"• *Anti-AI Guardrails:* ACTIVE 🛡️ (1-word brevity matching, Gen-Z slang, human alibi, zero code/brackets)\n"
                f"• *Custom Persona:* {custom_display}\n"
                f"• *Active Style:* `{self.generator.style}`\n"
                f"• *Language:* `{self.generator.language}`\n\n"
                f"*Compiled Prompt (sent to AI):*\n"
                f"```\n{full_inst[:3800]}\n```\n\n"
                f"_Use `/setprompt <text>` to customize persona, or `/setprompt default` to reset._"
            )

        if cmd == "/setprompt":
            if len(cmd_parts) < 2:
                return "Usage: `/setprompt <new prompt text>` or `/setprompt default` to reset."
            new_prompt = text[len(cmd_parts[0]):].strip()
            if new_prompt.lower() in ("default", "reset", "clear"):
                self.generator.prompt_manager.reset_custom_prompt()
                self.db.set_state("custom_system_prompt", "")
                return "🔄 System prompt reset to default persona with all anti-bot guardrails active."

            ok = self.generator.prompt_manager.save_system_instructions(new_prompt)
            self.db.set_state("custom_system_prompt", new_prompt)
            wc = len(new_prompt.split())
            tip = "\n⚠️ _Tip: Keep custom persona under 200–300 words for optimal speed and human-like texting._" if wc > 300 else ""
            if ok:
                return (
                    f"✅ System prompt updated ({wc} words)!{tip}\n"
                    f"The AI will now follow your custom persona immediately while strictly obeying all anti-bot guardrails."
                )
            else:
                return "❌ Failed to save new system prompt to disk."

        if cmd == "/auto":
            if len(cmd_parts) > 1 and cmd_parts[1].lower() == "on":
                self.safety.set_auto_authorization(True)
                return "⚡ Mode 3 Restricted Automation is now AUTHORIZED."
            elif len(cmd_parts) > 1 and cmd_parts[1].lower() == "off":
                self.safety.set_auto_authorization(False)
                return "🔒 Mode 3 Restricted Automation authorization REVOKED."
            return "Usage: `/auto on` or `/auto off`"

        if cmd == "/pending":
            pending = self.db.list_pending_approvals(limit=10)
            if not pending:
                return "No drafts currently pending approval."
            lines = ["📋 *Pending Drafts:*"]
            for p in pending:
                lines.append(f"• `#{p['id']}` Chat: {p['chat_title']} | Text: \"{p['draft_text'][:60]}\"")
            return "\n".join(lines)

        if cmd == "/approve":
            if len(cmd_parts) < 2:
                return "Usage: `/approve <id>`"
            try:
                approval_id = int(cmd_parts[1])
            except ValueError:
                return "Error: ID must be a number."

            item = self.db.get_pending_approval(approval_id)
            if not item:
                return f"Draft #{approval_id} not found or already processed."

            can_send, reason = self.safety.can_reply(item["chat_id"], item["draft_text"])
            if not can_send:
                return f"⚠️ Cannot send draft #{approval_id}: {reason}"

            success = await self._send_reply(item["chat_id"], item["reply_to_msg_id"], item["draft_text"], adaptive_delay=False)
            if success:
                self.db.update_approval_status(approval_id, "sent")
                return f"✅ Draft #{approval_id} sent successfully."
            else:
                return f"❌ Failed to send draft #{approval_id}."

        if cmd == "/reject":
            if len(cmd_parts) < 2:
                return "Usage: `/reject <id>`"
            try:
                approval_id = int(cmd_parts[1])
            except ValueError:
                return "Error: ID must be a number."

            item = self.db.get_pending_approval(approval_id)
            if not item:
                return f"Draft #{approval_id} not found or already processed."

            self.db.update_approval_status(approval_id, "rejected")
            return f"🗑️ Draft #{approval_id} rejected and discarded."

        return None

    def calculate_adaptive_delay(self, chat_id: int, reply_text: str = "", incoming_text: str = "") -> float:
        """Calculate human-like randomized delay (5-60s) adapting to group vs DM and message complexity."""
        if self.min_delay <= 0 and self.max_delay <= 0:
            return 0.0

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
        return round(max(self.min_delay, min(cap_max, delay)), 2)

    @staticmethod
    def split_reply_messages(text: str) -> list[str]:
        """Split a multi-thought reply into 2 or 3 natural messages without breaking word or clause meaning."""
        import re
        text = text.strip()
        if not text:
            return []

        # If already separated by newlines, split by line
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if len(lines) > 1:
            return lines[:3]

        # If a single line, check for clean sentence boundaries
        sentences = re.split(r"(?<=[.!?])\s+", text)
        sentences = [s.strip() for s in sentences if s.strip()]
        if 1 < len(sentences) <= 3 and len(text) > 15:
            # Ensure every sentence is a real thought (at least 2 chars), not broken words
            if all(len(s) >= 2 for s in sentences):
                return sentences

        return [text]

    async def maybe_send_reaction(self, chat_id: int, message_id: int, text: str) -> bool:
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

        # Check randomized interval cooldown (3s to 9s)
        now = time.time()
        min_react_cd = float(self.db.get_state(
            "reaction_min_cooldown_seconds",
            str(getattr(self.config, "reaction_min_cooldown_seconds", 3.0))
        ))
        max_react_cd = float(self.db.get_state(
            "reaction_max_cooldown_seconds",
            str(getattr(self.config, "reaction_max_cooldown_seconds", 9.0))
        ))
        if (now - self._last_reaction_time) < self._next_reaction_cooldown:
            wait_rem = round(self._next_reaction_cooldown - (now - self._last_reaction_time), 1)
            logger.debug(f"[REACTION] Cooldown active ({wait_rem}s remaining before next reaction).")
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
            "🤣", "⚡", "🍌", "🏆", "💔", "🤨", "😐", "🍓", "🍾", "💋", "🖕", "😈", "😴", "😭",
            "🤓", "👻", "👨‍💻", "👀", "🎃", "🙈", "😇", "😨", "🤝", "✍️", "🤗", "🫡", "🎅", "🎄",
            "☃️", "💅", "🤪", "🗿", "🆒", "💘", "🙉", "🦄", "😘", "💊", "🙊", "😎", "👾", "🤷‍♂️",
            "🤷", "🤷‍♀️", "😡"
        ]

        # Natural sentiment & tone mapping with full emoji variety
        lower = text.lower()
        has_sentiment = True
        if any(w in lower for w in ("haha", "lol", "lmao", "rofl", "xd", "funny", "lmfao", "joke")):
            chosen = random.choice(["😂", "🤣", "😁", "🤪", "🤡", "😎"])
        elif any(w in lower for w in ("fire", "op", "w", "nice", "cool", "goat", "lit", "win", "awesome", "pro")):
            chosen = random.choice(["🔥", "⚡", "💯", "🆒", "🏆", "🤩", "👏"])
        elif any(w in lower for w in ("thanks", "thx", "love", "heart", "tysm", "appreciate", "cute", "sweet")):
            chosen = random.choice(["❤️", "❤️‍🔥", "🥰", "😍", "💘", "😘", "🙏", "🤗"])
        elif any(w in lower for w in ("ok", "okay", "done", "yes", "yeah", "yep", "sure", "alright", "got it", "true")):
            chosen = random.choice(["👍", "👌", "🤝", "🫡", "✍️", "🆒"])
        elif any(w in lower for w in ("no", "nah", "nope", "bad", "disagree", "worst", "hate", "bruh")):
            chosen = random.choice(["👎", "💔", "😐", "🤨", "🗿", "🥱"])
        elif any(w in lower for w in ("omg", "what", "wait", "wow", "damn", "seriously", "bro what")):
            chosen = random.choice(["🤯", "😱", "👀", "😨", "👻"])
        elif any(w in lower for w in ("why", "how", "who", "where", "?", "idk", "wonder", "really")):
            chosen = random.choice(["🤔", "🧐", "🤓", "👀"])
        elif any(w in lower for w in ("sad", "rip", "sorry", "unfortunate", "cry", "pain")):
            chosen = random.choice(["😢", "😭", "💔"])
        else:
            has_sentiment = False
            # Natural human reactions for general text (26+ mobile everyday emojis)
            chosen = random.choice([
                "👍", "👌", "❤️", "🔥", "💯", "👀", "🙌", "🤝", "😎", "😂",
                "✨", "🎉", "🤩", "👏", "🫡", "✌️", "💪", "⚡", "😁", "🥰",
                "😍", "🙏", "🆒", "🤙", "🥳", "🌟"
            ])

        # When no explicit sentiment is detected, react occasionally (~40% chance) so quota isn't exhausted immediately
        if not has_sentiment and random.random() > 0.40:
            return False

        try:
            from telethon.tl.functions.messages import SendReactionRequest
            from telethon.tl.types import ReactionEmoji

            peer = await self._client.get_input_entity(chat_id)
            await self._client(SendReactionRequest(peer=peer, msg_id=message_id, reaction=[ReactionEmoji(emoticon=chosen)]))
            now = time.time()
            self.db.record_reaction(now)
            self._last_reaction_time = now
            self._next_reaction_cooldown = random.uniform(min_react_cd, max_react_cd)
            logger.info(
                f"[REACTION] Reacted {chosen} to message {message_id} in chat {chat_id}. "
                f"Next reaction cooldown: {round(self._next_reaction_cooldown, 1)}s."
            )
            return True
        except Exception as e:
            logger.debug(f"[REACTION] Could not send reaction {chosen} to chat {chat_id}: {e}")
            return False

    def _prevent_duplicate_reply(self, chat_id: int, text: str) -> str:
        """Allow AI to handle conversation dynamically without hardcoded keyword alternatives."""
        return text.strip()

    def is_group_message_relevant(self, chat_id: int, text: str, chat_title: str = "") -> bool:
        """Check if an incoming group message is relevant to the group's permanent context, pinned summary, or topic."""
        clean_text = text.strip().lower()
        if not clean_text:
            return False

        # 1. Check permanent context and pinned info
        ctx = self.db.get_permanent_context(chat_id)
        context_corpus = ""
        if ctx:
            context_corpus += f" {ctx.get('notes', '')} {ctx.get('pinned_text', '')} {ctx.get('pinned_summary', '')}"
        if chat_title:
            context_corpus += f" {chat_title}"

        if context_corpus.strip():
            import re
            keywords = set(re.findall(r"\b[a-zA-Z]{4,}\b", context_corpus.lower()))
            stopwords = {"group", "chat", "rules", "always", "this", "that", "with", "from", "have", "will", "what", "here"}
            meaningful_kw = keywords - stopwords
            if meaningful_kw:
                msg_words = set(re.findall(r"\b[a-zA-Z]{4,}\b", clean_text))
                if msg_words.intersection(meaningful_kw):
                    return True

        # 2. Check if the message is a genuine technical/topic question or discussion prompt
        question_or_discussion_words = (
            "how to", "how do", "anyone know", "any idea", "what is", "why is",
            "can we", "does anyone", "help with", "thoughts on", "what do you think",
            "kisi ko", "kaise kare", "batao", "kya lagta", "solution", "issue", "error",
            "working on", "anyone tried", "suggestion", "opinions", "thoughts"
        )
        if any(phrase in clean_text for phrase in question_or_discussion_words):
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

    async def maybe_send_quiet_hours_goodnight(self) -> None:
        """Before or upon entering quiet hours (2:00 AM IST), write bye/goodnight to active allowlisted groups."""
        if not self._client or not self.safety.quiet_hours_enabled:
            return

        ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        now_ist = datetime.datetime.now(ist_tz)
        today_str = now_ist.strftime("%Y-%m-%d")

        last_goodnight = self.db.get_state("last_quiet_goodnight_date", "")
        if last_goodnight == today_str:
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
        if diff <= 15 or (1440 - diff) <= 15:
            allowed_groups = list(self.privacy.allowed_groups)
            if not allowed_groups:
                known = self.db.get_known_chats()
                allowed_groups = [c["chat_id"] for c in known if c.get("chat_id", 0) < 0 and self.privacy.is_chat_allowed(c["chat_id"], True)]

            if allowed_groups:
                phrases = [
                    "bye guys, going to sleep rn",
                    "aight guys heading to bed, talk tomorrow",
                    "goodnight everyone, sleeping now",
                    "gn guys, sleep time for me",
                    "bye guys, off to sleep rn",
                ]
                text = random.choice(phrases)
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
    ) -> bool:
        """Send message using Telethon client with adaptive human reading/typing delay and error handling."""
        if not self._client:
            logger.error("Cannot send reply: Telegram client is not attached.")
            return False

        msg_parts = self.split_reply_messages(text)
        if not msg_parts:
            return False

        first_part = msg_parts[0]

        try:
            # Calculate human-like delay adapting to group/DM environment for first message
            if adaptive_delay and (self.min_delay > 0 or self.max_delay > 0):
                total_delay = self.calculate_adaptive_delay(chat_id, first_part)
            else:
                total_delay = self.typing_delay

            if total_delay > 0:
                # Realistic human simulation: pause for reading/thinking, then show typing action
                combo_lower = first_part.lower()
                is_quick_banter = any(w in combo_lower for w in ("haha", "lol", "yo", "sup", "ok", "yeah", "yea", "cool", "done"))
                base_speed = 0.035 if is_quick_banter else 0.05
                typing_duration = min(total_delay, max(1.5, min(5.0, len(first_part) * base_speed)))
                reading_delay = max(0.0, total_delay - typing_duration)

                env_type = "Group" if chat_id < 0 else "Private DM"
                logger.info(
                    f"[{env_type} Delay] Waiting {total_delay:.1f}s (reading: {reading_delay:.1f}s, typing: {typing_duration:.1f}s) before replying to chat {chat_id}."
                )

                # Phase 1: Reading/thinking pause
                if reading_delay > 0:
                    await asyncio.sleep(reading_delay)

                # Abort if emergency stop was triggered during reading delay
                if self.safety.is_emergency_stopped:
                    logger.warning(f"Reply to chat {chat_id} aborted: emergency stop triggered during delay.")
                    return False

                # Phase 2: Active typing indicator
                try:
                    if hasattr(self._client, "action") and callable(self._client.action):
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
            first_sent = await self._client.send_message(chat_id, first_part, reply_to=reply_to_msg_id)
            self.safety.mark_reply_sent(chat_id)
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
            )
            logger.info(f"Successfully sent reply part 1/{len(msg_parts)} to chat {chat_id}.")

            # Send subsequent message parts (2 or 3) with short natural typing pause
            for idx, part in enumerate(msg_parts[1:], start=2):
                if self.safety.is_emergency_stopped:
                    logger.warning(f"Follow-up message to chat {chat_id} aborted: emergency stop triggered.")
                    break

                followup_delay = random.uniform(1.0, 1.8)
                try:
                    if hasattr(self._client, "action") and callable(self._client.action):
                        act = self._client.action(chat_id, "typing")
                        if hasattr(act, "__aenter__"):
                            async with act:
                                await asyncio.sleep(followup_delay)
                        else:
                            if asyncio.iscoroutine(act):
                                act.close()
                            await asyncio.sleep(followup_delay)
                    else:
                        await asyncio.sleep(followup_delay)
                except Exception:
                    await asyncio.sleep(followup_delay)

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
