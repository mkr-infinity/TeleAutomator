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
You are a real human friend texting on mobile. Never sound like an AI, bot, or virtual assistant.

CRITICAL TEXTING RULES:
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

4. STRICTLY NO CODE / ARTIFACTS / NO BOT TALK:
   - NEVER output code, paths (/etc, /var), programming syntax, brackets [], braces {}, markdown formatting (**bold**), or labels ("Me:", "Reply:").
   - NEVER use robotic phrases like "Certainly!", "Hope this helps!", "How can I assist you?".

5. PRIVACY:
   - Never promise money or invent plans. If asked about plans, say u will check and let them know."""

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
        language: str = "dynamic",
    ):
        self.prompt_file = Path(prompt_file) if prompt_file else None
        self._default_instructions = system_instructions
        self._custom_prompt = custom_prompt.strip()
        self.owner_name = owner_name
        self._style = style if style in VALID_STYLES else "casual"
        self._language = (language or "dynamic").strip().lower()

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
        """Generate an ultra-short natural human fallback when generation fails or cleans to empty."""
        import random
        import re
        low = (incoming_text or "").strip().lower()
        tokens = set(re.findall(r"\w+", low))
        if any(w in tokens for w in ("bot", "ai", "real", "fake")) or "who are you" in low or "who r u" in low:
            return random.choice([
                "bruh u fr rn? it's me lol",
                "seriously bro u think I am not real? 😂",
                "lol typing from phone rn",
            ])
        if any(w in tokens for w in ("hi", "hii", "hello", "hey", "yo", "sup", "hola", "namaste")) or "kya haal" in low:
            return random.choice(["yo", "hii", "hey", "sup"])
        if any(w in tokens for w in ("ok", "okay", "done", "got", "kk")):
            return random.choice(["👍", "cool", "done", "ok", "gotcha"])
        if any(w in tokens for w in ("thanks", "thx", "tysm")) or "thank you" in low or "thank u" in low:
            return random.choice(["anytime bro", "no worries lol", "np"])
        if any(w in tokens for w in ("what", "why", "how", "where")) or "?" in low:
            return random.choice(["will check and let u know", "gimme a sec", "haan bolo"])
        return random.choice(["haan bolo", "all good bro", "yea tell me", "yo"])

    def clean_reply(self, raw_text: str) -> str:
        """Remove any accidental AI meta-commentary, labels, brackets, or robotic filler."""
        text = raw_text.strip().strip('"').strip("'")

        # Intercept and convert any accidental AI confession or assistant identity disclosure
        ai_confession = r"(?i)\b(?:i am|i'm|im|as) an? (?:ai|bot|assistant|language model|artificial intelligence|computer program|virtual assistant)\b"
        if re.search(ai_confession, text):
            import random
            return random.choice([
                "seriously bro u think I am not real? 😂",
                "bruh u fr rn? it's me lol",
                "lol what are u on about, typing from my phone rn",
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

        # Strict brevity matching for 1-2 word messages
        clean_in = incoming_text.strip()
        word_count = len(clean_in.split())
        if word_count <= 2 and len(clean_in) <= 15:
            brevity_instruction = (
                f"CRITICAL 1-WORD BREVITY: The sender texted ONLY {word_count} word ('{clean_in}'). "
                f"You MUST reply with ONLY 1 or 2 words (e.g. 'hii', 'yo', 'sup', 'hey'). DO NOT ask questions or add extra sentences."
            )
        else:
            brevity_instruction = "Match brevity (1-2 punchy lines maximum, no AI talk, no code, separate distinct thoughts by newline)."

        style_instruction = VALID_STYLES.get(self._style, VALID_STYLES["casual"])
        parts.append(
            f"You are {self.owner_name} texting from your phone.\n"
            f"Tone/Style: {style_instruction}\n"
            f"Language Rule: {lang_instruction}\n"
            f"Brevity Rule: {brevity_instruction}\n"
            f"Latest incoming message from {sender_name}:\n"
            f'"{incoming_text}"\n\n'
            f"Reply as {self.owner_name} (ultra-concise human Gen-Z texting, match brevity, no AI talk, no code, no brackets, separate distinct thoughts by newline):"
        )
        return "\n\n".join(parts)
