"""AgentGroup Discussion v3 – persona-aware, threaded, org-sorted."""
from __future__ import annotations
import re, time
from typing import List, Optional, Callable
from core.agent import Agent
from core.github_ops import GitHubOps
from core.telegram_bot import TelegramRelay

HIERARCHY_ORDER = [
    "Tech Lead / Architect",
    "Senior Software Engineer",
    "Software Engineer",
    "UI/UX Engineer",
    "Security Reviewer",
    "DevOps / Performance Engineer",
]


def _sort_agents(agents: List[Agent]) -> List[Agent]:
    def rank(a: Agent):
        try:    return HIERARCHY_ORDER.index(a.position)
        except: return 99
    return sorted(agents, key=rank)


def format_agent_message(agent: Agent, text: str, reply_to: Optional[str] = None) -> str:
    """Prepend persona signature or threaded reply prefix to a message."""
    if reply_to:
        prefix = agent.persona.render_reply_prefix(reply_to)
    else:
        prefix = agent.persona.render_signature_prefix()

    catchphrase = (agent.persona.linguistics.catchphrase or "").strip()
    if catchphrase:
        return f"{prefix} {text}\n\n_{catchphrase}_"
    return f"{prefix} {text}"


def _bubble_html(
    agent: Agent,
    text: str,
    reply_to: Optional[str] = None,
    vote: Optional[str] = None,
    is_reply: bool = False,
) -> str:
    reply_html = ""
    if reply_to:
        reply_html = f"<div class='reply-to'>↩ {reply_to}</div>"
    vote_html = ""
    if vote:
        cls = "vote-approve" if "APPROVE" in vote.upper() else "vote-reject"
        vote_html = f"<div class='vote'><span class='{cls}'>{vote}</span></div>"
    cls = "ag-msg reply" if is_reply else "ag-msg"

    # Catchphrase badge
    catchphrase = (agent.persona.linguistics.catchphrase or "").strip()
    cp_html = ""
    if catchphrase:
        cp_html = f"<div class='catchphrase'>💬 {catchphrase}</div>"

    # Tone / verbosity badges
    tone      = agent.persona.linguistics.tone
    verbosity = agent.persona.linguistics.verbosity
    badges_html = (
        f"<span class='persona-badge'>{tone}</span>"
        f"<span class='persona-badge'>{verbosity}</span>"
    )

    return (
        f"<div class='{cls}'>"
        f"  <div class='ag-avatar'>{agent.emoji}</div>"
        f"  <div class='ag-bubble'>"
        f"    <div class='sender'>{agent.name}"
        f"      <span class='role-tag'>{agent.position}</span>"
        f"      {badges_html}</div>"
        f"    {reply_html}"
        f"    <div class='body'>{text}</div>"
        f"    {cp_html}"
        f"    {vote_html}"
        f"  </div>"
        f"</div>"
    )


def _divider(text: str) -> str:
    return f"<div class='ag-divider'>— {text} —</div>"


class Discussion:
    def __init__(
        self,
        agents: List[Agent],
        github_ops: GitHubOps,
        telegram: Optional[TelegramRelay] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ):
        self.agents = _sort_agents(agents)
        self.gh     = github_ops
        self.tg     = telegram
        self.log    = log_callback or print
        self.html_parts: List[str] = []
        self.log_lines: List[str]  = []

    def _log(self, msg: str):
        self.log_lines.append(msg)
        self.log(msg)
        if self.tg:
            self.tg.send(msg)

    def _add_bubble(self, agent, text, reply_to=None, vote=None, is_reply=False):
        self.html_parts.append(_bubble_html(agent, text, reply_to, vote, is_reply))

    def _extract_diff(self, text: str) -> Optional[str]:
        m = re.search(r"```diff\n(.+?)```", text, re.DOTALL)
        return m.group(1) if m else None

    def _extract_vote(self, text: str) -> str:
        if re.search(r"\bAPPROVE\b", text, re.IGNORECASE):
            return "✅ APPROVE"
        m = re.search(r"REJECT:\s*(.+)", text, re.IGNORECASE)
        if m:
            return f"❌ REJECT: {m.group(1)[:120]}"
        return "🔄 DEFER"

    def _majority_approved(self, votes: List[str]) -> bool:
        return sum(1 for v in votes if "APPROVE" in v.upper()) > len(votes) / 2

    def _apply_diff(self, original: str, diff: str) -> str:
        result = []
        for line in diff.splitlines(keepends=True):
            if line.startswith("+") and not line.startswith("+++"):
                result.append(line[1:])
            elif line.startswith("-") and not line.startswith("---"):
                pass
            elif not line.startswith(("@@", "---", "+++")):
                result.append(line)
        return "".join(result) if result else original

    def _detect_reply_target(self, response: str, proposals: list) -> Optional[str]:
        """Detect which agent is being replied to using persona reply prefix patterns."""
        # Try persona-aware pattern first: "<name> responde a <other>:"
        m = re.search(r"responde a (\w+):", response, re.IGNORECASE)
        if m:
            return m.group(1)
        # Fallback: legacy "Replying to <Name>:"
        m2 = re.search(r"Replying to (\w+):", response)
        if m2:
            return m2.group(1)
        return None

    # ────────────────────────────────────────────────
    # Main run
    # ────────────────────────────────────────────────

    def run(self, file_paths: List[str], task: str = "Review and improve.", branch_prefix: str = "agentgroup") -> dict:

        # 1. Fetch files
        self.html_parts.append(_divider("📂 Loading repository files"))
        file_contents: dict = {}
        for fp in file_paths:
            try:
                content, sha = self.gh.get_file(fp)
                file_contents[fp] = {"content": content, "sha": sha}
                self._log(f"📂 Fetched `{fp}` ({len(content)} chars)")
            except Exception as e:
                self._log(f"⚠️ Could not fetch `{fp}`: {e}")

        if not file_contents:
            return {"chat_html": self._wrap_html(), "log": self.log_lines, "pr_url": None, "error": "No files fetched."}

        context_block = "\n\n".join(
            f"### {fp}\n```\n{d['content']}\n```" for fp, d in file_contents.items()
        )

        # 2. Turn-based proposals (org order)
        self.html_parts.append(_divider("🗣️ Round 1 — Proposals"))
        conversation_context = f"Task: {task}\n\nFiles:\n{context_block}"
        proposals = []

        for agent in self.agents:
            prior_summaries = ""
            if proposals:
                prior_summaries = "Previous agents said:\n" + "\n".join(
                    f"- {p['agent'].name} ({p['agent'].position}): {p['text'][:300]}"
                    for p in proposals
                )
            prompt = f"{conversation_context}\n\n{prior_summaries}\n\nYour turn, {agent.name}."
            self._log(f"\n🤖 {agent.name} ({agent.position}) is thinking…")
            response = agent.say(prompt)

            # Detect threading
            reply_to_name = self._detect_reply_target(response, proposals)
            reply_to_text = None
            if reply_to_name and proposals:
                matching = [p for p in proposals if p['agent'].name.lower() == reply_to_name.lower()]
                if matching:
                    snippet = matching[-1]['text'][:120]
                    reply_to_text = f"{reply_to_name}: \"{snippet}…\""

            is_reply = reply_to_text is not None

            # Format message with persona signature
            formatted = format_agent_message(agent, response, reply_to=reply_to_name)
            self._add_bubble(agent, formatted, reply_to=reply_to_text, is_reply=is_reply)
            self._log(f"{agent.persona.render_signature_prefix()} {response[:400]}")
            proposals.append({"agent": agent, "text": response})

        # 3. Voting round
        self.html_parts.append(_divider("🗳️ Round 2 — Voting"))
        approved_changes = []

        for prop in proposals:
            proposer = prop["agent"]
            voters   = [a for a in self.agents if a is not proposer]
            if not voters:
                continue

            vote_prompt = (
                f"{proposer.persona.render_signature_prefix()} proposed:\n{prop['text']}\n\n"
                "Vote APPROVE or REJECT: <reason>. "
                "Mention how this change might affect the rest of the codebase."
            )
            votes = []
            for voter in voters:
                vote_text = voter.say(vote_prompt, context=f"Proposal by {proposer.name}")
                vote_str  = self._extract_vote(vote_text)
                formatted_vote = format_agent_message(voter, vote_text, reply_to=proposer.name)
                self._add_bubble(voter, formatted_vote, reply_to=f"{proposer.name}'s proposal", vote=vote_str, is_reply=True)
                self._log(f"🗳️ {voter.persona.render_signature_prefix()} → {vote_str}")
                votes.append(vote_text)

            if self._majority_approved(votes):
                diff = self._extract_diff(prop["text"])
                if diff:
                    approved_changes.append({"file_path": file_paths[0], "diff": diff, "proposer": proposer.name})
                self.html_parts.append(_divider(f"✅ {proposer.name}'s proposal APPROVED"))
            else:
                self.html_parts.append(_divider(f"❌ {proposer.name}'s proposal REJECTED"))

        # 4. Apply + PR
        pr_url = None
        if approved_changes:
            branch = f"{branch_prefix}-{int(time.time())}"
            try:
                self.gh.create_branch(branch)
                self._log(f"🌿 Branch `{branch}` created")
            except Exception as e:
                self._log(f"⚠️ Branch creation failed: {e}")
                return {"chat_html": self._wrap_html(), "log": self.log_lines, "pr_url": None}

            for change in approved_changes:
                fp       = change["file_path"]
                original = file_contents[fp]["content"]
                sha      = file_contents[fp]["sha"]
                new_cont = self._apply_diff(original, change["diff"])
                try:
                    self.gh.update_file(fp, new_cont, f"[AgentGroup] {change['proposer']}: {fp}", sha, branch=branch)
                    self._log(f"📝 Committed `{fp}` on `{branch}`")
                except Exception as e:
                    self._log(f"⚠️ Commit failed for `{fp}`: {e}")

            body = "## AgentGroup Auto-PR\n\n" + "\n".join(
                f"- **{c['proposer']}**: `{c['file_path']}`" for c in approved_changes
            )
            try:
                pr    = self.gh.create_pull_request("[AgentGroup] Collaborative improvements", body, branch)
                pr_url = pr.get("html_url", "")
                self._log(f"🚀 PR: {pr_url}")
                self.html_parts.append(_divider(f"🚀 PR opened: {pr_url}"))
            except Exception as e:
                self._log(f"⚠️ PR failed: {e}")

        return {"chat_html": self._wrap_html(), "log": self.log_lines, "pr_url": pr_url}

    def _wrap_html(self) -> str:
        body = "\n".join(self.html_parts)
        return f"<div class='ag-chat'>{body}</div>"
