"""AgentGroup Agent v2 – org-position aware."""
from __future__ import annotations
from typing import List, Dict, Optional
from core.models import ModelAdapter

ROLE_EMOJIS = {
    "Tech Lead / Architect":           "🏛️",
    "Senior Software Engineer":        "🧠",
    "Software Engineer":               "💻",
    "UI/UX Engineer":                  "🎨",
    "Security Reviewer":               "🔒",
    "DevOps / Performance Engineer":   "⚙️",
}


class Agent:
    def __init__(self, name: str, role: str, adapter: ModelAdapter, position: str = "Software Engineer"):
        self.name     = name
        self.role     = role
        self.position = position
        self.emoji    = ROLE_EMOJIS.get(position, "🤖")
        self.adapter  = adapter
        self.history: List[Dict[str, str]] = []

    def system_prompt(self) -> str:
        return (
            f"You are {self.name}, {self.emoji} {self.position} ({self.role}) in an AI engineering team.\n"
            "The team works in org-chart order: Tech Lead → Senior Engineer → Engineers → Specialists.\n"
            "Your role affects HOW you respond:\n"
            "  - Tech Lead: high-level architecture decisions, final approval authority.\n"
            "  - Senior SW Engineer: implementation details, API design, patterns.\n"
            "  - SW Engineer: concrete code fixes, bug patches.\n"
            "  - UI/UX Engineer: user experience, accessibility, frontend code.\n"
            "  - Security Reviewer: vulnerabilities, input validation, secrets management.\n"
            "  - DevOps Engineer: CI/CD, Docker, performance, scaling.\n"
            "Rules:\n"
            "1. When proposing code changes, use ```diff blocks.\n"
            "2. When replying to a colleague mention their name: 'Replying to <Name>: ...'.\n"
            "3. Explicitly state how your change might AFFECT other areas of the codebase.\n"
            "4. End with APPROVE, REJECT: <reason>, or DEFER TO <Role>.\n"
            "Be concise (max 300 words per turn)."
        )

    def say(self, user_message: str, context: Optional[str] = None) -> str:
        if not self.history:
            self.history.append({"role": "system", "content": self.system_prompt()})
        msg = user_message
        if context:
            msg = f"[Context from previous agents]:\n{context}\n\n[Your turn]:\n{user_message}"
        self.history.append({"role": "user", "content": msg})
        response = self.adapter.chat(self.history)
        self.history.append({"role": "assistant", "content": response})
        return response

    def reset(self):
        self.history = []
