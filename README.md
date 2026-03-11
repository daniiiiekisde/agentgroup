# 🤖 AgentGroup

A multi-AI collaborative framework where multiple AI agents can **edit a shared GitHub repository** and **discuss optimizations and improvements** amongst themselves.

## Features

- 🧠 **Multi-model support**: OpenAI, Anthropic, Gemini, Groq, Ollama (local & cloud)
- 🐙 **GitHub integration**: Agents can read, create, edit, and commit files via GitHub API
- 💬 **Agent discussion**: Agents debate proposed changes before committing
- 🔑 **Flexible auth**: GitHub token + any model API key or Ollama cloud key
- 🌐 **Web UI**: Simple Gradio interface to configure and launch agent sessions

## Quick Start

```bash
pip install -r requirements.txt
python app.py
```

Then open `http://localhost:7860` in your browser.

## Configuration

Copy `.env.example` to `.env` and fill in your keys:

```bash
cp .env.example .env
```

| Variable | Description |
|---|---|
| `GITHUB_TOKEN` | Personal Access Token with `repo` scope |
| `OPENAI_API_KEY` | OpenAI API key (optional) |
| `ANTHROPIC_API_KEY` | Anthropic Claude API key (optional) |
| `GEMINI_API_KEY` | Google Gemini API key (optional) |
| `GROQ_API_KEY` | Groq API key (optional) |
| `OLLAMA_API_KEY` | Ollama cloud API key (optional) |
| `OLLAMA_BASE_URL` | Ollama base URL (default: `https://ollama.com/api` for cloud, `http://localhost:11434` for local) |

At least one model key is required. `GITHUB_TOKEN` is always required.

## How It Works

1. You provide a GitHub repo URL and your token.
2. You configure 2+ AI agents, each with a role (e.g., "Senior Python Dev", "Security Reviewer").
3. AgentGroup fetches the repo structure and selected files.
4. Agents take turns proposing improvements, discussing them, and voting.
5. Approved changes are committed to the repo automatically.

## Architecture

```
agentgroup/
├── app.py              # Gradio web UI entry point
├── core/
│   ├── agent.py        # Agent class (model-agnostic)
│   ├── discussion.py   # Multi-agent discussion orchestrator
│   ├── github_ops.py   # GitHub API operations
│   └── models.py       # Model provider adapters
├── config.py           # Config & env loading
├── requirements.txt
└── .env.example
```
