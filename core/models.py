"""Model provider adapters – unified chat(messages) -> str interface."""
from __future__ import annotations
from typing import List, Dict
import requests


class ModelAdapter:
    """Base class; subclasses implement `chat`."""

    def chat(self, messages: List[Dict[str, str]]) -> str:
        raise NotImplementedError


class OpenAIAdapter(ModelAdapter):
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        import openai
        self.client = openai.OpenAI(api_key=api_key)
        self.model = model

    def chat(self, messages):
        resp = self.client.chat.completions.create(model=self.model, messages=messages)
        return resp.choices[0].message.content


class AnthropicAdapter(ModelAdapter):
    def __init__(self, api_key: str, model: str = "claude-3-5-haiku-20241022"):
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def chat(self, messages):
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        user_msgs = [m for m in messages if m["role"] != "system"]
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system,
            messages=user_msgs,
        )
        return resp.content[0].text


class GeminiAdapter(ModelAdapter):
    def __init__(self, api_key: str, model: str = "gemini-1.5-flash"):
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        self.model_obj = genai.GenerativeModel(model)

    def chat(self, messages):
        text = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages)
        resp = self.model_obj.generate_content(text)
        return resp.text


class GroqAdapter(ModelAdapter):
    def __init__(self, api_key: str, model: str = "llama-3.1-8b-instant"):
        from groq import Groq
        self.client = Groq(api_key=api_key)
        self.model = model

    def chat(self, messages):
        resp = self.client.chat.completions.create(model=self.model, messages=messages)
        return resp.choices[0].message.content


class OllamaAdapter(ModelAdapter):
    """Works with local Ollama (http://localhost:11434) and Ollama Cloud.
    For Ollama Cloud set base_url='https://ollama.com/api' and provide api_key.
    """

    def __init__(
        self,
        model: str = "llama3.2",
        base_url: str = "http://localhost:11434",
        api_key: str = "",
    ):
        self.model = model
        # Ollama Cloud exposes OpenAI-compatible endpoint at /v1
        if "ollama.com" in base_url:
            self.endpoint = "https://ollama.com/api/chat"
        else:
            self.endpoint = base_url.rstrip("/") + "/api/chat"
        self.headers: Dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    def chat(self, messages):
        payload = {"model": self.model, "messages": messages, "stream": False}
        resp = requests.post(self.endpoint, json=payload, headers=self.headers, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"]


PROVIDER_MAP = {
    "openai": OpenAIAdapter,
    "anthropic": AnthropicAdapter,
    "gemini": GeminiAdapter,
    "groq": GroqAdapter,
    "ollama": OllamaAdapter,
}


def build_adapter(provider: str, **kwargs) -> ModelAdapter:
    cls = PROVIDER_MAP.get(provider)
    if cls is None:
        raise ValueError(f"Unknown provider: {provider}")
    return cls(**kwargs)
