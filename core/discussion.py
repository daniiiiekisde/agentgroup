"""AgentGroup Discussion v2 – turn-based, org-sorted, threaded HTML output."""
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
    return (
        f"<div class='{cls}'>"  
        f"  <div class='ag-avatar'>{agent.emoji}</div>"
        f"  <div class='ag-bubble'>"
        f"    <div class='sender'>{agent.name}"
        f"      <span class='role-tag'>{agent.position}</span></div>"
        f"    {reply_html}"
        f"    <div class='body'>{text}</div>"
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
        self.agents   = _sort_agents(agents)  # org-chart order
        self.gh       = github_ops
        self.tg       = telegram
        self.log      = log_callback or print
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

        for i, agent in enumerate(self.agents):
            prior_summaries = ""
            if proposals:
                prior_summaries = "Previous agents said:\n" + "\n".join(
                    f"- {p['agent'].name} ({p['agent'].position}): {p['text'][:300]}"
                    for p in proposals
                )
            prompt = f"{conversation_context}\n\n{prior_summaries}\n\nYour turn, {agent.name}."
            self._log(f"\n🤖 {agent.name} ({agent.position}) is thinking…")
            response = agent.say(prompt)

            # Detect if replying to a previous agent
            reply_to_text = None
            reply_match = re.search(r"Replying to (\w+):\s*(.{0,120})", response)
            if reply_match and proposals:
                mentioned = reply_match.group(1)
                snippet   = reply_match.group(2)
                reply_to_text = f"{mentioned}: "{snippet}…""

            is_reply = reply_to_text is not None
            self._add_bubble(agent, response, reply_to=reply_to_text, is_reply=is_reply)
            self._log(f"{agent.name}: {response[:400]}")
            proposals.append({"agent": agent, "text": response})

        # 3. Voting round (each agent votes on ALL others' proposals)
        self.html_parts.append(_divider("🗳️ Round 2 — Voting"))
        approved_changes = []

        for prop in proposals:
            proposer  = prop["agent"]
            voters    = [a for a in self.agents if a is not proposer]
            if not voters:
                continue

            vote_prompt = (
                f"{proposer.name} proposed:\n{prop['text']}\n\n"
                "Vote APPROVE or REJECT: <reason>. "
                "Also mention how this change might affect the rest of the codebase."
            )
            votes = []
            for voter in voters:
                vote_text = voter.say(vote_prompt, context=f"Proposal by {proposer.name}")
                vote_str  = self._extract_vote(vote_text)
                self._add_bubble(voter, vote_text, reply_to=f"{proposer.name}'s proposal", vote=vote_str, is_reply=True)
                self._log(f"🗳️ {voter.name} → {vote_str}")
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
                pr   = self.gh.create_pull_request("[AgentGroup] Collaborative improvements", body, branch)
                pr_url = pr.get("html_url", "")
                self._log(f"🚀 PR: {pr_url}")
                self.html_parts.append(_divider(f"🚀 PR opened: {pr_url}"))
            except Exception as e:
                self._log(f"⚠️ PR failed: {e}")

        return {"chat_html": self._wrap_html(), "log": self.log_lines, "pr_url": pr_url}

    def _wrap_html(self) -> str:
        body = "\n".join(self.html_parts)
        return f"<div class='ag-chat'>{body}</div>"
