# 🤖 AgentGroup v2

**Multi-AI Collaborative GitHub Editor** — turn-based, org-hierarchy aware, threaded discussion, Telegram notifications.

## Features

- 👥 **2–6 agents** with configurable org positions
- 🏛️ **Org-chart turn order**: Tech Lead → Senior Engineer → Engineers → Specialists
- 💬 **Threaded replies**: *"Replying to Alice: …"* with visible reply context
- 🔗 **Cascading awareness**: each agent sees what previous agents said before responding
- 🗳️ **Voting round**: all agents vote on each proposal; majority wins
- 📝 **Auto PR**: approved diffs committed to a new branch and a PR opened automatically
- 📱 **Telegram**: real-time forwarding of the whole discussion to a bot chat
- 🎨 **Rich dark UI**: chat bubbles, role badges, vote indicators, dividers

## Org Positions

| Position | Emoji | Focus |
|---|---|---|
| Tech Lead / Architect | 🏛️ | Architecture, final decisions |
| Senior Software Engineer | 🧠 | Implementation, patterns |
| Software Engineer | 💻 | Bug fixes, code quality |
| UI/UX Engineer | 🎨 | Frontend, accessibility |
| Security Reviewer | 🔒 | Vulnerabilities, hardening |
| DevOps / Performance Engineer | ⚙️ | CI/CD, Docker, performance |

## Quick Start

```bash
git clone https://github.com/daniiiiekisde/agentgroup
cd agentgroup
pip install -r requirements.txt
cp .env.example .env   # fill your keys
python app.py
# → http://localhost:7860
```

## Telegram Setup

1. Create a bot via [@BotFather](https://t.me/BotFather) → copy token
2. Get your Chat ID via [@userinfobot](https://t.me/userinfobot)
3. Paste both in the **Telegram Notifications** section of the UI (or in `.env`)

## Discussion Flow

```
[Repo files loaded]
       ↓
 Round 1 – Proposals (org order, each agent sees prior messages)
   🏛️ Alice (Tech Lead)  →  proposes architecture change
   🧠 Bob (Sr Engineer)  →  Replying to Alice: agrees + adds impl detail
   🎨 Clara (UI/UX)      →  Replying to Bob: flags accessibility impact
       ↓
 Round 2 – Voting (each agent votes on each other's proposal)
   Approved diffs → new branch → Pull Request
```

## Architecture

```
agentgroup/
├── app.py               # Gradio UI
├── config.py            # Env config
├── requirements.txt
├── .env.example
└── core/
    ├── agent.py         # Agent class (org-aware)
    ├── discussion.py    # Turn-based orchestrator
    ├── github_ops.py    # GitHub REST API
    ├── models.py        # Provider adapters
    └── telegram_bot.py  # Telegram relay
```
