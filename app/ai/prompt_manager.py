"""Prompt management and system guidelines for natural personal replies."""

from __future__ import annotations


import re
from pathlib import Path


# =============================================================================
# PERSONAL AI PERSONA & REPLY INSTRUCTIONS
# =============================================================================
# Users: You can customize your AI persona directly by editing:
#   system_prompt.txt  (in the project root directory)
# Or from Telegram Saved Messages by sending:
#   /setprompt <your instructions>
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
Output ONLY the raw text message ready to be sent to the recipient."""


class PromptManager:
    """Formats prompts for AI generation while enforcing personal communication style."""

    def __init__(
        self,
        prompt_file: Path | str | None = "system_prompt.txt",
        system_instructions: str = DEFAULT_SYSTEM_INSTRUCTIONS,
        owner_name: str = "Kaif",
    ):
        self.prompt_file = Path(prompt_file) if prompt_file else None
        self._default_instructions = system_instructions
        self.owner_name = owner_name

    def set_owner_name(self, name: str) -> None:
        """Update owner name fetched from Telegram account or configuration."""
        if name and name.strip():
            self.owner_name = name.strip()

    @property
    def system_instructions(self) -> str:
        """Return instructions from system_prompt.txt if present, otherwise default."""
        if self.prompt_file and self.prompt_file.exists():
            try:
                content = self.prompt_file.read_text(encoding="utf-8").strip()
                if content:
                    return content
            except Exception:
                pass
        return self._default_instructions

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
        """Remove any accidental AI meta-commentary, labels, or brackets."""
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

    def build_user_prompt(self, sender_name: str, incoming_text: str) -> str:
        """Create prompt containing message context and dynamic owner identity."""
        return (
            f"You are {self.owner_name}. {sender_name} sent you this message:\n"
            f'"{incoming_text}"\n\n'
            f"Reply as {self.owner_name} (casual human text, matching language, no AI talk):"
        )
