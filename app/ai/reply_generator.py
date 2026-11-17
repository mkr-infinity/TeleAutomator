"""Coordinates prompt construction and AI draft generation."""

from __future__ import annotations

import re
from contextlib import nullcontext
from typing import Any, Dict, List, Optional

from app.ai.prompt_manager import PromptManager
from app.ai.provider import AIProvider, GeminiProvider, IntentionalSilence, LocalRuleProvider, OpenAIProvider
from app.config import AppConfig
from app.logger import redact_secrets, register_secret, setup_logger
from app.safety_manager import SENSITIVE_CONTENT_PATTERNS

logger = setup_logger(__name__)


def create_ai_provider(config: AppConfig, database: Optional[Any] = None) -> AIProvider:
    """Factory creating the configured AI provider backend with runtime DB overrides."""
    active_provider = (database.get_state("ai_provider", config.ai_provider) if database else config.ai_provider).strip().lower()
    active_enabled = config.ai_enabled if active_provider == config.ai_provider else (active_provider != "local")
    if database and database.get_state("ai_enabled") in ("0", "1"):
        active_enabled = database.get_state("ai_enabled") == "1"

    if not active_enabled or active_provider == "local":
        logger.info("No AI model enabled; chat replies remain silent.")
        return LocalRuleProvider()

    usage_callback = database.record_token_usage if database else None
    active_api_key = (database.get_state("ai_api_key", config.ai_api_key) if database else config.ai_api_key).strip()
    register_secret(active_api_key)
    active_model = (database.get_state("ai_model", config.ai_model) if database else config.ai_model).strip()
    active_base_url = (database.get_state("ai_base_url", config.ai_base_url) if database else config.ai_base_url).strip()
    reasoning_effort = config.ai_reasoning_effort
    temperature, max_tokens = 0.6, None
    if database:
        reasoning_effort = database.get_state("ai_reasoning_effort", config.ai_reasoning_effort)
        try:
            temperature = float(database.get_state("ai_temperature", "0.6"))
        except ValueError:
            pass
        raw_mtok = database.get_state("ai_max_tokens", "")
        if raw_mtok.isdigit() and int(raw_mtok) > 0:
            max_tokens = int(raw_mtok)

    if active_provider == "gemini":
        logger.info("Initializing Google Gemini AI provider.")
        return GeminiProvider(
            api_key=active_api_key,
            model=active_model or "gemini-2.5-flash",
            usage_callback=usage_callback,
            temperature=temperature,
            max_tokens=max_tokens,
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

    # Optional callback(task, exc) for provider failures; runs in worker threads and must not block.
    on_model_error = None

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
        default_lang = getattr(config, "default_chat_language", "english")
        saved_lang = database.get_state("chat_language", default_lang) if database else default_lang
        saved_owner = database.get_state("owner_name", "") if database else ""
        self.prompt_manager = PromptManager(
            style=style,
            custom_prompt=custom_p,
            language=saved_lang,
            owner_name=saved_owner or "User",
        )

    def set_owner_name(self, name: str) -> None:
        """Propagate owner name to prompt manager."""
        self.prompt_manager.set_owner_name(name)

    def reload_provider(self) -> None:
        """Reload and rebuild the active AI provider using current database and config settings."""
        with self.db._context_lock if self.db is not None else nullcontext():
            self.provider = create_ai_provider(self.config, database=self.db)

    def _generate_reply(self, prompt: str, instructions: str, task: str = "reply") -> str:
        # History, pins, summaries and voice profiles need the same filtering as new messages.
        prompt = "\n".join(
            "[sensitive content omitted]" if any(p.search(line) for p in SENSITIVE_CONTENT_PATTERNS)
            else redact_secrets(line) for line in prompt.splitlines()
        )
        try:
            result = self.provider.generate_reply(prompt, redact_secrets(instructions))
            if task == "chat summary" and not isinstance(result, IntentionalSilence) and (not isinstance(result, str) or not result.strip()):
                raise RuntimeError("Model returned an empty chat summary")
            return result
        except Exception as exc:
            callback = self.on_model_error
            if callback is not None:
                try:
                    callback(task, exc)
                except Exception:
                    logger.debug("Model error callback failed")
            raise

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
        persona_override: Optional[str] = None,
        permanent_context: Optional[str] = None,
        is_group: bool = False,
        is_mention: bool = False,
        engagement: str = "",
    ) -> str:
        """Generate a draft reply text considering conversation context when provided."""
        prompt = self.prompt_manager.build_user_prompt(
            sender_name,
            incoming_text,
            conversation_history=conversation_history,
            permanent_context=permanent_context,
            is_group=is_group,
            is_mention=is_mention,
            persona_override=persona_override,
            style_override=style_override,
            engagement=engagement,
        )
        instructions = self.prompt_manager.get_system_instructions(
            style_override=style_override,
            persona_override=persona_override,
            is_group=is_group,
        )
        try:
            draft = self._generate_reply(prompt, instructions)
            return self.humanize_reply(draft, sender_name, incoming_text, conversation_history, persona_override, is_group)
        except Exception as e:
            logger.error(f"Failed to generate draft reply: {e}")
            # Never return fallbacks to groups or peer chats; raise so caller alerts Saved Messages exclusively
            raise RuntimeError(f"AI generation failed: {e}") from e

    def humanize_reply(self, draft, sender_name="Contact", incoming_text="", conversation_history=None, persona_override=None, is_group=False):
        """Local final stage: enforce the chat's length and text rules without another model call."""
        custom = (persona_override or "").strip() or (self.prompt_manager.custom_prompt if not is_group else "")
        return self.prompt_manager.clean_reply(
            draft, sender_name=sender_name, custom_limit=self.prompt_manager.get_custom_word_limit(custom),
            incoming_text=incoming_text, use_global_limit=False,
            participant_names=[str(row.get("sender", "")) for row in (conversation_history or []) if not row.get("is_outgoing")],
        )

    def summarize_chat_history(self, chat_title: str, existing_summary: str, raw_text: str, is_group: bool = True) -> str:
        """Condense recent chat messages into a short rolling recap using AI (no hardcoded text)."""
        if not raw_text or not raw_text.strip():
            return ""
        from app.ai.provider import LocalRuleProvider
        if isinstance(self.provider, LocalRuleProvider):
            # No configured provider is intentional silence, not a failed summary.
            # Keep the message marker for a later run when an AI provider is enabled.
            return IntentionalSilence()
        chat_type_label = "Telegram group chat" if is_group else "Telegram private chat"
        prompt = (
            f"You are building permanent memory for a {chat_type_label} '{chat_title}'.\n\n"
            f"Recap so far:\n{existing_summary.strip() or '(none)'}\n\n"
            f"New recent messages:\n{raw_text}\n\n"
            f"Update the recap in under 150 words. Focus strictly on retaining important permanent facts: "
            f"commitments, decisions, preferences, names/nicknames, dates/plans, personal facts mentioned, "
            f"rules, running jokes, and ongoing topics. "
            f"Describe the mood/energy. Never lose previously learned important facts. "
            f"Output ONLY the updated permanent memory text, no preamble."
        )
        try:
            draft = self._generate_reply(prompt, "You are a concise chat-memory system. Output only the updated recap.", task="chat summary")
            if isinstance(draft, IntentionalSilence):
                return draft
            return draft.strip()[:1500]
        except Exception as e:
            logger.error(f"Failed to summarize chat history: {e}")
            raise

    def generate_goodnight_signoff(self) -> str:
        """AI-written casual goodnight line for quiet-hours sign-off (never hardcoded)."""
        from app.ai.provider import LocalRuleProvider
        if isinstance(self.provider, LocalRuleProvider):
            return ""
        prompt = (
            "Write ONE short goodnight sign-off to end an active conversation before scheduled quiet hours. "
            "Do not claim a location, activity, personal plan, or specific time. "
            "Max 8 words, casual human mobile texting, light slang or small emoji ok, no question marks. "
            f"Reply as {self.prompt_manager.owner_name} speaking to the group. Output ONLY the line."
        )
        # Group rules only: the global DM persona and its word limit must not leak into group sign-offs.
        instructions = self.prompt_manager.get_system_instructions(is_group=True)
        draft = self._generate_reply(prompt, instructions, task="goodnight")
        return self.prompt_manager.clean_reply(draft)

    def generate_voice_profile(self, chat_title: str, raw_text: str) -> str:
        """Learn how a group's people actually talk from recent messages: tone, slang,
        message length, topics. AI-written voice profile used to blend in as a regular."""
        if not raw_text or not raw_text.strip():
            return ""
        from app.ai.provider import LocalRuleProvider
        if isinstance(self.provider, LocalRuleProvider):
            return ""

        prompt = (
            f"You are studying recent messages from the Telegram group '{chat_title}' so you can "
            f"text there exactly like one of its regular members.\n\n"
            f"Messages:\n{raw_text}\n\n"
            f"Write a compact voice profile (max 120 words) capturing ONLY what you observe:\n"
            f"- Tone and energy (dry, hyped, sarcastic, wholesome, etc.)\n"
            f"- Typical message length and style (one-liners vs paragraphs, caps, punctuation habits)\n"
            f"- Slang, greetings, filler words and emoji habits (cite real examples from these messages)\n"
            f"- Recurring topics, running jokes and nicknames people use\n"
            f"- How banter and disagreements sound in this group\n\n"
            f"Write it as direct instructions starting with 'Talk like: '. Output ONLY the profile, no preamble."
        )
        system_inst = "You are a chat-behavior analyst. Output only the requested profile text."
        try:
            draft = self._generate_reply(prompt, system_inst, task="voice profile")
            return draft.strip()[:1500]
        except Exception as e:
            logger.error(f"Failed to generate voice profile: {e}")
            return ""

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
            summary = self._generate_reply(prompt, system_inst, task="pinned messages")
            clean_summary = summary.strip()
            if clean_summary:
                return clean_summary
        except Exception as e:
            logger.debug(f"AI context distillation failed: {e}; falling back to raw text.")
        return raw_text[:1000].strip()
