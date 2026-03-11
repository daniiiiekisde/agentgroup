"""AgentGroup v2 – Gradio Web UI with org-chart, threaded replies, Telegram."""
from __future__ import annotations
import gradio as gr
from config import config
from core.models import build_adapter
from core.agent import Agent
from core.discussion import Discussion
from core.github_ops import GitHubOps
from core.telegram_bot import TelegramRelay


PROVIDER_MODELS = {
    "openai":    ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
    "anthropic": ["claude-opus-4-5", "claude-sonnet-4-5", "claude-3-5-haiku-20241022"],
    "gemini":    ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash"],
    "groq":      ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
    "ollama":    ["llama3.2", "llama3.1", "mistral", "codellama", "deepseek-coder", "gpt-oss:120b", "gpt-oss:20b"],
}

ROLE_HIERARCHY = [
    "Tech Lead / Architect",
    "Senior Software Engineer",
    "Software Engineer",
    "UI/UX Engineer",
    "Security Reviewer",
    "DevOps / Performance Engineer",
]

ROLE_EMOJIS = {
    "Tech Lead / Architect":           "🏛️",
    "Senior Software Engineer":        "🧠",
    "Software Engineer":               "💻",
    "UI/UX Engineer":                  "🎨",
    "Security Reviewer":               "🔒",
    "DevOps / Performance Engineer":   "⚙️",
}


def get_api_key(provider: str) -> str:
    return {
        "openai":    config.openai_api_key,
        "anthropic": config.anthropic_api_key,
        "gemini":    config.gemini_api_key,
        "groq":      config.groq_api_key,
        "ollama":    config.ollama_api_key,
    }.get(provider, "")


def build_agent_ui(name, role, provider, model, api_key_override, position):
    key = api_key_override.strip() or get_api_key(provider)
    kwargs: dict = {"model": model}
    if provider == "ollama":
        kwargs["base_url"] = config.ollama_base_url
        if key: kwargs["api_key"] = key
    elif key:
        kwargs["api_key"] = key
    adapter = build_adapter(provider, **kwargs)
    return Agent(name=name, role=role, adapter=adapter, position=position)


# ──────────────────────────────────────────────
# Session runner
# ──────────────────────────────────────────────

def run_session(
    github_token, repo_url, files_csv, task,
    tg_token, tg_chat_id,
    # agents (6 slots × 6 fields each)
    a1n, a1r, a1p, a1m, a1k, a1pos,
    a2n, a2r, a2p, a2m, a2k, a2pos,
    a3n, a3r, a3p, a3m, a3k, a3pos,
    a4n, a4r, a4p, a4m, a4k, a4pos,
    a5n, a5r, a5p, a5m, a5k, a5pos,
    a6n, a6r, a6p, a6m, a6k, a6pos,
):
    slots = [
        (a1n,a1r,a1p,a1m,a1k,a1pos),(a2n,a2r,a2p,a2m,a2k,a2pos),
        (a3n,a3r,a3p,a3m,a3k,a3pos),(a4n,a4r,a4p,a4m,a4k,a4pos),
        (a5n,a5r,a5p,a5m,a5k,a5pos),(a6n,a6r,a6p,a6m,a6k,a6pos),
    ]
    agents = []
    errors = []
    for s in slots:
        name, role, provider, model, key, pos = s
        if name and provider:
            try:
                agents.append(build_agent_ui(name, role, provider, model, key, pos))
            except Exception as e:
                errors.append(f"⚠️ Agent '{name}' skipped: {e}")

    if len(agents) < 2:
        return "❌ Minimum 2 agents required.", "", ""
    if len(agents) > 6:
        agents = agents[:6]

    try:
        parts = repo_url.rstrip("/").split("/")
        owner, repo = parts[-2], parts[-1]
    except Exception:
        return "❌ Invalid repo URL.", "", ""

    gh  = GitHubOps(token=github_token or config.github_token, owner=owner, repo=repo)
    tg  = TelegramRelay(tg_token, tg_chat_id) if (tg_token and tg_chat_id) else None

    file_paths = [f.strip() for f in files_csv.split(",") if f.strip()]
    if not file_paths:
        return "❌ Provide at least one file path.", "", ""

    disc   = Discussion(agents=agents, github_ops=gh, telegram=tg)
    result = disc.run(file_paths=file_paths, task=task)

    chat_html  = result["chat_html"]
    log_text   = "\n".join(result["log"])
    pr_link    = result.get("pr_url") or "No PR created."
    return chat_html, log_text, pr_link


# ──────────────────────────────────────────────
# CSS
# ──────────────────────────────────────────────

CSS = """
.ag-chat { background:#0f1117; border-radius:12px; padding:16px;
            max-height:600px; overflow-y:auto; font-family:'Inter',sans-serif; }
.ag-msg  { display:flex; gap:10px; margin-bottom:14px; }
.ag-msg.reply { margin-left:48px; border-left:3px solid #3d444d; padding-left:8px; }
.ag-avatar { width:36px; height:36px; border-radius:50%; display:flex;
              align-items:center; justify-content:center; font-size:18px;
              flex-shrink:0; background:#21262d; }
.ag-bubble { background:#161b22; border:1px solid #30363d; border-radius:10px;
              padding:10px 14px; max-width:680px; color:#e6edf3; }
.ag-bubble .sender { font-weight:700; font-size:.85rem; margin-bottom:4px; }
.ag-bubble .role-tag { font-size:.72rem; color:#7d8590;
                        background:#21262d; border-radius:4px;
                        padding:1px 6px; margin-left:6px; }
.ag-bubble .reply-to { font-size:.78rem; color:#7d8590; margin-bottom:6px;
                         border-left:2px solid #3d444d; padding-left:6px; }
.ag-bubble .body { font-size:.88rem; line-height:1.5; white-space:pre-wrap; }
.ag-bubble .vote { margin-top:6px; font-size:.8rem; }
.vote-approve { color:#3fb950; font-weight:700; }
.vote-reject  { color:#f85149; font-weight:700; }
.ag-divider { text-align:center; color:#484f58; font-size:.78rem;
               margin:10px 0; border-top:1px solid #21262d; padding-top:6px; }
.orgchart { background:#161b22; border-radius:10px; padding:12px;
             border:1px solid #30363d; font-size:.85rem; }
.orgchart .level { display:flex; gap:10px; justify-content:center; flex-wrap:wrap;
                    margin:6px 0; }
.org-card { background:#21262d; border:1px solid #3d444d; border-radius:8px;
             padding:6px 12px; color:#e6edf3; display:flex; align-items:center; gap:6px; }
"""


# ──────────────────────────────────────────────
# Build UI
# ──────────────────────────────────────────────

providers = list(PROVIDER_MODELS.keys())

def agent_panel(idx: int, default_name: str, default_role: str, default_pos: str, required: bool):
    label = f"Agent {idx}" + (" ✱" if required else " (optional)")
    with gr.Accordion(label, open=required):
        with gr.Row():
            name     = gr.Textbox(label="Name", value=default_name, scale=2)
            position = gr.Dropdown(label="Org Position", choices=ROLE_HIERARCHY, value=default_pos, scale=3)
        with gr.Row():
            role     = gr.Textbox(label="Custom Role Description", value=default_role, scale=3)
        with gr.Row():
            provider = gr.Dropdown(label="Provider", choices=providers, value="openai", scale=2)
            model    = gr.Dropdown(label="Model", choices=PROVIDER_MODELS["openai"],
                                    value=PROVIDER_MODELS["openai"][0], scale=3)
        api_key  = gr.Textbox(label="API Key (optional override)", type="password",
                               placeholder="Leave blank to use .env")

        def upd(p):
            ms = PROVIDER_MODELS.get(p, [])
            return gr.Dropdown(choices=ms, value=ms[0] if ms else None)
        provider.change(upd, provider, model)

    return name, role, provider, model, api_key, position


with gr.Blocks(title="AgentGroup", theme=gr.themes.Base(), css=CSS) as demo:
    gr.Markdown(
        """# 🤖 AgentGroup v2
**Multi-AI Collaborative GitHub Editor** — turn-based, org-aware, threaded discussion"""
    )

    with gr.Tabs():

        # ── TAB 1: Repo & Task ────────────────
        with gr.Tab("📁 Repo & Task"):
            with gr.Row():
                github_token = gr.Textbox(label="GitHub Token", type="password",
                                           placeholder="ghp_...", scale=2)
                repo_url     = gr.Textbox(label="Repository URL",
                                           placeholder="https://github.com/owner/repo", scale=3)
            files_csv = gr.Textbox(label="Files to review (comma-separated)",
                                    placeholder="README.md, src/main.py")
            task = gr.Textbox(
                label="Task / Goal",
                value="Review this code and propose improvements: bugs, performance, security, readability.",
                lines=3,
            )
            with gr.Accordion("🤖 Telegram Notifications", open=False):
                with gr.Row():
                    tg_token   = gr.Textbox(label="Bot Token", type="password",
                                             placeholder="123456:ABC-...", scale=2)
                    tg_chat_id = gr.Textbox(label="Chat ID", placeholder="-1001234567890", scale=2)
                gr.Markdown(
                    "Each agent message will be forwarded to your Telegram chat in real-time.  \n"
                    "Create a bot via [@BotFather](https://t.me/BotFather) and get your chat ID via [@userinfobot](https://t.me/userinfobot)."
                )

        # ── TAB 2: Agents ─────────────────────
        with gr.Tab("🧑‍💼 Agents (2–6)"):
            gr.Markdown(
                "Configure **2 to 6 agents**. Agents speak in org-chart order (Tech Lead first).  \n"
                "Each agent's message directly influences the next agent's turn."
            )
            a1 = agent_panel(1, "Alice",   "Architect & final decision maker",   "Tech Lead / Architect",         True)
            a2 = agent_panel(2, "Bob",     "Core feature implementation",         "Senior Software Engineer",      True)
            a3 = agent_panel(3, "Clara",   "UI components and accessibility",     "UI/UX Engineer",                False)
            a4 = agent_panel(4, "Diego",   "Security audits and hardening",       "Security Reviewer",             False)
            a5 = agent_panel(5, "Eva",     "CI/CD, Docker, performance",          "DevOps / Performance Engineer", False)
            a6 = agent_panel(6, "Frank",   "Bug fixing and code quality",         "Software Engineer",             False)

        # ── TAB 3: Run ────────────────────────
        with gr.Tab("🚀 Run"):
            run_btn = gr.Button("▶  Start AgentGroup Session", variant="primary", size="lg")

            gr.Markdown("### 💬 Discussion Thread")
            chat_out = gr.HTML(value="<div class='ag-chat'><p style='color:#484f58'>Discussion will appear here…</p></div>")

            with gr.Accordion("📜 Raw Log", open=False):
                log_out = gr.Textbox(label="", lines=20, interactive=False)

            pr_out = gr.Textbox(label="🔗 Pull Request URL", interactive=False)

            run_btn.click(
                run_session,
                inputs=[
                    github_token, repo_url, files_csv, task, tg_token, tg_chat_id,
                    *a1, *a2, *a3, *a4, *a5, *a6,
                ],
                outputs=[chat_out, log_out, pr_out],
            )

if __name__ == "__main__":
    demo.launch(share=False)
