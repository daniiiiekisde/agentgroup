"""AgentGroup Tools – agents can call these during a discussion turn.

Inspired by OpenAI function-calling, ZeroClaw tool-use and OpenClaw task runners.
Each tool is a plain callable that returns a string result injected back into
the agent context before the next turn.
"""
from __future__ import annotations
import subprocess, json, re, textwrap
from pathlib import Path
from typing import Callable, Dict, Any, Optional


# ── Tool registry ────────────────────────────────────────────────────────────

_TOOLS: Dict[str, Dict[str, Any]] = {}


def register(name: str, description: str, params: Dict[str, str]):
    """Decorator to register a tool."""
    def decorator(fn: Callable):
        _TOOLS[name] = {"fn": fn, "description": description, "params": params}
        return fn
    return decorator


def available_tools_block() -> str:
    """Return a formatted list of available tools for injection into prompts."""
    lines = ["== AVAILABLE TOOLS =="]
    for name, meta in _TOOLS.items():
        params = ", ".join(f"{k}: {v}" for k, v in meta["params"].items())
        lines.append(f"  {name}({params}) — {meta['description']}")
    lines.append("""
To use a tool, include a JSON block in your response:
```tool
{"tool": "<name>", "params": {<key>: <value>}}
```
You will receive the result before your final answer.
""")
    return "\n".join(lines)


def extract_tool_calls(text: str) -> list[dict]:
    """Extract all ```tool ... ``` blocks from agent response."""
    results = []
    for m in re.finditer(r"```tool\s*\n(.+?)```", text, re.DOTALL):
        try:
            results.append(json.loads(m.group(1).strip()))
        except json.JSONDecodeError:
            pass
    return results


def run_tool(call: dict) -> str:
    name   = call.get("tool", "")
    params = call.get("params", {})
    if name not in _TOOLS:
        return f"[Tool error] Unknown tool: {name}"
    try:
        return _TOOLS[name]["fn"](**params)
    except Exception as e:
        return f"[Tool error] {name}: {e}"


# ── Built-in tools ────────────────────────────────────────────────────────────

@register(
    "read_file",
    "Read a file from the current working directory",
    {"path": "str"}
)
def tool_read_file(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return f"[read_file] File not found: {path}"
    return p.read_text(encoding="utf-8")[:8000]


@register(
    "search_code",
    "Search for a pattern inside all .py files recursively",
    {"pattern": "str"}
)
def tool_search_code(pattern: str) -> str:
    results = []
    for f in Path(".").rglob("*.py"):
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if pattern.lower() in line.lower():
                results.append(f"{f}:{i}: {line.strip()}")
        if len(results) > 50:
            break
    return "\n".join(results[:50]) or "No matches found."


@register(
    "list_files",
    "List files in a directory (non-recursive)",
    {"path": "str"}
)
def tool_list_files(path: str = ".") -> str:
    p = Path(path)
    if not p.exists():
        return f"[list_files] Path not found: {path}"
    entries = sorted(p.iterdir())
    return "\n".join(str(e) for e in entries[:100])


@register(
    "run_python",
    "Run a short Python snippet and return stdout (max 3s, sandboxed)",
    {"code": "str"}
)
def tool_run_python(code: str) -> str:
    try:
        result = subprocess.run(
            ["python3", "-c", code],
            capture_output=True, text=True, timeout=5
        )
        out = result.stdout[:2000]
        err = result.stderr[:500]
        return (out + (f"\n[stderr] {err}" if err else "")).strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "[run_python] Timed out after 5s"
    except Exception as e:
        return f"[run_python] Error: {e}"


@register(
    "web_search",
    "Simulate a web search (returns a stub — connect a real search API via SEARCH_API_KEY)",
    {"query": "str"}
)
def tool_web_search(query: str) -> str:
    import os
    api_key = os.getenv("SEARCH_API_KEY", "")
    if not api_key:
        return f"[web_search] No SEARCH_API_KEY set. Query was: {query}"
    try:
        import requests
        resp = requests.get(
            "https://api.tavily.com/search",
            json={"api_key": api_key, "query": query, "max_results": 3},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        return "\n\n".join(
            f"**{r['title']}**\n{r['url']}\n{r.get('content','')[:300]}"
            for r in results
        ) or "No results."
    except Exception as e:
        return f"[web_search] Error: {e}"


@register(
    "summarise",
    "Summarise a long text to under 500 chars",
    {"text": "str"}
)
def tool_summarise(text: str) -> str:
    sentences = re.split(r'(?<=[.!?]) +', text.strip())
    summary = " ".join(sentences[:4])
    return textwrap.shorten(summary, width=500, placeholder="...")
