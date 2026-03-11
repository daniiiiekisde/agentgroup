"""AgentGroup Session Memory – per-agent short-term + cross-agent shared memory.

Inspired by MemGPT / Letta memory blocks and ZeroClaw's context window management.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from pathlib import Path


@dataclass
class MemoryBlock:
    """A named, editable block of text that persists in agent context."""
    name: str
    content: str = ""
    max_chars: int = 1000

    def update(self, text: str):
        self.content = text[:self.max_chars]

    def append(self, text: str):
        combined = (self.content + "\n" + text).strip()
        self.content = combined[-self.max_chars:]

    def render(self) -> str:
        return f"[{self.name}]\n{self.content}" if self.content else ""


@dataclass
class AgentMemory:
    """Per-agent memory: persona block + working notes + recall store."""
    agent_name: str
    persona: MemoryBlock = field(default_factory=lambda: MemoryBlock("persona", max_chars=600))
    working: MemoryBlock = field(default_factory=lambda: MemoryBlock("working_notes", max_chars=800))
    recall: List[str]    = field(default_factory=list)  # previous session summaries

    def recall_str(self, n: int = 3) -> str:
        recent = self.recall[-n:]
        return "\n".join(f"- {r}" for r in recent) if recent else ""

    def render_context(self) -> str:
        parts = []
        if self.persona.content:
            parts.append(self.persona.render())
        if self.working.content:
            parts.append(self.working.render())
        if self.recall:
            parts.append(f"[recall]\n{self.recall_str()}")
        return "\n\n".join(parts)


class SessionMemory:
    """Shared cross-agent memory for a single discussion session."""

    def __init__(self):
        self.shared_notes: List[str]         = []
        self.decisions:    List[str]         = []
        self.agent_mems:   Dict[str, AgentMemory] = {}

    def get_agent(self, name: str) -> AgentMemory:
        if name not in self.agent_mems:
            self.agent_mems[name] = AgentMemory(agent_name=name)
        return self.agent_mems[name]

    def add_shared_note(self, note: str):
        self.shared_notes.append(note)
        if len(self.shared_notes) > 30:
            self.shared_notes = self.shared_notes[-30:]

    def record_decision(self, agent_name: str, decision: str):
        self.decisions.append(f"{agent_name}: {decision}")

    def shared_context_block(self) -> str:
        parts = []
        if self.shared_notes:
            notes = "\n".join(f"• {n}" for n in self.shared_notes[-10:])
            parts.append(f"[shared_notes]\n{notes}")
        if self.decisions:
            decs = "\n".join(f"• {d}" for d in self.decisions[-6:])
            parts.append(f"[decisions_so_far]\n{decs}")
        return "\n\n".join(parts)

    def save(self, path: str | Path):
        data = {
            "shared_notes": self.shared_notes,
            "decisions":    self.decisions,
            "agents": {
                name: {
                    "persona":  mem.persona.content,
                    "working":  mem.working.content,
                    "recall":   mem.recall,
                }
                for name, mem in self.agent_mems.items()
            }
        }
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False))

    @classmethod
    def load(cls, path: str | Path) -> "SessionMemory":
        sm = cls()
        data = json.loads(Path(path).read_text())
        sm.shared_notes = data.get("shared_notes", [])
        sm.decisions    = data.get("decisions", [])
        for name, mem_data in data.get("agents", {}).items():
            am = sm.get_agent(name)
            am.persona.content = mem_data.get("persona", "")
            am.working.content = mem_data.get("working", "")
            am.recall          = mem_data.get("recall", [])
        return sm
