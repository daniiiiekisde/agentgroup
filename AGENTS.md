# AGENTS.md

## Project overview

AgentGroup is a multi-agent app where 2 to 6 AI agents collaborate on a GitHub repository, discuss proposed changes in turn, vote on them, and optionally open a pull request.

## Core rules

- Preserve the turn-based organizational hierarchy.
- Never let two agents speak at the same time.
- Every message should be aware of previous messages in the thread.
- Agent replies should support explicit threading, for example: "Gemini responde a Claude: ...".
- Prioritize UI quality and usability in the app itself.
- Keep Telegram formatting readable and concise.
- Do not leak tokens, secrets, or API keys in logs, chat bubbles, Telegram messages, or pull requests.

## Agent behavior

- Each agent has a persona profile loaded from `agents/*.json`.
- The persona profile affects tone, signature, conflict style, verbosity, priorities, and reply style.
- Agents must mention cross-impact when proposing changes, for example how a UI change affects backend validation.
- Agents should stay inside their specialty unless explicitly asked to broaden scope.
- Tech Lead / Architect has the highest decision weight.
- Security Reviewer can block unsafe changes.
- UI/UX Engineer must review accessibility and UX impact.

## Build and run

- Install dependencies with `pip install -r requirements.txt`
- Start the app with `python app.py`

## Code style

- Keep Python modules small and focused.
- Prefer explicit dataclasses and typed helpers.
- Avoid giant prompts hardcoded inline when they can be assembled from persona data.
- Keep persona presets portable and human-editable.

## Testing checklist

- App starts without syntax errors.
- Persona profiles load correctly.
- Agents can render signatures like "Claude dice:".
- Agents can render threaded replies like "Gemini responde a Claude:".
- Telegram relay still works.
- Minimum 2 agents, maximum 6 agents.

## PR guidance

- Title format: `[AgentGroup] <short description>`
- Mention whether a change affects UI, orchestration, personas, or provider adapters.
