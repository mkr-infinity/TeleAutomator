"""Coordinates prompt construction and AI draft generation."""

from __future__ import annotations

from typing import Optional

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
        return GeminiProvider(api_key=config.ai_api_key, model=config.ai_model or "gemini-1.5-flash")

    if config.ai_provider == "openai":
        logger.info("Initializing OpenAI AI provider.")
        return OpenAIProvider(api_key=config.ai_api_key, model=config.ai_model or "gpt-4o-mini")

    logger.warning(f"Unknown provider '{config.ai_provider}', falling back to LocalRuleProvider.")
    return LocalRuleProvider()


class ReplyGenerator:
    """Generates suggested draft replies."""

    def __init__(self, config: AppConfig, provider: Optional[AIProvider] = None):
        self.config = config
        self.provider = provider or create_ai_provider(config)
        self.prompt_manager = PromptManager()

    def generate(self, sender_name: str, incoming_text: str) -> str:
        """Generate a draft reply text."""
        prompt = self.prompt_manager.build_user_prompt(sender_name, incoming_text)
        try:
            draft = self.provider.generate_reply(prompt, self.prompt_manager.system_instructions)
            return draft.strip()
        except Exception as e:
            logger.error(f"Failed to generate draft reply: {e}")
            return ""
