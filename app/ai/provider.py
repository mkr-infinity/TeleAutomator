"""AI reply providers using standard library HTTP requests to keep dependencies minimal."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from app.logger import setup_logger

logger = setup_logger(__name__)


def _reply_marker(text: str) -> str:
    """Recognize standalone output markers through quotes and light formatting."""
    return text.strip().strip("\"'`.*_?! \t\r\n").lower()


def normalize_base_url(value: str, default: str = "https://api.openai.com/v1") -> str:
    url = (value or default).strip().rstrip("/")
    if "://" not in url:
        url = "https://" + url
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.query or parsed.fragment or parsed.username:
        raise ValueError("Use an HTTP(S) API base URL without credentials, query parameters, or fragments.")
    for suffix in ("/chat/completions", "/models"):
        if url.endswith(suffix):
            url = url[:-len(suffix)].rstrip("/")
    return url


class AIProvider(ABC):
    """Abstract interface for AI draft generation backends."""

    @abstractmethod
    def generate_reply(self, prompt: str, system_instructions: str) -> str:
        """Generate a response string given prompt and system guidelines."""
        raise NotImplementedError


class LocalRuleProvider(AIProvider):
    """Silent placeholder when no AI model is configured; never sends canned replies."""

    def generate_reply(self, prompt: str, system_instructions: str) -> str:
        """No configured model means silence; never manufacture a canned chat reply."""
        return ""


class GeminiProvider(AIProvider):
    """Google Gemini API provider using standard library urllib."""

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash", usage_callback: Optional[Any] = None,
                 temperature: float = 0.6, max_tokens: Optional[int] = None):
        self.api_key = api_key
        raw = (model or "gemini-2.5-flash").strip()
        cleaned_parts = [p.strip().removeprefix("models/") for p in raw.replace(";", ",").split(",") if p.strip()]
        self.model = ",".join(cleaned_parts) if cleaned_parts else "gemini-2.5-flash"
        self.usage_callback = usage_callback
        self.temperature = temperature
        self.max_tokens = max_tokens

    def get_candidate_models(self) -> list[str]:
        configured = [m.strip().removeprefix("models/") for m in self.model.replace(";", ",").split(",") if m.strip()]
        res: list[str] = []
        for m in configured:
            if m and m not in res:
                res.append(m)
        for fallback in (
            "gemini-2.5-flash-lite",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
        ):
            if fallback not in res:
                res.append(fallback)
        return res

    def check_working_models(self, timeout: float = 8.0) -> list[tuple[str, bool, str]]:
        """Ping candidate Gemini models with a minimal test prompt to verify live availability."""
        candidates = self.get_candidate_models()
        results: list[tuple[str, bool, str]] = []
        working: list[str] = []
        payload = {
            "contents": [{"parts": [{"text": "hi"}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 10},
        }
        data = json.dumps(payload).encode("utf-8")
        for m in candidates:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={self.api_key}"
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
                method="POST",
            )
            try:
                t0 = time.time()
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    latency = int((time.time() - t0) * 1000)
                    body = json.loads(resp.read().decode("utf-8"))
                    candidates_out = body.get("candidates", [])
                    if candidates_out:
                        results.append((m, True, f"200 OK ({latency}ms)"))
                        working.append(m)
                    else:
                        results.append((m, False, "Empty candidates"))
            except urllib.error.HTTPError as e:
                detail = f"HTTP {e.code}"
                try:
                    eb = json.loads(e.read().decode("utf-8"))
                    if isinstance(eb, dict) and "error" in eb:
                        detail = f"HTTP {e.code}: {eb['error'].get('message', eb['error'])}"[:45]
                except Exception:
                    pass
                results.append((m, False, detail))
            except Exception as e:
                results.append((m, False, str(e)[:35]))
        if working:
            self.model = ",".join(working)
        return results

    def generate_reply(self, prompt: str, system_instructions: str) -> str:
        # Candidate models to try in sequence with priority for fast Flash and Lite options
        candidate_models = self.get_candidate_models()

        payload = {
            "system_instruction": {"parts": [{"text": system_instructions}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": self.temperature},
        }
        if self.max_tokens is not None:
            payload["generationConfig"]["maxOutputTokens"] = self.max_tokens
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
                    if self.usage_callback and ("usageMetadata" in body or body.get("candidates")):
                        try:
                            meta = body.get("usageMetadata", {})
                            pt = int(meta.get("promptTokenCount", 0))
                            ct = int(meta.get("candidatesTokenCount", 0))
                            tt = int(meta.get("totalTokenCount", pt + ct))
                            self.usage_callback("gemini", m, pt, ct, tt)
                        except Exception:
                            pass
                    candidates = body.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            raw_text = parts[0].get("text")
                            marker = _reply_marker(str(raw_text)) if raw_text is not None else ""
                            if marker in ("null", "undefined", ""):
                                logger.warning(f"Gemini model '{m}' returned malformed empty text. Trying fallback...")
                                continue
                            if marker == "none":
                                logger.info(f"Gemini model '{m}' returned intentional silence (NONE).")
                                return ""
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
        self.active_model = ""
        self.endpoint_url = normalize_base_url(base_url) + "/chat/completions"
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

        host = urllib.parse.urlsplit(self.endpoint_url).hostname or ""
        if self._is_inception():
            for fallback in ("mercury-3", "mercury-3-preview-1014", "mercury-3-preview-1002"):
                if fallback not in candidates:
                    candidates.append(fallback)
        elif host == "api.openai.com":
            for fallback in ("gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo"):
                if fallback not in candidates:
                    candidates.append(fallback)
        elif host == "integrate.api.nvidia.com":
            for fallback in ("meta/llama-3.1-70b-instruct", "meta/llama-3.1-8b-instruct"):
                if fallback not in candidates:
                    candidates.append(fallback)

        return candidates or [self.model]

    # Mercury is a reasoning model: thinking tokens share max_tokens, so a small limit leaves no room
    # for the answer and the API returns HTTP 200 with empty content. Inception recommends >= 3000.
    REASONING_TOKEN_FLOOR = 3000
    INSTANT_TOKEN_FLOOR = 256

    def _is_inception(self) -> bool:
        host = urllib.parse.urlsplit(self.endpoint_url).hostname or ""
        return host == "inceptionlabs.ai" or host.endswith(".inceptionlabs.ai")

    def effective_max_tokens(self) -> Optional[int]:
        """The limit actually sent: the owner's value, raised when it would starve a reasoning model."""
        if self.max_tokens is None or self.max_tokens <= 0:
            return None
        if not self._is_inception():
            return self.max_tokens
        floor = self.INSTANT_TOKEN_FLOOR if self.reasoning_effort == "instant" else self.REASONING_TOKEN_FLOOR
        return max(self.max_tokens, floor)

    def _request_headers(self) -> Dict[str, str]:
        # Some gateways (Cloudflare-fronted APIs) reject urllib's default User-Agent with HTTP 403.
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "TeleAutomator/3 (+https://github.com/mkr-infinity/TeleAutomator)",
            "Accept": "application/json",
        }

    def _build_request(self, url: str, data: bytes) -> urllib.request.Request:
        return urllib.request.Request(url, data=data, headers=self._request_headers(), method="POST")

    def _fallback_endpoint(self) -> str:
        """Many OpenAI-compatible hosts only serve /v1; a base URL typed without it is retried once."""
        parts = urllib.parse.urlsplit(self.endpoint_url)
        if parts.path.rstrip("/") == "/chat/completions":
            return urllib.parse.urlunsplit((parts.scheme, parts.netloc, "/v1/chat/completions", "", ""))
        return ""

    def generate_reply(self, prompt: str, system_instructions: str) -> str:
        candidates = self.get_candidate_models()
        last_error: Optional[Exception] = None
        is_inception = self._is_inception()
        token_limit = self.effective_max_tokens()

        for m in candidates:
            payload: Dict[str, Any] = {
                "model": m,
                "messages": [
                    {"role": "system", "content": system_instructions},
                    {"role": "user", "content": prompt},
                ],
                "temperature": self.temperature,
            }
            if token_limit:
                payload["max_tokens"] = token_limit
            if is_inception and self.reasoning_effort not in ("off", "none", "", "default"):
                payload["reasoning_effort"] = self.reasoning_effort

            data = json.dumps(payload).encode("utf-8")

            try:
                try:
                    with urllib.request.urlopen(self._build_request(self.endpoint_url, data), timeout=20) as resp:
                        body = json.loads(resp.read().decode("utf-8"))
                except urllib.error.HTTPError as http_error:
                    alternate = self._fallback_endpoint() if http_error.code == 404 else ""
                    if not alternate:
                        raise
                    with urllib.request.urlopen(self._build_request(alternate, data), timeout=20) as resp:
                        body = json.loads(resp.read().decode("utf-8"))
                    self.endpoint_url = alternate  # remember what works
                    logger.info("Endpoint answered only under /v1; using %s from now on.", alternate)
                usage = body.get("usage", {})
                if self.usage_callback and usage:
                    try:
                        pt = int(usage.get("prompt_tokens", 0))
                        ct = int(usage.get("completion_tokens", 0))
                        tt = int(usage.get("total_tokens", pt + ct))
                        self.usage_callback("custom", m, pt, ct, tt)
                    except Exception as ue:
                        logger.debug(f"Failed to record token usage: {ue}")

                choices = body.get("choices", [])
                if choices:
                    raw_content = choices[0].get("message", {}).get("content")
                    marker = _reply_marker(str(raw_content)) if raw_content is not None else ""
                    if marker in ("null", "undefined", ""):
                        message = choices[0].get("message", {}) or {}
                        logger.warning(
                            "OpenAI-compatible model '%s' returned malformed empty content "
                            "(finish_reason=%s, completion_tokens=%s, max_tokens=%s, reasoning_effort=%s, has_reasoning=%s). "
                            "Trying next candidate...",
                            m, choices[0].get("finish_reason"), usage.get("completion_tokens"), token_limit,
                            self.reasoning_effort, bool(message.get("reasoning_content") or message.get("reasoning")),
                        )
                        last_error = RuntimeError(f"{m} returned empty content (finish_reason={choices[0].get('finish_reason')})")
                        continue
                    content = str(raw_content).strip().strip('"')
                    self.active_model = m

                    if marker == "none":
                        logger.info(f"OpenAI-compatible model '{m}' returned intentional silence (NONE).")
                        return ""
                    return content
                last_error = RuntimeError(f"{m} returned no choices")
                logger.warning("OpenAI-compatible model '%s' returned no choices. Trying next candidate...", m)
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
        working: list[str] = []
        is_inception = self._is_inception()

        for m in candidates:
            payload: Dict[str, Any] = {
                "model": m,
                "messages": [{"role": "user", "content": "hi"}],
            }
            if self.effective_max_tokens():
                payload["max_tokens"] = self.effective_max_tokens()
            if is_inception and self.reasoning_effort not in ("off", "none", "", "default"):
                payload["reasoning_effort"] = self.reasoning_effort
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.endpoint_url,
                data=data,
                headers=self._request_headers(),
                method="POST",
            )
            try:
                try:
                    with urllib.request.urlopen(req, timeout=timeout) as resp:
                        body = json.loads(resp.read().decode("utf-8"))
                except urllib.error.HTTPError as error:
                    alternate = self._fallback_endpoint() if error.code == 404 else ""
                    if not alternate:
                        raise
                    with urllib.request.urlopen(self._build_request(alternate, data), timeout=timeout) as resp:
                        body = json.loads(resp.read().decode("utf-8"))
                    self.endpoint_url = alternate
                choices = body.get("choices") or []
                content = (choices[0].get("message") or {}).get("content") if choices else None
                if _reply_marker(str(content) if content is not None else "") not in ("", "null", "undefined"):
                    results.append((m, True, "200 OK"))
                    working.append(m)
                else:
                    results.append((m, False, "Empty content"))
            except urllib.error.HTTPError as e:
                results.append((m, False, f"HTTP {e.code}"))
            except Exception as e:
                results.append((m, False, str(e)[:30]))

        if working:
            self.model = ",".join(working)
        return results
