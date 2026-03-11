"""Multi-agent discussion orchestrator."""
from __future__ import annotations
from typing import List, Callable, Optional
from core.agent import Agent
from core.github_ops import GitHubOps
import re


class Discussion:
    """
    Orchestrates a round-table discussion among agents about a set of files.
    Workflow:
      1. Each agent reviews the files and proposes improvements.
      2. Every other agent votes (APPROVE / REJECT).
      3. Changes approved by majority are applied to a new branch + PR.
    """

    def __init__(
        self,
        agents: List[Agent],
        github_ops: GitHubOps,
        log_callback: Optional[Callable[[str], None]] = None,
    ):
        self.agents = agents
        self.gh = github_ops
        self.log = log_callback or print

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _majority_approved(self, votes: List[str]) -> bool:
        approvals = sum(1 for v in votes if "APPROVE" in v.upper())
        return approvals > len(votes) / 2

    def _extract_diff(self, text: str) -> Optional[str]:
        match = re.search(r"```diff\n(.+?)```", text, re.DOTALL)
        return match.group(1) if match else None

    def _apply_diff_naive(self, original: str, diff: str) -> str:
        """
        Very simple unified-diff applicator for single-file changes.
        For production, use the `patch` stdlib or `whatthepatch`.
        """
        lines = original.splitlines(keepends=True)
        result = []
        for line in diff.splitlines(keepends=True):
            if line.startswith("+") and not line.startswith("+++"):
                result.append(line[1:])
            elif line.startswith("-") and not line.startswith("---"):
                pass  # remove line
            elif not line.startswith(("@@", "---", "+++")):
                result.append(line)
        # Fallback: if result is empty, return original
        return "".join(result) if result else original

    # ------------------------------------------------------------------ #
    # Main workflow
    # ------------------------------------------------------------------ #

    def run(
        self,
        file_paths: List[str],
        task: str = "Review this code and propose improvements.",
        branch_prefix: str = "agentgroup",
    ) -> dict:
        """
        Run a full discussion cycle.
        Returns a dict with the discussion log and PR URL (if created).
        """
        log_lines = []

        def log(msg: str):
            log_lines.append(msg)
            self.log(msg)

        # 1. Fetch files
        file_contents = {}
        for fp in file_paths:
            try:
                content, sha = self.gh.get_file(fp)
                file_contents[fp] = {"content": content, "sha": sha}
                log(f"📂 Fetched `{fp}` ({len(content)} chars)")
            except Exception as e:
                log(f"⚠️  Could not fetch `{fp}`: {e}")

        if not file_contents:
            return {"log": log_lines, "pr_url": None, "error": "No files fetched."}

        # Build context block
        context = "\n\n".join(
            f"### {fp}\n```\n{d['content']}\n```" for fp, d in file_contents.items()
        )
        full_task = f"{task}\n\n{context}"

        # 2. Each agent proposes
        proposals: List[dict] = []
        for agent in self.agents:
            log(f"\n🤖 **{agent.name}** ({agent.role}) is reviewing…")
            proposal_text = agent.say(full_task)
            log(f"💬 {agent.name}: {proposal_text[:600]}…" if len(proposal_text) > 600 else f"💬 {agent.name}: {proposal_text}")
            proposals.append({"agent": agent, "text": proposal_text})

        # 3. Vote on each proposal
        approved_changes: List[dict] = []
        for prop in proposals:
            proposer = prop["agent"]
            voters = [a for a in self.agents if a is not proposer]
            if not voters:
                log(f"✅ Auto-approved (single agent): {proposer.name}")
                diff = self._extract_diff(prop["text"])
                if diff:
                    approved_changes.append({"file_path": file_paths[0], "diff": diff, "proposer": proposer.name})
                continue

            vote_prompt = (
                f"{proposer.name} proposes the following changes:\n\n{prop['text']}\n\n"
                "Vote APPROVE or REJECT: <reason>."
            )
            votes = []
            for voter in voters:
                vote = voter.say(vote_prompt)
                log(f"🗳️  {voter.name} → {vote[:200]}")
                votes.append(vote)

            if self._majority_approved(votes):
                log(f"✅ Proposal by {proposer.name} APPROVED ({sum(1 for v in votes if 'APPROVE' in v.upper())}/{len(votes)})")
                diff = self._extract_diff(prop["text"])
                if diff:
                    approved_changes.append({
                        "file_path": file_paths[0],
                        "diff": diff,
                        "proposer": proposer.name,
                    })
            else:
                log(f"❌ Proposal by {proposer.name} REJECTED")

        # 4. Apply approved changes and open PR
        pr_url = None
        if approved_changes:
            import time
            branch = f"{branch_prefix}-{int(time.time())}"
            try:
                self.gh.create_branch(branch)
                log(f"🌿 Created branch `{branch}`")
            except Exception as e:
                log(f"⚠️  Branch creation failed: {e}")
                return {"log": log_lines, "pr_url": None, "error": str(e)}

            for change in approved_changes:
                fp = change["file_path"]
                original = file_contents[fp]["content"]
                sha = file_contents[fp]["sha"]
                new_content = self._apply_diff_naive(original, change["diff"])
                commit_msg = f"[AgentGroup] {change['proposer']}: improvements to {fp}"
                try:
                    self.gh.update_file(fp, new_content, commit_msg, sha, branch=branch)
                    log(f"📝 Committed changes to `{fp}` on branch `{branch}`")
                except Exception as e:
                    log(f"⚠️  Could not commit `{fp}`: {e}")

            # Open PR
            pr_body = "## AgentGroup Auto-PR\n\n" + "\n".join(
                f"- **{c['proposer']}**: applied changes to `{c['file_path']}`" for c in approved_changes
            )
            try:
                pr = self.gh.create_pull_request(
                    title="[AgentGroup] Collaborative improvements",
                    body=pr_body,
                    head=branch,
                )
                pr_url = pr.get("html_url", "")
                log(f"🚀 PR opened: {pr_url}")
            except Exception as e:
                log(f"⚠️  PR creation failed: {e}")

        return {"log": log_lines, "pr_url": pr_url}
