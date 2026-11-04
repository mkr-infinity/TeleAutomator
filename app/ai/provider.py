"""AI reply providers using standard library HTTP requests to keep dependencies minimal."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from typing import Any, Dict

from app.logger import setup_logger

logger = setup_logger(__name__)


class AIProvider(ABC):
    """Abstract interface for AI draft generation backends."""

    @abstractmethod
    def generate_reply(self, prompt: str, system_instructions: str) -> str:
        """Generate a response string given prompt and system guidelines."""
        raise NotImplementedError


class LocalRuleProvider(AIProvider):
    """Local, offline draft generator that transmits zero data to third-party APIs."""

    def generate_reply(self, prompt: str, system_instructions: str) -> str:
        lower = prompt.lower()
        if any(w in lower for w in ("hello", "hey", "hi")):
            return "Hey! Thanks for reaching out. What's up?"
        if any(w in lower for w in ("how are you", "how are u")):
            return "Doing well, thanks for asking! Hope you're having a good day."
        if any(w in lower for w in ("busy", "available", "free")):
            return "Got your message, currently a bit tied up but will get back to you soon!"
        if any(w in lower for w in ("thanks", "thank you")):
            return "You're welcome!"
        # Fallback polite draft
        return "Thanks for your message! I've noted this and will reply shortly."


class GeminiProvider(AIProvider):
    """Google Gemini API provider using standard library urllib."""

    def __init__(self, api_key: str, model: str = "gemini-1.5-flash"):
        self.api_key = api_key
        self.model = model or "gemini-1.5-flash"

    def generate_reply(self, prompt: str, system_instructions: str) -> str:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        payload = {
            "system_instruction": {"parts": [{"text": system_instructions}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.6, "maxOutputTokens": 200},
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                candidates = body.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        return str(parts[0].get("text", "")).strip().strip('"')
        except Exception as e:
            logger.error(f"Gemini API request failed: {e}")
            raise
        return ""


class OpenAIProvider(AIProvider):
    """OpenAI API provider using standard library urllib."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.api_key = api_key
        self.model = model or "gpt-4o-mini"

    def generate_reply(self, prompt: str, system_instructions: str) -> str:
        url = "https://api.openai.com/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_instructions},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.6,
            "max_tokens": 200,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                choices = body.get("choices", [])
                if choices:
                    return str(choices[0].get("message", {}).get("content", "")).strip().strip('"')
        except Exception as e:
            logger.error(f"OpenAI API request failed: {e}")
            raise
        return ""
