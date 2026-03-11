"""An AgentGroup Agent: a named AI with a role and a model backend."""
from __future__ import annotations
from typing import List, Dict
from core.models import ModelAdapter


class Agent:
    def __init__(self, name: str, role: str, adapter: ModelAdapter):
        self.name = name
        self.role = role
        self.adapter = adapter
        self.history: List[Dict[str, str]] = []

    # ------------------------------------------------------------------ #
    # Core interaction
    # ------------------------------------------------------------------ #

    def system_prompt(self) -> str:
        return (
            f"You are {self.name}, a {self.role} in an AI collaborative coding team.\n"
            "Your team is working together to review, improve, and commit changes to a "
            "GitHub repository. Be concise, constructive, and technical.\n"
            "When proposing code changes, wrap them in ```diff blocks.\n"
            "When you agree with a proposal write APPROVE. When you disagree write REJECT: <reason>."
        )

    def say(self, user_message: str) -> str:
        """Send a message and get a response, maintaining conversation history."""
        if not self.history:
            self.history.append({"role": "system", "content": self.system_prompt()})
        self.history.append({"role": "user", "content": user_message})
        response = self.adapter.chat(self.history)
        self.history.append({"role": "assistant", "content": response})
        return response

    def reset(self):
        self.history = []
