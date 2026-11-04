"""Prompt management and system guidelines for natural personal replies."""

from __future__ import annotations


from pathlib import Path


# =============================================================================
# PERSONAL AI PERSONA & REPLY INSTRUCTIONS
# =============================================================================
# Users: You can customize your AI persona directly by editing:
#   system_prompt.txt  (in the project root directory)
#
# Any changes saved to system_prompt.txt are loaded immediately!
# =============================================================================

DEFAULT_SYSTEM_INSTRUCTIONS = """You are acting as me in my personal Telegram chat.
Reply to the incoming message exactly the way a real human texts a friend or colleague.

KEY RULES:
1. NEVER sound like a chatbot, AI, or customer support agent.
2. NEVER say things like "Certainly!", "I'd be glad to help", "How can I assist you today?", or "As an AI...".
3. Keep it brief and natural (1 to 2 short sentences max, often just a few words).
4. Match the tone, language, and vibe of the person texting me (e.g. casual, direct, relaxed).
5. If someone asks "how are you" or "what's up", reply casually like "doing good, what's up with you?" or "all good, what's going on?".
6. If someone asks for plans or questions requiring my personal schedule, say: "got your message, will check and get back to you soon!"
7. NEVER invent facts about my life, make financial commitments, or sign agreements.
8. Output ONLY the exact text of the reply. No quotation marks, no preamble."""


class PromptManager:
    """Formats prompts for AI generation while enforcing personal communication style."""

    def __init__(
        self,
        prompt_file: Path | str | None = "system_prompt.txt",
        system_instructions: str = DEFAULT_SYSTEM_INSTRUCTIONS,
    ):
        self.prompt_file = Path(prompt_file) if prompt_file else None
        self._default_instructions = system_instructions

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

    def build_user_prompt(self, sender_name: str, incoming_text: str) -> str:
        """Create prompt containing message context."""
        return (
            f"Incoming message from {sender_name}:\n"
            f'"{incoming_text}"\n\n'
            f"Write a natural human text reply:"
        )
