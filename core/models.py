"""Model provider adapters – unified chat(messages) -> str interface.

Providers: OpenAI, Anthropic, Gemini, Groq, Ollama, DeepSeek, Mistral, xAI (Grok)
"""
from __future__ import annotations
from typing import List, Dict
import requests


class ModelAdapter:
    def chat(self, messages: List[Dict[str, str]]) -> str:
        raise NotImplementedError


class OpenAIAdapter(ModelAdapter):
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        import openai
        self.client = openai.OpenAI(api_key=api_key)
        self.model  = model

    def chat(self, messages):
        resp = self.client.chat.completions.create(model=self.model, messages=messages)
        return resp.choices[0].message.content


class AnthropicAdapter(ModelAdapter):
    def __init__(self, api_key: str, model: str = "claude-3-5-haiku-20241022"):
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model  = model

    def chat(self, messages):
        system    = next((m["content"] for m in messages if m["role"] == "system"), "")
        user_msgs = [m for m in messages if m["role"] != "system"]
        resp = self.client.messages.create(
            model=self.model, max_tokens=4096, system=system, messages=user_msgs
        )
        return resp.content[0].text


class GeminiAdapter(ModelAdapter):
    def __init__(self, api_key: str, model: str = "gemini-1.5-flash"):
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        self.model_obj = genai.GenerativeModel(model)

    def chat(self, messages):
        text = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages)
        return self.model_obj.generate_content(text).text


class GroqAdapter(ModelAdapter):
    def __init__(self, api_key: str, model: str = "llama-3.1-8b-instant"):
        from groq import Groq
        self.client = Groq(api_key=api_key)
        self.model  = model

    def chat(self, messages):
        resp = self.client.chat.completions.create(model=self.model, messages=messages)
        return resp.choices[0].message.content


class OllamaAdapter(ModelAdapter):
    def __init__(self, model: str = "llama3.2", base_url: str = "http://localhost:11434", api_key: str = ""):
        self.model    = model
        self.endpoint = ("https://ollama.com/api/chat" if "ollama.com" in base_url
                         else base_url.rstrip("/") + "/api/chat")
        self.headers: Dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    def chat(self, messages):
        resp = requests.post(self.endpoint, json={"model": self.model, "messages": messages, "stream": False},
                             headers=self.headers, timeout=120)
        resp.raise_for_status()
        return resp.json()["message"]["content"]


class DeepSeekAdapter(ModelAdapter):
    """DeepSeek via their OpenAI-compatible API."""
    BASE = "https://api.deepseek.com/v1"

    def __init__(self, api_key: str, model: str = "deepseek-coder"):
        import openai
        self.client = openai.OpenAI(api_key=api_key, base_url=self.BASE)
        self.model  = model

    def chat(self, messages):
        resp = self.client.chat.completions.create(model=self.model, messages=messages)
        return resp.choices[0].message.content


class MistralAdapter(ModelAdapter):
    """Mistral AI via their official client."""

    def __init__(self, api_key: str, model: str = "mistral-large-latest"):
        from mistralai import Mistral
        self.client = Mistral(api_key=api_key)
        self.model  = model

    def chat(self, messages):
        resp = self.client.chat.complete(model=self.model, messages=messages)
        return resp.choices[0].message.content


class XAIAdapter(ModelAdapter):
    """xAI Grok via OpenAI-compatible API."""
    BASE = "https://api.x.ai/v1"

    def __init__(self, api_key: str, model: str = "grok-3-mini"):
        import openai
        self.client = openai.OpenAI(api_key=api_key, base_url=self.BASE)
        self.model  = model

    def chat(self, messages):
        resp = self.client.chat.completions.create(model=self.model, messages=messages)
        return resp.choices[0].message.content


class CohereAdapter(ModelAdapter):
    """Cohere Command via their client."""

    def __init__(self, api_key: str, model: str = "command-r-plus"):
        import cohere
        self.client = cohere.ClientV2(api_key=api_key)
        self.model  = model

    def chat(self, messages):
        resp = self.client.chat(model=self.model, messages=messages)
        return resp.message.content[0].text


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
        raise ValueError(f"Unknown provider: '{provider}'. Available: {list(PROVIDER_MAP)}")
    return cls(**kwargs)
