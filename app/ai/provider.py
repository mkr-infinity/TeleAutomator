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
    """Local, offline draft generator using natural human texting patterns (zero API calls)."""

    def generate_reply(self, prompt: str, system_instructions: str) -> str:
        lower = prompt.lower()
        if any(w in lower for w in ("bot", "ai", "real", "fake", "who are you")):
            return "bruh u fr rn it's me lol"
        if any(w in lower for w in ("tonight", "free", "available", "meet", "time", "coming", "there")):
            return "yeah sounds good, will let you know 👍"
        if any(w in lower for w in ("thanks", "thank")):
            return "anytime bro 👍"
        return "sounds good bro 👍"


class GeminiProvider(AIProvider):
    """Google Gemini API provider using standard library urllib."""

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash", usage_callback: Optional[Any] = None):
        self.api_key = api_key
        clean = (model or "gemini-2.5-flash").strip()
        if clean.startswith("models/"):
            clean = clean[len("models/"):]
        self.model = clean
        self.usage_callback = usage_callback

    def generate_reply(self, prompt: str, system_instructions: str) -> str:
        # Candidate models to try in sequence with priority for fast Flash and Lite options
        candidate_models = [self.model]
        for fallback in (
            "gemini-3.5-flash-lite",
            "gemini-3.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-2.5-flash",
            "gemini-1.5-flash",
        ):
            if fallback not in candidate_models:
                candidate_models.append(fallback)

        payload = {
            "system_instruction": {"parts": [{"text": system_instructions}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.6},
        }
        data = json.dumps(payload).encode("utf-8")

        last_error = None
        for m in candidate_models:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{m}:generateContent?key={self.api_key}"
            )
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": self.api_key,
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                    candidates = body.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            raw_text = parts[0].get("text")
                            if raw_text is None or str(raw_text).strip().lower() in ("none", "none.", "null", "null.", "undefined", ""):
                                logger.warning(f"Gemini model '{m}' returned empty/None text. Trying fallback...")
                                continue
                            if self.usage_callback:
                                try:
                                    meta = body.get("usageMetadata", {})
                                    pt = int(meta.get("promptTokenCount", 0))
                                    ct = int(meta.get("candidatesTokenCount", 0))
                                    tt = int(meta.get("totalTokenCount", pt + ct))
                                    self.usage_callback("gemini", m, pt, ct, tt)
                                except Exception:
                                    pass
                            return str(raw_text).strip().strip('"')
            except urllib.error.HTTPError as e:
                last_error = e
                logger.warning(f"Gemini model '{m}' request failed ({e.code}). Trying fallback...")
                continue
            except Exception as e:
                last_error = e
                logger.warning(f"Gemini model '{m}' error: {e}. Trying fallback...")
                continue

        logger.error(f"All Gemini candidate models failed: {last_error}")
        raise last_error if last_error else RuntimeError("Gemini reply generation failed.")


class OpenAIProvider(AIProvider):
    """OpenAI and OpenAI-compatible provider (Inception Labs, NVIDIA, Groq, Together, DeepSeek, Local Ollama)."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        base_url: str = "",
        usage_callback: Optional[Any] = None,
        reasoning_effort: str = "default",
        temperature: float = 0.6,
        max_tokens: Optional[int] = None,
    ):
        self.api_key = api_key
        self.model = model or "gpt-4o-mini"
        raw_url = (base_url or "https://api.openai.com/v1").strip().rstrip("/")
        if not raw_url.endswith("/chat/completions"):
            raw_url = f"{raw_url}/chat/completions"
        self.endpoint_url = raw_url
        self.usage_callback = usage_callback
        self.reasoning_effort = reasoning_effort
        self.temperature = temperature
        self.max_tokens = max_tokens

    def get_candidate_models(self) -> list[str]:
        """Build priority list of candidate models with automatic verified fallbacks."""
        candidates: list[str] = []
        for m in self.model.replace(";", ",").split(","):
            cleaned = m.strip()
            if cleaned and cleaned not in candidates:
                candidates.append(cleaned)

        endpoint_lower = self.endpoint_url.lower()
        if "inceptionlabs" in endpoint_lower:
            for fallback in ("mercury-3", "mercury-3-preview-1014", "mercury-3-preview-1002"):
                if fallback not in candidates:
                    candidates.append(fallback)
        elif "openai.com" in endpoint_lower:
            for fallback in ("gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo"):
                if fallback not in candidates:
                    candidates.append(fallback)
        elif "nvidia" in endpoint_lower:
            for fallback in ("meta/llama-3.1-70b-instruct", "meta/llama-3.1-8b-instruct"):
                if fallback not in candidates:
                    candidates.append(fallback)

        return candidates or [self.model]

    def generate_reply(self, prompt: str, system_instructions: str) -> str:
        candidates = self.get_candidate_models()
        last_error: Optional[Exception] = None
        is_inception = "inceptionlabs" in self.endpoint_url.lower()

        for m in candidates:
            payload: Dict[str, Any] = {
                "model": m,
                "messages": [
                    {"role": "system", "content": system_instructions},
                    {"role": "user", "content": prompt},
                ],
                "temperature": self.temperature,
            }
            if self.max_tokens is not None and self.max_tokens > 0:
                payload["max_tokens"] = self.max_tokens
            if is_inception and self.reasoning_effort not in ("off", "none", "", "default"):
                payload["reasoning_effort"] = self.reasoning_effort

            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.endpoint_url,
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
                        raw_content = choices[0].get("message", {}).get("content")
                        if raw_content is None or str(raw_content).strip().lower() in ("none", "none.", "null", "null.", "undefined", ""):
                            logger.warning(f"OpenAI-compatible model '{m}' returned empty/None content. Trying next candidate...")
                            continue
                        content = str(raw_content).strip().strip('"')
                        if m != self.model:
                            logger.info(f"AI model automatically switched from '{self.model}' to working fallback '{m}'.")
                            self.model = m

                        usage = body.get("usage", {})
                        if self.usage_callback and usage:
                            try:
                                pt = int(usage.get("prompt_tokens", 0))
                                ct = int(usage.get("completion_tokens", 0))
                                tt = int(usage.get("total_tokens", pt + ct))
                                self.usage_callback("custom", m, pt, ct, tt)
                            except Exception as ue:
                                logger.debug(f"Failed to record token usage: {ue}")

                        return content
            except Exception as e:
                last_error = e
                logger.warning(f"OpenAI-compatible model '{m}' request failed: {e}. Trying next candidate...")
                continue

        logger.error(f"All candidate models failed on {self.endpoint_url}: {last_error}")
        raise last_error if last_error else RuntimeError("AI reply generation failed.")

    def check_working_models(self, timeout: float = 8.0) -> list[tuple[str, bool, str]]:
        """Ping all candidate models with a minimal test prompt to verify live availability."""
        candidates = self.get_candidate_models()
        results: list[tuple[str, bool, str]] = []
        first_working: Optional[str] = None
        is_inception = "inceptionlabs" in self.endpoint_url.lower()

        for m in candidates:
            payload: Dict[str, Any] = {
                "model": m,
                "messages": [{"role": "user", "content": "hi"}],
            }
            if self.max_tokens is not None and self.max_tokens > 0:
                payload["max_tokens"] = self.max_tokens
            if is_inception and self.reasoning_effort not in ("off", "none", "", "default"):
                payload["reasoning_effort"] = self.reasoning_effort
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.endpoint_url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                    if body.get("choices"):
                        results.append((m, True, "200 OK"))
                        if not first_working:
                            first_working = m
                    else:
                        results.append((m, False, "Empty choices"))
            except urllib.error.HTTPError as e:
                results.append((m, False, f"HTTP {e.code}"))
            except Exception as e:
                results.append((m, False, str(e)[:30]))

        if first_working:
            self.model = first_working
        return results
