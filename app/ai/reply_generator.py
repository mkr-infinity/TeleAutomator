"""Coordinates prompt construction and AI draft generation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.ai.prompt_manager import PromptManager
from app.ai.provider import AIProvider, GeminiProvider, LocalRuleProvider, OpenAIProvider
from app.config import AppConfig
from app.logger import setup_logger

logger = setup_logger(__name__)


def create_ai_provider(config: AppConfig) -> AIProvider:
    """Factory creating the configured AI provider backend."""
    if not config.ai_enabled or config.ai_provider == "local":
        logger.info("Using LocalRuleProvider (offline, privacy-preserving draft mode).")
        return LocalRuleProvider()

    if config.ai_provider == "gemini":
        logger.info("Initializing Google Gemini AI provider.")
        return GeminiProvider(api_key=config.ai_api_key, model=config.ai_model or "gemini-3.5-flash")

    if config.ai_provider == "openai":
        logger.info("Initializing OpenAI AI provider.")
        return OpenAIProvider(api_key=config.ai_api_key, model=config.ai_model or "gpt-4o-mini")

    logger.warning(f"Unknown provider '{config.ai_provider}', falling back to LocalRuleProvider.")
    return LocalRuleProvider()


class ReplyGenerator:
    """Generates suggested draft replies."""

    def __init__(self, config: AppConfig, provider: Optional[AIProvider] = None, style: str = "casual"):
        self.config = config
        self.provider = provider or create_ai_provider(config)
        self.prompt_manager = PromptManager(style=style)

    def set_owner_name(self, name: str) -> None:
        """Propagate owner name to prompt manager."""
        self.prompt_manager.set_owner_name(name)

    def set_style(self, style: str) -> bool:
        """Set AI response style (casual, concise, formal, humorous)."""
        return self.prompt_manager.set_style(style)

    @property
    def style(self) -> str:
        """Active AI response style."""
        return self.prompt_manager.style

    def generate(
        self,
        sender_name: str,
        incoming_text: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """Generate a draft reply text considering conversation context when provided."""
        prompt = self.prompt_manager.build_user_prompt(
            sender_name, incoming_text, conversation_history=conversation_history
        )
        try:
            draft = self.provider.generate_reply(prompt, self.prompt_manager.system_instructions)
            return self.prompt_manager.clean_reply(draft)
        except Exception as e:
            logger.error(f"Failed to generate draft reply: {e}")
            # Never return fallbacks to groups or peer chats; raise so caller alerts Saved Messages exclusively
            raise RuntimeError(f"AI generation failed: {e}") from e
