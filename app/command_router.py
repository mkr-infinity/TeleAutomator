"""Modular Command Router for TeleAutomator.

Routes user control commands across specialized domains:
- Core controls (status, modes, pause/resume, safety)
- Rules & approval drafts
- Chat allowlisting & context memory
- Persona & identity tuning
- Humanization & delay simulation
- AI engines, models, and provider settings
"""

import asyncio
import datetime
import difflib
import json
import math
import os
import random
import re
import shutil
import time
from pathlib import Path
from typing import Optional, Any

from app.logger import setup_logger

logger = setup_logger(__name__)
from app.miniapp_server import resolve_miniapp_url

_BOT_COMMAND_NAMES = (
    "/help", "/start", "/status", "/mode", "/style", "/styles", "/lang", "/auto", "/pause", "/resume", "/stop",
    "/reaction", "/reactioncooldown", "/chatcooldown", "/globalcooldown", "/ratelimit", "/editfix", "/ownreact",
    "/typo", "/followup", "/debounce", "/multibubble", "/quiethours", "/sleep", "/aiconfig", "/setai", "/apikey",
    "/usage", "/checkmodels", "/thinking", "/temp", "/maxtokens", "/model", "/baseurl", "/provider",
    "/addrule", "/delrule", "/rules", "/chats", "/allowchat", "/removechat",
    "/blockchat", "/mentiononly", "/contextttl", "/clearcontext", "/syncpins", "/setcontext", "/showcontext",
    "/delcontext", "/backup", "/pending", "/approve", "/reject", "/name", "/prompt", "/setprompt", "/chatty",
    "/chatprompt", "/gencontext", "/safemode", "/miniapp",
)


def _parse_time_str(val: str) -> Optional[str]:
    """Parse and normalize HH:MM string."""
    m = re.match(r"^(\d{1,2}):(\d{2})$", val.strip())
    if not m:
        return None
    h, mins = int(m.group(1)), int(m.group(2))
    if 0 <= h <= 23 and 0 <= mins <= 59:
        return f"{h:02d}:{mins:02d}"
    return None


class CommandRouterMixin:
    """Mixin providing modular control command dispatchers for ReplyManager."""

    async def handle_control_command(self, text: str) -> Optional[str]:
        """Handle control commands sent via the control channel (control bot or Saved Messages)."""
        cmd_parts = text.strip().split()
        if not cmd_parts:
            return None

        cmd = cmd_parts[0].lower().split("@")[0]

        routers = (
            self._route_core_control,
            self._route_rules_and_drafts,
            self._route_chat_context,
            self._route_persona_identity,
            self._route_humanization,
            self._route_ai_settings,
        )

        for router in routers:
            res = await router(cmd, cmd_parts, text)
            if res is not None:
                return res

        if not cmd.startswith("/"):
            return None  # plain text (e.g. notes) — no command response needed

        closest = difflib.get_close_matches(cmd, _BOT_COMMAND_NAMES, n=3, cutoff=0.6)
        known = ", ".join(f"`{c}`" for c in _BOT_COMMAND_NAMES)
        hint = f"\nDid you mean: {chr(32).join(f"`{c}`" for c in closest)}?" if closest else ""
        return (
            f"❓ Unknown command `{cmd}`.\n"
            f"Common ones: {known}{hint}\n"
            f"Send */help* for the full guide."
        )

    async def _route_core_control(self, cmd: str, cmd_parts: list[str], text: str) -> Optional[str]:
        if cmd in ("/help", "/start"):
            return (
                "🤖 *TeleAutomator Commands:*\n\n"
                "*Core Controls:*\n"
                "• `/status` - Health, active identity, pause timer, & mode\n"
                "• `/mode <draft|approval|auto>` - Switch automation mode on the fly\n"
                "• `/style <casual|concise|formal|humorous>` - Change AI reply style\n"
                "• `/lang <dynamic|english|hindi|...>` - Chat language selection\n"
                "• `/auto on` / `/auto off` - Authorize or revoke automated replies\n"
                "• `/pause <time>` - Snooze replies (e.g. `/pause 2h`, `/pause 30 min`, `/pause 90s`) - auto-resumes with an alert\n"
                "• `/resume` - Resume operations (clears pause & stop)\n"
                "• `/stop` - Emergency stop switch (halts all replies)\n\n"
                "*Reactions & Cooldowns:*\n"
                "• `/reaction on` / `/reaction off` - Enable or disable auto-reactions\n"
                "• `/reactioncooldown <min> <max>` - Set random reaction cooldown (e.g. `15 60` seconds)\n"
                "• `/chatcooldown <min> <max>` - Custom per-chat reply cooldown (e.g. `5 60`)\n"
                "• `/globalcooldown <min> <max>` - Custom global reply cooldown (e.g. `5 60`)\n"
                "• `/ratelimit <per_min>` - Anti-spam base burst limit (e.g. `/ratelimit 5`)\n"
                "• `/editfix on|off` - Self-typo-then-edit simulation (send with typo, edit clean seconds later)\n"
                "• `/ownreact on|off` - React to your own sent messages occasionally\n"
                "• `/typo on|off` - Natural typo + correction follow-up simulation\n"
                "• `/followup <on|off>` - Spontaneous delayed follow-ups for short replies\n"
                "• `/debounce <on|off|seconds>` - Incoming burst debouncer (stitches rapid messages)\n"
                "• `/multibubble <on|off>` - Multi-bubble response splitting (rapid sequential bubbles)\n\n"
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
                "• `/thinking <default|low|medium|high|off>` - Adjust AI thinking/reasoning effort\n"
                "• `/temp <0.0-1.0>` - Adjust AI randomness/creativity\n"
                "• `/maxtokens <tokens>` - Maximum output tokens per response\n"
                "• `/model <name>` - Set model name or comma-separated fallback chain\n"
                "• `/baseurl <url>` - Set custom API endpoint/base URL\n"
                "• `/provider <name>` - Switch AI engine (custom, gemini, openai, nvidia, local)\n"
                "• `/style [chat_id] <style>` - Global or per-chat persona override\n"
                "• `/styles` - List all per-chat persona overrides\n\n"
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
                "• `/gencontext <chat_id>` - Rebuild AI voice profile from recent group messages\n"
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
                "• `/chatprompt <chat_id> <text>` - Custom AI persona for one chat only\n"
                "• `/chatty` - Banter picker per group (inline buttons) or global %"
            )

        if cmd in ("/mode", "/setmode"):
            if len(cmd_parts) < 2:
                curr = self.current_mode
                return (
                    f"⚙️ *Current Reply Mode:* `{curr}`\n\n"
                    f"*Available Modes:*\n"
                    f"• `/mode draft` - Suggests drafts in terminal/logs; NEVER sends.\n"
                    f"• `/mode approval` - Sends drafts to your control channel for `/approve <id>`.\n"
                    f"• `/mode auto` - Directly replies to allowlisted chats without manual approval."
                )
            target = cmd_parts[1].lower().strip()
            if target in ("draft", "draft_only", "drafts"):
                self.set_mode("draft")
                return "📝 Mode switched to *Draft Only*. Replies will be generated and logged, but never sent to recipients."
            elif target in ("approval", "pending", "review"):
                self.set_mode("approval")
                return "📋 Mode switched to *Approval Required*. Every draft will be sent to your control channel (bot / Saved Messages) for review."
            elif target in ("auto", "restricted_auto", "automatic"):
                self.set_mode("restricted_auto")
                self.safety.set_auto_authorization(True)
                return "⚡ Mode switched to *Restricted Auto*. Allowlisted chats will receive automated replies directly."
            else:
                return (
                    "❌ /mode failed\n"
                    "Missing: Valid mode (draft, approval, or auto)\n"
                    "Fix: /mode draft | /mode approval | /mode auto"
                )

        if cmd in ("/miniapp", "/panel", "/gui", "/app"):
            from app.miniapp_server import resolve_miniapp_url
            url = resolve_miniapp_url()
            if url:
                return (
                    "📱 *TeleAutomator Mini App Control Panel*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"🔗 Web App URL: {url}\n\n"
                    "_Tap the '⚡ TeleAutomator' button in your chat menu or open the link above._"
                )
            return (
                "📱 *TeleAutomator Mini App Control Panel*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "Mini app server is running on local port 8080.\n"
                "On Railway, the '⚡ TeleAutomator' menu button is auto-registered without any extra domain setup."
            )

        if cmd == "/status":
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
            _ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
            _ist_now = datetime.datetime.now(_ist).strftime("%H:%M")
            qh_desc = (
                f"ON ({qh_start}–{qh_end} IST · {'Sleeping 💤' if is_quiet else 'Awake ☀️'} · now {_ist_now} IST)"
                if qh_enabled else "OFF"
            )
            min_r_sec = float(self.db.get_state("reaction_min_cooldown_seconds", str(getattr(self.config, "reaction_min_cooldown_seconds", 15.0))))
            max_r_sec = float(self.db.get_state("reaction_max_cooldown_seconds", str(getattr(self.config, "reaction_max_cooldown_seconds", 60.0))))
            chat_cd_range = f"{int(self.safety.min_chat_cooldown)}s–{int(self.safety.max_chat_cooldown)}s"
            global_cd_range = f"{int(self.safety.min_global_cooldown)}s–{int(self.safety.max_global_cooldown)}s"
            recent_min = self.db.get_recent_reply_count(60.0) if hasattr(self.db, "get_recent_reply_count") else 0
            chats_df = await self.get_allowed_chats_dataframe()
            stop_icon = "🔴" if self.safety.is_emergency_stopped else "🟢"
            pause_icon = "⏸️" if remaining > 0 else "▶️"
            from app import __version__ as app_version
            return (
                f"📊 *TeleAutomator — Live Status*  `v{app_version}`\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"👤 *Identity*\n"
                f"　• Name: *{owner}*\n\n"
                f"⚡ *Automation*\n"
                f"　• State: {pause_icon} *{pause_str}*\n"
                f"　• Mode: `{mode_display}`\n"
                f"　• Auto-authorize: {'✅ authorized' if self.safety.is_auto_authorized else '🔒 disabled'}\n"
                f"　• Emergency stop: {stop_icon} *{stop_status}*\n"
                f"　• Pending approvals: `{pending_count}`\n"
                f"　• Safe-mode guard: {self._safe_mode_status_inline()}\n\n"
                f"🤖 *AI Engine*\n"
                f"　• Provider: `{active_prov.upper()}`\n"
                f"　• Model: `{active_mod}`{url_str}\n"
                f"　• Style: `{style_display}` · Language: `{lang_display}`\n"
                f"　• Group banter: `{int(chatty_prob * 100)}%`\n\n"
                f"💬 *Chat Rules*\n"
                f"　• Reactions: *{react_status}* · every `{int(min_r_sec)}–{int(max_r_sec)}s` · max `{max_r}` per `{win_m}m`\n"
                f"　• Cooldowns: chat `{chat_cd_range}` · global `{global_cd_range}`\n"
                f"　• Anti-spam: *{self.safety.max_replies_per_minute}/min base (dynamic)* · used last 60s: `{recent_min}`\n"
                f"　• Quiet hours: *{qh_desc}*\n\n"
                f"_💡 Quick controls: `/mode` · `/style` · `/lang` · `/quiethours` · `/chatty`_\n\n"
                f"📋 *Target Chats & Groups:*\n{chats_df}"
            )

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

        if cmd in ("/pause", "/off"):
            if len(cmd_parts) < 2:
                return (
                    "❌ /pause failed\n"
                    "Missing: Duration argument\n"
                    "Fix: /pause <duration> (e.g. /pause 30m, /pause 2h, /pause 90s)"
                )
            seconds = self._parse_duration(" ".join(cmd_parts[1:]))
            if not seconds:
                return (
                    "❌ /pause failed\n"
                    "Missing: Valid duration format\n"
                    "Fix: /pause <duration> (e.g. /pause 30m, /pause 2h, /pause 90s)"
                )
            self.safety.set_timed_pause(seconds)
            mins = int(seconds // 60)
            hours = round(seconds / 3600, 1)
            display = f"{hours} hour(s)" if seconds >= 3600 else f"{mins} minute(s)"
            return (f"⏸️ Automation PAUSED for {display}. All auto-replies are paused.\n"
                    f"When the window ends you'll get a *pause ended* alert here and engagement resumes automatically. "
                    f"Or send `/resume` anytime to reactivate early.")

        if cmd in ("/stop", "/halt"):
            self.safety.set_emergency_stop(True)
            return "🛑 Emergency stop ACTIVATED. All automated actions halted."

        if cmd in ("/resume", "/unpause"):
            self.safety.clear_pause()
            return "▶️ Automation RESUMED. Emergency stop and timed pauses cleared."

        if cmd == "/safemode":
            active = self.db.get_state("safe_mode_active", "0") == "1"
            try:
                threshold = self.db.get_state("safe_mode_restarts", "3")
                recover = self.db.get_state("safe_mode_recover_minutes", "15")
            except ValueError:
                threshold, recover = "3", "15"
            if active:
                try:
                    since = float(self.db.get_state("safe_mode_since", "0"))
                    waited = max(0, int((time.time() - since) / 60))
                except ValueError:
                    waited = 0
                return (f"🛡️ *Safe mode ACTIVE* — automation held in *draft* (nothing sent to chats).\n"
                        f"• Stable for: *{waited}/{recover} min* (auto-recovers to the previous mode)\n"
                        f"• Trigger: {threshold} rapid restarts within 10 minutes")
            return (f"🛡️ *Safe-mode guard:* READY\n"
                    f"• Triggers at {threshold} rapid restarts in 10 min (crash-loop protection)\n"
                    f"• Auto-recovers after {recover} min of stable uptime\n"
                    f"• Crash protection is automatic — no action needed.")

        if cmd == "/auto":
            if len(cmd_parts) > 1 and cmd_parts[1].lower() == "on":
                self.safety.set_auto_authorization(True)
                return "⚡ Mode 3 Restricted Automation is now AUTHORIZED."
            elif len(cmd_parts) > 1 and cmd_parts[1].lower() == "off":
                self.safety.set_auto_authorization(False)
                return "🔒 Mode 3 Restricted Automation authorization REVOKED."
            return "Usage: `/auto on` or `/auto off`"

        return None

    async def _route_rules_and_drafts(self, cmd: str, cmd_parts: list[str], text: str) -> Optional[str]:
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
                    "❌ /addrule failed\n"
                    "Missing: Keyword separator '=>' and reply text\n"
                    "Fix: /addrule <keyword> => <reply> (e.g. /addrule pricing => We are updating our packages, will send details soon!)"
                )
            kw, reply = raw_args.split(sep, 1)
            kw, reply = kw.strip(), reply.strip()
            if not kw or not reply:
                return (
                    "❌ /addrule failed\n"
                    "Missing: Non-empty keyword or reply\n"
                    "Fix: /addrule <keyword> => <reply> (e.g. /addrule hello => Hey there!)"
                )
            self.db.add_keyword_rule(kw, reply)
            return f"✅ Keyword rule added!\n• When message contains: *'{kw}'*\n• Client will reply: \"{reply}\""

        if cmd == "/delrule":
            if len(cmd_parts) < 2:
                return (
                    "❌ /delrule failed\n"
                    "Missing: Keyword to delete\n"
                    "Fix: /delrule <keyword> (e.g. /delrule pricing)"
                )
            kw = " ".join(cmd_parts[1:]).strip()
            ok = self.db.delete_keyword_rule(kw)
            if ok:
                return f"🗑️ Keyword trigger rule for *'{kw}'* has been deleted."
            return f"Rule for *'{kw}'* not found."

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
                return (
                    "❌ /approve failed\n"
                    "Missing: Draft ID\n"
                    "Fix: /approve <id> (e.g. /approve 1)"
                )
            try:
                approval_id = int(cmd_parts[1])
            except ValueError:
                return (
                    "❌ /approve failed\n"
                    "Missing: Valid numeric draft ID\n"
                    "Fix: /approve <id> (e.g. /approve 1)"
                )

            item = self.db.get_pending_approval(approval_id)
            if not item:
                return (
                    f"❌ Draft #{approval_id} no longer exists.\n"
                    "Missing: Active pending draft\n"
                    "Fix: /pending to see current drafts."
                )

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
                return (
                    "❌ /reject failed\n"
                    "Missing: Draft ID\n"
                    "Fix: /reject <id> (e.g. /reject 1)"
                )
            try:
                approval_id = int(cmd_parts[1])
            except ValueError:
                return (
                    "❌ /reject failed\n"
                    "Missing: Valid numeric draft ID\n"
                    "Fix: /reject <id> (e.g. /reject 1)"
                )

            item = self.db.get_pending_approval(approval_id)
            if not item:
                return (
                    f"❌ Draft #{approval_id} no longer exists.\n"
                    "Missing: Active pending draft\n"
                    "Fix: /pending to see current drafts."
                )

            self.db.update_approval_status(approval_id, "rejected")
            return f"🗑️ Draft #{approval_id} rejected and discarded."

        return None

    async def _route_chat_context(self, cmd: str, cmd_parts: list[str], text: str) -> Optional[str]:
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

        if cmd in ("/allowchat", "/allow"):
            if len(cmd_parts) < 2:
                return (
                    "❌ /allowchat failed\n"
                    "Missing: Chat ID\n"
                    "Fix: /allowchat <chat_id> (e.g. /allowchat -1001234567890 or /allowchat 123456789)"
                )
            try:
                cid = int(cmd_parts[1])
                self.privacy.allow_chat(cid)

                title = ""
                username = ""
                if self._client:
                    try:
                        entity = await self._client.get_entity(cid)
                        if hasattr(entity, "title") and entity.title:
                            title = entity.title
                        elif hasattr(entity, "first_name") and entity.first_name:
                            title = f"{entity.first_name} {getattr(entity, 'last_name', '') or ''}".strip()
                        if hasattr(entity, "username") and entity.username:
                            username = f"@{entity.username}"
                    except Exception:
                        pass

                if not title and self.db:
                    meta = self.db.get_chat_metadata(cid)
                    if meta:
                        title = meta.get("title", "")
                        if meta.get("username"):
                            username = f"@{meta.get('username')}"

                target = "Group" if cid < 0 else "Private contact"
                if (title or username) and self.db:
                    self.db.record_chat_metadata(
                        cid,
                        title=title,
                        username=username.lstrip("@"),
                        chat_type=target,
                    )
                info_parts = []
                if title:
                    info_parts.append(f"*{title}*")
                if username:
                    info_parts.append(f"({username})")
                info_str = f" {' '.join(info_parts)}" if info_parts else ""

                result = f"✅ {target}{info_str} [ID: `{cid}`] has been added to the allowlist!"
                if cid < 0 and self._client:
                    # Auto-build this group's AI voice profile from its recent messages (background task)
                    asyncio.create_task(self.generate_chat_voice_profile(cid))
                    result += "\n\n🧠 _AI is now reading recent messages to learn how this group talks (voice profile). Use `/gencontext %d` to rebuild it later._" % cid
                return result
            except ValueError:
                return (
                    "❌ /allowchat failed\n"
                    "Missing: Valid integer chat ID\n"
                    "Fix: /allowchat <chat_id> (e.g. /allowchat -1001234567890)"
                )

        if cmd == "/removechat":
            if len(cmd_parts) < 2:
                return (
                    "❌ /removechat failed\n"
                    "Missing: Chat ID\n"
                    "Fix: /removechat <chat_id> (e.g. /removechat 123456789)"
                )
            try:
                cid = int(cmd_parts[1])
                self.privacy.remove_chat(cid)
                return f"🗑️ Chat `{cid}` removed from allowlist."
            except ValueError:
                return (
                    "❌ /removechat failed\n"
                    "Missing: Valid integer chat ID\n"
                    "Fix: /removechat <chat_id> (e.g. /removechat 123456789)"
                )

        if cmd in ("/blockchat", "/ban"):
            if len(cmd_parts) < 2:
                return (
                    "❌ /blockchat failed\n"
                    "Missing: Chat ID\n"
                    "Fix: /blockchat <chat_id> (e.g. /blockchat 123456789)"
                )
            try:
                cid = int(cmd_parts[1])
                self.privacy.block_chat(cid)
                return f"🚫 Chat `{cid}` is now blocked."
            except ValueError:
                return (
                    "❌ /blockchat failed\n"
                    "Missing: Valid integer chat ID\n"
                    "Fix: /blockchat <chat_id> (e.g. /blockchat 123456789)"
                )

        if cmd in ("/mentiononly", "/mentions"):
            if len(cmd_parts) < 2 or cmd_parts[1].lower() not in ("on", "off"):
                current = "ON (strict: only replies when mentioned/replied to)" if self.db.get_state("group_mention_only", "0") == "1" else "OFF (natural human engagement: replies/reacts to relevant topics, mentions, or after 20m idle)"
                return f"Group mention filter is currently: *{current}*\nFix: Use `/mentiononly on` or `/mentiononly off`."
            val = "1" if cmd_parts[1].lower() == "on" else "0"
            self.db.set_state("group_mention_only", val)
            if val == "1":
                return "🛡️ Group automation: *Mentions Only* activated. The client will only reply in groups when someone mentions your @username or replies directly to your message."
            else:
                return "🌟 Group automation: *Smart Human Engagement* activated. The client will naturally reply or react to relevant group topics, answer mentions, and chime in after 20 minutes of idle time."

        if cmd in ("/gencontext", "/genvoice"):
            if not self._client:
                return (
                    "❌ /gencontext failed\n"
                    "Missing: Active Telegram client session\n"
                    "Fix: Authenticate session via ./authenticate.sh and restart bot."
                )
            if len(cmd_parts) >= 2:
                try:
                    target_cid = int(cmd_parts[1])
                except ValueError:
                    return (
                        "❌ /gencontext failed\n"
                        "Missing: Valid integer chat ID\n"
                        "Fix: /gencontext <chat_id> (e.g. /gencontext -1001234567890)"
                    )
                if target_cid >= 0:
                    return (
                        "❌ /gencontext failed\n"
                        "Missing: Negative group chat ID\n"
                        "Fix: /gencontext <chat_id> with a group ID (e.g. /gencontext -1001234567890). Private chats use the global persona."
                    )
                profile = await self.generate_chat_voice_profile(target_cid)
                if not profile:
                    return f"⚠️ Couldn't build a voice profile for `{target_cid}` — need recent text messages in that group. Try again after some chat activity."
                meta = self.db.get_chat_metadata(target_cid) or {}
                name = meta.get("title") or f"Group {target_cid}"
                username = f" ({'@' + meta['username']})" if meta.get("username") else ""
                preview = profile[:300] + ("…" if len(profile) > 300 else "")
                return (
                    "🧠 *AI Voice Profile Rebuilt*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"🗣 *Group:* {name}{username} · `{target_cid}`\n\n"
                    f"*Profile:*\n_{preview}_\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "_The AI now mirrors how people talk, their slang and message lengths in this group._"
                )
            priv, grps = self.privacy.get_all_allowed_chats()
            targets = sorted(g for g in grps if g < 0)
            if not targets:
                return (
                    "❌ /gencontext failed\n"
                    "Missing: Allowlisted groups\n"
                    "Fix: Use /allowchat <group_id> to add a group first."
                )
            built = 0
            for gid in targets:
                if await self.generate_chat_voice_profile(gid):
                    built += 1
            return f"🧠 Voice profiles rebuilt for *{built}/{len(targets)}* allowlisted groups."

        if cmd in ("/contextttl", "/aging"):
            if len(cmd_parts) < 2:
                curr = self.db.get_state("context_ttl_hours", "24.0")
                return (
                    f"⏳ *Conversation Context Auto-Aging:* `{curr} hours`\n"
                    "After this period of inactivity, older conversation context expires so the AI starts fresh.\n"
                    "Usage: `/contextttl <hours|days>` (e.g. `/contextttl 24.0` or `/contextttl 1d`)"
                )
            raw_input = " ".join(cmd_parts[1:]).strip().lower()
            val = None
            if raw_input in ("1d", "1day", "1 day", "day"):
                val = 24.0
            elif raw_input in ("12h", "12hr", "12hrs", "12 hours"):
                val = 12.0
            elif raw_input.endswith("d") and raw_input[:-1].replace(".", "", 1).isdigit():
                val = float(raw_input[:-1]) * 24.0
            elif raw_input.endswith("h") and raw_input[:-1].replace(".", "", 1).isdigit():
                val = float(raw_input[:-1])
            else:
                try:
                    val = float(cmd_parts[1])
                except ValueError:
                    val = None

            if val is not None and val >= 0.1:
                self.db.set_state("context_ttl_hours", str(val))
                return f"⏳ Context aging window set to *{val} hours*. Messages older than this will expire from AI prompt memory."
            return (
                "❌ /contextttl failed\n"
                "Missing: Valid positive number of hours or days\n"
                "Fix: /contextttl <hours> (e.g. /contextttl 24.0 or /contextttl 1d)"
            )

        if cmd in ("/clearcontext", "/resetcontext"):
            if len(cmd_parts) < 2:
                return (
                    "❌ /clearcontext failed\n"
                    "Missing: Chat ID\n"
                    "Fix: /clearcontext <chat_id> (e.g. /clearcontext -1001234567890)"
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
                return (
                    "❌ /clearcontext failed\n"
                    "Missing: Valid integer chat ID\n"
                    "Fix: /clearcontext <chat_id> (e.g. /clearcontext -1001234567890)"
                )

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
                    return (
                        "❌ /syncpins failed\n"
                        "Missing: Valid integer chat ID\n"
                        "Fix: /syncpins <chat_id> (e.g. /syncpins -1001234567890) or bare /syncpins to sync all groups"
                    )
            groups = list(self.privacy.get_all_allowed_chats()[1])
            if not groups:
                return (
                    "❌ /syncpins failed\n"
                    "Missing: Allowlisted groups\n"
                    "Fix: Use /allowchat <group_id> to add a group first."
                )
            synced_count = 0
            for gid in groups:
                res = await self.sync_pinned_context_from_telegram(gid)
                if res:
                    synced_count += 1
            return f"📌 Synced pinned messages for {synced_count}/{len(groups)} allowlisted groups into permanent context."

        if cmd == "/setcontext":
            if len(cmd_parts) < 3:
                return (
                    "❌ /setcontext failed\n"
                    "Missing: Chat ID and context notes\n"
                    "Fix: /setcontext <chat_id> <important details / rules> (e.g. /setcontext -1001234567890 Solana trading group, focus on meme coins, keep replies brief)"
                )
            try:
                target_cid = int(cmd_parts[1])
                notes_text = " ".join(cmd_parts[2:]).strip()
                self.db.set_permanent_context(target_cid, notes=notes_text)
                meta = self.db.get_chat_metadata(target_cid) or {}
                name = meta.get("title") or f"Chat {target_cid}"
                username = f" ({'@' + meta['username']})" if meta.get("username") else ""
                return (
                    "✅ *Permanent Context Saved*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"🗣 *Chat:* {name}{username} · `{target_cid}`\n\n"
                    f"📝 *Saved notes:*\n_{notes_text}_\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "_Remembered permanently across all conversations in this chat._"
                )
            except ValueError:
                return (
                    "❌ /setcontext failed\n"
                    "Missing: Valid integer chat ID\n"
                    "Fix: /setcontext <chat_id> <notes> (e.g. /setcontext -1001234567890 Solana trading group)"
                )

        if cmd == "/showcontext":
            if len(cmd_parts) < 2:
                return (
                    "❌ /showcontext failed\n"
                    "Missing: Chat ID\n"
                    "Fix: /showcontext <chat_id> (e.g. /showcontext -1001234567890)"
                )
            try:
                target_cid = int(cmd_parts[1])
                ctx = self.db.get_permanent_context(target_cid)
                pinned = ctx.get("pinned_text") or "(No pinned message cached)"
                notes = ctx.get("notes") or "(No custom notes set)"
                voice = self.db.get_state(f"chat_voice_profile_{target_cid}")
                voice_str = voice if voice else "(No AI voice profile yet — `/gencontext %d` to build)" % target_cid
                meta = self.db.get_chat_metadata(target_cid) or {}
                name = meta.get("title") or f"Chat {target_cid}"
                username = f" ({'@' + meta['username']})" if meta.get("username") else ""
                return (
                    "📌 *Permanent Context*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"🗣 *Chat:* {name}{username} · `{target_cid}`\n\n"
                    "📌 *Pinned info / rules:*\n"
                    f"{pinned}\n\n"
                    "📝 *Custom notes:*\n"
                    f"{notes}\n\n"
                    "🧠 *AI voice profile:*\n"
                    f"{voice_str}\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"_Update notes: `/setcontext {target_cid} <notes>` · Refresh pins: `/syncpins {target_cid}`_"
                )
            except ValueError:
                return (
                    "❌ /showcontext failed\n"
                    "Missing: Valid integer chat ID\n"
                    "Fix: /showcontext <chat_id> (e.g. /showcontext -1001234567890)"
                )

        if cmd == "/delcontext":
            if len(cmd_parts) < 2:
                return (
                    "❌ /delcontext failed\n"
                    "Missing: Chat ID\n"
                    "Fix: /delcontext <chat_id> (e.g. /delcontext -1001234567890)"
                )
            try:
                target_cid = int(cmd_parts[1])
                ok = self.db.delete_permanent_context(target_cid)
                if ok:
                    return f"🗑️ Permanent context for chat `{target_cid}` has been removed."
                return f"No permanent context found for chat `{target_cid}`."
            except ValueError:
                return (
                    "❌ /delcontext failed\n"
                    "Missing: Valid integer chat ID\n"
                    "Fix: /delcontext <chat_id> (e.g. /delcontext -1001234567890)"
                )

        if cmd in ("/backup", "/exportdb"):
            db_path = getattr(self.db, "db_path", None)
            if not db_path or not db_path.exists():
                return (
                    "❌ /backup failed\n"
                    "Missing: Database file\n"
                    "Fix: Ensure database path exists in configuration"
                )
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

        return None

    async def _route_persona_identity(self, cmd: str, cmd_parts: list[str], text: str) -> Optional[str]:
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
                    return (
                        "❌ /style failed\n"
                        "Missing: Valid integer chat ID\n"
                        "Fix: /style <chat_id> <style> (e.g. /style 123456 formal)"
                    )
                target_style = cmd_parts[2].lower().strip()
                if target_style in ("default", "clear", "reset", "none"):
                    self.db.set_state(f"chat_style_{target_cid}", "")
                    if hasattr(self.db, "sync_chat_context_file"):
                        self.db.sync_chat_context_file(target_cid)
                    return f"🔄 Chat `{target_cid}` reset to default global style (*{self.generator.style}*)."
                if target_style not in ("casual", "concise", "formal", "humorous"):
                    return (
                        "❌ /style failed\n"
                        "Missing: Valid style option\n"
                        "Fix: /style <chat_id> casual|concise|formal|humorous|default"
                    )
                self.db.set_state(f"chat_style_{target_cid}", target_style)
                if hasattr(self.db, "sync_chat_context_file"):
                    self.db.sync_chat_context_file(target_cid)
                return f"🎨 Chat `{target_cid}` custom AI persona set to *{target_style}*."

            target_style = cmd_parts[1].lower().strip()
            ok = self.generator.set_style(target_style)
            if ok:
                self.db.set_state("reply_style", target_style)
                return f"🎨 Global AI response style switched to *{target_style}*."
            return (
                "❌ /style failed\n"
                "Missing: Valid style option\n"
                "Fix: /style casual|concise|formal|humorous"
            )

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

        if cmd == "/chatprompt":
            if len(cmd_parts) < 2:
                lines = ["🗣 *Per-Chat AI Personas:*"]
                overrides_found = 0
                priv, grps = self.privacy.get_all_allowed_chats()
                for cid in sorted(priv | grps):
                    p = self.db.get_state(f"chat_prompt_{cid}")
                    if p:
                        overrides_found += 1
                        meta = self.db.get_chat_metadata(cid) or {}
                        name = meta.get("title") or f"Chat {cid}"
                        preview = p[:60] + ("…" if len(p) > 60 else "")
                        lines.append(f"• {name} (`{cid}`): _{preview}_")
                if not overrides_found:
                    lines.append("• _All chats currently use the default global persona._")
                lines.append(
                    "\n*Usage:* `/chatprompt <chat_id> <prompt>` — custom AI behavior for that chat only.\n"
                    "*Example:* `/chatprompt -1001234567890 Talk like a crypto trader, use Hindi slang, keep replies under 5 words.`\n"
                    "_Reset: `/chatprompt <chat_id> default`_"
                )
                return "\n".join(lines)
            try:
                target_cid = int(cmd_parts[1])
            except ValueError:
                return (
                    "❌ /chatprompt failed\n"
                    "Missing: Valid integer chat ID\n"
                    "Fix: /chatprompt <chat_id> <prompt> (e.g. /chatprompt -1001234567890 Talk like a crypto trader)"
                )
            persona_text = " ".join(cmd_parts[2:]).strip()
            if persona_text.lower() in ("default", "clear", "reset", "none", ""):
                self.db.set_state(f"chat_prompt_{target_cid}", "")
                if hasattr(self.db, "sync_chat_context_file"):
                    self.db.sync_chat_context_file(target_cid)
                meta = self.db.get_chat_metadata(target_cid) or {}
                name = meta.get("title") or f"Chat {target_cid}"
                return f"🔄 {name} (`{target_cid}`) reset to the default global persona."
            if len(persona_text) < 5:
                return (
                    "❌ /chatprompt failed\n"
                    "Missing: Meaningful persona description\n"
                    "Fix: /chatprompt <chat_id> <prompt> (write at least a few words describing how the AI should talk)"
                )
            self.db.set_state(f"chat_prompt_{target_cid}", persona_text)
            if hasattr(self.db, "sync_chat_context_file"):
                self.db.sync_chat_context_file(target_cid)
            meta = self.db.get_chat_metadata(target_cid) or {}
            name = meta.get("title") or f"Chat {target_cid}"
            username = f" ({'@' + meta['username']})" if meta.get("username") else ""
            return (
                "✅ *Per-Chat Persona Saved*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"🗣 *Chat:* {name}{username} · `{target_cid}`\n\n"
                f"*Custom persona:*\n_{persona_text}_\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "_The AI follows this persona only in this chat; all other chats keep the default._"
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

        if cmd in ("/chatty", "/banter"):
            if len(cmd_parts) < 2:
                curr_prob = float(self.db.get_state(
                    "chatty_probability",
                    str(getattr(self.config, "chatty_probability", 0.15))
                ))
                lines = [
                    "💬 *Group Banter Rate*",
                    "━━━━━━━━━━━━━━━━━━━━",
                    f"🌐 *Global default:* `{int(curr_prob * 100)}%`",
                    "🎯 *Unset chats:* random 30–60% band (natural human default)",
                    "",
                    "*Per-chat settings:*",
                ]
                overrides_found = 0
                priv, grps = self.privacy.get_all_allowed_chats()
                for cid in sorted(grps):
                    p = self.db.get_state(f"chat_chatty_{cid}")
                    if p:
                        overrides_found += 1
                        meta = self.db.get_chat_metadata(cid) or {}
                        name = meta.get("title") or f"Group {cid}"
                        try:
                            pct = int(float(p) * 100)
                            lines.append(f"• {name} (`{cid}`): *{pct}%*")
                        except ValueError:
                            continue
                if not overrides_found:
                    lines.append("• _No per-chat overrides — every group uses the global default / band._")
                lines.append(
                    "\n👇 *Tap a chat below to set its banter %* — or globally: `/chatty off` (mention-only) · `/chatty <0-100>`."
                )
                return "\n".join(lines)
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

        if cmd == "/name":
            if len(cmd_parts) < 2 or cmd_parts[1].lower() in ("sync", "fetch", "auto"):
                synced = await self.sync_owner_name_from_telegram()
                return f"✅ Identity name: *'{synced}'* (synced directly from Telegram profile).\nUsage: `/name <CustomName>` or `/name sync`"
            new_name = " ".join(cmd_parts[1:]).strip()
            self.generator.set_owner_name(new_name)
            self.db.set_state("owner_name", new_name)
            return f"✅ Identity updated! The AI will now reply as '{new_name}'."

        if cmd in ("/prompt", "/showprompt", "/getprompt", "/activeprompt"):
            # '/prompt <your prompt here>' sets the persona directly (matching the bot menu usage);
            # bare '/prompt' (or '/prompt view') shows the active instructions.
            persona_text = text[len(cmd_parts[0]):].strip()
            if persona_text and persona_text.lower() not in ("view", "show"):
                return await self.handle_control_command("/setprompt " + persona_text)
            custom = self.generator.prompt_manager.custom_prompt
            mode_str = f"Custom Persona ({len(custom.split())} words)" if custom else "Default Persona"
            full_inst = self.generator.prompt_manager.system_instructions
            custom_display = f'"{custom}"' if custom else "None — using default system_prompt.txt"
            if len(custom_display) > 1200:
                custom_display = custom_display[:1100].rstrip() + '...[truncated]'
            # Keep the whole response well under Telegram's 4096-char message limit, or delivery fails silently
            prompt_preview = full_inst if len(full_inst) <= 2400 else (full_inst[:2360].rstrip() + "\n...[truncated for Telegram display]")
            from app import __version__ as app_version
            return (
                f"📜 *Active System Instructions*  `v{app_version}`\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🧬 *Persona*\n"
                f"　• Source: *{mode_str}*\n"
                f"　• Custom text: {custom_display}\n\n"
                f"🛡️ *Guardrails*\n"
                f"　• Anti-AI guardrails: *ACTIVE* — natural human length (one word to one short line), "
                f"any Telegram emoji placed naturally, no names/@usernames, no code\n"
                f"　• Style: `{self.generator.style}` · Language: `{self.generator.language}`\n\n"
                f"🧠 *Compiled Prompt (sent to AI)*\n"
                f"　• Length: `{len(full_inst)} chars`\n\n"
                f"{prompt_preview}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"_💡 `/setprompt <text>` customize · `/setprompt default` reset_"
            )

        if cmd == "/setprompt":
            if len(cmd_parts) < 2:
                return (
                    "❌ /setprompt failed\n"
                    "Missing: Prompt text\n"
                    "Fix: /setprompt <new prompt text> or /setprompt default to reset"
                )
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

        return None

    async def _route_humanization(self, cmd: str, cmd_parts: list[str], text: str) -> Optional[str]:
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

        if cmd in ("/sleep", "/goodnight"):
            if len(cmd_parts) >= 2 and cmd_parts[1].lower() in ("off", "stop", "wake", "resume"):
                self.safety.set_quiet_hours(False)
                return "☀️ Quiet hours *DISABLED*. Automated replies and reactions are now active 24/7."
            await self.maybe_send_quiet_hours_goodnight(force=True)
            self.safety.set_quiet_hours(True)
            s, e = self.safety.quiet_hours_window
            return (
                f"🌙 *Goodnight sign-off sent!* Quiet hours (sleep schedule {s}–{e}) is now *ON*.\n"
                f"Auto-replies are paused. Send `/quiethours off` or `/resume` to wake up anytime."
            )

        if cmd in ("/quiethours", "/quiet"):
            if len(cmd_parts) < 2:
                qh_enabled = self.safety.quiet_hours_enabled
                qh_start, qh_end = self.safety.quiet_hours_window
                is_quiet, _ = self.safety.is_in_quiet_hours()
                _ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
                now_str = datetime.datetime.now(_ist).strftime("%H:%M")
                status_title = "ON" if qh_enabled else "OFF"
                sleep_state = "Sleeping 💤 (Auto-replies & reactions paused)" if is_quiet else "Awake ☀️ (Active)"
                return (
                    f"🌙 *Quiet Hours (Sleep Schedule):* *{status_title}*\n"
                    f"　• Schedule: `{qh_start}` → `{qh_end}` *IST* (UTC+5:30)\n"
                    f"　• Current time: `{now_str} IST`\n"
                    f"　• State: *{sleep_state}*\n\n"
                    f"*Commands:*\n"
                    f"　• `/quiethours on [start] [end]` — turn ON (e.g. `/quiethours on 23:00 07:00`)\n"
                    f"　• `/quiethours off` — turn OFF sleep schedule\n"
                    f"　• `/quiethours <start> <end>` — update schedule & enable (e.g. `/quiethours 01:00 08:00`)"
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
                        return (
                            "❌ /quiethours failed\n"
                            "Missing: Valid 24h format times (HH:MM)\n"
                            "Fix: /quiethours on 23:00 07:00 (e.g. start at 23:00, wake at 07:00 IST)"
                        )
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
                    return (
                        "❌ /quiethours failed\n"
                        "Missing: Valid 24h format times (HH:MM)\n"
                        "Fix: /quiethours 23:00 07:00 (e.g. 23:00 07:00)"
                    )
                self.safety.set_quiet_hours(True, t_start, t_end)
                return f"🌙 Quiet hours schedule set to *{t_start}* – *{t_end}* and *ENABLED*."

            return "Usage: `/quiethours on [start] [end]`, `/quiethours off`, or `/quiethours <start> <end>`"

        if cmd in ("/typo", "/typos", "/typosim"):
            if len(cmd_parts) < 2:
                typo_on = self.db.get_state("typo_correction_enabled", "1") == "1"
                status = "ON (3-5% chance)" if typo_on else "OFF"
                return (
                    f"✍️ *Typo & Self-Edit Simulation:* *{status}*\n"
                    f"Simulates occasional realistic smartphone touchscreen typos, then seamlessly edits the message clean 1-3s later (just like a real human noticing and fixing their text in-place).\n\n"
                    f"• `/typo on` - Enable natural typo and in-place self-edit\n"
                    f"• `/typo off` - Disable typo simulation"
                )
            target = cmd_parts[1].lower().strip()
            if target == "on":
                self.db.set_state("typo_correction_enabled", "1")
                return "✍️ Typo & self-edit simulation *ENABLED* (~4% natural occurrence, edits in-place)."
            elif target == "off":
                self.db.set_state("typo_correction_enabled", "0")
                return "🔒 Typo simulation *DISABLED*."
            return "Usage: `/typo on` or `/typo off`"

        if cmd in ("/editfix", "/editself", "/selfedit"):
            if len(cmd_parts) < 2:
                fix_on = self.db.get_state("editfix_enabled", "1") == "1"
                status = "ON (~10% chance)" if fix_on else "OFF"
                return (
                    f"✏️ *Self-Edit Fix Simulation:* *{status}*\n"
                    f"Occasionally sends a reply with a small typo, then edits the same message clean 2-3s later (like a human re-reading and fixing).\n\n"
                    f"• `/editfix on` - Enable self-edit simulation\n"
                    f"• `/editfix off` - Disable self-edit simulation"
                )
            target = cmd_parts[1].lower().strip()
            if target == "on":
                self.db.set_state("editfix_enabled", "1")
                return "✏️ Self-edit fix simulation *ENABLED* (~10% of replies)."
            elif target == "off":
                self.db.set_state("editfix_enabled", "0")
                return "🔒 Self-edit fix simulation *DISABLED*."
            return "Usage: `/editfix on` or `/editfix off`"

        if cmd in ("/ownreact", "/ownreaction", "/selfreact"):
            if len(cmd_parts) < 2:
                own_on = self.db.get_state("ownreact_enabled", "1") == "1"
                status = "ON (~20% chance)" if own_on else "OFF"
                return (
                    f"🫵 *Own-Reply Reaction:* *{status}*\n"
                    f"Occasionally reacts to your own sent message with a fitting emoji (respecting all reaction cooldowns).\n\n"
                    f"• `/ownreact on` - Enable own-reply reactions\n"
                    f"• `/ownreact off` - Disable own-reply reactions"
                )
            target = cmd_parts[1].lower().strip()
            if target == "on":
                self.db.set_state("ownreact_enabled", "1")
                return "🫵 Own-reply reactions *ENABLED* (~20% of replies)."
            elif target == "off":
                self.db.set_state("ownreact_enabled", "0")
                return "🔒 Own-reply reactions *DISABLED*."
            return "Usage: `/ownreact on` or `/ownreact off`"

        if cmd in ("/reactioncooldown", "/reactcd", "/reactionlimit", "/reactioninterval"):
            min_react = float(self.db.get_state(
                "reaction_min_cooldown_seconds",
                str(getattr(self.config, "reaction_min_cooldown_seconds", 15.0))
            ))
            max_react = float(self.db.get_state(
                "reaction_max_cooldown_seconds",
                str(getattr(self.config, "reaction_max_cooldown_seconds", 60.0))
            ))
            max_r = self.db.get_state("reaction_max_per_window", str(getattr(self.config, "reaction_max_per_window", 4)))
            win_m = int(float(self.db.get_state("reaction_window_seconds", str(getattr(self.config, "reaction_window_seconds", 600.0)))) // 60)

            if len(cmd_parts) < 2:
                return (
                    f"⚡ *Reaction Cooldown Settings:*\n"
                    f"• Interval: Random `{int(min_react)}s` to `{int(max_react)}s` between reactions\n"
                    f"• Rolling Rate Limit: Max *{max_r}* reactions per *{win_m}* minutes\n\n"
                    f"*Commands:*\n"
                    f"• `/reactioncooldown <min_sec> <max_sec>` - Set random interval (e.g. `/reactioncooldown 15 60`)\n"
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
                    return (
                        "❌ /reactioncooldown failed\n"
                        "Missing: Valid numbers for count and minutes\n"
                        "Fix: /reactioncooldown limit <max_count> <window_mins> (e.g. /reactioncooldown limit 4 10)"
                    )

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
                    return (
                        "❌ /reactioncooldown failed\n"
                        "Missing: Valid numeric cooldown values\n"
                        "Fix: /reactioncooldown <min_sec> <max_sec> (e.g. /reactioncooldown 15 60)"
                    )

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
                return (
                    "❌ /chatcooldown failed\n"
                    "Missing: Valid integer seconds\n"
                    "Fix: /chatcooldown <min> <max> (e.g. /chatcooldown 5 60) or /chatcooldown 30"
                )

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
                return (
                    "❌ /globalcooldown failed\n"
                    "Missing: Valid integer seconds\n"
                    "Fix: /globalcooldown <min> <max> (e.g. /globalcooldown 5 60) or /globalcooldown 15"
                )

        if cmd in ("/ratelimit", "/spamlimits", "/rate", "/antispam"):
            if len(cmd_parts) < 2:
                recent_min = self.db.get_recent_reply_count(60.0) if hasattr(self.db, "get_recent_reply_count") else 0
                return (
                    f"🛡️ *Telegram Anti-Spam Rate Limits:*\n"
                    f"• Burst Limit: *{self.safety.max_replies_per_minute}* replies/min base, dynamic *(Used in last 60s: *{recent_min}*)*\n"
                    f"• Per-Chat Limit: *{self.safety.max_chat_replies_per_minute}* replies/min per chat\n"
                    f"• Chat Cooldown: *{int(self.safety.min_chat_cooldown)}s – {int(self.safety.max_chat_cooldown)}s*\n"
                    f"• Global Cooldown: *{int(self.safety.min_global_cooldown)}s – {int(self.safety.max_global_cooldown)}s*\n\n"
                    f"The per-minute cap randomly fluctuates around your base value and auto-boosts in busy chats (human-style).\n"
                    f"Usage: `/ratelimit <per_minute>` (e.g. `/ratelimit 5`)"
                )
            try:
                per_min = max(1, int(cmd_parts[1]))
                self.db.set_state("max_replies_per_minute", str(per_min))
                return f"✅ Anti-spam base burst limit updated to *{per_min}* replies/min (dynamic range applies on top)."
            except ValueError:
                return (
                    "❌ /ratelimit failed\n"
                    "Missing: Valid positive integer rate limit\n"
                    "Fix: /ratelimit <per_minute> (e.g. /ratelimit 5)"
                )

        if cmd in ("/followup", "/followups", "/spontaneous"):
            if len(cmd_parts) > 1:
                sub = cmd_parts[1].lower().strip()
                if sub in ("on", "enable", "1"):
                    self.db.set_state("spontaneous_followup_enabled", "1")
                    return "✅ Spontaneous delayed follow-ups *ENABLED* (10–20s later for 1–3 word replies)."
                elif sub in ("off", "disable", "0"):
                    self.db.set_state("spontaneous_followup_enabled", "0")
                    return "🛑 Spontaneous delayed follow-ups *DISABLED*."
            curr = "ENABLED" if self.db.get_state("spontaneous_followup_enabled", "1") == "1" else "DISABLED"
            return f"💬 Spontaneous follow-ups: *{curr}* (Toggle with `/followup <on|off>`)."

        if cmd in ("/debounce", "/burst", "/debouncer"):
            if len(cmd_parts) > 1:
                sub = cmd_parts[1].lower().strip()
                if sub in ("on", "enable", "1"):
                    self.db.set_state("debounce_enabled", "1")
                    curr_sec = self.db.get_state("debounce_seconds", "3.0")
                    return f"✅ Message burst debouncer *ENABLED* ({curr_sec}s stitching window)."
                elif sub in ("off", "disable", "0"):
                    self.db.set_state("debounce_enabled", "0")
                    return "🛑 Message burst debouncer *DISABLED* (messages processed immediately)."
                else:
                    try:
                        sec = float(sub)
                        sec = max(0.5, min(10.0, sec))
                        self.db.set_state("debounce_enabled", "1")
                        self.db.set_state("debounce_seconds", str(sec))
                        return f"⏱️ Message burst debouncer set to *{sec}s* window."
                    except ValueError:
                        return "Usage: `/debounce on`, `/debounce off`, or `/debounce <0.5-10.0>`"
            curr = "ENABLED" if self.db.get_state("debounce_enabled", "1") == "1" else "DISABLED"
            curr_sec = self.db.get_state("debounce_seconds", "3.0")
            return f"💬 Burst debouncer: *{curr}* ({curr_sec}s window). Toggle with `/debounce <on|off|seconds>`."

        if cmd in ("/multibubble", "/split", "/bubbles"):
            if len(cmd_parts) > 1:
                sub = cmd_parts[1].lower().strip()
                if sub in ("on", "enable", "1"):
                    self.db.set_state("multibubble_enabled", "1")
                    return "✅ Multi-bubble response splitting *ENABLED* (rapid 1.2–2.5s sequential bubbles)."
                elif sub in ("off", "disable", "0"):
                    self.db.set_state("multibubble_enabled", "0")
                    return "🛑 Multi-bubble response splitting *DISABLED* (replies sent in single message)."
            curr = "ENABLED" if self.db.get_state("multibubble_enabled", "1") == "1" else "DISABLED"
            return f"💬 Multi-bubble response splitting: *{curr}* (Toggle with `/multibubble <on|off>`)."

        return None

    async def _route_ai_settings(self, cmd: str, cmd_parts: list[str], text: str) -> Optional[str]:
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

            model_lines = []
            for bm in stats["by_model"]:
                model_lines.append(f"• `{bm['model']}`: {bm['tokens']:,} tokens ({bm['calls']} requests)")
            by_model_str = "\n".join(model_lines) if model_lines else "• _No API requests logged yet._"

            return (
                f"📊 *Inception Labs / AI Token Tracker:*\n\n"
                f"• Total AI Requests: `{reqs:,}`\n"
                f"• Total Tokens Used: *{tot_tokens:,}* / 100,000,000 ({used_pct:.4f}%)\n"
                f"• 24h Daily Consumption: *{daily_tokens:,}* tokens\n"
                f"• Prompt Tokens: `{p_tokens:,}`\n"
                f"• Completion Tokens: `{c_tokens:,}`\n"
                f"• Remaining Free Quota: *{rem_tokens:,}* tokens\n\n"
                f"*Breakdown by Model:*\n{by_model_str}"
            )

        if cmd in ("/quotathreshold", "/threshold"):
            return "ℹ️ Daily token quota threshold alerts have been disabled and removed."

        if cmd in ("/quotaalert", "/thresholdalert"):
            return "ℹ️ Daily quota warning alerts have been disabled and removed."

        if cmd in ("/thinking", "/reasoning", "/effort"):
            if len(cmd_parts) < 2:
                curr = self.db.get_state("ai_reasoning_effort", "default")
                return (
                    f"🧠 *Current AI Thinking/Reasoning Effort:* `{curr}` (Default: `default`)\n\n"
                    f"*Options:*\n"
                    f"• `/thinking default` - Model's native default thinking (Default, no forced low/high)\n"
                    f"• `/thinking low` - Ultra-fast discrete generation\n"
                    f"• `/thinking medium` - Balanced reasoning depth\n"
                    f"• `/thinking high` - In-depth logical analysis\n"
                    f"• `/thinking off` - Disable explicit reasoning effort parameter"
                )
            target = cmd_parts[1].lower().strip()
            if target not in ("default", "low", "medium", "high", "off", "none"):
                return (
                    "❌ /thinking failed\n"
                    "Missing: Valid reasoning effort option\n"
                    "Fix: /thinking <default|low|medium|high|off> (e.g. /thinking medium)"
                )
            self.db.set_state("ai_reasoning_effort", target)
            if hasattr(self.generator.provider, "reasoning_effort"):
                self.generator.provider.reasoning_effort = target
            return f"🧠 AI thinking/reasoning effort set to *{target}*."

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
                return (
                    "❌ /temp failed\n"
                    "Missing: Valid temperature between 0.0 and 1.0\n"
                    "Fix: /temp <0.0-1.0> (e.g. /temp 0.7)"
                )

        if cmd in ("/maxtokens", "/maxoutput"):
            if len(cmd_parts) < 2:
                curr = self.db.get_state("ai_max_tokens", "")
                curr_display = curr if curr else "default (provider decided)"
                return f"📝 *Current Max Output Tokens:* `{curr_display}`\nUsage: `/maxtokens <tokens>` or `/maxtokens default`"
            target = cmd_parts[1].lower().strip()
            if target in ("default", "reset", "auto", "provider", "none", "off"):
                self.db.set_state("ai_max_tokens", "")
                if hasattr(self.generator.provider, "max_tokens"):
                    self.generator.provider.max_tokens = None
                return "📝 AI max output tokens reset to *default* (let provider decide)."
            try:
                val = max(10, int(cmd_parts[1]))
                self.db.set_state("ai_max_tokens", str(val))
                if hasattr(self.generator.provider, "max_tokens"):
                    self.generator.provider.max_tokens = val
                return f"📝 AI max output tokens set to *{val}*."
            except ValueError:
                return (
                    "❌ /maxtokens failed\n"
                    "Missing: Valid integer >= 10 or 'default'\n"
                    "Fix: /maxtokens <tokens> (e.g. /maxtokens 150) or /maxtokens default"
                )

        if cmd in ("/aiconfig", "/aisettings"):
            prov = self.db.get_state("ai_provider", self.config.ai_provider)
            mod = self.db.get_state("ai_model", self.config.ai_model or "mercury-3")
            url = self.db.get_state("ai_base_url", self.config.ai_base_url or "https://api.inceptionlabs.ai/v1")
            eff = self.db.get_state("ai_reasoning_effort", "default")
            temp = self.db.get_state("ai_temperature", "0.6")
            raw_mtok = self.db.get_state("ai_max_tokens", "")
            mtok = raw_mtok if raw_mtok else "default (provider decided)"
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
                f"• Thinking / Reasoning Effort: `{eff}` (change via `/thinking <effort>`)\n"
                f"• Temperature: `{temp}` (change via `/temp <0.0-1.0>`)\n"
                f"• Max Output Tokens: `{mtok}` (change via `/maxtokens <tokens>`)\n\n"
                f"_Quick Setup:_ `/setai <provider> <api_key> <endpoint> [model]` or `/setai mercury <key>`\n"
                f"_Send `/checkmodels` to ping and verify candidate models in real-time._"
            )

        if cmd in ("/checkmodels", "/testmodels"):
            curr_key = self.db.get_state("ai_api_key", self.config.ai_api_key or "").strip()
            if not curr_key:
                return (
                    "❌ /checkmodels needs an API key.\n"
                    "Missing: AI_API_KEY\n"
                    "Fix: /setai gemini <your-key> or /setai mercury <your-key>"
                )
            if not hasattr(self.generator.provider, "check_working_models"):
                return (
                    "❌ /checkmodels failed\n"
                    "Missing: OpenAI or Custom compatible provider\n"
                    "Fix: Live model verification is supported on OpenAI and Inception Labs custom providers. Use /setai mercury <key> or /provider custom."
                )
            results = self.generator.provider.check_working_models()
            lines = ["🔍 *Model Live Health Check:*"]
            for m, ok, detail in results:
                icon = "✅" if ok else "❌"
                lines.append(f"{icon} `{m}`: {detail}")
            active = getattr(self.generator.provider, "model", "")
            lines.append(f"\n🎯 Active working model set to: *{active}*")
            self.db.set_state("ai_model", active)
            return "\n".join(lines)

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
            return (
                "❌ /provider failed\n"
                "Missing: Supported provider name\n"
                "Fix: /provider <custom|gemini|openai|nvidia|local> (e.g. /provider custom)"
            )

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
                    "❌ /setai failed\n"
                    "Missing: Required provider and API key arguments\n"
                    "Fix: /setai mercury <api_key> OR /setai <provider> <api_key> <endpoint_url> [models]"
                )

        return None
