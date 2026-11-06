"""Coordinates prompt construction and AI draft generation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.ai.prompt_manager import PromptManager
from app.ai.provider import AIProvider, GeminiProvider, LocalRuleProvider, OpenAIProvider
from app.config import AppConfig
from app.logger import setup_logger

logger = setup_logger(__name__)


def create_ai_provider(config: AppConfig, database: Optional[Any] = None) -> AIProvider:
    """Factory creating the configured AI provider backend with runtime DB overrides."""
    active_provider = (database.get_state("ai_provider", config.ai_provider) if database else config.ai_provider).strip().lower()
    active_enabled = config.ai_enabled if active_provider == config.ai_provider else (active_provider != "local")

    if not active_enabled or active_provider == "local":
        logger.info("Using LocalRuleProvider (offline, privacy-preserving draft mode).")
        return LocalRuleProvider()

    usage_callback = database.record_token_usage if database else None
    active_api_key = (database.get_state("ai_api_key", config.ai_api_key) if database else config.ai_api_key).strip()
    active_model = (database.get_state("ai_model", config.ai_model) if database else config.ai_model).strip()
    active_base_url = (database.get_state("ai_base_url", config.ai_base_url) if database else config.ai_base_url).strip()

    if active_provider == "gemini":
        logger.info("Initializing Google Gemini AI provider.")
        return GeminiProvider(
            api_key=active_api_key,
            model=active_model or "gemini-2.5-flash",
            usage_callback=usage_callback,
        )

    if active_provider in ("openai", "custom", "nvidia", "groq", "together", "deepseek", "inception"):
        target_name = active_provider.upper()
        default_model = "gpt-4o-mini"
        default_base_url = active_base_url
        if active_provider == "nvidia":
            default_model = "meta/llama-3.1-70b-instruct"
        elif active_provider == "inception":
            default_model = "mercury-3,mercury-3-preview-1014,mercury-3-preview-1002"
            if not default_base_url:
                default_base_url = "https://api.inceptionlabs.ai/v1"

        reasoning_effort = "default"
        temperature = 0.6
        max_tokens = None
        if database:
            reasoning_effort = database.get_state("ai_reasoning_effort", "default")
            try:
                temperature = float(database.get_state("ai_temperature", "0.6"))
            except ValueError:
                pass
            raw_mtok = database.get_state("ai_max_tokens", "")
            if raw_mtok and raw_mtok.strip().isdigit() and int(raw_mtok.strip()) > 0:
                max_tokens = int(raw_mtok.strip())

        logger.info(f"Initializing {target_name} OpenAI-compatible AI provider (base_url: {default_base_url or 'default'}).")
        return OpenAIProvider(
            api_key=active_api_key,
            model=active_model or default_model,
            base_url=default_base_url,
            usage_callback=usage_callback,
            reasoning_effort=reasoning_effort,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    logger.warning(f"Unknown provider '{active_provider}', falling back to LocalRuleProvider.")
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
        saved_lang = database.get_state("chat_language", "english") if database else "english"
        self.prompt_manager = PromptManager(style=style, custom_prompt=custom_p, language=saved_lang)

    def set_owner_name(self, name: str) -> None:
        """Propagate owner name to prompt manager."""
        self.prompt_manager.set_owner_name(name)

    def reload_provider(self) -> None:
        """Reload and rebuild the active AI provider using current database and config settings."""
        self.provider = create_ai_provider(self.config, database=self.db)

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
        permanent_context: Optional[str] = None,
        is_group: bool = False,
        is_mention: bool = False,
    ) -> str:
        """Generate a draft reply text considering conversation context when provided."""
        prompt = self.prompt_manager.build_user_prompt(
            sender_name,
            incoming_text,
            conversation_history=conversation_history,
            permanent_context=permanent_context,
            is_group=is_group,
            is_mention=is_mention,
        )
        instructions = self.prompt_manager.get_system_instructions(style_override=style_override)
        try:
            draft = self.provider.generate_reply(prompt, instructions)
            return self.prompt_manager.clean_reply(draft, sender_name=sender_name)
        except Exception as e:
            logger.error(f"Failed to generate draft reply: {e}")
            # Never return fallbacks to groups or peer chats; raise so caller alerts Saved Messages exclusively
            raise RuntimeError(f"AI generation failed: {e}") from e

    def distill_group_context(self, chat_title: str, raw_text: str) -> str:
        """Distill raw pinned messages and group announcements into concise permanent context using AI."""
        if not raw_text or not raw_text.strip():
            return ""
        from app.ai.provider import LocalRuleProvider
        if isinstance(self.provider, LocalRuleProvider):
            return raw_text[:1000].strip()

        prompt = (
            f"Analyze these pinned announcements/rules for the Telegram group '{chat_title}':\n\n"
            f"{raw_text}\n\n"
            f"Extract the essential permanent context in 2-3 concise points:\n"
            f"- Group Purpose/Topic\n"
            f"- Key Rules & Guidelines\n"
            f"- Behavior to follow\n"
            f"Output ONLY the concise points without conversational preamble."
        )
        system_inst = "You are a factual context summarizer. Be extremely concise, factual, and direct."
        try:
            summary = self.provider.generate_reply(prompt, system_inst)
            clean_summary = summary.strip()
            if clean_summary:
                return clean_summary
        except Exception as e:
            logger.debug(f"AI context distillation failed: {e}; falling back to raw text.")
        return raw_text[:1000].strip()
