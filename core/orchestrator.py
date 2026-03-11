"""AgentGroup Orchestrator – autonomous multi-agent task runner.

Inspired by:
- ZeroClaw  : tool-use loop with self-correction
- OpenClaw  : multi-agent planner → executor → reviewer pipeline
- OpenAI Agents SDK : handoffs + guardrails
- AutoGen   : two-agent and group-chat patterns

Modes:
  DISCUSS   – classic turn-based discussion + vote (original Discussion flow)
  PLAN      – Tech Lead decomposes task → agents execute sub-tasks in parallel slots
  AUTONOMOUS– agents loop with tool calls until task is DONE or max_rounds reached
"""
from __future__ import annotations
import re, time
from enum import Enum
from typing import List, Optional, Callable
from core.agent import Agent
from core.memory import SessionMemory
from core.tools import available_tools_block, extract_tool_calls, run_tool
from core.github_ops import GitHubOps
from core.telegram_bot import TelegramRelay


class OrchestratorMode(str, Enum):
    DISCUSS    = "discuss"
    PLAN       = "plan"
    AUTONOMOUS = "autonomous"


HIERARCHY_ORDER = [
    "Tech Lead / Architect",
    "Senior Software Engineer",
    "Software Engineer",
    "UI/UX Engineer",
    "Security Reviewer",
    "DevOps / Performance Engineer",
]


def _sort_agents(agents: List[Agent]) -> List[Agent]:
    def rank(a):
        try:    return HIERARCHY_ORDER.index(a.position)
        except: return 99
    return sorted(agents, key=rank)


def _extract_vote(text: str) -> str:
    if re.search(r"\bAPPROVE\b", text, re.IGNORECASE):
        return "✅ APPROVE"
    m = re.search(r"REJECT:\s*(.+)", text, re.IGNORECASE)
    if m:
        return f"❌ REJECT: {m.group(1)[:120]}"
    return "🔄 DEFER"


def _majority_approved(votes: List[str]) -> bool:
    return sum(1 for v in votes if "APPROVE" in v.upper()) > len(votes) / 2


def _divider(text: str) -> str:
    return f"<div class='ag-divider'>— {text} —</div>"


def _bubble_html(agent: Agent, text: str, reply_to=None, vote=None, is_reply=False, tool_result=None) -> str:
    from core.discussion import format_agent_message
    reply_html = f"<div class='reply-to'>↩ {reply_to}</div>" if reply_to else ""
    vote_html  = ""
    if vote:
        cls = "vote-approve" if "APPROVE" in vote.upper() else "vote-reject"
        vote_html = f"<div class='vote'><span class='{cls}'>{vote}</span></div>"
    tool_html = ""
    if tool_result:
        tool_html = f"<div class='tool-result'><b>🛠 Tool result:</b><pre>{tool_result[:600]}</pre></div>"
    catchphrase = (agent.persona.linguistics.catchphrase or "").strip()
    cp_html = f"<div class='catchphrase'>💬 {catchphrase}</div>" if catchphrase else ""
    tone      = agent.persona.linguistics.tone
    verbosity = agent.persona.linguistics.verbosity
    badges    = f"<span class='persona-badge'>{tone}</span><span class='persona-badge'>{verbosity}</span>"
    cls_msg   = "ag-msg reply" if is_reply else "ag-msg"
    return (
        f"<div class='{cls_msg}'>"
        f"  <div class='ag-avatar'>{agent.emoji}</div>"
        f"  <div class='ag-bubble'>"
        f"    <div class='sender'>{agent.name}<span class='role-tag'>{agent.position}</span>{badges}</div>"
        f"    {reply_html}{tool_html}"
        f"    <div class='body'>{text}</div>"
        f"    {cp_html}{vote_html}"
        f"  </div>"
        f"</div>"
    )


class Orchestrator:
    """
    Unified multi-agent orchestrator.

    Parameters
    ----------
    agents      : list of Agent (2–6)
    github_ops  : GitHubOps instance
    mode        : DISCUSS | PLAN | AUTONOMOUS
    memory      : optional SessionMemory (created fresh if None)
    telegram    : optional TelegramRelay
    log_callback: called with each log line
    max_rounds  : max autonomous loop iterations
    """

    def __init__(
        self,
        agents: List[Agent],
        github_ops: GitHubOps,
        mode: OrchestratorMode = OrchestratorMode.DISCUSS,
        memory: Optional[SessionMemory] = None,
        telegram: Optional[TelegramRelay] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        max_rounds: int = 4,
    ):
        self.agents     = _sort_agents(agents)
        self.gh         = github_ops
        self.mode       = mode
        self.memory     = memory or SessionMemory()
        self.tg         = telegram
        self.log        = log_callback or print
        self.max_rounds = max_rounds
        self.html_parts: list[str] = []
        self.log_lines:  list[str] = []

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _log(self, msg: str):
        self.log_lines.append(msg)
        self.log(msg)
        if self.tg:
            self.tg.send(msg)

    def _add_bubble(self, agent, text, reply_to=None, vote=None, is_reply=False, tool_result=None):
        self.html_parts.append(_bubble_html(agent, text, reply_to, vote, is_reply, tool_result))

    def _tool_loop(self, agent: Agent, initial_response: str) -> tuple[str, str | None]:
        """Process tool calls in agent response. Returns (final_text, tool_result_summary)."""
        calls = extract_tool_calls(initial_response)
        if not calls:
            return initial_response, None
        tool_results = []
        for call in calls:
            result = run_tool(call)
            tool_results.append(f"Tool `{call.get('tool')}` → {result}")
            self._log(f"🛠 {agent.name} used tool `{call.get('tool')}`")
        combined_results = "\n\n".join(tool_results)
        # Feed results back to agent
        follow_up = (
            f"Tool results:\n{combined_results}\n\n"
            "Continue your response using these results. Do not call tools again."
        )
        final = agent.say(follow_up)
        return final, combined_results

    def _fetch_files(self, file_paths: list[str]) -> dict:
        file_contents = {}
        for fp in file_paths:
            try:
                content, sha = self.gh.get_file(fp)
                file_contents[fp] = {"content": content, "sha": sha}
                self._log(f"📂 Fetched `{fp}` ({len(content)} chars)")
                self.memory.add_shared_note(f"Loaded file: {fp}")
            except Exception as e:
                self._log(f"⚠️ Could not fetch `{fp}`: {e}")
        return file_contents

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

    def _wrap_html(self) -> str:
        return f"<div class='ag-chat'>{''.join(self.html_parts)}</div>"

    # ── Public run entry point ────────────────────────────────────────────────

    def run(self, file_paths: list[str], task: str = "Review and improve.", branch_prefix: str = "agentgroup") -> dict:
        self.html_parts.append(_divider(f"🚦 Mode: {self.mode.value.upper()}"))
        file_contents = self._fetch_files(file_paths)
        if not file_contents:
            return {"chat_html": self._wrap_html(), "log": self.log_lines, "pr_url": None, "error": "No files fetched."}

        if self.mode == OrchestratorMode.DISCUSS:
            return self._run_discuss(file_contents, task, branch_prefix)
        elif self.mode == OrchestratorMode.PLAN:
            return self._run_plan(file_contents, task, branch_prefix)
        elif self.mode == OrchestratorMode.AUTONOMOUS:
            return self._run_autonomous(file_contents, task, branch_prefix)
        return {"chat_html": self._wrap_html(), "log": self.log_lines, "pr_url": None}

    # ── DISCUSS mode (original flow + tool-use + memory) ─────────────────────

    def _run_discuss(self, file_contents: dict, task: str, branch_prefix: str) -> dict:
        context_block = "\n\n".join(
            f"### {fp}\n```\n{d['content']}\n```" for fp, d in file_contents.items()
        )
        tools_block = available_tools_block()
        proposals   = []

        self.html_parts.append(_divider("🗣️ Round 1 — Proposals"))
        for agent in self.agents:
            mem_ctx = self.memory.get_agent(agent.name).render_context()
            shared  = self.memory.shared_context_block()
            prior   = "Previous agents said:\n" + "\n".join(
                f"- {p['agent'].name}: {p['text'][:250]}" for p in proposals
            ) if proposals else ""

            prompt = "\n\n".join(filter(None, [
                f"Task: {task}",
                f"Files:\n{context_block}",
                tools_block,
                shared,
                mem_ctx,
                prior,
                f"Your turn, {agent.name}.",
            ]))
            self._log(f"\n🤖 {agent.name} is thinking…")
            raw = agent.say(prompt)
            final, tool_result = self._tool_loop(agent, raw)

            # Threading detection
            reply_to_name = self._detect_reply_target(final, proposals)
            reply_to_text = None
            if reply_to_name:
                matching = [p for p in proposals if p["agent"].name.lower() == reply_to_name.lower()]
                if matching:
                    snippet = matching[-1]["text"][:100]
                    reply_to_text = f"{reply_to_name}: \"{snippet}…\""

            from core.discussion import format_agent_message
            formatted = format_agent_message(agent, final, reply_to=reply_to_name)
            self._add_bubble(agent, formatted, reply_to=reply_to_text, is_reply=bool(reply_to_text), tool_result=tool_result)
            self._log(f"{agent.persona.render_signature_prefix()} {final[:300]}")

            # Update working memory
            self.memory.get_agent(agent.name).working.append(f"Round 1: {final[:200]}")
            self.memory.add_shared_note(f"{agent.name} proposed: {final[:150]}")
            proposals.append({"agent": agent, "text": final})

        return self._voting_and_pr(proposals, file_contents, branch_prefix)

    # ── PLAN mode – Tech Lead decomposes, others execute ─────────────────────

    def _run_plan(self, file_contents: dict, task: str, branch_prefix: str) -> dict:
        tech_lead = next((a for a in self.agents if a.position == "Tech Lead / Architect"), self.agents[0])
        context_block = "\n\n".join(
            f"### {fp}\n```\n{d['content']}\n```" for fp, d in file_contents.items()
        )
        self.html_parts.append(_divider("🗺️ Planning Phase — Tech Lead decomposes task"))

        plan_prompt = (
            f"Task: {task}\n\nFiles:\n{context_block}\n\n"
            "Decompose this task into 1 sub-task per team member listed below, "
            "formatted as a JSON array:\n"
            "[{\"agent\": \"<name>\", \"subtask\": \"<description>\"}]\n\n"
            "Team: " + ", ".join(f"{a.name} ({a.position})" for a in self.agents if a is not tech_lead)
        )
        plan_raw = tech_lead.say(plan_prompt)
        self._add_bubble(tech_lead, plan_raw)
        self._log(f"📋 {tech_lead.name} decomposed task")

        # Parse sub-tasks
        sub_tasks: list[dict] = []
        m = re.search(r"\[.*?\]", plan_raw, re.DOTALL)
        if m:
            try:
                sub_tasks = __import__("json").loads(m.group(0))
            except Exception:
                pass

        if not sub_tasks:
            self._log("⚠️ Could not parse plan, falling back to DISCUSS mode")
            return self._run_discuss(file_contents, task, branch_prefix)

        self.html_parts.append(_divider("⚙️ Execution Phase — agents work on sub-tasks"))
        proposals = []
        tools_block = available_tools_block()
        for item in sub_tasks:
            name    = item.get("agent", "")
            subtask = item.get("subtask", "")
            agent   = next((a for a in self.agents if a.name == name), None)
            if not agent:
                continue
            prompt = f"Your sub-task: {subtask}\n\nFiles:\n{context_block}\n\n{tools_block}"
            self._log(f"🤖 {agent.name} executing: {subtask[:80]}")
            raw   = agent.say(prompt)
            final, tool_result = self._tool_loop(agent, raw)
            from core.discussion import format_agent_message
            formatted = format_agent_message(agent, final)
            self._add_bubble(agent, formatted, tool_result=tool_result)
            self.memory.add_shared_note(f"{agent.name} sub-task done: {subtask[:80]}")
            proposals.append({"agent": agent, "text": final})

        return self._voting_and_pr(proposals, file_contents, branch_prefix)

    # ── AUTONOMOUS mode – agents loop until DONE ─────────────────────────────

    def _run_autonomous(self, file_contents: dict, task: str, branch_prefix: str) -> dict:
        context_block = "\n\n".join(
            f"### {fp}\n```\n{d['content']}\n```" for fp, d in file_contents.items()
        )
        tools_block = available_tools_block()
        proposals   = []

        for round_num in range(1, self.max_rounds + 1):
            self.html_parts.append(_divider(f"🔁 Autonomous Round {round_num}/{self.max_rounds}"))
            done_count = 0

            for agent in self.agents:
                shared  = self.memory.shared_context_block()
                mem_ctx = self.memory.get_agent(agent.name).render_context()
                prior   = "\n".join(f"- {p['agent'].name}: {p['text'][:200]}" for p in proposals[-6:])

                prompt = "\n\n".join(filter(None, [
                    f"Task: {task}",
                    f"Files:\n{context_block}",
                    tools_block,
                    shared,
                    mem_ctx,
                    f"Recent activity:\n{prior}" if prior else "",
                    f"Round {round_num}/{self.max_rounds}. "
                    "If the task is complete, end your message with DONE. "
                    "Otherwise continue working. Your turn.",
                ]))
                self._log(f"\n🔄 Round {round_num} | {agent.name}…")
                raw   = agent.say(prompt)
                final, tool_result = self._tool_loop(agent, raw)

                from core.discussion import format_agent_message
                formatted = format_agent_message(agent, final)
                self._add_bubble(agent, formatted, tool_result=tool_result)
                self._log(f"{agent.name}: {final[:300]}")

                self.memory.get_agent(agent.name).working.append(f"R{round_num}: {final[:150]}")
                self.memory.add_shared_note(f"[R{round_num}] {agent.name}: {final[:100]}")
                proposals.append({"agent": agent, "text": final})

                if re.search(r"\bDONE\b", final, re.IGNORECASE):
                    done_count += 1

            if done_count >= len(self.agents) // 2 + 1:
                self._log("✅ Majority of agents signalled DONE")
                break

        return self._voting_and_pr(proposals, file_contents, branch_prefix)

    # ── Shared: voting + PR ───────────────────────────────────────────────────

    def _voting_and_pr(self, proposals: list, file_contents: dict, branch_prefix: str) -> dict:
        self.html_parts.append(_divider("🗳️ Voting Round"))
        approved_changes = []
        file_paths = list(file_contents.keys())

        for prop in proposals:
            proposer = prop["agent"]
            voters   = [a for a in self.agents if a is not proposer]
            if not voters:
                continue
            vote_prompt = (
                f"{proposer.name} proposed:\n{prop['text']}\n\n"
                "Vote APPROVE or REJECT: <reason>. Mention codebase cross-impact."
            )
            votes = []
            for voter in voters:
                vote_text = voter.say(vote_prompt, context=f"Proposal by {proposer.name}")
                vote_str  = _extract_vote(vote_text)
                from core.discussion import format_agent_message
                formatted = format_agent_message(voter, vote_text, reply_to=proposer.name)
                self._add_bubble(voter, formatted, reply_to=f"{proposer.name}'s proposal", vote=vote_str, is_reply=True)
                self._log(f"🗳️ {voter.name} → {vote_str}")
                self.memory.record_decision(voter.name, vote_str)
                votes.append(vote_text)

            if _majority_approved(votes):
                diff = re.search(r"```diff\n(.+?)```", prop["text"], re.DOTALL)
                if diff and file_paths:
                    approved_changes.append({"file_path": file_paths[0], "diff": diff.group(1), "proposer": proposer.name})
                self.html_parts.append(_divider(f"✅ {proposer.name}'s proposal APPROVED"))
            else:
                self.html_parts.append(_divider(f"❌ {proposer.name}'s proposal REJECTED"))

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
                    self._log(f"📝 Committed `{fp}`")
                except Exception as e:
                    self._log(f"⚠️ Commit failed for `{fp}`: {e}")

            body = (
                "## AgentGroup Auto-PR\n\n"
                f"**Mode:** {self.mode.value}\n\n"
                + "\n".join(f"- **{c['proposer']}**: `{c['file_path']}`" for c in approved_changes)
            )
            try:
                pr    = self.gh.create_pull_request("[AgentGroup] Collaborative improvements", body, branch)
                pr_url = pr.get("html_url", "")
                self._log(f"🚀 PR: {pr_url}")
                self.html_parts.append(_divider(f"🚀 PR opened: {pr_url}"))
            except Exception as e:
                self._log(f"⚠️ PR failed: {e}")

        return {"chat_html": self._wrap_html(), "log": self.log_lines, "pr_url": pr_url}

    def _detect_reply_target(self, response: str, proposals: list) -> str | None:
        m = re.search(r"responde a (\w+):", response, re.IGNORECASE)
        if m: return m.group(1)
        m2 = re.search(r"Replying to (\w+):", response)
        if m2: return m2.group(1)
        return None
