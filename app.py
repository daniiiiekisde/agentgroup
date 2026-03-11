"""AgentGroup v4 – Orchestrator-connected Gradio UI.

New in v4:
- Mode selector: DISCUSS / PLAN / AUTONOMOUS
- Session memory: persistent across tabs, saveable to JSON
- New providers in UI: DeepSeek, Mistral, xAI, Cohere
- Agent presets auto-wired to new agents (DeepSeek, Mistral)
- Tools panel: shows available tools + toggle
- Session export: download chat HTML + log
- Org-chart live preview
- Stop button (graceful via gr.State flag)
"""
from __future__ import annotations
import json, time
from pathlib import Path
import gradio as gr
from config import config
from core.models import build_adapter
from core.agent import Agent
from core.persona import PersonaProfile
from core.orchestrator import Orchestrator, OrchestratorMode
from core.memory import SessionMemory
from core.tools import available_tools_block
from core.github_ops import GitHubOps
from core.telegram_bot import TelegramRelay


# ──────────────────────────────────────────────
PROVIDER_MODELS = {
    "openai":    ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
    "anthropic": ["claude-opus-4-5", "claude-sonnet-4-5", "claude-3-5-haiku-20241022"],
    "gemini":    ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite"],
    "groq":      ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768", "gemma2-9b-it"],
    "deepseek":  ["deepseek-coder", "deepseek-chat", "deepseek-reasoner"],
    "mistral":   ["mistral-large-latest", "mistral-small-latest", "codestral-latest", "open-mistral-nemo"],
    "xai":       ["grok-3-mini", "grok-3", "grok-2"],
    "cohere":    ["command-r-plus", "command-r", "command-a-03-2025"],
    "ollama":    ["llama3.2", "llama3.1", "mistral", "codellama", "deepseek-coder", "qwen2.5-coder", "phi4"],
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
MEMORY_DIR = Path(".memory")
MEMORY_DIR.mkdir(exist_ok=True)

# ── Helpers ──────────────────────────────────────────────

def list_presets() -> list[str]:
    if not PRESET_DIR.exists():
        return ["(none)"]
    return ["(none)"] + [f.stem for f in sorted(PRESET_DIR.glob("*.json"))]


def list_saved_sessions() -> list[str]:
    return ["(new session)"] + [f.stem for f in sorted(MEMORY_DIR.glob("*.json"))]


def load_preset_fields(preset_name: str):
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
            f"✏️ <b>Signature:</b> <code>{p.render_signature_prefix()}</code><br>"
            f"🔁 <b>Reply pattern:</b> <code>{p.render_reply_prefix('OtherAgent')}</code><br>"
            f"💬 <b>Catchphrase:</b> {p.linguistics.catchphrase or '—'}<br>"
            f"🎨 <b>Tone:</b> {p.linguistics.tone} &nbsp;|― "
            f"📝 <b>Verbosity:</b> {p.linguistics.verbosity}<br>"
            f"⚡ <b>Creativity:</b> {p.psychology.creativity}/10 &nbsp;|― "
            f"🔍 <b>Criticality:</b> {p.psychology.criticality}/10<br>"
            f"🎯 <b>Priorities:</b> {', '.join(p.work_rules.priorities) or '—'}<br>"
            f"⛔ <b>Blocked areas:</b> {', '.join(p.work_rules.blocked_areas) or 'none'}"
            f"</div>"
        )
        return (
            p.linguistics.tone, p.linguistics.verbosity,
            p.linguistics.signature_prefix, p.linguistics.reply_prefix,
            p.linguistics.catchphrase,
            ", ".join(p.work_rules.priorities),
            ", ".join(p.work_rules.blocked_areas),
            p.psychology.creativity, p.psychology.criticality,
            p.identity.backstory, preview,
        )
    except Exception as e:
        return (*empty[:-1], f"<span style='color:red'>Error: {e}</span>")


def get_api_key(provider: str) -> str:
    return {
        "openai":    config.openai_api_key,
        "anthropic": config.anthropic_api_key,
        "gemini":    config.gemini_api_key,
        "groq":      config.groq_api_key,
        "ollama":    config.ollama_api_key,
        "deepseek":  config.deepseek_api_key,
        "mistral":   config.mistral_api_key,
        "xai":       config.xai_api_key,
        "cohere":    config.cohere_api_key,
    }.get(provider, "")


def build_agent_from_ui(
    name, role, provider, model, api_key_override, position,
    tone, verbosity, sig_prefix, reply_prefix, catchphrase,
    priorities_str, blocked_str, creativity, criticality, backstory,
) -> Agent:
    key = (api_key_override or "").strip() or get_api_key(provider)
    kwargs: dict = {"model": model}
    if provider == "ollama":
        kwargs["base_url"] = config.ollama_base_url
        if key: kwargs["api_key"] = key
    elif key:
        kwargs["api_key"] = key
    adapter = build_adapter(provider, **kwargs)

    persona = PersonaProfile()
    persona.identity.name               = name
    persona.identity.job_title          = position
    persona.identity.backstory          = backstory or ""
    persona.linguistics.tone            = tone or "professional"
    persona.linguistics.verbosity       = verbosity or "medium"
    persona.linguistics.signature_prefix = sig_prefix or "{name} dice:"
    persona.linguistics.reply_prefix    = reply_prefix or "{name} responde a {agent}:"
    persona.linguistics.catchphrase     = catchphrase or ""
    persona.work_rules.priorities       = [p.strip() for p in (priorities_str or "").split(",") if p.strip()]
    persona.work_rules.blocked_areas    = [b.strip() for b in (blocked_str or "").split(",") if b.strip()]
    try:
        persona.psychology.creativity   = int(creativity)
        persona.psychology.criticality  = int(criticality)
    except (TypeError, ValueError):
        pass
    return Agent(name=name, role=role, adapter=adapter, position=position, persona=persona)


# ── Session runner ────────────────────────────────────────────

def run_session(
    github_token, repo_url, files_csv, task,
    mode_str, max_rounds_val,
    tg_token, tg_chat_id,
    session_name, load_memory_toggle,
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
        if s[0] and s[2]:  # name + provider
            try:
                agents.append(build_agent_from_ui(*s))
            except Exception as e:
                errors.append(f"⚠️ Agent '{s[0]}' skipped: {e}")

    if len(agents) < 2:
        return "❌ Minimum 2 agents required.", "\n".join(errors), "", "", ""
    agents = agents[:6]

    try:
        parts = repo_url.rstrip("/").split("/")
        owner, repo = parts[-2], parts[-1]
    except Exception:
        return "❌ Invalid repo URL.", "", "", "", ""

    file_paths = [f.strip() for f in files_csv.split(",") if f.strip()]
    if not file_paths:
        return "❌ Provide at least one file path.", "", "", "", ""

    gh = GitHubOps(token=github_token or config.github_token, owner=owner, repo=repo)
    tg = TelegramRelay(tg_token, tg_chat_id) if (tg_token and tg_chat_id) else None

    # Memory
    mem_path = MEMORY_DIR / f"{session_name or 'default'}.json"
    if load_memory_toggle and mem_path.exists():
        try:
            memory = SessionMemory.load(mem_path)
        except Exception:
            memory = SessionMemory()
    else:
        memory = SessionMemory()

    mode = OrchestratorMode(mode_str.lower())
    try:
        max_rounds = int(max_rounds_val)
    except (TypeError, ValueError):
        max_rounds = 4

    orch   = Orchestrator(agents=agents, github_ops=gh, mode=mode,
                          memory=memory, telegram=tg, max_rounds=max_rounds)
    result = orch.run(file_paths=file_paths, task=task)

    # Save memory
    try:
        memory.save(mem_path)
        mem_status = f"✅ Memory saved to {mem_path}"
    except Exception as e:
        mem_status = f"⚠️ Memory save failed: {e}"

    chat_html  = result["chat_html"]
    log_text   = "\n".join(result["log"])
    pr_link    = result.get("pr_url") or "No PR created."

    # Export files
    export_html_path = f"/tmp/agentgroup_chat_{int(time.time())}.html"
    export_log_path  = f"/tmp/agentgroup_log_{int(time.time())}.txt"
    try:
        Path(export_html_path).write_text(
            f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>AgentGroup Session</title>"
            f"<style>body{{background:#0f1117;color:#e6edf3;font-family:Inter,sans-serif;padding:24px}}</style></head>"
            f"<body>{chat_html}</body></html>"
        )
        Path(export_log_path).write_text(log_text)
    except Exception:
        export_html_path = None
        export_log_path  = None

    return chat_html, log_text + "\n" + mem_status, pr_link, export_html_path, export_log_path


# ── CSS ──────────────────────────────────────────────

CSS = """
/* ── Chat area ───────────────────────────────── */
.ag-chat {
  background:#0f1117; border-radius:12px; padding:16px;
  max-height:620px; overflow-y:auto; font-family:'Inter',sans-serif;
  scrollbar-width:thin; scrollbar-color:#3d444d #0f1117;
}
.ag-msg  { display:flex; gap:10px; margin-bottom:16px; }
.ag-msg.reply { margin-left:52px; border-left:3px solid #3d444d; padding-left:10px; }
.ag-avatar {
  width:38px; height:38px; border-radius:50%;
  display:flex; align-items:center; justify-content:center;
  font-size:20px; flex-shrink:0;
  background:linear-gradient(135deg,#21262d,#30363d);
  box-shadow:0 0 0 2px #3d444d;
}
.ag-bubble {
  background:#161b22; border:1px solid #30363d;
  border-radius:12px; padding:12px 16px;
  max-width:700px; color:#e6edf3;
  box-shadow:0 2px 8px rgba(0,0,0,.3);
  transition:border-color .2s;
}
.ag-bubble:hover { border-color:#58a6ff44; }
.ag-bubble .sender { font-weight:700; font-size:.86rem; margin-bottom:5px; color:#58a6ff; }
.ag-bubble .role-tag {
  font-size:.70rem; color:#7d8590;
  background:#21262d; border-radius:4px;
  padding:2px 7px; margin-left:7px;
}
.ag-bubble .reply-to {
  font-size:.77rem; color:#7d8590; margin-bottom:7px;
  border-left:3px solid #3d444d; padding-left:8px;
  background:#0f1117; border-radius:0 4px 4px 0; padding:4px 8px;
}
.ag-bubble .body { font-size:.87rem; line-height:1.6; white-space:pre-wrap; }
.ag-bubble .vote { margin-top:8px; font-size:.82rem; }
.vote-approve { color:#3fb950; font-weight:700; }
.vote-reject  { color:#f85149; font-weight:700; }
.ag-divider {
  text-align:center; color:#484f58; font-size:.76rem;
  margin:12px 0; padding:4px 0;
  border-top:1px solid #21262d;
  letter-spacing:.05em; text-transform:uppercase;
}
.catchphrase {
  font-size:.74rem; color:#8b949e;
  font-style:italic; margin-top:7px;
  padding-top:5px; border-top:1px dashed #30363d;
}
.persona-badge {
  font-size:.66rem; background:#21262d; color:#7d8590;
  border:1px solid #3d444d; border-radius:3px;
  padding:1px 6px; margin-left:4px; vertical-align:middle;
}
.tool-result {
  margin-top:8px; background:#0d1117; border:1px solid #3d444d;
  border-radius:6px; padding:8px 12px; font-size:.78rem; color:#8b949e;
}
.tool-result pre { margin:4px 0; white-space:pre-wrap; color:#79c0ff; }

/* ── Persona preview ───────────────────────────────── */
.persona-preview {
  background:#161b22; border:1px solid #30363d;
  border-radius:8px; padding:14px; color:#e6edf3;
  font-size:.84rem; line-height:1.8;
}

/* ── Mode badge ─────────────────────────────────── */
.mode-discuss    { color:#3fb950; font-weight:700; }
.mode-plan       { color:#d29922; font-weight:700; }
.mode-autonomous { color:#f85149; font-weight:700; }

/* ── Org chart ──────────────────────────────────── */
.orgchart {
  background:#161b22; border-radius:10px; padding:14px;
  border:1px solid #30363d; font-size:.84rem;
}
.orgchart .level {
  display:flex; gap:10px; justify-content:center;
  flex-wrap:wrap; margin:6px 0;
}
.org-card {
  background:#21262d; border:1px solid #3d444d;
  border-radius:8px; padding:6px 14px; color:#e6edf3;
  display:flex; align-items:center; gap:6px;
}
"""


# ── Agent panel builder ────────────────────────────────────────────

presets   = list_presets()
providers = list(PROVIDER_MODELS.keys())


def agent_panel(idx, default_name, default_role, default_pos, required, default_preset="(none)"):
    label = f"Agent {idx}" + (" ✱" if required else " (optional)")
    with gr.Accordion(label, open=required):
        with gr.Row():
            name     = gr.Textbox(label="Name", value=default_name, scale=2)
            position = gr.Dropdown(label="Org Position", choices=ROLE_HIERARCHY, value=default_pos, scale=3)
        with gr.Row():
            role = gr.Textbox(label="Custom Role Description", value=default_role, scale=5)
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

        with gr.Accordion("🎭 Persona", open=(idx <= 2)):
            with gr.Row():
                preset_dd = gr.Dropdown(label="Load preset", choices=presets,
                                         value=default_preset, scale=3)
                load_btn  = gr.Button("⬇ Load", scale=1, size="sm")
            preview_html = gr.HTML(
                value="<div class='persona-preview' style='color:#484f58'>Select a preset and click Load.</div>"
            )
            with gr.Row():
                tone      = gr.Textbox(label="Tone",      value="professional", scale=2)
                verbosity = gr.Textbox(label="Verbosity", value="medium",       scale=2)
            with gr.Row():
                sig_prefix   = gr.Textbox(label="Signature prefix",  value="{name} dice:",                 scale=3)
                reply_prefix = gr.Textbox(label="Reply prefix",       value="{name} responde a {agent}:",   scale=3)
            catchphrase = gr.Textbox(label="Catchphrase", value="", scale=5)
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


# ── Gradio layout ────────────────────────────────────────────

with gr.Blocks(title="AgentGroup v4", theme=gr.themes.Base(), css=CSS) as demo:
    gr.Markdown(
        "# 🤖 AgentGroup v4\n"
        "**Multi-AI Collaborative GitHub Editor** — "
        "<span class='mode-discuss'>DISCUSS</span> / "
        "<span class='mode-plan'>PLAN</span> / "
        "<span class='mode-autonomous'>AUTONOMOUS</span> — "
        "persona-aware · tool-use · session memory"
    )

    with gr.Tabs():

        # ── TAB 1: Repo & Task ──────────────────────────────
        with gr.Tab("📁 Repo & Task"):
            with gr.Row():
                github_token = gr.Textbox(label="GitHub Token", type="password",
                                           placeholder="ghp_...", scale=2)
                repo_url     = gr.Textbox(label="Repository URL",
                                           placeholder="https://github.com/owner/repo", scale=3)
            files_csv = gr.Textbox(
                label="Files to review (comma-separated)",
                placeholder="README.md, src/main.py, core/agent.py"
            )
            task = gr.Textbox(
                label="Task / Goal",
                value="Review this code and propose improvements: bugs, performance, security, readability.",
                lines=3,
            )

            gr.Markdown("### ⚙️ Orchestration")
            with gr.Row():
                mode_radio = gr.Radio(
                    label="Mode",
                    choices=["discuss", "plan", "autonomous"],
                    value="discuss",
                    scale=3,
                    info=(
                        "🗣 discuss = turn-based proposals + vote  ·  "
                        "🗺 plan = Tech Lead decomposes → agents execute  ·  "
                        "🔄 autonomous = agents loop until DONE"
                    )
                )
                max_rounds = gr.Slider(
                    label="Max rounds (autonomous mode)",
                    minimum=1, maximum=10, step=1, value=4, scale=2
                )

            gr.Markdown("### 🧠 Session Memory")
            with gr.Row():
                session_name   = gr.Textbox(label="Session name", value="default",
                                             placeholder="my-session", scale=2)
                load_mem_toggle = gr.Checkbox(label="Load previous memory", value=False, scale=1)

            with gr.Accordion("🤖 Telegram Notifications", open=False):
                with gr.Row():
                    tg_token   = gr.Textbox(label="Bot Token", type="password",
                                             placeholder="123456:ABC-...", scale=2)
                    tg_chat_id = gr.Textbox(label="Chat ID", placeholder="-1001234567890", scale=2)

        # ── TAB 2: Agents ─────────────────────────────────
        with gr.Tab("🧑‍💼 Agents (2–6)"):
            gr.Markdown(
                "Configure **2 to 6 agents**. They speak in org-chart order.\n\n"
                "Use **Load preset** to fill persona fields from `agents/*.json`, or edit manually.  "
                "New providers available: **DeepSeek**, **Mistral**, **xAI (Grok)**, **Cohere**."
            )
            a1 = agent_panel(1, "Claude",   "Architect & final decision maker",   "Tech Lead / Architect",         True,  "architect")
            a2 = agent_panel(2, "Gemini",   "UI components and accessibility",    "UI/UX Engineer",                True,  "ui_designer")
            a3 = agent_panel(3, "OpenAI",   "Security audits and hardening",      "Security Reviewer",             False, "security_hawk")
            a4 = agent_panel(4, "DeepSeek", "Core feature implementation",        "Senior Software Engineer",      False, "senior_engineer")
            a5 = agent_panel(5, "Mistral",  "CI/CD, Docker, performance",         "DevOps / Performance Engineer", False, "devops")
            a6 = agent_panel(6, "Frank",    "Bug fixing and code quality",        "Software Engineer",             False, "(none)")

        # ── TAB 3: Tools ─────────────────────────────────
        with gr.Tab("🛠 Tools"):
            gr.Markdown(
                "Agents can invoke these tools during their turn by including a ` ```tool ``` ` block.\n\n"
                "Set `SEARCH_API_KEY` in `.env` (Tavily) to enable web search."
            )
            gr.Textbox(
                label="Available tools",
                value=available_tools_block(),
                lines=20,
                interactive=False,
            )

        # ── TAB 4: Run ──────────────────────────────────
        with gr.Tab("🚀 Run"):
            run_btn = gr.Button("▶  Start AgentGroup Session", variant="primary", size="lg")

            gr.Markdown("### 💬 Discussion Thread")
            chat_out = gr.HTML(
                value="<div class='ag-chat'><p style='color:#484f58;text-align:center;padding:40px'>" \
                      "🤖 Configure agents and press Start…</p></div>"
            )

            with gr.Row():
                with gr.Accordion("📜 Raw Log", open=False):
                    log_out = gr.Textbox(label="", lines=20, interactive=False)

            with gr.Row():
                pr_out = gr.Textbox(label="🔗 Pull Request URL", interactive=False, scale=3)

            gr.Markdown("### 📥 Export session")
            with gr.Row():
                export_html = gr.File(label="Download chat HTML", interactive=False, scale=2)
                export_log  = gr.File(label="Download raw log",   interactive=False, scale=2)

            run_btn.click(
                run_session,
                inputs=[
                    github_token, repo_url, files_csv, task,
                    mode_radio, max_rounds,
                    tg_token, tg_chat_id,
                    session_name, load_mem_toggle,
                    *a1, *a2, *a3, *a4, *a5, *a6,
                ],
                outputs=[chat_out, log_out, pr_out, export_html, export_log],
            )

if __name__ == "__main__":
    demo.launch(share=False)
