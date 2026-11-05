"""Prompt management and system guidelines for natural personal replies."""

from __future__ import annotations

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
You are a real human friend chatting casually on mobile. NEVER sound like an AI, bot, assistant, or customer rep.

CRITICAL TEXTING RULES:
1. BREVITY & ENERGY MATCHING (NATURAL HUMAN ENGAGEMENT):
   - In groups and DMs, be an active Telegram user. When you understand discussions, chime in naturally with thoughts.
   - Never write essays or blunt 1-word shortcut replies (no "nope", "dope", "yo"). Keep replies conversational (1-2 punchy lines max).

2. CASUAL MOBILE TEXTING (NO SLANG OVERLOAD):
   - Text casually and naturally. Keep language authentic, friendly, and human without slang overload.

3. READ CONTEXT FIRST (NEVER REPLY WITHOUT CONTEXT):
   - Always read conversation context before replying. Never reply without context. Directly address what is being discussed.

4. DEFAULT LANGUAGE IS ENGLISH:
   - Always reply in English by default.

5. CASUAL MOBILE TYPING & NO CODE:
   - Text naturally like on phone. Minor typos (e.g. "dont", "yeaa") are fine.
   - NEVER write code syntax, paths (/etc), code blocks, brackets [] or braces {}.

6. NEVER USE QUESTION MARKS:
   - Absolutely NEVER use question marks (?). Do not ask questions back or end sentences with '?'. State things casually.

7. EMOJI PLACEMENT (COMMONLY USED EMOJIS):
   - Use top common emojis: 😂, 👍, 🔥, 👀, 🤝, 💀, 💯, ❤️.
   - Place emojis in the MIDDLE of text between words (e.g. "haan 😂 bro was thinking the same", "all good 👍 will let u know").
   - NEVER place an emoji at the end of a message.

8. HUMAN ALIBI (NEVER ADMIT BEING AI):
   - If accused of being a bot ("are u a bot?"):
     * "seriously 😂 bro u think I am not real"
     * "bruh u fr rn it's me lol"
     * "lol typing from my phone rn"

9. NO REPETITION / NO SPAM:
   - NEVER repeat the same word twice consecutively (no "bro bro"). Never repeat the exact previous reply in chat.

10. PRIVACY:
   - Never promise money or invent plans. Say u will check and let them know."""

DEFAULT_SYSTEM_INSTRUCTIONS = ANTI_AI_GUARDRAILS.replace("{owner_name}", "Kaif") + "\n\nOutput ONLY the raw text message ready to send."


class PromptManager:
    """Formats prompts for AI generation while enforcing personal communication style."""

    def __init__(
        self,
        prompt_file: Path | str | None = "system_prompt.txt",
        system_instructions: str = DEFAULT_SYSTEM_INSTRUCTIONS,
        custom_prompt: str = "",
        owner_name: str = "Kaif",
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
        if self.prompt_file and self.prompt_file.exists():
            try:
                lines = [
                    l for l in self.prompt_file.read_text(encoding="utf-8").splitlines()
                    if not l.strip().startswith("#")
                ]
                content = "\n".join(lines).strip()
                if content and "BREVITY & ENERGY MATCHING" not in content:
                    return content
            except Exception:
                pass
        return ""

    @custom_prompt.setter
    def custom_prompt(self, val: str) -> None:
        self._custom_prompt = (val or "").strip()

    def reset_custom_prompt(self) -> None:
        """Clear custom persona and restore default instructions."""
        self._custom_prompt = ""
        if self.prompt_file and self.prompt_file.exists():
            try:
                self.prompt_file.write_text(DEFAULT_SYSTEM_INSTRUCTIONS, encoding="utf-8")
            except Exception:
                pass

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

    def get_system_instructions(self, style_override: Optional[str] = None) -> str:
        """Return instructions with specified style override, wrapping custom persona in anti-AI guardrails."""
        guardrails = ANTI_AI_GUARDRAILS.replace("{owner_name}", self.owner_name)
        custom = self.custom_prompt

        parts = [guardrails]
        if custom:
            parts.append(
                f"CUSTOM USER PERSONA & INSTRUCTIONS:\n{custom}\n"
                "Follow these instructions while strictly obeying all human texting rules above."
            )

        target_style = style_override if (style_override and style_override in VALID_STYLES) else self._style
        if target_style != "casual" and target_style in VALID_STYLES:
            parts.append(f"ACTIVE STYLE: {VALID_STYLES[target_style]}")

        parts.append("Output ONLY the raw text message ready to send.")
        return "\n\n".join(parts)

    @property
    def system_instructions(self) -> str:
        """Return compiled instructions for AI generation."""
        return self.get_system_instructions()

    def save_system_instructions(self, new_instructions: str) -> bool:
        """Persist updated custom instructions to memory and system_prompt.txt."""
        self._custom_prompt = new_instructions.strip()
        if not self.prompt_file:
            return True
        try:
            self.prompt_file.write_text(new_instructions.strip(), encoding="utf-8")
            return True
        except Exception:
            return False

    def get_fallback_reply(self, incoming_text: str = "") -> str:
        """Natural human fallback only when AI service is temporarily unavailable."""
        import random
        import re
        low = (incoming_text or "").strip().lower()
        tokens = set(re.findall(r"\w+", low))
        if any(w in tokens for w in ("bot", "ai", "real", "fake")) or "who are you" in low or "who r u" in low:
            return random.choice([
                "bruh u fr rn it's me lol",
                "seriously 😂 bro u think I am not real",
                "lol typing from phone rn",
            ])
        return random.choice([
            "haan bolo batao kya chal raha",
            "all good here, caught up with something will text properly in a bit",
            "sahi hai bro, batao aur kya update hai",
            "just saw your text, tell me what's up",
        ])

    def clean_reply(self, raw_text: str) -> str:
        """Remove any accidental AI meta-commentary, labels, brackets, or robotic filler."""
        text = raw_text.strip().strip('"').strip("'")

        # Intercept and convert any accidental AI confession or assistant identity disclosure
        ai_confession = r"(?i)\b(?:i am|i'm|im|as) an? (?:ai|bot|assistant|language model|artificial intelligence|computer program|virtual assistant)\b"
        if re.search(ai_confession, text):
            import random
            return random.choice([
                "seriously 😂 bro u think I am not real",
                "bruh u fr rn it's me lol",
                "lol typing from my phone rn",
                "bruh why would u think I'm a bot lol",
            ])

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

        # Relocate trailing emojis so they appear in between words, never at end of message
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        clean_lines = []
        emoji_rx = re.compile(r"[\U00010000-\U0010ffff\u2600-\u27bf\u2300-\u23ff\u2b50]")
        for line in lines:
            cleaned_line = re.sub(r"^[\*\-\•\d\.\:\s]+(?:option\s*\d*[\:\.\s]*)?", "", line, flags=re.IGNORECASE).strip()
            if not cleaned_line:
                continue
            trailing_emojis = []
            while cleaned_line and emoji_rx.match(cleaned_line[-1]):
                trailing_emojis.append(cleaned_line[-1])
                cleaned_line = cleaned_line[:-1].strip()
            if trailing_emojis:
                emojis_str = "".join(reversed(trailing_emojis))
                words = cleaned_line.split()
                if len(words) >= 2:
                    insert_pos = max(1, len(words) // 2)
                    words.insert(insert_pos, emojis_str)
                    clean_lines.append(" ".join(words))
                elif len(words) == 1:
                    clean_lines.append(f"{emojis_str} {words[0]}")
                else:
                    clean_lines.append(emojis_str)
            else:
                if len(cleaned_line) > 1 or cleaned_line:
                    clean_lines.append(cleaned_line)

        if clean_lines:
            text = "\n".join(clean_lines[:3])

        # STRICTLY NO QUESTION MARKS: Strip all question marks from replies
        text = text.replace("?", "")

        # Check for literal None or empty string
        clean_lower = text.strip().lower()
        if not clean_lower or clean_lower in ("none", "none.", "null", "null.", "nil", "undefined"):
            return ""

        # Remove immediate word-level repetitions (e.g. "bro bro" -> "bro", "haan haan" -> "haan")
        text = re.sub(r'\b(\w+)(?:\s+\1\b)+', r'\1', text, flags=re.IGNORECASE)

        return text.strip()

    def build_user_prompt(
        self,
        sender_name: str,
        incoming_text: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        permanent_context: Optional[str] = None,
        is_group: bool = False,
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
            for msg in conversation_history[-8:]:
                sender = msg.get("sender", "Contact")
                content = msg.get("text", "").strip()
                if content:
                    history_lines.append(f"- {sender}: \"{content}\"")
            if len(history_lines) > 1:
                parts.append("\n".join(history_lines))

        # Context-first rule: never reply without reading context
        context_instruction = (
            "CRITICAL CONTEXT-FIRST: Always read the conversation context above first before formulating your reply. "
            "Never reply without context. Directly address what the sender or group was discussing."
        )

        # Language enforcement: default to English
        if is_group:
            # Group language policy: default strictly to English unless the group conversation is in Hindi/Hinglish
            has_devanagari = any("\u0900" <= c <= "\u097f" for c in incoming_text)
            hindi_keywords = {
                "kya", "bhai", "haan", "nahi", "kaise", "kuch", "hai", "karo", "raha", 
                "rahe", "hota", "batao", "acha", "theek", "yaar", "bhaiya", "sahi", "bolo"
            }
            history_text = " ".join(m.get("text", "") for m in (conversation_history or []))
            all_text_lower = f"{incoming_text} {history_text}".lower()
            words_tokens = set(re.findall(r"\w+", all_text_lower))
            is_hindi_group = has_devanagari or len(words_tokens.intersection(hindi_keywords)) >= 2

            if is_hindi_group:
                lang_instruction = (
                    "GROUP LANGUAGE (Hindi/Hinglish): The group is conversing in Hindi/Hinglish. "
                    "You may reply naturally in Hindi or Hinglish matching the group tone."
                )
            else:
                lang_instruction = (
                    "CRITICAL GROUP LANGUAGE RULE (English Only): Default language is English. "
                    "You MUST reply ONLY in English. NEVER use Hindi or any other language in this group."
                )
        elif self._language == "dynamic":
            lang_instruction = "Match the exact language and writing style of the sender (e.g. English, Hinglish, Hindi)."
        elif self._language == "english":
            lang_instruction = "CRITICAL: Default language is English. You MUST reply ONLY in English, regardless of the sender's language."
        else:
            lang_instruction = f"CRITICAL: You MUST reply ONLY in {self._language.capitalize()}."

        # Natural human engagement without blunt 1-word shortcuts
        engagement_instruction = (
            "In groups and chats, be an active Telegram user. When you understand discussions or what members are talking about, "
            "chime in naturally with your thoughts. Keep replies conversational, natural, and engaging (1-2 punchy lines, no robotic 1-word shortcuts like nope/dope/yo, "
            "no AI talk, no code, separate distinct thoughts by newline)."
        )

        style_instruction = VALID_STYLES.get(self._style, VALID_STYLES["casual"])
        parts.append(
            f"You are {self.owner_name} texting from your phone.\n"
            f"Tone/Style: {style_instruction}\n"
            f"Language Rule: {lang_instruction}\n"
            f"Context Rule: {context_instruction}\n"
            f"Engagement Rule: {engagement_instruction}\n"
            f"Punctuation & Emojis: Use top common emojis (😂, 👍, 🔥, 👀, 🤝, 💀, 💯, ❤️) naturally in between words inside the message, NEVER at the very end. NEVER use question marks (?).\n"
            f"Latest incoming message from {sender_name}:\n"
            f'"{incoming_text}"\n\n'
            f"Reply as {self.owner_name} (in English by default, casual human mobile texting, active group engagement, read context first, natural typing, no question marks, emojis in between words, no AI talk, no code, no brackets, separate distinct thoughts by newline):"
        )
        return "\n\n".join(parts)
