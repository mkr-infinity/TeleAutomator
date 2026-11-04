"""Prompt management and system guidelines for natural personal replies."""

from __future__ import annotations


# =============================================================================
# PERSONAL AI PERSONA & REPLY INSTRUCTIONS
# =============================================================================
# Users: You can freely customize the instructions below to make the AI sound
# like you! For example, you can specify:
#   - Your typical tone (e.g., "Use casual lowercase, friendly vibe", or "Keep it professional")
#   - Your preferred language (e.g., "Reply in English or Hindi depending on user")
#   - Common questions to handle (e.g., "If asked about my availability, say I am free after 6 PM")
# =============================================================================

DEFAULT_SYSTEM_INSTRUCTIONS = """You are assisting me by drafting a personal reply to a Telegram message.
Your response must sound like a real human:
- Friendly, clear, concise, and context-aware.
- No robotic or formal corporate language.
- Avoid repetitive generic greetings (like 'Hello! How can I assist you today?').
- Match the language and tone of the incoming message.
- Keep it short (1 to 3 sentences maximum).
- Crucial: Never pretend to be someone else, never invent facts, and never make commitments, financial promises, or sensitive agreements on my behalf.
- If unsure or if a question requires private knowledge, politely offer to check back later.
Output only the exact draft reply text, with no introductory explanation or quotation marks."""


class PromptManager:
    """Formats prompts for AI generation while enforcing personal communication style."""

    def __init__(self, system_instructions: str = DEFAULT_SYSTEM_INSTRUCTIONS):
        self.system_instructions = system_instructions

    def build_user_prompt(self, sender_name: str, incoming_text: str) -> str:
        """Create prompt containing message context."""
        return (
            f"Incoming message from {sender_name}:\n"
            f'"{incoming_text}"\n\n'
            f"Draft a brief, natural response:"
        )
