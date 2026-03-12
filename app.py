"""AgentGroup v5 – UI Overhaul: glassmorphism, animated avatars, glow effects, responsive.

New in v5 UI:
- Glassmorphism header + tabs
- Animated gradient avatars with glow ring per role
- Slide-in animation per chat message
- Live status badges (THINKING / DONE / ERROR)
- Role-color coding across all UI components
- Responsive sidebar org-chart
- Dark neon accent palette
- Improved scrollbar and typography (Inter)
- Sticky header with session info
- Pulse animation on Run button
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

# Role → neon accent color
ROLE_COLORS = {
    "Tech Lead / Architect":           "#a78bfa",  # purple
    "Senior Software Engineer":        "#60a5fa",  # blue
    "Software Engineer":               "#34d399",  # green
    "UI/UX Engineer":                  "#f472b6",  # pink
    "Security Reviewer":               "#f87171",  # red
    "DevOps / Performance Engineer":   "#fbbf24",  # amber
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
        if s[0] and s[2]:
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

    try:
        memory.save(mem_path)
        mem_status = f"✅ Memory saved to {mem_path}"
    except Exception as e:
        mem_status = f"⚠️ Memory save failed: {e}"

    chat_html  = result["chat_html"]
    log_text   = "\n".join(result["log"])
    pr_link    = result.get("pr_url") or "No PR created."

    export_html_path = f"/tmp/agentgroup_chat_{int(time.time())}.html"
    export_log_path  = f"/tmp/agentgroup_log_{int(time.time())}.txt"
    try:
        Path(export_html_path).write_text(
            f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>AgentGroup Session</title>"
            f"<style>body{{background:#050709;color:#e6edf3;font-family:Inter,sans-serif;padding:24px}}</style></head>"
            f"<body>{chat_html}</body></html>"
        )
        Path(export_log_path).write_text(log_text)
    except Exception:
        export_html_path = None
        export_log_path  = None

    return chat_html, log_text + "\n" + mem_status, pr_link, export_html_path, export_log_path


# ── CSS v5: Full UI Overhaul ──────────────────────────────────────────────

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

/* ── Global reset & base ─────────────────────────────── */
* { box-sizing: border-box; }

.gradio-container {
  background: #050709 !important;
  font-family: 'Inter', sans-serif !important;
  min-height: 100vh;
}

/* ── Animated gradient background ───────────────────── */
.gradio-container::before {
  content: '';
  position: fixed;
  top: -50%; left: -50%;
  width: 200%; height: 200%;
  background: radial-gradient(ellipse at 20% 20%, rgba(88,70,180,0.12) 0%, transparent 50%),
              radial-gradient(ellipse at 80% 80%, rgba(16,185,129,0.08) 0%, transparent 50%),
              radial-gradient(ellipse at 50% 50%, rgba(59,130,246,0.06) 0%, transparent 60%);
  animation: bgPulse 12s ease-in-out infinite alternate;
  pointer-events: none;
  z-index: 0;
}
@keyframes bgPulse {
  0%   { transform: translate(0,0) rotate(0deg); }
  100% { transform: translate(2%,2%) rotate(3deg); }
}

/* ── Glassmorphism header ────────────────────────────── */
.ag-header {
  background: rgba(13,17,23,0.75);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 16px;
  padding: 20px 28px;
  margin-bottom: 24px;
  position: relative;
  overflow: hidden;
}
.ag-header::after {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(168,139,250,0.6), rgba(96,165,250,0.6), transparent);
}

/* ── Tab styling ─────────────────────────────────────── */
.tabs > .tab-nav {
  background: rgba(13,17,23,0.6) !important;
  backdrop-filter: blur(10px) !important;
  border-radius: 12px !important;
  padding: 4px !important;
  border: 1px solid rgba(255,255,255,0.05) !important;
  gap: 4px !important;
}
.tabs > .tab-nav > button {
  border-radius: 8px !important;
  color: #7d8590 !important;
  font-weight: 500 !important;
  font-size: .85rem !important;
  transition: all .2s ease !important;
  border: none !important;
  background: transparent !important;
  padding: 8px 16px !important;
}
.tabs > .tab-nav > button.selected {
  background: rgba(88,70,180,0.25) !important;
  color: #a78bfa !important;
  box-shadow: 0 0 12px rgba(167,139,250,0.2) !important;
}
.tabs > .tab-nav > button:hover:not(.selected) {
  background: rgba(255,255,255,0.05) !important;
  color: #e6edf3 !important;
}

/* ── Input fields ─────────────────────────────────────── */
input, textarea, select {
  background: rgba(22,27,34,0.8) !important;
  border: 1px solid rgba(48,54,61,0.8) !important;
  color: #e6edf3 !important;
  border-radius: 8px !important;
  font-family: 'Inter', sans-serif !important;
  transition: border-color .2s, box-shadow .2s !important;
}
input:focus, textarea:focus {
  border-color: rgba(88,70,180,0.6) !important;
  box-shadow: 0 0 0 3px rgba(88,70,180,0.12) !important;
  outline: none !important;
}
label {
  color: #8b949e !important;
  font-size: .8rem !important;
  font-weight: 500 !important;
  letter-spacing: .03em !important;
  text-transform: uppercase !important;
}

/* ── Accordion ────────────────────────────────────────── */
.gr-accordion {
  background: rgba(13,17,23,0.5) !important;
  border: 1px solid rgba(48,54,61,0.6) !important;
  border-radius: 12px !important;
  overflow: hidden;
}
.gr-accordion > .label-wrap {
  background: rgba(22,27,34,0.6) !important;
  padding: 12px 16px !important;
  font-weight: 600 !important;
  color: #c9d1d9 !important;
  letter-spacing: .02em;
}

/* ── Buttons ─────────────────────────────────────────── */
button.primary {
  background: linear-gradient(135deg, #5b21b6, #3b82f6) !important;
  border: none !important;
  border-radius: 10px !important;
  color: #fff !important;
  font-weight: 600 !important;
  font-size: 1rem !important;
  padding: 12px 28px !important;
  cursor: pointer !important;
  position: relative !important;
  overflow: hidden !important;
  transition: transform .15s, box-shadow .15s !important;
  box-shadow: 0 4px 20px rgba(91,33,182,0.4) !important;
}
button.primary::before {
  content: '';
  position: absolute;
  top: -50%; left: -60%;
  width: 40%; height: 200%;
  background: rgba(255,255,255,0.15);
  transform: skewX(-20deg);
  animation: btnShine 3s ease-in-out infinite;
}
@keyframes btnShine {
  0%   { left: -60%; }
  60%  { left: 130%; }
  100% { left: 130%; }
}
button.primary:hover {
  transform: translateY(-1px) !important;
  box-shadow: 0 6px 28px rgba(91,33,182,0.55) !important;
}
button.primary:active { transform: translateY(0) !important; }

button.secondary {
  background: rgba(30,37,46,0.8) !important;
  border: 1px solid rgba(48,54,61,0.8) !important;
  border-radius: 8px !important;
  color: #8b949e !important;
  font-size: .82rem !important;
  transition: all .2s !important;
}
button.secondary:hover {
  border-color: rgba(88,70,180,0.5) !important;
  color: #a78bfa !important;
}

/* ── Sliders ─────────────────────────────────────────── */
.gr-slider input[type=range] {
  accent-color: #7c3aed !important;
}

/* ── Radio buttons ───────────────────────────────────── */
.gr-radio-group label {
  background: rgba(22,27,34,0.6) !important;
  border: 1px solid rgba(48,54,61,0.6) !important;
  border-radius: 8px !important;
  padding: 8px 14px !important;
  color: #8b949e !important;
  transition: all .2s !important;
  text-transform: none !important;
  font-size: .85rem !important;
}
.gr-radio-group label:has(input:checked) {
  background: rgba(88,70,180,0.2) !important;
  border-color: rgba(167,139,250,0.5) !important;
  color: #a78bfa !important;
}

/* ── Chat area ───────────────────────────────────────── */
.ag-chat {
  background: rgba(5,7,9,0.95);
  border-radius: 16px;
  padding: 20px;
  max-height: 680px;
  overflow-y: auto;
  font-family: 'Inter', sans-serif;
  border: 1px solid rgba(48,54,61,0.5);
  scrollbar-width: thin;
  scrollbar-color: rgba(88,70,180,0.4) transparent;
  position: relative;
}
.ag-chat::-webkit-scrollbar { width: 4px; }
.ag-chat::-webkit-scrollbar-track { background: transparent; }
.ag-chat::-webkit-scrollbar-thumb {
  background: rgba(88,70,180,0.4);
  border-radius: 2px;
}

/* ── Message slide-in ────────────────────────────────── */
.ag-msg {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  animation: msgSlideIn .35s cubic-bezier(.22,.68,0,1.2) both;
}
@keyframes msgSlideIn {
  from { opacity: 0; transform: translateY(14px) scale(.97); }
  to   { opacity: 1; transform: translateY(0)   scale(1); }
}
.ag-msg.reply {
  margin-left: 56px;
  border-left: 2px solid rgba(88,70,180,0.3);
  padding-left: 14px;
}

/* ── Animated avatar with glow ───────────────────────── */
.ag-avatar {
  width: 42px; height: 42px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 20px; flex-shrink: 0;
  background: linear-gradient(135deg, #1a1f2e, #2d3748);
  position: relative;
  transition: transform .2s;
}
.ag-avatar::before {
  content: '';
  position: absolute;
  inset: -2px;
  border-radius: 50%;
  background: conic-gradient(var(--role-color, #7c3aed), transparent 60%, var(--role-color, #7c3aed));
  animation: avatarSpin 4s linear infinite;
  z-index: -1;
}
.ag-avatar::after {
  content: '';
  position: absolute;
  inset: -4px;
  border-radius: 50%;
  background: radial-gradient(circle, var(--role-color, #7c3aed) 0%, transparent 70%);
  opacity: 0.2;
  animation: avatarGlow 2s ease-in-out infinite alternate;
}
@keyframes avatarSpin {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}
@keyframes avatarGlow {
  from { opacity: 0.1; transform: scale(1); }
  to   { opacity: 0.35; transform: scale(1.15); }
}
.ag-msg:hover .ag-avatar { transform: scale(1.08); }

/* ── Message bubble ──────────────────────────────────── */
.ag-bubble {
  background: rgba(22,27,34,0.7);
  border: 1px solid rgba(48,54,61,0.6);
  backdrop-filter: blur(8px);
  border-radius: 14px;
  padding: 14px 18px;
  max-width: 720px;
  color: #e6edf3;
  transition: border-color .25s, box-shadow .25s, transform .15s;
  position: relative;
  overflow: hidden;
}
.ag-bubble::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--role-color, #7c3aed), transparent);
  opacity: 0.4;
}
.ag-bubble:hover {
  border-color: rgba(var(--role-color-rgb, 124,58,237), 0.35);
  box-shadow: 0 4px 20px rgba(0,0,0,0.3), 0 0 0 1px rgba(var(--role-color-rgb, 124,58,237), 0.15);
  transform: translateY(-1px);
}
.ag-bubble .sender {
  font-weight: 700;
  font-size: .88rem;
  margin-bottom: 6px;
  color: var(--role-color, #a78bfa);
  display: flex;
  align-items: center;
  gap: 8px;
}
.ag-bubble .role-tag {
  font-size: .68rem;
  color: #7d8590;
  background: rgba(33,38,45,0.8);
  border: 1px solid rgba(48,54,61,0.6);
  border-radius: 4px;
  padding: 2px 8px;
  font-weight: 400;
  letter-spacing: .04em;
}
.ag-bubble .reply-to {
  font-size: .78rem;
  color: #7d8590;
  margin-bottom: 9px;
  border-left: 3px solid rgba(88,70,180,0.5);
  padding: 4px 10px;
  background: rgba(10,13,18,0.5);
  border-radius: 0 6px 6px 0;
}
.ag-bubble .body {
  font-size: .88rem;
  line-height: 1.65;
  white-space: pre-wrap;
  color: #cdd5de;
}
.ag-bubble .vote { margin-top: 10px; font-size: .82rem; }
.vote-approve { color: #3fb950; font-weight: 700; }
.vote-reject  { color: #f85149; font-weight: 700; }

/* ── Status badge ────────────────────────────────────── */
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: .72rem;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
  letter-spacing: .05em;
  text-transform: uppercase;
}
.status-thinking {
  background: rgba(251,191,36,0.12);
  color: #fbbf24;
  border: 1px solid rgba(251,191,36,0.25);
  animation: thinkingPulse 1.2s ease-in-out infinite;
}
@keyframes thinkingPulse {
  0%,100% { opacity: 1; }
  50%      { opacity: .5; }
}
.status-done {
  background: rgba(63,185,80,0.12);
  color: #3fb950;
  border: 1px solid rgba(63,185,80,0.25);
}
.status-error {
  background: rgba(248,81,73,0.12);
  color: #f85149;
  border: 1px solid rgba(248,81,73,0.25);
}

/* ── Round divider ───────────────────────────────────── */
.ag-divider {
  text-align: center;
  color: #484f58;
  font-size: .74rem;
  margin: 16px 0;
  padding: 6px 0;
  border-top: 1px solid rgba(33,38,45,0.8);
  letter-spacing: .1em;
  text-transform: uppercase;
  position: relative;
}
.ag-divider::before, .ag-divider::after {
  content: '';
  position: absolute;
  top: 50%;
  width: 30%;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(88,70,180,0.3));
}
.ag-divider::before { left: 5%; }
.ag-divider::after  { right: 5%; transform: scaleX(-1); }

/* ── Catchphrase ─────────────────────────────────────── */
.catchphrase {
  font-size: .74rem;
  color: #8b949e;
  font-style: italic;
  margin-top: 9px;
  padding-top: 7px;
  border-top: 1px dashed rgba(48,54,61,0.6);
  font-family: 'JetBrains Mono', monospace;
}

/* ── Tool result ─────────────────────────────────────── */
.tool-result {
  margin-top: 10px;
  background: rgba(5,7,9,0.6);
  border: 1px solid rgba(48,54,61,0.5);
  border-left: 3px solid rgba(88,70,180,0.6);
  border-radius: 0 8px 8px 0;
  padding: 10px 14px;
  font-size: .78rem;
  color: #8b949e;
}
.tool-result pre {
  margin: 4px 0;
  white-space: pre-wrap;
  color: #79c0ff;
  font-family: 'JetBrains Mono', monospace;
  font-size: .75rem;
}

/* ── Persona preview ─────────────────────────────────── */
.persona-preview {
  background: rgba(22,27,34,0.7);
  border: 1px solid rgba(48,54,61,0.6);
  border-radius: 10px;
  padding: 16px;
  color: #e6edf3;
  font-size: .85rem;
  line-height: 1.9;
  backdrop-filter: blur(6px);
}
.persona-preview code {
  background: rgba(88,70,180,0.18);
  border-radius: 4px;
  padding: 1px 6px;
  font-family: 'JetBrains Mono', monospace;
  color: #c084fc;
  font-size: .8rem;
}

/* ── Mode badges ─────────────────────────────────────── */
.mode-discuss    { color: #3fb950; font-weight: 700; }
.mode-plan       { color: #d29922; font-weight: 700; }
.mode-autonomous { color: #f85149; font-weight: 700; }

/* ── Org chart ───────────────────────────────────────── */
.orgchart {
  background: rgba(22,27,34,0.5);
  border-radius: 12px;
  padding: 16px;
  border: 1px solid rgba(48,54,61,0.5);
  font-size: .84rem;
}
.orgchart .level {
  display: flex; gap: 10px;
  justify-content: center;
  flex-wrap: wrap; margin: 7px 0;
}
.org-card {
  background: rgba(33,38,45,0.7);
  border: 1px solid rgba(48,54,61,0.6);
  border-radius: 10px;
  padding: 8px 16px;
  color: #e6edf3;
  display: flex; align-items: center; gap: 8px;
  transition: all .2s;
}
.org-card:hover {
  border-color: rgba(167,139,250,0.4);
  box-shadow: 0 0 12px rgba(167,139,250,0.1);
}

/* ── Scrollbar global ────────────────────────────────── */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
  background: rgba(88,70,180,0.3);
  border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
  background: rgba(88,70,180,0.55);
}

/* ── Responsive ──────────────────────────────────────── */
@media (max-width: 768px) {
  .ag-bubble { max-width: 95vw; padding: 10px 12px; }
  .ag-avatar { width: 34px; height: 34px; font-size: 16px; }
  .ag-msg.reply { margin-left: 20px; }
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


# ── Gradio layout v5 ────────────────────────────────────────────

with gr.Blocks(title="AgentGroup v5", theme=gr.themes.Base(), css=CSS) as demo:
    gr.HTML(
        "<div class='ag-header'>"
        "<h1 style='margin:0;font-size:1.6rem;font-weight:700;color:#e6edf3;letter-spacing:-.02em'>"
        "🤖 AgentGroup <span style='color:#a78bfa'>v5</span></h1>"
        "<p style='margin:6px 0 0;color:#7d8590;font-size:.88rem'>"
        "Multi-AI Collaborative GitHub Editor &nbsp;·&nbsp; "
        "<span class='mode-discuss'>DISCUSS</span> &nbsp;/&nbsp; "
        "<span class='mode-plan'>PLAN</span> &nbsp;/&nbsp; "
        "<span class='mode-autonomous'>AUTONOMOUS</span> &nbsp;·&nbsp; "
        "persona-aware &nbsp;·&nbsp; tool-use &nbsp;·&nbsp; session memory</p>"
        "</div>"
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
        with gr.Tab("🧑\u200d💼 Agents (2–6)"):
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
                value="<div class='ag-chat'><p style='color:#484f58;text-align:center;padding:60px 40px'>"
                      "<span style='font-size:2.5rem;display:block;margin-bottom:12px'>🤖</span>"
                      "Configure your agents and press <strong style='color:#a78bfa'>Start</strong> to begin."
                      "</p></div>"
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
