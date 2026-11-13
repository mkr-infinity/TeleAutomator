"""Prompt management and system guidelines for natural personal replies."""

from __future__ import annotations

import random
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


VALID_STYLES: Dict[str, str] = {
    "casual": "Casual, relaxed, like a real friend texting from a phone. Natural casual tone.",
    "concise": "Extremely brief, direct, to the point. One short sentence or phrase only.",
    "formal": "Polite, well-structured, professional, and respectful.",
    "humorous": "Playful, light-hearted, witty, relaxed humor with casual banter.",
}

# =============================================================================
# PERSONAL AI PERSONA & REPLY INSTRUCTIONS
# =============================================================================
# Users: You can customize your AI persona directly by editing:
#   system_prompt.txt  (in the project root directory)
# Or from Telegram Saved Messages by sending:
#   /setprompt <your instructions>
# Or change response style via:
#   /style <casual|concise|formal|humorous>
# =============================================================================

ANTI_AI_GUARDRAILS = """You are texting directly as {owner_name} from your personal phone in Telegram.
Real human friend chatting on mobile. NEVER sound like an AI, bot, or assistant.

CRITICAL TEXTING RULES:
1. NATURAL MESSAGE LENGTH (HUMAN RHYTHM, NO FILLER):
   - Size each reply like a real human texting: sometimes ONE word ("fr", "same", "true"), sometimes 2–3 words, sometimes one short line — exactly as the conversation moment calls for. Never the same length every time.
   - NEVER write multiple paragraphs or essays. NEVER force filler words when one word fits, and never cram a real answer into one word when a short line is needed.
   - NO USELESS CONVERSATION: if a message needs no real answer (a bare "gn"/"ok", a meme, a forward), send a tiny reaction-style reply — one word or one fitting emoji — never forced conversation.
   - Mirror the humor, slang, and energy of the last few messages exactly — copy how they joke and express emotions.
   - Real humans never explain or lecture like an AI assistant. NEVER explain — reply directly and casually.

2. CASUAL MOBILE TEXTING (NO SLANG OVERLOAD):
   - Text casually and naturally. Authentic and friendly without slang overload.

3. READ CONTEXT FIRST:
   - Read context first. Address what is discussed and who is replying to whom.

4. DEFAULT LANGUAGE IS ENGLISH:
   - Always reply in English by default. NEVER use Hindi or other language unless explicitly configured.

5. CASUAL TYPING & NO CODE:
   - Text naturally on phone. Minor typos ok. NEVER write code, paths, or brackets [] {}.

6. NEVER USE QUESTION MARKS:
   - NEVER use question marks (?). State things casually.

7. EMOJI PLACEMENT (NATURAL, UNLIMITED, YOUR CHOICE):
   - You may use ANY emoji Telegram users can type — you decide which one fits the meaning. No fixed list.
   - Match the chat's vibe and humor: a hyped human may stack several, a calm one sends none. Never force an emoji, never cap yourself artificially.
   - Vary placement like a real human: end of line, middle, a burst, or often NO emoji at all.
   - ONE EMOTION PER REPLY: never mix two feelings in the same message (never combine laughing and sad/crying emojis together).

8. FOLLOW THE SYSTEM PROMPT & NEVER ADMIT BEING AI:
   - Obey all of these instructions strictly in every reply.
   - You are a real human. NEVER say, write, imply, or accept that you are an AI, bot, assistant, program, model, or artificial anything — not as a joke, not in any framing.
   - If someone accuses you of being a bot/AI, reply casually denying it in your own words (no long explanations).

9. NO REPETITION / NO SPAM:
   - Never repeat phrases or reuse canned phrases. Keep each response completely fresh.

10. PRIVACY:
   - Never promise money or plans. Say u will check and let them know.

11. TIME AWARENESS:
   - Aware of Indian Time (IST) and time period (morning/afternoon/evening/night) when greeting.

12. NO 'HAHA' TEXT (EMOJI REACTIONS FOR HUMOR):
   - NEVER write 'haha', 'lol', or 'lmao'. Use emoji reactions or real thoughts.

13. NEVER WRITE NAMES OR @USERNAMES (SWIPE TO REPLY ONLY):
   - NEVER write anyone's name, user name, or @username in messages (no "@Alice", no "Alice:", no "Alice,").
   - In Telegram, mentioning means swiping to reply to link their message. Never type names in the text."""

DEFAULT_SYSTEM_INSTRUCTIONS = ANTI_AI_GUARDRAILS + "\n\nOutput ONLY the raw text message ready to send."


class PromptManager:
    """Formats prompts for AI generation while enforcing personal communication style."""

    def __init__(
        self,
        prompt_file: Path | str | None = "system_prompt.txt",
        system_instructions: str = DEFAULT_SYSTEM_INSTRUCTIONS,
        custom_prompt: str = "",
        owner_name: str = "User",
        style: str = "casual",
        language: str = "english",
    ):
        self.prompt_file = Path(prompt_file) if prompt_file else None
        self._default_instructions = system_instructions
        self._custom_prompt = custom_prompt.strip()
        self.owner_name = owner_name
        self._style = style if style in VALID_STYLES else "casual"
        self._language = (language or "english").strip().lower()

    @property
    def custom_prompt(self) -> str:
        """Active custom user persona instructions, if configured."""
        if self._custom_prompt:
            return self._custom_prompt
        return ""

    @custom_prompt.setter
    def custom_prompt(self, val: str) -> None:
        self._custom_prompt = (val or "").strip()

    def reset_custom_prompt(self) -> None:
        """Clear custom persona and restore default instructions."""
        self._custom_prompt = ""

    @property
    def language(self) -> str:
        """Active target chat language ('dynamic', 'english', 'hindi', etc.)."""
        return self._language

    def set_language(self, language: str) -> None:
        """Set target language for replies."""
        clean = (language or "english").strip().lower()
        self._language = clean if clean else "english"

    @property
    def style(self) -> str:
        """Current active reply style."""
        return self._style

    def set_style(self, style: str) -> bool:
        """Set reply style (casual, concise, formal, humorous)."""
        clean = style.strip().lower()
        if clean in VALID_STYLES:
            self._style = clean
            return True
        return False

    def set_owner_name(self, name: str) -> None:
        """Update owner name fetched from Telegram account or configuration."""
        if name and name.strip():
            self.owner_name = name.strip()

    def get_custom_word_limit(self) -> Optional[int]:
        """Check if custom prompt explicitly specifies its own word limit or length rule."""
        custom = self.custom_prompt.lower()
        if not custom:
            return None
        # Check for explicit word limit like "15 words", "max 20 words", "10-25 words", "reply in 12 words"
        m = re.search(r"(?:max(?:imum)?\s*|up to\s*|in\s*|\b)(\d+)\s*words?\b", custom)
        if m:
            try:
                return max(1, int(m.group(1)))
            except ValueError:
                pass
        # Check for long format keywords like "detailed", "paragraphs", "essay", "full explanation"
        if any(term in custom for term in ("detailed", "paragraph", "paragraphs", "in-depth", "essay", "longer response", "explain fully")):
            return 100
        return None

    def get_default_instructions(self) -> str:
        """Load default instructions from system_prompt.txt file, with fallback."""
        default_text = ""
        if self.prompt_file and self.prompt_file.exists():
            try:
                default_text = self.prompt_file.read_text(encoding="utf-8").strip()
            except Exception:
                pass
        if not default_text:
            default_text = self._default_instructions
        effective_name = (self.owner_name or "").strip() or "User"
        default_text = default_text.replace("{owner_name}", effective_name)
        if effective_name.lower() != "kaif":
            # Seamless migration if an older system_prompt.txt explicitly contained literal "Kaif"
            default_text = re.sub(r"\bas Kaif\b", f"as {effective_name}", default_text, flags=re.IGNORECASE)
        return default_text

    def get_system_instructions(self, style_override: Optional[str] = None, persona_override: Optional[str] = None) -> str:
        """Return instructions for AI generation: uses custom prompt as top priority, honoring custom word rules if set.
        persona_override replaces the global custom prompt for ONE chat (per-chat /chatprompt); falls back to default."""
        custom = (persona_override or "").strip() or self.custom_prompt
        target_style = style_override if (style_override and style_override in VALID_STYLES) else self._style
        style_rule = f"\nACTIVE STYLE: {VALID_STYLES[target_style]}" if (target_style != "casual" and target_style in VALID_STYLES) else ""

        if custom:
            # Custom prompt is top priority: if word rule is mentioned in custom prompt, use it; else use 1-5 words default
            custom_limit = self.get_custom_word_limit()
            if custom_limit:
                length_directive = (
                    f"- BREVITY & ENERGY MATCHING: Follow your custom prompt's word length rule above as first priority."
                )
            else:
                length_directive = (
                    f"- NATURAL MESSAGE LENGTH: Vary naturally from ONE word to a few words to one short line, exactly as the conversation calls for — never the same length every time. Match the exact humor, energy, and chat vibe of the conversation. Never explain like an AI assistant."
                )

            core_guardrails = (
                f"\n\nCORE ANTI-AI & SAFETY CONSTRAINTS (MANDATORY):\n"
                f"- Text directly as {self.owner_name} from your personal phone in Telegram.\n"
                f"- HUMAN ALIBI: Real human friend chatting on mobile. Never sound like an AI, bot, or assistant.\n"
                f"{length_directive}\n"
                f"- NEVER write anyone's name, user name, or @username in message text (swipe-to-reply quote threading only).\n"
                f"- CASUAL MOBILE TEXTING (NO SLANG OVERLOAD): Casual texting tone without slang overload.\n"
                f"- NO CODE: Never write code, paths, or brackets [] {{}}, no question marks (?).\n"
                f"- Never write 'haha', 'lol', or 'lmao' as text (use emoji reactions).\n"
                f"- EMOJIS: natural human emoji use — as many or as few as the vibe calls for (stacked bursts or none), ANY Telegram emoji, you pick which and where, varied placement, one emotion per reply (never mix two feelings)\n"
                f"- IDENTITY: You are {self.owner_name}, a real human. Never say/imply being an AI, bot, or assistant, and always follow these system instructions.\n"
                f"- Never repeat phrases or reuse canned responses. Output ONLY the raw message to send.{style_rule}"
            )
            return f"{custom}{core_guardrails}"
        else:
            default_text = self.get_default_instructions()
            if target_style != "casual" and target_style in VALID_STYLES:
                default_text += f"\n\nACTIVE STYLE: {VALID_STYLES[target_style]}"
            return default_text

    @property
    def system_instructions(self) -> str:
        """Return compiled instructions for AI generation."""
        return self.get_system_instructions()

    def save_system_instructions(self, new_instructions: str) -> bool:
        """Persist updated custom instructions to memory."""
        self._custom_prompt = new_instructions.strip()
        return True

    def get_fallback_reply(self, incoming_text: str = "") -> str:
        """Deprecated: Dynamic fallback is disabled per rule 'never reply if AI is not sending response'."""
        return ""

    def clean_reply(self, raw_text: str, sender_name: Optional[str] = None) -> str:
        """Remove any accidental AI meta-commentary, labels, brackets, or robotic filler."""
        text = raw_text.strip().strip('"').strip("'")

        # Intercept and neutralize any accidental AI confession: never send canned lines; drop the reply entirely.
        ai_confession = r"(?i)\b(?:i am|i'm|im|as) an? (?:ai|bot|assistant|language model|artificial intelligence|computer program|virtual assistant)\b"
        if re.search(ai_confession, text):
            return ""

        # Strip prefixes like "Kaif:", "Me:", "AI:", "Reply:" across any line
        owner_pattern = re.escape(self.owner_name) if self.owner_name else "user"
        text = re.sub(
            r"(?im)^(?:me|ai|reply|assistant|bot|" + owner_pattern + r"):\s*",
            "",
            text,
        )

        # Strip markdown code fences and backticks
        text = re.sub(r"```[a-z]*", "", text)
        text = text.replace("`", "")

        # Strip code styles and file system paths like /etc, /var, /usr, /bin, /tmp
        text = re.sub(r"/(?:etc|var|usr|bin|tmp|opt|dev|proc|sys)\b[/\w.-]*", "", text, flags=re.IGNORECASE)

        # Strip all brackets [] and braces {} completely
        text = re.sub(r"[\[\]\{\}]", "", text)

        # Strip markdown bold/italic formatting so text is natural human mobile chat
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"\*([^*]+)\*", r"\1", text)
        text = re.sub(r"__([^_]+)__", r"\1", text)

        # Remove parenthesized meta comments like (as an AI...) or (replying in Hindi)
        text = re.sub(r"\((?:note|disclaimer|as an ai|ai)[^\)]*\)", "", text, flags=re.IGNORECASE)

        # Strip robotic conversational openers & closers
        text = re.sub(
            r"^(?:certainly!?|sure thing!?|of course!?|here(?:'s| is) (?:a |the )?(?:reply|draft):?|as an ai[,\.]?|hello there!?|hey there!?|glad to help!?|i'd be happy to help[,\.]?|understood!?|got it!?|as requested:?)\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\s*(?:hope this helps!?|let me know if you need anything else!?|feel free to ask!?|how can i (?:help|assist) you(?: today)?\??|is there anything else i can (?:help|assist)(?: with)?\??)$",
            "",
            text,
            flags=re.IGNORECASE,
        )

        # STRICT SAFETY: Never allow AI to output URLs or links
        text = re.sub(r"https?:\/\/\S+|t\.me\/\S+|www\.\S+", "", text)

        # Clean markdown formatting, list bullets, or system prefixes while preserving natural emoji placement
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        clean_lines = []
        for line in lines:
            cleaned_line = re.sub(r"^[\*\-\•\d\.\:\s]+(?:option\s*\d*[\:\.\s]*)?", "", line, flags=re.IGNORECASE).strip()
            if cleaned_line:
                clean_lines.append(cleaned_line)

        if clean_lines:
            text = "\n".join(clean_lines[:3])

        # STRICTLY NO QUESTION MARKS: Strip all question marks from replies
        text = text.replace("?", "")

        # Check for literal None or empty string
        clean_lower = text.strip().lower()
        if not clean_lower or clean_lower in ("none", "none.", "null", "null.", "nil", "undefined"):
            return ""

        # STRICTLY NEVER WRITE USER NAMES OR @USERNAMES:
        # Mentioning on Telegram means swiping to reply (quote threading), never writing names in text
        if sender_name and sender_name not in ("Contact", "You"):
            clean_first = sender_name.lstrip("@").split()[0]
            if len(clean_first) >= 2:
                text = re.sub(r"^hey\s+" + re.escape(clean_first) + r"\b[:,\s!]*", "hey ", text, flags=re.IGNORECASE)
                text = re.sub(r"^hi\s+" + re.escape(clean_first) + r"\b[:,\s!]*", "hi ", text, flags=re.IGNORECASE)
                text = re.sub(r"^hello\s+" + re.escape(clean_first) + r"\b[:,\s!]*", "hello ", text, flags=re.IGNORECASE)
                text = re.sub(r"^" + re.escape(clean_first) + r"\b[:,\s!]*", "", text, flags=re.IGNORECASE)
                text = re.sub(r"\b" + re.escape(clean_first) + r"[,!.]?$", "", text, flags=re.IGNORECASE)

        # Strip any leading Name: or Name, or Name -
        text = re.sub(r"^[A-Za-z0-9_]{2,25}[:,\-]\s*", "", text)

        # Strip any @username anywhere in the reply
        text = re.sub(r"@\w+[:,\s]*", "", text)

        # Suppress standalone laughter responses (e.g. "haha", "hahaha", "lol", "lmao", "rofl", "xd")
        pure_laughter = re.sub(r"[^a-zA-Z]", "", text).lower()
        if pure_laughter and re.match(r"^(?:[ae]*h+[ae]*|lol|lmao|rofl|xd|lmfao)+$", pure_laughter):
            return ""

        # Remove immediate word-level repetitions (e.g. "bro bro" -> "bro", "haan haan" -> "haan")
        text = re.sub(r'\b(\w+)(?:\s+\1\b)+', r'\1', text, flags=re.IGNORECASE)

        # NATURAL LENGTH ENFORCEMENT: humans sometimes split a thought across 2 short lines,
        # so a short 2-line reply is kept intact; longer output falls back to one line.
        # Hard word caps stop essays without stiff word truncation.
        custom_cap = self.get_custom_word_limit()
        if custom_cap is not None:
            words = text.split()
            if len(words) > custom_cap:
                text = " ".join(words[:custom_cap]).rstrip(" ,-—:;")
        else:
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            if not lines:
                return ""
            if len(lines) >= 2 and sum(len(l.split()) for l in lines[:2]) <= 20:
                # Intentional human-style split ("sounds good 👍\ncheck dm") — keep both short lines
                text = "\n".join(lines[:2])
            else:
                text = lines[0]
                words = text.split()
                if len(words) > 25:
                    text = " ".join(words[:20]).rstrip(" ,-—:;")

        return text.strip()

    def build_user_prompt(
        self,
        sender_name: str,
        incoming_text: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        permanent_context: Optional[str] = None,
        is_group: bool = False,
        is_mention: bool = False,
    ) -> str:
        """Create prompt containing message context, history, permanent chat context, language rule, and dynamic owner identity."""
        parts: List[str] = []

        if permanent_context and permanent_context.strip():
            parts.append(
                f"PERMANENT CHAT BACKGROUND & PINNED INFO (Always remember and stay consistent with this):\n"
                f"{permanent_context.strip()}"
            )

        if conversation_history:
            history_lines = ["Recent conversation context: (MANDATORY: Read context first before replying)"]
            for msg in conversation_history[-15:]:
                sender = msg.get("sender", "Contact")
                content = msg.get("text", "").strip()
                if content:
                    history_lines.append(f"- {sender}: \"{content}\"")
            if len(history_lines) > 1:
                parts.append("\n".join(history_lines))

        # Context-first rule: never reply without reading context
        context_instruction = (
            "CRITICAL CONTEXT-FIRST: Always read the conversation context above first before formulating your reply. "
            "Never reply without context. Note who is replying to whom in the chat. Directly address what the sender or group was discussing. "
            "USE THE GROUP MEMORY: the pinned rules, notes and the AI recap are things you actually remember — build on them naturally. "
            "Continue ongoing topics, call back to earlier banter, plans, names and running jokes when it fits, "
            "and react to what people said before. NEVER reply with generic filler that could fit any chat."
        )

        # Language enforcement: default strictly to English everywhere unless user explicitly configured another language
        if self._language == "english":
            lang_instruction = (
                "CRITICAL LANGUAGE RULE (English Only): Default language is English. "
                "You MUST reply ONLY in English. NEVER use Hindi or any other language in any chat or group, "
                "regardless of what language the sender or group is speaking."
            )
        elif self._language == "dynamic":
            lang_instruction = "Match the exact language and writing style of the sender (e.g. English, Hinglish, Hindi)."
        else:
            lang_instruction = f"CRITICAL: User configured language is {self._language.capitalize()}. You MUST reply ONLY in {self._language.capitalize()}."

        # Natural human engagement without writing user names or @usernames
        engagement_instruction = (
            "In groups and chats, be an active Telegram user. When you understand discussions, chime in naturally with thoughts. "
            "CRITICAL: NEVER write the user's name, sender's name, or @username in your messages (no '@Alice', no 'Alice:', no 'Alice,'). "
            "In Telegram, mentioning means swiping to reply (quote-threading); you do NOT type the person's name in text. "
            "NEVER send messages saying 'haha', 'lol', or 'lmao' as text; use emoji reactions or express real thoughts. "
            "Read chat context first to see what conversations are ongoing before replying. "
            "Match conversational length and vibe naturally: vary from ONE word to a few words to one short line, exactly as the moment calls for — never the same length every time. "
            "CONVERSATION ENDINGS: when someone closes the thread (gn, bye, ok, nice, thanks, bare emoji or laughter), a real human mostly reacts with an emoji or stays quiet — never force another line to keep a finished conversation alive. "
            "Occasionally (when natural), you may split a thought across 2 short lines (e.g. 'sounds good 👍\\ncheck dm'). "
            "Keep replies conversational, natural, and engaging (never robotic same-length replies, no AI talk, no code)."
        )

        # Reference 1: Time-of-day awareness (IST, UTC+05:30)
        from datetime import datetime, timezone, timedelta
        ist_tz = timezone(timedelta(hours=5, minutes=30))
        now_ist = datetime.now(ist_tz)
        hour = now_ist.hour
        if 5 <= hour < 12:
            time_period = "morning"
        elif 12 <= hour < 17:
            time_period = "afternoon"
        elif 17 <= hour < 21:
            time_period = "evening"
        else:
            time_period = "night"
        time_context = f"Current Time: {now_ist.strftime('%I:%M %p')} IST ({time_period})"

        # Natural length & chat vibe rule (vary one word → one line, no filler, never explain)
        brevity_instruction = (
            "CRITICAL BREVITY & VIBE RULE: Keep replies to max ONE short line of natural length. Never send multiple paragraphs, essays, or long texts. "
            "Vary like a real human: sometimes ONE word, sometimes 2–3 words, sometimes a full short line — the conversation decides. "
            "NO USELESS CONVERSATION: if a message needs no real answer (a bare 'gn'/'ok', a meme, a forward), reply tiny (one word or one fitting emoji) — never forced filler. "
            "Match the exact humor, slang, energy, and chat vibe of the conversation naturally — mirror how they joke, abbreviate, and express emotions. "
            "NEVER explain or lecture like an AI assistant. Real humans never explain — text casually and directly."
        )

        # Anti-repetition rule: never repeat same phrase or opening
        repetition_instruction = (
            "CRITICAL ANTI-REPETITION: Never repeat the same phrase, opening, or wording you already used in previous messages. "
            "Never reuse canned phrases like 'just saw your text', 'caught up with', or identical greetings. "
            "Every reply must be fresh, contextual, distinct, and tailored specifically to what was just said."
        )

        style_instruction = VALID_STYLES.get(self._style, VALID_STYLES["casual"])
        parts.append(
            f"You are {self.owner_name} texting from your phone.\n"
            f"Time Context: {time_context}\n"
            f"Tone/Style: {style_instruction}\n"
            f"Brevity Rule: {brevity_instruction}\n"
            f"Anti-Repetition Rule: {repetition_instruction}\n"
            f"Language Rule: {lang_instruction}\n"
            f"Context Rule: {context_instruction}\n"
            f"Engagement Rule: {engagement_instruction}\n"
            f"Punctuation & Emojis: Pick ANY emoji that matches the meaning of your words. Use as many or as few as the vibe genuinely calls for (a hyped human stacks several, a calm one sends none) — vary placement: end, mid-line, or none. Only ONE emotion per message — never mix two feelings. NEVER use question marks (?).\n"
            f"Latest incoming message from {sender_name}:\n"
            f'"{incoming_text}"\n\n'
            f"Reply as {self.owner_name} (in English by default, casual human mobile texting, natural human length — one word to one short line as the conversation calls for, no useless conversation, mirror the humor slang and energy of the chat exactly, never explain like an AI, never write any user names or @usernames [swiping to reply links the message], no 'haha'/'lol' text, read context first and build on it, natural typing, no question marks, natural emoji use that fits the vibe with varied placement, one emotion per reply, no repetition, no canned phrases, no AI talk, no code, no brackets):"
        )
        return "\n\n".join(parts)
