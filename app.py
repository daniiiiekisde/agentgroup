"""AgentGroup – Gradio Web UI."""
from __future__ import annotations
import gradio as gr
from config import config
from core.models import build_adapter
from core.agent import Agent
from core.discussion import Discussion
from core.github_ops import GitHubOps


# ------------------------------------------------------------------ #
# Provider / model options
# ------------------------------------------------------------------ #

PROVIDER_MODELS = {
    "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
    "anthropic": [
        "claude-opus-4-5",
        "claude-sonnet-4-5",
        "claude-3-5-haiku-20241022",
    ],
    "gemini": ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash"],
    "groq": [
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "mixtral-8x7b-32768",
    ],
    "ollama": [
        "llama3.2",
        "llama3.1",
        "mistral",
        "codellama",
        "deepseek-coder",
        "gpt-oss:120b",  # Ollama Cloud
        "gpt-oss:20b",   # Ollama Cloud
    ],
}


def get_api_key(provider: str) -> str:
    return {
        "openai": config.openai_api_key,
        "anthropic": config.anthropic_api_key,
        "gemini": config.gemini_api_key,
        "groq": config.groq_api_key,
        "ollama": config.ollama_api_key,
    }.get(provider, "")


def build_agent_from_ui(
    name: str,
    role: str,
    provider: str,
    model: str,
    api_key_override: str,
) -> Agent:
    api_key = api_key_override.strip() or get_api_key(provider)
    kwargs: dict = {"model": model}
    if provider == "ollama":
        kwargs["base_url"] = config.ollama_base_url
        if api_key:
            kwargs["api_key"] = api_key
    else:
        if api_key:
            kwargs["api_key"] = api_key
    adapter = build_adapter(provider, **kwargs)
    return Agent(name=name, role=role, adapter=adapter)


# ------------------------------------------------------------------ #
# Main session runner
# ------------------------------------------------------------------ #

def run_session(
    github_token: str,
    repo_url: str,
    files_csv: str,
    task: str,
    # Agent 1
    a1_name, a1_role, a1_provider, a1_model, a1_key,
    # Agent 2
    a2_name, a2_role, a2_provider, a2_model, a2_key,
    # Agent 3 (optional)
    a3_name, a3_role, a3_provider, a3_model, a3_key,
):
    """Runs a full AgentGroup discussion session."""
    logs = []

    def log(msg):
        logs.append(msg)

    # Parse repo
    try:
        parts = repo_url.rstrip("/").split("/")
        owner, repo = parts[-2], parts[-1]
    except Exception:
        return "❌ Invalid repo URL. Use https://github.com/owner/repo", ""

    gh = GitHubOps(token=github_token or config.github_token, owner=owner, repo=repo)

    # Build agents
    agents = []
    for args in [
        (a1_name, a1_role, a1_provider, a1_model, a1_key),
        (a2_name, a2_role, a2_provider, a2_model, a2_key),
    ]:
        if args[0] and args[2]:  # name and provider required
            try:
                agents.append(build_agent_from_ui(*args))
            except Exception as e:
                return f"❌ Error building agent '{args[0]}': {e}", ""

    if a3_name and a3_provider:
        try:
            agents.append(build_agent_from_ui(a3_name, a3_role, a3_provider, a3_model, a3_key))
        except Exception as e:
            log(f"⚠️  Agent 3 skipped: {e}")

    if len(agents) < 2:
        return "❌ Need at least 2 valid agents.", ""

    file_paths = [f.strip() for f in files_csv.split(",") if f.strip()]
    if not file_paths:
        return "❌ Provide at least one file path.", ""

    disc = Discussion(agents=agents, github_ops=gh, log_callback=log)
    result = disc.run(file_paths=file_paths, task=task)

    log_text = "\n".join(result["log"])
    pr_link = result.get("pr_url") or "No PR created (no approved changes or all rejected)."
    return log_text, pr_link


# ------------------------------------------------------------------ #
# Gradio UI
# ------------------------------------------------------------------ #

with gr.Blocks(title="AgentGroup", theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 🤖 AgentGroup\n### Multi-AI Collaborative GitHub Editor")

    with gr.Tab("Setup"):
        with gr.Row():
            github_token = gr.Textbox(
                label="GitHub Token",
                placeholder="ghp_...",
                type="password",
                info="Personal Access Token with repo scope",
            )
            repo_url = gr.Textbox(
                label="Target Repository URL",
                placeholder="https://github.com/owner/repo",
            )
        files_csv = gr.Textbox(
            label="Files to Review (comma-separated paths)",
            placeholder="README.md, src/main.py, lib/utils.py",
        )
        task = gr.Textbox(
            label="Task / Instructions",
            value="Review this code and propose concrete improvements including bug fixes, performance optimizations, and best practices.",
            lines=3,
        )

    providers = list(PROVIDER_MODELS.keys())

    def agent_row(label: str, default_name: str, default_role: str):
        with gr.Group():
            gr.Markdown(f"### {label}")
            with gr.Row():
                name = gr.Textbox(label="Name", value=default_name)
                role = gr.Textbox(label="Role", value=default_role)
            with gr.Row():
                provider = gr.Dropdown(label="Provider", choices=providers, value="openai")
                model = gr.Dropdown(label="Model", choices=PROVIDER_MODELS["openai"], value="gpt-4o-mini")
            api_key = gr.Textbox(label="API Key override (optional)", type="password",
                                 placeholder="Leave empty to use .env")

            def update_models(p):
                models = PROVIDER_MODELS.get(p, [])
                return gr.Dropdown(choices=models, value=models[0] if models else None)

            provider.change(update_models, provider, model)
        return name, role, provider, model, api_key

    with gr.Tab("Agents"):
        a1 = agent_row("Agent 1", "Alice", "Senior Python Developer")
        a2 = agent_row("Agent 2", "Bob", "Security & Code Quality Reviewer")
        a3 = agent_row("Agent 3 (optional)", "", "DevOps & Performance Engineer")

    with gr.Tab("Run"):
        run_btn = gr.Button("🚀 Start AgentGroup Session", variant="primary")
        log_out = gr.Textbox(label="Session Log", lines=30, interactive=False)
        pr_out = gr.Textbox(label="Pull Request URL", interactive=False)

        run_btn.click(
            run_session,
            inputs=[
                github_token, repo_url, files_csv, task,
                *a1, *a2, *a3,
            ],
            outputs=[log_out, pr_out],
        )

if __name__ == "__main__":
    demo.launch(share=False)
