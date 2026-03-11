"""AgentGroup – configuration loader."""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    github_token:      str = field(default_factory=lambda: os.getenv("GITHUB_TOKEN", ""))
    openai_api_key:    str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    gemini_api_key:    str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    groq_api_key:      str = field(default_factory=lambda: os.getenv("GROQ_API_KEY", ""))
    ollama_api_key:    str = field(default_factory=lambda: os.getenv("OLLAMA_API_KEY", ""))
    ollama_base_url:   str = field(default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
    deepseek_api_key:  str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""))
    mistral_api_key:   str = field(default_factory=lambda: os.getenv("MISTRAL_API_KEY", ""))
    xai_api_key:       str = field(default_factory=lambda: os.getenv("XAI_API_KEY", ""))
    cohere_api_key:    str = field(default_factory=lambda: os.getenv("COHERE_API_KEY", ""))
    telegram_token:    str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id:  str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
    search_api_key:    str = field(default_factory=lambda: os.getenv("SEARCH_API_KEY", ""))


config = Config()
