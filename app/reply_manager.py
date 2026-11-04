"""Reply orchestration handling Draft, Approval, and Restricted Automation modes."""

from __future__ import annotations

import asyncio
import random
from typing import Any, Optional

from app.ai.reply_generator import ReplyGenerator
from app.config import AppConfig
from app.logger import setup_logger
from app.privacy_manager import PrivacyManager
from app.safety_manager import SafetyManager
from app.storage.database import Database

logger = setup_logger(__name__)


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

        # Restore saved style if stored in DB
        saved_style = self.db.get_state("reply_style")
        if saved_style:
            self.generator.set_style(saved_style)

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

    async def handle_incoming_eligible_message(
        self,
        chat_id: int,
        chat_title: str,
        message_id: int,
        sender_id: Optional[int],
        sender_name: str,
        text: str,
        conversation_history: Optional[Any] = None,
    ) -> None:
        """Process an incoming message that has passed initial message filters."""
        # Sanitize incoming text before passing to generator
        clean_text = self.privacy.sanitize_text(text)

        # Check for custom keyword trigger rule before calling AI
        matched_rule = self.db.match_keyword_rule(clean_text)
        if matched_rule:
            logger.info(f"[KEYWORD TRIGGER] Matched custom trigger rule for chat {chat_id}.")
            draft = matched_rule
        else:
            draft = self.generator.generate(
                sender_name=sender_name,
                incoming_text=clean_text,
                conversation_history=conversation_history,
            )

        if not draft:
            logger.warning(f"No draft generated for chat {chat_id}.")
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
                logger.warning(f"[AUTO REPLY SUPPRESSED] Chat {chat_id}: {reason}")
                return

            await self._send_reply(chat_id, message_id, draft, adaptive_delay=True)

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
        notification = (
            f"📝 *Pending Approval #{approval_id}*\n"
            f"• *Chat:* {chat_title} (`{chat_id}`)\n"
            f"• *From:* {sender_name}\n"
            f"• *Incoming:* \"{incoming_text[:200]}\"\n"
            f"• *Suggested Reply:* \"{draft_text}\"\n\n"
            f"Send `/approve {approval_id}` to send, or `/reject {approval_id}` to discard."
        )
        if self._client:
            try:
                # 'me' in Telethon resolves to the user's private Saved Messages
                await self._client.send_message("me", notification, parse_mode="md")
            except Exception as e:
                logger.error(f"Failed to send approval notification to Saved Messages: {e}")

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
                "• `/auto on` / `/auto off` - Authorize or revoke automated replies\n"
                "• `/pause <time>` - Snooze replies (e.g. `/pause 2h`, `/pause 30m`)\n"
                "• `/resume` - Resume operations (clears pause & stop)\n"
                "• `/stop` - Emergency stop switch (halts all replies)\n\n"
                "*Custom Keyword Auto-Replies:*\n"
                "• `/addrule <word> => <reply>` - Auto-reply when a word is detected\n"
                "• `/delrule <word>` - Delete keyword trigger\n"
                "• `/rules` - List all active custom keyword triggers\n\n"
                "*Chat & Group Management:*\n"
                "• `/chats` - View all allowlisted private contacts & groups\n"
                "• `/allowchat <id>` - Allow a contact or group directly from Telegram\n"
                "• `/removechat <id>` - Remove chat from allowlist\n"
                "• `/blockchat <id>` - Block a chat ID\n"
                "• `/mentiononly on|off` - Group safety: reply only when mentioned/replied to\n\n"
                "*Approvals & Drafts:*\n"
                "• `/pending` - List drafts waiting for review\n"
                "• `/approve <id>` - Approve & send pending draft\n"
                "• `/reject <id>` - Discard pending draft\n\n"
                "*Identity & Persona:*\n"
                "• `/name <name>` - Set your display name for AI persona\n"
                "• `/prompt` - View active system prompt\n"
                "• `/setprompt <text>` - Update system prompt on the fly"
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
            priv, grps = self.privacy.get_all_allowed_chats()
            lines = ["📋 *Active Allowlisted Chats:*"]
            if priv:
                lines.append("• *Private Chats:* " + ", ".join(f"`{c}`" for c in sorted(priv)))
            else:
                lines.append("• *Private Chats:* (none)")
            if grps:
                lines.append("• *Groups:* " + ", ".join(f"`{g}`" for g in sorted(grps)))
            else:
                lines.append("• *Groups:* (none)")
            mention_only = self.db.get_state("group_mention_only", "1") == "1"
            lines.append(f"\n*Group Filter:* {'@Mentions / Replies Only' if mention_only else 'All Group Messages'}")
            lines.append("\n_Use `/allowchat <id>` to add, or `/removechat <id>` to remove._")
            return "\n".join(lines)

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
                current = "ON (safe: only replies when mentioned/replied to)" if self.db.get_state("group_mention_only", "1") == "1" else "OFF (replies to all group messages)"
                return f"Group mention filter is currently: *{current}*\nUsage: `/mentiononly on` or `/mentiononly off`"
            val = "1" if cmd_parts[1].lower() == "on" else "0"
            self.db.set_state("group_mention_only", val)
            if val == "1":
                return "🛡️ Group automation: *Mentions Only* activated. The client will only reply in groups when someone mentions your @username or replies directly to your message."
            else:
                return "⚠️ Group automation: *All Messages* activated. The client may reply to any message in allowlisted groups."

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
                    f"• `/style humorous` - Witty, playful banter."
                )
            target_style = cmd_parts[1].lower().strip()
            ok = self.generator.set_style(target_style)
            if ok:
                self.db.set_state("reply_style", target_style)
                return f"🎨 AI response style switched to *{target_style}*."
            return "Invalid style. Available: `/style casual`, `/style concise`, `/style formal`, `/style humorous`."

        if cmd == "/status":
            auto_status = "AUTHORIZED" if self.safety.is_auto_authorized else "DISABLED"
            stop_status = "ACTIVE" if self.safety.is_emergency_stopped else "NORMAL"
            remaining = self.safety.get_remaining_pause_seconds()
            pause_str = f"PAUSED ({int(remaining // 60)}m left)" if remaining > 0 else "ACTIVE"
            pending_count = len(self.db.list_pending_approvals())
            owner = self.generator.prompt_manager.owner_name
            mode_display = self.current_mode
            style_display = self.generator.style
            return (
                f"📊 *TeleAutomator Status:*\n"
                f"• Identity Name: `{owner}`\n"
                f"• Automation: *{pause_str}*\n"
                f"• Reply Mode: `{mode_display}` (change with `/mode <draft|approval|auto>`)\n"
                f"• AI Style: `{style_display}` (change with `/style <casual|concise|formal|humorous>`)\n"
                f"• Auto Authorized: *{auto_status}*\n"
                f"• Emergency Stop: *{stop_status}*\n"
                f"• Pending Approvals: `{pending_count}`\n"
                f"• AI Provider: `{self.config.ai_provider}` (model={self.config.ai_model or 'default'})"
            )

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
            if len(cmd_parts) < 2:
                return f"Current identity name is `{self.generator.prompt_manager.owner_name}`.\nUsage: `/name <YourName>`"
            new_name = " ".join(cmd_parts[1:]).strip()
            self.generator.set_owner_name(new_name)
            self.db.set_state("owner_name", new_name)
            return f"✅ Identity updated! The AI will now reply as '{new_name}'."

        if cmd == "/prompt":
            current_prompt = self.generator.prompt_manager.system_instructions
            return f"📜 *Active System Prompt:*\n\n{current_prompt[:1500]}"

        if cmd == "/setprompt":
            if len(cmd_parts) < 2:
                return "Usage: `/setprompt <new prompt text>`"
            new_prompt = text[len(cmd_parts[0]):].strip()
            ok = self.generator.prompt_manager.save_system_instructions(new_prompt)
            if ok:
                return "✅ System prompt updated successfully! The AI will now follow your new instructions immediately."
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

        return round(max(self.min_delay, min(self.max_delay, delay)), 2)

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

        try:
            # Calculate human-like delay adapting to group/DM environment
            if adaptive_delay and (self.min_delay > 0 or self.max_delay > 0):
                total_delay = self.calculate_adaptive_delay(chat_id, text)
            else:
                total_delay = self.typing_delay

            if total_delay > 0:
                # Realistic human simulation: pause for reading/thinking, then show typing action
                typing_duration = min(total_delay, max(2.0, min(6.0, len(text) * 0.05)))
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
                        async with self._client.action(chat_id, "typing"):
                            await asyncio.sleep(typing_duration)
                    else:
                        await asyncio.sleep(typing_duration)
                except Exception:
                    await asyncio.sleep(typing_duration)

            await self._client.send_message(chat_id, text, reply_to=reply_to_msg_id)
            self.safety.mark_reply_sent(chat_id)
            logger.info(f"Successfully sent reply to chat {chat_id}.")
            return True
        except Exception as e:
            self.safety.record_error()
            logger.error(f"Failed to send message to chat {chat_id}: {e}")
            return False
