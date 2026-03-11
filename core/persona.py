from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Any
import json
from pathlib import Path


@dataclass
class PersonaIdentity:
    name: str = "Agent"
    job_title: str = "Software Engineer"
    backstory: str = ""


@dataclass
class PersonaPsychology:
    traits: List[str] = field(default_factory=list)
    conflict_style: str = "balanced"
    risk_tolerance: str = "medium"
    creativity: int = 5
    criticality: int = 5


@dataclass
class PersonaLinguistics:
    tone: str = "professional"
    verbosity: str = "medium"
    signature_prefix: str = "{name} dice:"
    reply_prefix: str = "{name} responde a {agent}:"
    catchphrase: str = ""


@dataclass
class PersonaWorkRules:
    allowed_areas: List[str] = field(default_factory=list)
    blocked_areas: List[str] = field(default_factory=list)
    priorities: List[str] = field(default_factory=list)
    must_reference_previous_agents: bool = True
    must_describe_cross_impact: bool = True


@dataclass
class PersonaSocial:
    respect_hierarchy: bool = True
    challenges_superiors: bool = False
    preferred_targets: List[str] = field(default_factory=list)


@dataclass
class PersonaProfile:
    identity: PersonaIdentity = field(default_factory=PersonaIdentity)
    psychology: PersonaPsychology = field(default_factory=PersonaPsychology)
    linguistics: PersonaLinguistics = field(default_factory=PersonaLinguistics)
    work_rules: PersonaWorkRules = field(default_factory=PersonaWorkRules)
    social: PersonaSocial = field(default_factory=PersonaSocial)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PersonaProfile":
        return cls(
            identity=PersonaIdentity(**data.get("identity", {})),
            psychology=PersonaPsychology(**data.get("psychology", {})),
            linguistics=PersonaLinguistics(**data.get("linguistics", {})),
            work_rules=PersonaWorkRules(**data.get("work_rules", {})),
            social=PersonaSocial(**data.get("social", {})),
        )

    @classmethod
    def from_json_file(cls, path: str | Path) -> "PersonaProfile":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def render_signature_prefix(self) -> str:
        return self.linguistics.signature_prefix.format(
            name=self.identity.name
        )

    def render_reply_prefix(self, agent_name: str) -> str:
        return self.linguistics.reply_prefix.format(
            name=self.identity.name,
            agent=agent_name,
        )

    def prompt_block(self) -> str:
        return "\n".join([
            f"Identity: {self.identity.name}, {self.identity.job_title}.",
            f"Backstory: {self.identity.backstory or 'N/A'}",
            f"Traits: {', '.join(self.psychology.traits) or 'N/A'}",
            f"Conflict style: {self.psychology.conflict_style}.",
            f"Risk tolerance: {self.psychology.risk_tolerance}.",
            f"Tone: {self.linguistics.tone}.",
            f"Verbosity: {self.linguistics.verbosity}.",
            f"Signature prefix: {self.render_signature_prefix()}",
            f"Reply prefix pattern: {self.linguistics.reply_prefix}",
            f"Catchphrase: {self.linguistics.catchphrase or 'N/A'}",
            f"Allowed areas: {', '.join(self.work_rules.allowed_areas) or 'any'}",
            f"Blocked areas: {', '.join(self.work_rules.blocked_areas) or 'none'}",
            f"Priorities: {', '.join(self.work_rules.priorities) or 'quality'}",
            f"Reference previous agents: {self.work_rules.must_reference_previous_agents}",
            f"Describe cross impact: {self.work_rules.must_describe_cross_impact}",
            f"Respect hierarchy: {self.social.respect_hierarchy}",
            f"Can challenge superiors: {self.social.challenges_superiors}",
        ])
