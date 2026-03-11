"""AgentGroup v3 – Gradio UI with persona presets, live preview, org-chart."""
from __future__ import annotations
import json
from pathlib import Path
import gradio as gr
from config import config
from core.models import build_adapter
from core.agent import Agent
from core.persona import PersonaProfile
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

PRESET_DIR = Path("agents")


def list_presets() -> list[str]:
    if not PRESET_DIR.exists():
        return ["(none)"]
    files = sorted(PRESET_DIR.glob("*.json"))
    return ["(none)"] + [f.stem for f in files]


def load_preset_fields(preset_name: str):
    """Return (tone, verbosity, sig_prefix, reply_prefix, catchphrase, priorities, blocked, creativity, criticality, backstory, preview_html)"""
    empty = ("", "", "{name} dice:", "{name} responde a {agent}:", "", "", "", 5, 5, "", "")
    if not preset_name or preset_name == "(none)":
        return empty
    path = PRESET_DIR / f"{preset_name}.json"
    if not path.exists():
        return empty
    try:
        p = PersonaProfile.from_json_file(path)
        preview = (
            f"<div class='persona-preview'>"
            f"<b>{p.identity.name}</b> — {p.identity.job_title}<br>"
            f"<i>{p.identity.backstory}</i><br><br>"
            f"<b>Signature:</b> {p.render_signature_prefix()}<br>"
            f"<b>Reply:</b> {p.render_reply_prefix('Gemini')}<br>"
            f"<b>Catchphrase:</b> {p.linguistics.catchphrase or '—'}<br>"
            f"<b>Tone:</b> {p.linguistics.tone} | <b>Verbosity:</b> {p.linguistics.verbosity}<br>"
            f"<b>Priorities:</b> {', '.join(p.work_rules.priorities)}<br>"
            f"<b>Blocked areas:</b> {', '.join(p.work_rules.blocked_areas) or 'none'}"
            f"</div>"
        )
        return (
            p.linguistics.tone,
            p.linguistics.verbosity,
            p.linguistics.signature_prefix,
            p.linguistics.reply_prefix,
            p.linguistics.catchphrase,
            ", ".join(p.work_rules.priorities),
            ", ".join(p.work_rules.blocked_areas),
            p.psychology.creativity,
            p.psychology.criticality,
            p.identity.backstory,
            preview,
        )
    except Exception as e:
        return (*empty[:-1], f"<span style='color:red'>Error loading preset: {e}</span>")


def get_api_key(provider: str) -> str:
    return {
        "openai":    config.openai_api_key,
        "anthropic": config.anthropic_api_key,
        "gemini":    config.gemini_api_key,
        "groq":      config.groq_api_key,
        "ollama":    config.ollama_api_key,
    }.get(provider, "")


def build_agent_from_ui(
    name, role, provider, model, api_key_override, position,
    tone, verbosity, sig_prefix, reply_prefix, catchphrase,
    priorities_str, blocked_str, creativity, criticality, backstory,
) -> Agent:
    key = api_key_override.strip() or get_api_key(provider)
    kwargs: dict = {"model": model}
    if provider == "ollama":
        kwargs["base_url"] = config.ollama_base_url
        if key: kwargs["api_key"] = key
    elif key:
        kwargs["api_key"] = key
    adapter = build_adapter(provider, **kwargs)

    persona = PersonaProfile()
    persona.identity.name       = name
    persona.identity.job_title  = position
    persona.identity.backstory  = backstory or ""
    persona.linguistics.tone              = tone or "professional"
    persona.linguistics.verbosity         = verbosity or "medium"
    persona.linguistics.signature_prefix  = sig_prefix or "{name} dice:"
    persona.linguistics.reply_prefix      = reply_prefix or "{name} responde a {agent}:"
    persona.linguistics.catchphrase       = catchphrase or ""
    persona.work_rules.priorities         = [p.strip() for p in priorities_str.split(",") if p.strip()]
    persona.work_rules.blocked_areas      = [b.strip() for b in blocked_str.split(",") if b.strip()]
    try:
        persona.psychology.creativity  = int(creativity)
        persona.psychology.criticality = int(criticality)
    except (TypeError, ValueError):
        pass

    return Agent(name=name, role=role, adapter=adapter, position=position, persona=persona)


# ──────────────────────────────────────────────
# Session runner
# ──────────────────────────────────────────────

def run_session(
    github_token, repo_url, files_csv, task,
    tg_token, tg_chat_id,
    # agents: 6 slots × 16 fields each
    a1n,a1r,a1p,a1m,a1k,a1pos,a1tone,a1verb,a1sig,a1rep,a1cp,a1pri,a1blk,a1cre,a1cri,a1back,
    a2n,a2r,a2p,a2m,a2k,a2pos,a2tone,a2verb,a2sig,a2rep,a2cp,a2pri,a2blk,a2cre,a2cri,a2back,
    a3n,a3r,a3p,a3m,a3k,a3pos,a3tone,a3verb,a3sig,a3rep,a3cp,a3pri,a3blk,a3cre,a3cri,a3back,
    a4n,a4r,a4p,a4m,a4k,a4pos,a4tone,a4verb,a4sig,a4rep,a4cp,a4pri,a4blk,a4cre,a4cri,a4back,
    a5n,a5r,a5p,a5m,a5k,a5pos,a5tone,a5verb,a5sig,a5rep,a5cp,a5pri,a5blk,a5cre,a5cri,a5back,
    a6n,a6r,a6p,a6m,a6k,a6pos,a6tone,a6verb,a6sig,a6rep,a6cp,a6pri,a6blk,a6cre,a6cri,a6back,
):
    slots = [
        (a1n,a1r,a1p,a1m,a1k,a1pos,a1tone,a1verb,a1sig,a1rep,a1cp,a1pri,a1blk,a1cre,a1cri,a1back),
        (a2n,a2r,a2p,a2m,a2k,a2pos,a2tone,a2verb,a2sig,a2rep,a2cp,a2pri,a2blk,a2cre,a2cri,a2back),
        (a3n,a3r,a3p,a3m,a3k,a3pos,a3tone,a3verb,a3sig,a3rep,a3cp,a3pri,a3blk,a3cre,a3cri,a3back),
        (a4n,a4r,a4p,a4m,a4k,a4pos,a4tone,a4verb,a4sig,a4rep,a4cp,a4pri,a4blk,a4cre,a4cri,a4back),
        (a5n,a5r,a5p,a5m,a5k,a5pos,a5tone,a5verb,a5sig,a5rep,a5cp,a5pri,a5blk,a5cre,a5cri,a5back),
        (a6n,a6r,a6p,a6m,a6k,a6pos,a6tone,a6verb,a6sig,a6rep,a6cp,a6pri,a6blk,a6cre,a6cri,a6back),
    ]
    agents, errors = [], []
    for s in slots:
        name = s[0]
        provider = s[2]
        if name and provider:
            try:
                agents.append(build_agent_from_ui(*s))
            except Exception as e:
                errors.append(f"⚠️ Agent '{name}' skipped: {e}")

    if len(agents) < 2:
        return "❌ Minimum 2 agents required.", "\n".join(errors), ""
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

    chat_html = result["chat_html"]
    log_text  = "\n".join(result["log"])
    pr_link   = result.get("pr_url") or "No PR created."
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
.catchphrase { font-size:.75rem; color:#8b949e; font-style:italic; margin-top:6px; }
.persona-badge { font-size:.68rem; background:#21262d; color:#7d8590;
                  border-radius:3px; padding:1px 5px; margin-left:4px; }
.persona-preview { background:#161b22; border:1px solid #30363d; border-radius:8px;
                    padding:12px; color:#e6edf3; font-size:.85rem; line-height:1.7; }
.orgchart { background:#161b22; border-radius:10px; padding:12px;
             border:1px solid #30363d; font-size:.85rem; }
.orgchart .level { display:flex; gap:10px; justify-content:center; flex-wrap:wrap; margin:6px 0; }
.org-card { background:#21262d; border:1px solid #3d444d; border-radius:8px;
             padding:6px 12px; color:#e6edf3; display:flex; align-items:center; gap:6px; }
"""


# ──────────────────────────────────────────────
# Agent panel builder
# ──────────────────────────────────────────────

presets = list_presets()
providers = list(PROVIDER_MODELS.keys())


def agent_panel(
    idx: int,
    default_name: str,
    default_role: str,
    default_pos: str,
    required: bool,
    default_preset: str = "(none)",
):
    label = f"Agent {idx}" + (" ✱" if required else " (optional)")
    with gr.Accordion(label, open=required):
        # ── Identity row
        with gr.Row():
            name     = gr.Textbox(label="Name", value=default_name, scale=2)
            position = gr.Dropdown(label="Org Position", choices=ROLE_HIERARCHY, value=default_pos, scale=3)
        with gr.Row():
            role = gr.Textbox(label="Custom Role Description", value=default_role, scale=5)

        # ── Provider row
        with gr.Row():
            provider = gr.Dropdown(label="Provider", choices=providers, value="openai", scale=2)
            model    = gr.Dropdown(label="Model", choices=PROVIDER_MODELS["openai"],
                                    value=PROVIDER_MODELS["openai"][0], scale=3)
        api_key = gr.Textbox(label="API Key (optional override)", type="password",
                              placeholder="Leave blank to use .env")

        def upd_models(p):
            ms = PROVIDER_MODELS.get(p, [])
            return gr.Dropdown(choices=ms, value=ms[0] if ms else None)
        provider.change(upd_models, provider, model)

        # ── Persona preset
        with gr.Accordion("🎭 Persona", open=(idx <= 2)):
            with gr.Row():
                preset_dd = gr.Dropdown(label="Load preset", choices=presets,
                                         value=default_preset, scale=3)
                load_btn  = gr.Button("⬇ Load", scale=1, size="sm")

            preview_html = gr.HTML(value="<div class='persona-preview' style='color:#484f58'>Select a preset and click Load.</div>")

            with gr.Row():
                tone      = gr.Textbox(label="Tone", value="professional", scale=2)
                verbosity = gr.Textbox(label="Verbosity", value="medium", scale=2)
            with gr.Row():
                sig_prefix   = gr.Textbox(label="Signature prefix", value="{name} dice:", scale=3)
                reply_prefix = gr.Textbox(label="Reply prefix", value="{name} responde a {agent}:", scale=3)
            catchphrase  = gr.Textbox(label="Catchphrase", value="", scale=5)
            with gr.Row():
                priorities_txt = gr.Textbox(label="Priorities (comma-separated)", value="", scale=3)
                blocked_txt    = gr.Textbox(label="Blocked areas (comma-separated)", value="", scale=3)
            with gr.Row():
                creativity  = gr.Slider(label="Creativity",  minimum=1, maximum=10, step=1, value=5, scale=2)
                criticality = gr.Slider(label="Criticality", minimum=1, maximum=10, step=1, value=5, scale=2)
            backstory = gr.Textbox(label="Backstory", value="", lines=2, scale=5)

            persona_outputs = [tone, verbosity, sig_prefix, reply_prefix, catchphrase,
                                priorities_txt, blocked_txt, creativity, criticality, backstory, preview_html]

            load_btn.click(load_preset_fields, inputs=[preset_dd], outputs=persona_outputs)

    return (name, role, provider, model, api_key, position,
            tone, verbosity, sig_prefix, reply_prefix, catchphrase,
            priorities_txt, blocked_txt, creativity, criticality, backstory)


# ──────────────────────────────────────────────
# Gradio layout
# ──────────────────────────────────────────────

with gr.Blocks(title="AgentGroup", theme=gr.themes.Base(), css=CSS) as demo:
    gr.Markdown(
        "# 🤖 AgentGroup v3\n"
        "**Multi-AI Collaborative GitHub Editor** — persona-aware, turn-based, threaded discussion"
    )

    with gr.Tabs():

        with gr.Tab("📁 Repo & Task"):
            with gr.Row():
                github_token = gr.Textbox(label="GitHub Token", type="password",
                                           placeholder="ghp_...", scale=2)
                repo_url = gr.Textbox(label="Repository URL",
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

        with gr.Tab("🧑‍💼 Agents (2–6)"):
            gr.Markdown(
                "Configure **2 to 6 agents**. Agents speak in org-chart order.  \n"
                "Use **Load preset** to fill persona fields from `agents/*.json`, or edit them manually."
            )
            a1 = agent_panel(1, "Claude",  "Architect & final decision maker",  "Tech Lead / Architect",         True,  "architect")
            a2 = agent_panel(2, "Gemini",  "UI components and accessibility",   "UI/UX Engineer",                True,  "ui_designer")
            a3 = agent_panel(3, "OpenAI",  "Security audits and hardening",     "Security Reviewer",             False, "security_hawk")
            a4 = agent_panel(4, "Diego",   "Core feature implementation",       "Senior Software Engineer",      False, "(none)")
            a5 = agent_panel(5, "Eva",     "CI/CD, Docker, performance",        "DevOps / Performance Engineer", False, "(none)")
            a6 = agent_panel(6, "Frank",   "Bug fixing and code quality",       "Software Engineer",             False, "(none)")

        with gr.Tab("🚀 Run"):
            run_btn  = gr.Button("▶  Start AgentGroup Session", variant="primary", size="lg")
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
