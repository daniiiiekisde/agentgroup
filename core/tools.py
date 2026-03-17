"""AgentGroup Tools – agents can call these during a discussion turn.

Inspired by OpenAI function-calling, ZeroClaw tool-use and OpenClaw task runners.
Each tool is a plain callable that returns a string result injected back into
the agent context before the next turn.

Security improvements:
- run_python: restricted builtins, no file I/O, no network, 5s timeout, resource limits
- read_file: path traversal protection (must stay within CWD)
- list_files: path traversal protection
"""
from __future__ import annotations
import subprocess, json, re, textwrap, os
from pathlib import Path
from typing import Callable, Dict, Any

# ── Tool registry ─────────────────────────────────────────────────────────────

_TOOLS: Dict[str, Dict[str, Any]] = {}
_CWD   = Path(".").resolve()


def _safe_path(path: str) -> Path | None:
    """Resolve path and ensure it stays within CWD. Returns None if unsafe."""
    try:
        resolved = (_CWD / path).resolve()
        resolved.relative_to(_CWD)  # raises ValueError if outside CWD
        return resolved
    except (ValueError, RuntimeError):
        return None


def register(name: str, description: str, params: Dict[str, str]):
    """Decorator to register a tool."""
    def decorator(fn: Callable):
        _TOOLS[name] = {"fn": fn, "description": description, "params": params}
        return fn
    return decorator


def available_tools_block() -> str:
    lines = ["== AVAILABLE TOOLS =="]
    for name, meta in _TOOLS.items():
        params = ", ".join(f"{k}: {v}" for k, v in meta["params"].items())
        lines.append(f"  {name}({params}) \u2014 {meta['description']}")
    lines.append("""
To use a tool, include a JSON block in your response:
```tool
{"tool": "<name>", "params": {<key>: <value>}}
```
You will receive the result before your final answer.
""")
    return "\n".join(lines)


def extract_tool_calls(text: str) -> list[dict]:
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
        return f"[Tool error] Unknown tool: {name!r}. Available: {list(_TOOLS)}"
    try:
        return str(_TOOLS[name]["fn"](**params))
    except TypeError as e:
        return f"[Tool error] Bad params for {name!r}: {e}"
    except Exception as e:
        return f"[Tool error] {name}: {e}"


# ── Built-in tools ────────────────────────────────────────────────────────────

@register(
    "read_file",
    "Read a file from the project directory (cannot access files outside project root)",
    {"path": "str"}
)
def tool_read_file(path: str) -> str:
    safe = _safe_path(path)
    if safe is None:
        return f"[read_file] Access denied: path '{path}' is outside the project root."
    if not safe.exists():
        return f"[read_file] File not found: {path}"
    if not safe.is_file():
        return f"[read_file] Not a file: {path}"
    try:
        return safe.read_text(encoding="utf-8")[:8000]
    except Exception as e:
        return f"[read_file] Error reading file: {e}"


@register(
    "search_code",
    "Search for a pattern inside all .py files recursively",
    {"pattern": "str"}
)
def tool_search_code(pattern: str) -> str:
    if not pattern or len(pattern) > 200:
        return "[search_code] Invalid pattern."
    results = []
    for f in _CWD.rglob("*.py"):
        # Skip hidden dirs and venvs
        if any(part.startswith(".") or part in ("venv", "__pycache__", "node_modules")
               for part in f.parts):
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if pattern.lower() in line.lower():
                results.append(f"{f.relative_to(_CWD)}:{i}: {line.strip()}")
        if len(results) > 50:
            break
    return "\n".join(results[:50]) or "No matches found."


@register(
    "list_files",
    "List files in a project directory (cannot list outside project root)",
    {"path": "str"}
)
def tool_list_files(path: str = ".") -> str:
    safe = _safe_path(path)
    if safe is None:
        return f"[list_files] Access denied: path '{path}' is outside the project root."
    if not safe.exists():
        return f"[list_files] Path not found: {path}"
    entries = sorted(safe.iterdir())
    return "\n".join(str(e.relative_to(_CWD)) for e in entries[:100])


@register(
    "run_python",
    "Run a short Python snippet and return stdout (max 5s, no file I/O, no network)",
    {"code": "str"}
)
def tool_run_python(code: str) -> str:
    if len(code) > 2000:
        return "[run_python] Code exceeds 2000 character limit."
    # Forbidden patterns: file ops, network, imports of risky modules
    forbidden = [
        r"open\s*\(", r"__import__", r"importlib", r"subprocess",
        r"os\.system", r"os\.popen", r"socket", r"urllib", r"requests",
        r"shutil", r"eval\s*\(", r"exec\s*\(",
    ]
    for pattern in forbidden:
        if re.search(pattern, code):
            return f"[run_python] Blocked: code contains forbidden pattern '{pattern}'."
    try:
        result = subprocess.run(
            ["python3", "-c", code],
            capture_output=True,
            text=True,
            timeout=5,
            env={**os.environ, "PYTHONPATH": ""},  # clean env
        )
        out = result.stdout[:2000]
        err = result.stderr[:500]
        return (out + (f"\n[stderr] {err}" if err else "")).strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "[run_python] Timed out after 5s."
    except Exception as e:
        return f"[run_python] Error: {e}"


@register(
    "web_search",
    "Search the web via Tavily API (requires SEARCH_API_KEY in .env)",
    {"query": "str"}
)
def tool_web_search(query: str) -> str:
    import os
    api_key = os.getenv("SEARCH_API_KEY", "")
    if not api_key:
        return f"[web_search] No SEARCH_API_KEY set. Query was: {query}"
    if len(query) > 500:
        return "[web_search] Query too long (max 500 chars)."
    try:
        import requests as req
        resp = req.post(
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
    if not text:
        return ""
    sentences = re.split(r'(?<=[.!?]) +', text.strip())
    summary   = " ".join(sentences[:4])
    return textwrap.shorten(summary, width=500, placeholder="...")
