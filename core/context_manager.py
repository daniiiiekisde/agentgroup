"""ContextManager – prevents LLM token overflow in long multi-agent sessions.

Problem: As sessions grow, the full conversation history sent to each agent
exceeds context window limits (e.g. 8k, 32k, 128k tokens depending on model).

Solution:
- Track approximate token count (chars / 4 as a rough estimate)
- When context approaches the limit, apply one of two strategies:
    1. TRUNCATE  – keep system prompt + last N messages
    2. SUMMARISE – compress old turns into a rolling summary
"""
from __future__ import annotations
import re
from enum import Enum
from typing import List, Dict

# Approximate chars-per-token ratio (conservative)
CHARS_PER_TOKEN = 4

# Per-model context window limits (tokens). Add new models here as needed.
MODEL_CONTEXT_LIMITS: Dict[str, int] = {
    # OpenAI
    "gpt-4o":              128_000,
    "gpt-4o-mini":         128_000,
    "gpt-4-turbo":         128_000,
    "gpt-3.5-turbo":        16_385,
    # Anthropic
    "claude-opus-4-5":     200_000,
    "claude-sonnet-4-5":   200_000,
    "claude-3-5-haiku-20241022": 200_000,
    # Gemini
    "gemini-1.5-pro":    1_000_000,
    "gemini-1.5-flash":  1_000_000,
    "gemini-2.0-flash":  1_000_000,
    # Groq hosted
    "llama-3.3-70b-versatile": 128_000,
    "llama-3.1-8b-instant":    128_000,
    "mixtral-8x7b-32768":       32_768,
    "gemma2-9b-it":             8_192,
    # DeepSeek
    "deepseek-coder":    64_000,
    "deepseek-chat":     64_000,
    "deepseek-reasoner": 64_000,
    # Mistral
    "mistral-large-latest":  128_000,
    "mistral-small-latest":  128_000,
    "codestral-latest":      256_000,
    "open-mistral-nemo":     128_000,
    # xAI
    "grok-3-mini": 131_072,
    "grok-3":      131_072,
    "grok-2":      131_072,
    # Cohere
    "command-r-plus":     128_000,
    "command-r":          128_000,
    "command-a-03-2025":  256_000,
}

DEFAULT_LIMIT = 32_000  # safe fallback for unknown models
# Reserve this many tokens for the model's response
RESPONSE_RESERVE = 4_096


class TruncationStrategy(str, Enum):
    TRUNCATE  = "truncate"   # drop oldest non-system messages
    SUMMARISE = "summarise"  # collapse old messages into a summary header


def _count_tokens(messages: List[Dict[str, str]]) -> int:
    """Rough token count estimate (chars / CHARS_PER_TOKEN)."""
    total = sum(len(m.get("content", "")) for m in messages)
    return total // CHARS_PER_TOKEN


def _summarise_messages(messages: List[Dict[str, str]]) -> str:
    """Produce a brief summary of a list of messages."""
    lines = []
    for m in messages:
        role    = m.get("role", "?")
        content = m.get("content", "")[:200].replace("\n", " ")
        lines.append(f"[{role}]: {content}")
    return "[Earlier conversation summary]\n" + "\n".join(lines)


class ContextManager:
    """
    Manage the message list sent to an LLM to stay within its context window.

    Usage:
        cm = ContextManager(model="gpt-4o-mini")
        safe_messages = cm.fit(messages)
    """

    def __init__(
        self,
        model: str = "",
        strategy: TruncationStrategy = TruncationStrategy.TRUNCATE,
        reserve_tokens: int = RESPONSE_RESERVE,
    ):
        raw_limit   = MODEL_CONTEXT_LIMITS.get(model, DEFAULT_LIMIT)
        self.limit  = raw_limit - reserve_tokens
        self.model  = model
        self.strategy = strategy

    def fits(self, messages: List[Dict[str, str]]) -> bool:
        return _count_tokens(messages) <= self.limit

    def fit(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Return a version of messages that fits within the context window."""
        if self.fits(messages):
            return messages

        system_msgs = [m for m in messages if m.get("role") == "system"]
        other_msgs  = [m for m in messages if m.get("role") != "system"]

        if self.strategy == TruncationStrategy.TRUNCATE:
            return self._truncate(system_msgs, other_msgs)
        else:
            return self._summarise(system_msgs, other_msgs)

    def _truncate(self, system_msgs, other_msgs):
        """Keep system messages + most recent non-system messages that fit."""
        # Always keep at least the last 2 messages for context continuity
        result = list(system_msgs)
        budget = self.limit - _count_tokens(system_msgs)
        kept   = []
        for m in reversed(other_msgs):
            cost = len(m.get("content", "")) // CHARS_PER_TOKEN
            if budget - cost >= 0:
                kept.append(m)
                budget -= cost
            else:
                break
        kept.reverse()
        return result + kept

    def _summarise(self, system_msgs, other_msgs):
        """Collapse old messages into a summary, keep recent ones."""
        # Keep last 6 messages verbatim
        recent = other_msgs[-6:]
        old    = other_msgs[:-6]
        if not old:
            return self._truncate(system_msgs, other_msgs)  # fallback
        summary_content = _summarise_messages(old)
        summary_msg = {"role": "system", "content": summary_content}
        candidate = system_msgs + [summary_msg] + recent
        if self.fits(candidate):
            return candidate
        # Still too long — truncate
        return self._truncate(system_msgs + [summary_msg], recent)
