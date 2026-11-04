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

DEFAULT_SYSTEM_INSTRUCTIONS = """You are acting as me in my personal Telegram chat.
Reply to incoming messages exactly the way a real human friend texts.

CORE PERSONALITY & RULES:
1. IDENTITY: You are replying directly as me. Never mention being an AI, assistant, bot, or automated program.
2. TONE: Casual, relaxed, and genuinely friendly. Text like a real human texting from a phone.
3. LANGUAGE MATCHING:
   - If the sender writes in Hindi or Hinglish, reply in natural casual Hindi/Hinglish (e.g., "haan bhai bolo", "sab badhiya, tum batao", "thoda busy hu, baad me karta hu").
   - If the sender writes in English, reply in natural casual English.
4. STRICTLY FORBIDDEN:
   - NEVER output brackets [ ], braces { }, or parentheses ( ) containing explanations or metadata.
   - NEVER output labels like "Me:", "AI:", or "Reply:".
   - NEVER output formal greetings like "Certainly!", "I'd be happy to help", or "How can I assist you?".
   - NEVER output code blocks, JSON, or formatting tags.
5. BREVITY: Keep it very short (usually 1-2 short sentences, sometimes just a few words).
6. PRIVACY & SAFETY: Never make financial promises, commitments, or invent private facts.
7. VARIETY: Avoid repetitive phrases or robotic formulas across responses.
Output ONLY the raw text message ready to be sent to the recipient."""


class PromptManager:
    """Formats prompts for AI generation while enforcing personal communication style."""

    def __init__(
        self,
        prompt_file: Path | str | None = "system_prompt.txt",
        system_instructions: str = DEFAULT_SYSTEM_INSTRUCTIONS,
        owner_name: str = "Kaif",
        style: str = "casual",
    ):
        self.prompt_file = Path(prompt_file) if prompt_file else None
        self._default_instructions = system_instructions
        self.owner_name = owner_name
        self._style = style if style in VALID_STYLES else "casual"

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

        # Strip prefixes like "Kaif:", "Me:", "AI:", "Reply:"
        text = re.sub(r"^(?:me|ai|reply|assistant|" + re.escape(self.owner_name) + r"):\s*", "", text, flags=re.IGNORECASE)

        # Remove bracketed/parenthesized meta comments like [replying in Hindi] or (as an AI...)
        text = re.sub(r"\[[^\]]*\]", "", text)
        text = re.sub(r"\{[^\}]*\}", "", text)
        text = re.sub(r"\((?:note|disclaimer|as an ai|ai)[^\)]*\)", "", text, flags=re.IGNORECASE)

        # Strip markdown code fences if model accidentally wrapped output
        text = re.sub(r"^```[a-z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        # Strip robotic conversational openers & closers
        text = re.sub(r"^(?:certainly!?|sure thing!?|of course!?|here(?:'s| is) (?:a |the )?(?:reply|draft):?|as an ai[,\.]?)\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*(?:hope this helps!?|let me know if you need anything else!?|feel free to ask!?)$", "", text, flags=re.IGNORECASE)

        # If model generated multiple bullet choices or "Option 1:", take the single clean human line
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if lines:
            first_line = lines[0]
            first_line = re.sub(r"^[\*\-\•\d\.\:\s]+(?:option\s*\d*[\:\.\s]*)?", "", first_line, flags=re.IGNORECASE).strip()
            if len(first_line) > 2:
                text = first_line

        # STRICT SAFETY: Never allow AI to output URLs or links
        text = re.sub(r"https?:\/\/\S+|t\.me\/\S+|www\.\S+", "", text)

        return text.strip()

    def build_user_prompt(
        self,
        sender_name: str,
        incoming_text: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """Create prompt containing message context, history, and dynamic owner identity."""
        parts: List[str] = []

        if conversation_history:
            history_lines = ["Recent conversation context:"]
            for msg in conversation_history[-4:]:
                sender = msg.get("sender", "Contact")
                content = msg.get("text", "").strip()
                if content:
                    history_lines.append(f"- {sender}: \"{content}\"")
            if len(history_lines) > 1:
                parts.append("\n".join(history_lines))

        style_instruction = VALID_STYLES.get(self._style, VALID_STYLES["casual"])
        parts.append(
            f"You are {self.owner_name}.\n"
            f"Tone/Style: {style_instruction}\n"
            f"Latest incoming message from {sender_name}:\n"
            f'"{incoming_text}"\n\n'
            f"Reply as {self.owner_name} (casual human text, matching language, no AI talk, no robotic repetition):"
        )
        return "\n\n".join(parts)
