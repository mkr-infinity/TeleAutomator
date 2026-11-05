"""Coordinates prompt construction and AI draft generation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.ai.prompt_manager import PromptManager
from app.ai.provider import AIProvider, GeminiProvider, LocalRuleProvider, OpenAIProvider
from app.config import AppConfig
from app.logger import setup_logger

logger = setup_logger(__name__)


def create_ai_provider(config: AppConfig, database: Optional[Any] = None) -> AIProvider:
    """Factory creating the configured AI provider backend."""
    if not config.ai_enabled or config.ai_provider == "local":
        logger.info("Using LocalRuleProvider (offline, privacy-preserving draft mode).")
        return LocalRuleProvider()

    usage_callback = database.record_token_usage if database else None

    if config.ai_provider == "gemini":
        logger.info("Initializing Google Gemini AI provider.")
        return GeminiProvider(
            api_key=config.ai_api_key,
            model=config.ai_model or "gemini-2.5-flash",
            usage_callback=usage_callback,
        )

    if config.ai_provider in ("openai", "custom", "nvidia", "groq", "together", "deepseek", "inception"):
        target_name = config.ai_provider.upper()
        default_model = "gpt-4o-mini"
        default_base_url = config.ai_base_url
        if config.ai_provider == "nvidia":
            default_model = "meta/llama-3.1-70b-instruct"
        elif config.ai_provider == "inception":
            default_model = "mercury-3,mercury-3-preview-1014,mercury-3-preview-1002"
            if not default_base_url:
                default_base_url = "https://api.inceptionlabs.ai/v1"

        reasoning_effort = "low"
        temperature = 0.6
        max_tokens = 200
        if database:
            reasoning_effort = database.get_state("ai_reasoning_effort", "low")
            try:
                temperature = float(database.get_state("ai_temperature", "0.6"))
            except ValueError:
                pass
            try:
                max_tokens = int(database.get_state("ai_max_tokens", "200"))
            except ValueError:
                pass

        logger.info(f"Initializing {target_name} OpenAI-compatible AI provider (base_url: {default_base_url or 'default'}).")
        return OpenAIProvider(
            api_key=config.ai_api_key,
            model=config.ai_model or default_model,
            base_url=default_base_url,
            usage_callback=usage_callback,
            reasoning_effort=reasoning_effort,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    logger.warning(f"Unknown provider '{config.ai_provider}', falling back to LocalRuleProvider.")
    return LocalRuleProvider()


class ReplyGenerator:
    """Generates suggested draft replies."""

    def __init__(
        self,
        config: AppConfig,
        provider: Optional[AIProvider] = None,
        style: str = "casual",
        database: Optional[Any] = None,
    ):
        self.config = config
        self.db = database
        self.provider = provider or create_ai_provider(config, database=database)
        custom_p = database.get_state("custom_system_prompt", "") if database else ""
        self.prompt_manager = PromptManager(style=style, custom_prompt=custom_p)

    def set_owner_name(self, name: str) -> None:
        """Propagate owner name to prompt manager."""
        self.prompt_manager.set_owner_name(name)

    def set_language(self, language: str) -> None:
        """Set language rule (dynamic, english, hindi, etc.)."""
        self.prompt_manager.set_language(language)

    @property
    def language(self) -> str:
        """Active target chat language."""
        return self.prompt_manager.language

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
        style_override: Optional[str] = None,
    ) -> str:
        """Generate a draft reply text considering conversation context when provided."""
        prompt = self.prompt_manager.build_user_prompt(
            sender_name, incoming_text, conversation_history=conversation_history
        )
        instructions = self.prompt_manager.get_system_instructions(style_override=style_override)
        try:
            draft = self.provider.generate_reply(prompt, instructions)
            return self.prompt_manager.clean_reply(draft)
        except Exception as e:
            logger.error(f"Failed to generate draft reply: {e}")
            # Never return fallbacks to groups or peer chats; raise so caller alerts Saved Messages exclusively
            raise RuntimeError(f"AI generation failed: {e}") from e
