"""Agent – a single AI participant in the group discussion.

Fixes:
- Integrates ContextManager to prevent context window overflow
- Adds history size limit to avoid unbounded memory growth
- Cleaner error propagation with descriptive messages
"""
from __future__ import annotations
from typing import Optional
from core.models import ModelAdapter
from core.persona import PersonaProfile
from core.context_manager import ContextManager, TruncationStrategy

# Max messages kept in agent history before truncation
MAX_HISTORY = 50

ROLE_EMOJIS = {
    "Tech Lead / Architect":           "\U0001f3db\ufe0f",
    "Senior Software Engineer":        "\U0001f9e0",
    "Software Engineer":               "\U0001f4bb",
    "UI/UX Engineer":                  "\U0001f3a8",
    "Security Reviewer":               "\U0001f512",
    "DevOps / Performance Engineer":   "\u2699\ufe0f",
}


class Agent:
    """
    A single agent in the group session.

    Parameters
    ----------
    name     : display name
    role     : free-text role description used in the system prompt
    adapter  : ModelAdapter instance (provider-specific)
    position : org-chart role (must match ROLE_HIERARCHY)
    persona  : PersonaProfile (tone, verbosity, rules, etc.)
    """

    def __init__(
        self,
        name:     str,
        role:     str,
        adapter:  ModelAdapter,
        position: str = "Software Engineer",
        persona:  Optional[PersonaProfile] = None,
    ):
        self.name     = name
        self.role     = role
        self.adapter  = adapter
        self.position = position
        self.persona  = persona or PersonaProfile()
        self.emoji    = ROLE_EMOJIS.get(position, "\U0001f916")
        self.history: list[dict] = []

        # Context manager sized to the adapter's model (if known)
        model_name = getattr(adapter, "model", "")
        self._ctx  = ContextManager(
            model=model_name,
            strategy=TruncationStrategy.SUMMARISE,
        )

    # ─ System prompt ────────────────────────────────────────────────────────────

    def _build_system_prompt(self) -> str:
        p = self.persona
        lines = [
            f"You are {self.name}, {self.role}.",
            f"Org position: {self.position}.",
            f"Tone: {p.linguistics.tone}. Verbosity: {p.linguistics.verbosity}.",
        ]
        if p.identity.backstory:
            lines.append(f"Background: {p.identity.backstory}")
        if p.work_rules.priorities:
            lines.append(f"Priorities: {', '.join(p.work_rules.priorities)}")
        if p.work_rules.blocked_areas:
            lines.append(f"Do NOT comment on: {', '.join(p.work_rules.blocked_areas)}")
        if p.work_rules.must_reference_previous_agents:
            lines.append(
                "Always reference and build on what previous agents said."
            )
        if p.work_rules.must_describe_cross_impact:
            lines.append(
                "Describe the cross-impact of your proposals on other components."
            )
        if p.linguistics.catchphrase:
            lines.append(f"Your catchphrase is: '{p.linguistics.catchphrase}'")
        return "\n".join(lines)

    # ─ Core say() ──────────────────────────────────────────────────────────────

    def say(self, user_message: str, context: str = "") -> str:
        """
        Send a message to the agent and return its response.

        Parameters
        ----------
        user_message : the prompt / task text
        context      : optional extra context prepended to user_message
        """
        full_user = f"{context}\n\n{user_message}".strip() if context else user_message

        self.history.append({"role": "user", "content": full_user})

        # Trim history if it grows too large
        if len(self.history) > MAX_HISTORY:
            self.history = self.history[-MAX_HISTORY:]

        messages = [
            {"role": "system", "content": self._build_system_prompt()},
            *self.history,
        ]

        # Fit within context window
        messages = self._ctx.fit(messages)

        try:
            response = self.adapter.chat(messages)
        except Exception as e:
            error_msg = f"[{self.name}] API error: {e}"
            self.history.pop()  # remove failed user message
            return error_msg

        self.history.append({"role": "assistant", "content": response})
        return response

    def reset_history(self):
        """Clear conversation history (start fresh)."""
        self.history.clear()

    def __repr__(self) -> str:
        return f"Agent(name={self.name!r}, position={self.position!r}, model={getattr(self.adapter, 'model', '?')!r})"
