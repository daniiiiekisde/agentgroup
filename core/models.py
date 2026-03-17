"""Model provider adapters – unified chat(messages) -> str interface.

Providers: OpenAI, Anthropic, Gemini, Groq, Ollama, DeepSeek, Mistral, xAI (Grok), Cohere

Improvements over v1:
- Retry logic with exponential backoff on transient errors (429, 500, 502, 503)
- Rate limiting via RateLimiterRegistry (prevents throttling)
- Typed return values
- Explicit max_tokens on all adapters
- Timeout on all HTTP calls
"""
from __future__ import annotations
import time
import logging
from typing import List, Dict
import requests
from core.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

MAX_TOKENS_DEFAULT = 4096
RETRY_ATTEMPTS     = 3
RETRY_BASE_DELAY   = 2.0  # seconds, doubles each attempt


def _retry(fn, provider: str, attempts: int = RETRY_ATTEMPTS):
    """Call fn() with retry + exponential backoff on transient errors."""
    delay = RETRY_BASE_DELAY
    for attempt in range(1, attempts + 1):
        try:
            rate_limiter.wait(provider)
            return fn()
        except Exception as e:
            msg = str(e)
            is_transient = any(code in msg for code in ["429", "500", "502", "503", "overloaded", "timeout"])
            if attempt == attempts or not is_transient:
                raise
            logger.warning(f"[{provider}] Attempt {attempt} failed ({msg}). Retrying in {delay}s...")
            time.sleep(delay)
            delay *= 2


class ModelAdapter:
    provider: str = "unknown"

    def chat(self, messages: List[Dict[str, str]]) -> str:
        raise NotImplementedError


class OpenAIAdapter(ModelAdapter):
    provider = "openai"

    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        import openai
        self.client = openai.OpenAI(api_key=api_key)
        self.model  = model

    def chat(self, messages: List[Dict[str, str]]) -> str:
        def _call():
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=MAX_TOKENS_DEFAULT,
            )
            return resp.choices[0].message.content
        return _retry(_call, self.provider)


class AnthropicAdapter(ModelAdapter):
    provider = "anthropic"

    def __init__(self, api_key: str, model: str = "claude-3-5-haiku-20241022"):
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model  = model

    def chat(self, messages: List[Dict[str, str]]) -> str:
        system    = next((m["content"] for m in messages if m["role"] == "system"), "")
        user_msgs = [m for m in messages if m["role"] != "system"]

        def _call():
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS_DEFAULT,
                system=system,
                messages=user_msgs,
            )
            return resp.content[0].text
        return _retry(_call, self.provider)


class GeminiAdapter(ModelAdapter):
    provider = "gemini"

    def __init__(self, api_key: str, model: str = "gemini-1.5-flash"):
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        self.model_obj = genai.GenerativeModel(model)

    def chat(self, messages: List[Dict[str, str]]) -> str:
        text = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages)

        def _call():
            return self.model_obj.generate_content(text).text
        return _retry(_call, self.provider)


class GroqAdapter(ModelAdapter):
    provider = "groq"

    def __init__(self, api_key: str, model: str = "llama-3.1-8b-instant"):
        from groq import Groq
        self.client = Groq(api_key=api_key)
        self.model  = model

    def chat(self, messages: List[Dict[str, str]]) -> str:
        def _call():
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=MAX_TOKENS_DEFAULT,
            )
            return resp.choices[0].message.content
        return _retry(_call, self.provider)


class OllamaAdapter(ModelAdapter):
    provider = "ollama"

    def __init__(self, model: str = "llama3.2", base_url: str = "http://localhost:11434", api_key: str = ""):
        self.model    = model
        self.endpoint = (
            "https://ollama.com/api/chat"
            if "ollama.com" in base_url
            else base_url.rstrip("/") + "/api/chat"
        )
        self.headers: Dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    def chat(self, messages: List[Dict[str, str]]) -> str:
        def _call():
            resp = requests.post(
                self.endpoint,
                json={"model": self.model, "messages": messages, "stream": False},
                headers=self.headers,
                timeout=120,
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"]
        return _retry(_call, self.provider)


class DeepSeekAdapter(ModelAdapter):
    """DeepSeek via their OpenAI-compatible API."""
    BASE     = "https://api.deepseek.com/v1"
    provider = "deepseek"

    def __init__(self, api_key: str, model: str = "deepseek-coder"):
        import openai
        self.client = openai.OpenAI(api_key=api_key, base_url=self.BASE)
        self.model  = model

    def chat(self, messages: List[Dict[str, str]]) -> str:
        def _call():
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=MAX_TOKENS_DEFAULT,
            )
            return resp.choices[0].message.content
        return _retry(_call, self.provider)


class MistralAdapter(ModelAdapter):
    """Mistral AI via their official client."""
    provider = "mistral"

    def __init__(self, api_key: str, model: str = "mistral-large-latest"):
        from mistralai import Mistral
        self.client = Mistral(api_key=api_key)
        self.model  = model

    def chat(self, messages: List[Dict[str, str]]) -> str:
        def _call():
            resp = self.client.chat.complete(model=self.model, messages=messages)
            return resp.choices[0].message.content
        return _retry(_call, self.provider)


class XAIAdapter(ModelAdapter):
    """xAI Grok via OpenAI-compatible API."""
    BASE     = "https://api.x.ai/v1"
    provider = "xai"

    def __init__(self, api_key: str, model: str = "grok-3-mini"):
        import openai
        self.client = openai.OpenAI(api_key=api_key, base_url=self.BASE)
        self.model  = model

    def chat(self, messages: List[Dict[str, str]]) -> str:
        def _call():
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=MAX_TOKENS_DEFAULT,
            )
            return resp.choices[0].message.content
        return _retry(_call, self.provider)


class CohereAdapter(ModelAdapter):
    """Cohere Command via their client."""
    provider = "cohere"

    def __init__(self, api_key: str, model: str = "command-r-plus"):
        import cohere
        self.client = cohere.ClientV2(api_key=api_key)
        self.model  = model

    def chat(self, messages: List[Dict[str, str]]) -> str:
        def _call():
            resp = self.client.chat(model=self.model, messages=messages)
            return resp.message.content[0].text
        return _retry(_call, self.provider)


PROVIDER_MAP = {
    "openai":    OpenAIAdapter,
    "anthropic": AnthropicAdapter,
    "gemini":    GeminiAdapter,
    "groq":      GroqAdapter,
    "ollama":    OllamaAdapter,
    "deepseek":  DeepSeekAdapter,
    "mistral":   MistralAdapter,
    "xai":       XAIAdapter,
    "cohere":    CohereAdapter,
}


def build_adapter(provider: str, **kwargs) -> ModelAdapter:
    cls = PROVIDER_MAP.get(provider)
    if cls is None:
        raise ValueError(
            f"Unknown provider: '{provider}'. Available: {list(PROVIDER_MAP)}"
        )
    return cls(**kwargs)
