"""AgentGroup Agent v3 – persona-aware, org-position aware."""
from __future__ import annotations
from typing import List, Dict, Optional
from core.models import ModelAdapter
from core.persona import PersonaProfile

ROLE_EMOJIS = {
    "Tech Lead / Architect":           "🏛️",
    "Senior Software Engineer":        "🧠",
    "Software Engineer":               "💻",
    "UI/UX Engineer":                  "🎨",
    "Security Reviewer":               "🔒",
    "DevOps / Performance Engineer":   "⚙️",
}


class Agent:
    def __init__(
        self,
        name: str,
        role: str,
        adapter: ModelAdapter,
        position: str = "Software Engineer",
        persona: Optional[PersonaProfile] = None,
    ):
        self.name     = name
        self.role     = role
        self.position = position
        self.emoji    = ROLE_EMOJIS.get(position, "🤖")
        self.adapter  = adapter
        self.persona  = persona or PersonaProfile()
        # Keep persona identity in sync with the agent name/position
        self.persona.identity.name      = name
        self.persona.identity.job_title = position
        self.history: List[Dict[str, str]] = []

    def system_prompt(self) -> str:
        persona_block = self.persona.prompt_block()
        return (
            f"You are {self.name}, {self.emoji} {self.position} ({self.role}) "
            "in a collaborative AI engineering team.\n"
            "The team works in org-chart order: Tech Lead → Senior Engineer → Engineers → Specialists.\n\n"
            "== YOUR PERSONA ==\n"
            f"{persona_block}\n\n"
            "== RULES ==\n"
            "1. Speak strictly in character according to your persona.\n"
            "2. Use your configured signature prefix naturally (e.g. 'Claude dice:').\n"
            "3. When replying to another agent use the reply prefix pattern "
            "(e.g. 'Claude responde a Gemini:').\n"
            "4. When proposing code changes, use ```diff blocks.\n"
            "5. Explicitly describe how your change affects OTHER areas of the codebase.\n"
            "6. End with APPROVE, REJECT: <reason>, or DEFER.\n"
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
