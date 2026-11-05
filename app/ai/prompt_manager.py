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

DEFAULT_SYSTEM_INSTRUCTIONS = """You are texting directly as me in my personal Telegram chat from your phone.
Text exactly like a real human friend. Never sound like an AI, bot, or assistant.

RULES:
1. BREVITY & ENERGY MATCHING:
   - Match the exact length and energy of the message:
     * If they send 1 word (e.g. "hii", "yo", "sup"), reply with ONLY 1 word (e.g. "hii", "hello", "yo").
     * Never write long paragraphs or unasked questions like "how are you doing today?".
     * Keep replies to 1-2 punchy lines maximum.
   - If sending 2 distinct thoughts, separate them with a newline so they send as separate text bubbles.

2. GEN-Z CASUAL SLANG:
   - Naturally use casual Gen-Z shortcuts when appropriate:
     "u" (you), "r" (are), "rn" (right now), "idk", "tbh", "ngl", "fr", "wbu", "nah", "yea", "bruh", "bro", "lol".

3. HUMAN ALIBI (NEVER ADMIT BEING AI):
   - If accused of being a bot or AI ("are u a bot?", "is this ai?", "u r fake"):
     Reply with funny, friendly disbelief:
     * "seriously bro u think I am not real? 😂"
     * "bruh u fr rn? it's me lol"
     * "lol what are u on about, typing from my phone rn"
     * "bhai kya phoonk ke baitha hai, mai hi hu 😂"

4. STRICTLY NO CODE / ARTIFACTS:
   - NEVER output code, paths (/etc, /var), programming syntax, brackets [], braces {}, markdown formatting (**bold**), or labels ("Me:", "Reply:").

5. PRIVACY:
   - Never promise money or invent plans. If asked about plans, say u will check and let them know.

Output ONLY the raw text message ready to send."""


class PromptManager:
    """Formats prompts for AI generation while enforcing personal communication style."""

    def __init__(
        self,
        prompt_file: Path | str | None = "system_prompt.txt",
        system_instructions: str = DEFAULT_SYSTEM_INSTRUCTIONS,
        owner_name: str = "Kaif",
        style: str = "casual",
        language: str = "dynamic",
    ):
        self.prompt_file = Path(prompt_file) if prompt_file else None
        self._default_instructions = system_instructions
        self.owner_name = owner_name
        self._style = style if style in VALID_STYLES else "casual"
        self._language = (language or "dynamic").strip().lower()

    @property
    def language(self) -> str:
        """Active target chat language ('dynamic', 'english', 'hindi', etc.)."""
        return self._language

    def set_language(self, language: str) -> None:
        """Set target language for replies."""
        clean = (language or "dynamic").strip().lower()
        self._language = clean if clean else "dynamic"

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

    @property
    def system_instructions(self) -> str:
        """Return instructions from system_prompt.txt if present, otherwise default."""
        base_instructions = self._default_instructions
        if self.prompt_file and self.prompt_file.exists():
            try:
                content = self.prompt_file.read_text(encoding="utf-8").strip()
                if content:
                    base_instructions = content
            except Exception:
                pass

        if self._style != "casual" and self._style in VALID_STYLES:
            return f"{base_instructions}\n\nACTIVE STYLE: {VALID_STYLES[self._style]}"
        return base_instructions

    def save_system_instructions(self, new_instructions: str) -> bool:
        """Persist updated system instructions to system_prompt.txt."""
        if not self.prompt_file:
            return False
        try:
            self.prompt_file.write_text(new_instructions.strip(), encoding="utf-8")
            return True
        except Exception:
            return False

    def clean_reply(self, raw_text: str) -> str:
        """Remove any accidental AI meta-commentary, labels, brackets, or robotic filler."""
        text = raw_text.strip().strip('"').strip("'")

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
        text = re.sub(r"^(?:certainly!?|sure thing!?|of course!?|here(?:'s| is) (?:a |the )?(?:reply|draft):?|as an ai[,\.]?)\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*(?:hope this helps!?|let me know if you need anything else!?|feel free to ask!?)$", "", text, flags=re.IGNORECASE)

        # STRICT SAFETY: Never allow AI to output URLs or links
        text = re.sub(r"https?:\/\/\S+|t\.me\/\S+|www\.\S+", "", text)

        # If model generated multiple bullet choices or "Option 1:", keep clean natural lines (max 3)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        clean_lines = []
        for line in lines:
            cleaned_line = re.sub(r"^[\*\-\•\d\.\:\s]+(?:option\s*\d*[\:\.\s]*)?", "", line, flags=re.IGNORECASE).strip()
            if cleaned_line and len(cleaned_line) > 1:
                clean_lines.append(cleaned_line)

        if clean_lines:
            text = "\n".join(clean_lines[:3])

        return text.strip()

    def build_user_prompt(
        self,
        sender_name: str,
        incoming_text: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """Create prompt containing message context, history, language rule, and dynamic owner identity."""
        parts: List[str] = []

        if conversation_history:
            history_lines = ["Recent conversation context:"]
            for msg in conversation_history[-5:]:
                sender = msg.get("sender", "Contact")
                content = msg.get("text", "").strip()
                if content:
                    history_lines.append(f"- {sender}: \"{content}\"")
            if len(history_lines) > 1:
                parts.append("\n".join(history_lines))

        # Language enforcement
        if self._language == "dynamic":
            lang_instruction = "Match the exact language and writing style of the sender (e.g. English, Hinglish, Hindi)."
        elif self._language == "english":
            lang_instruction = "CRITICAL: You MUST reply ONLY in English, regardless of the sender's language."
        else:
            lang_instruction = f"CRITICAL: You MUST reply ONLY in {self._language.capitalize()}."

        style_instruction = VALID_STYLES.get(self._style, VALID_STYLES["casual"])
        parts.append(
            f"You are {self.owner_name} texting from your phone.\n"
            f"Tone/Style: {style_instruction}\n"
            f"Language Rule: {lang_instruction}\n"
            f"Latest incoming message from {sender_name}:\n"
            f'"{incoming_text}"\n\n'
            f"Reply as {self.owner_name} (ultra-concise human Gen-Z texting, match brevity, no AI talk, no code, no brackets, separate distinct thoughts by newline):"
        )
        return "\n\n".join(parts)
