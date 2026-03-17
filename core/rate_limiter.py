"""RateLimiter – simple token-bucket per provider to avoid 429 errors.

Each provider has a configurable RPM (requests per minute) limit.
The limiter blocks with time.sleep() before each API call.
"""
from __future__ import annotations
import time
from threading import Lock
from typing import Dict

# Default safe RPM limits per provider (conservative defaults)
DEFAULT_RPM: Dict[str, int] = {
    "openai":    60,
    "anthropic": 50,
    "gemini":    60,
    "groq":      30,   # Groq free tier is very limited
    "deepseek":  30,
    "mistral":   60,
    "xai":       60,
    "cohere":    40,
    "ollama":    120,  # local, no real limit
}


class ProviderRateLimiter:
    """Token-bucket rate limiter for a single provider."""

    def __init__(self, rpm: int):
        self.min_interval = 60.0 / max(rpm, 1)
        self._last_call   = 0.0
        self._lock        = Lock()

    def wait(self):
        with self._lock:
            now     = time.monotonic()
            elapsed = now - self._last_call
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self._last_call = time.monotonic()


class RateLimiterRegistry:
    """Global registry of per-provider rate limiters."""

    def __init__(self):
        self._limiters: Dict[str, ProviderRateLimiter] = {}
        self._lock = Lock()

    def get(self, provider: str, rpm: int | None = None) -> ProviderRateLimiter:
        with self._lock:
            if provider not in self._limiters:
                effective_rpm = rpm or DEFAULT_RPM.get(provider, 60)
                self._limiters[provider] = ProviderRateLimiter(effective_rpm)
            return self._limiters[provider]

    def wait(self, provider: str):
        self.get(provider).wait()


# Singleton
rate_limiter = RateLimiterRegistry()
