"""Unit tests for AgentGroup core modules.

Run with: pytest tests/test_core.py -v
"""
import pytest
from unittest.mock import MagicMock, patch


# ── tools.py ────────────────────────────────────────────────────────────

class TestTools:
    def test_extract_tool_calls_valid(self):
        from core.tools import extract_tool_calls
        text = '```tool\n{"tool": "read_file", "params": {"path": "README.md"}}\n```'
        calls = extract_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["tool"] == "read_file"

    def test_extract_tool_calls_invalid_json(self):
        from core.tools import extract_tool_calls
        text = '```tool\n{invalid json}\n```'
        assert extract_tool_calls(text) == []

    def test_run_tool_unknown(self):
        from core.tools import run_tool
        result = run_tool({"tool": "nonexistent_tool", "params": {}})
        assert "Unknown tool" in result

    def test_read_file_path_traversal(self):
        from core.tools import tool_read_file
        result = tool_read_file("../../../etc/passwd")
        assert "Access denied" in result or "not found" in result.lower()

    def test_read_file_not_found(self):
        from core.tools import tool_read_file
        result = tool_read_file("this_file_does_not_exist_xyz.txt")
        assert "not found" in result.lower() or "Access denied" in result

    def test_list_files_path_traversal(self):
        from core.tools import tool_list_files
        result = tool_list_files("../../")
        assert "Access denied" in result

    def test_run_python_simple(self):
        from core.tools import tool_run_python
        result = tool_run_python("print(1 + 1)")
        assert "2" in result

    def test_run_python_blocked_open(self):
        from core.tools import tool_run_python
        result = tool_run_python("open('/etc/passwd')")
        assert "Blocked" in result

    def test_run_python_blocked_subprocess(self):
        from core.tools import tool_run_python
        result = tool_run_python("import subprocess; subprocess.run(['ls'])")
        assert "Blocked" in result

    def test_summarise(self):
        from core.tools import tool_summarise
        text = "Hello world. This is a test. Another sentence here."
        result = tool_summarise(text)
        assert len(result) <= 500
        assert len(result) > 0

    def test_search_code_no_match(self):
        from core.tools import tool_search_code
        result = tool_search_code("ZZZZZ_no_such_pattern_ZZZZZ")
        assert "No matches found" in result


# ── context_manager.py ────────────────────────────────────────────────────────

class TestContextManager:
    def _make_messages(self, n: int, chars_each: int = 100):
        return [
            {"role": "user" if i % 2 == 0 else "assistant", "content": "x" * chars_each}
            for i in range(n)
        ]

    def test_fits_small_context(self):
        from core.context_manager import ContextManager
        cm = ContextManager(model="gpt-4o-mini")  # 128k limit
        msgs = self._make_messages(10, 100)
        assert cm.fits(msgs)

    def test_truncate_reduces_size(self):
        from core.context_manager import ContextManager, TruncationStrategy
        cm = ContextManager(model="gemma2-9b-it", strategy=TruncationStrategy.TRUNCATE)
        # Create messages that exceed the 8k token limit
        msgs = self._make_messages(500, 200)
        result = cm.fit(msgs)
        assert len(result) < len(msgs)
        from core.context_manager import _count_tokens
        assert _count_tokens(result) <= cm.limit

    def test_summarise_strategy(self):
        from core.context_manager import ContextManager, TruncationStrategy
        cm = ContextManager(model="gemma2-9b-it", strategy=TruncationStrategy.SUMMARISE)
        msgs = (
            [{"role": "system", "content": "You are helpful."}]
            + self._make_messages(200, 200)
        )
        result = cm.fit(msgs)
        from core.context_manager import _count_tokens
        assert _count_tokens(result) <= cm.limit

    def test_system_messages_preserved(self):
        from core.context_manager import ContextManager, TruncationStrategy
        cm = ContextManager(model="gemma2-9b-it", strategy=TruncationStrategy.TRUNCATE)
        sys_msg = {"role": "system", "content": "System prompt"}
        msgs    = [sys_msg] + self._make_messages(500, 200)
        result  = cm.fit(msgs)
        assert result[0]["role"] == "system"


# ── rate_limiter.py ───────────────────────────────────────────────────────────

class TestRateLimiter:
    def test_registry_returns_limiter(self):
        from core.rate_limiter import RateLimiterRegistry
        reg = RateLimiterRegistry()
        lim = reg.get("openai")
        assert lim is not None

    def test_same_provider_same_instance(self):
        from core.rate_limiter import RateLimiterRegistry
        reg = RateLimiterRegistry()
        l1 = reg.get("openai")
        l2 = reg.get("openai")
        assert l1 is l2

    def test_wait_does_not_crash(self):
        from core.rate_limiter import RateLimiterRegistry
        reg = RateLimiterRegistry()
        # Should not raise; with rpm=10000 the wait is negligible
        reg.get("openai", rpm=10000).wait()


# ── agent.py ──────────────────────────────────────────────────────────────

class TestAgent:
    def _make_agent(self, name="TestAgent"):
        from core.agent import Agent
        from core.persona import PersonaProfile
        adapter       = MagicMock()
        adapter.model = "gpt-4o-mini"
        adapter.chat  = MagicMock(return_value="Test response")
        return Agent(name=name, role="Tester", adapter=adapter)

    def test_say_returns_response(self):
        agent = self._make_agent()
        result = agent.say("Hello")
        assert result == "Test response"

    def test_say_appends_history(self):
        agent = self._make_agent()
        agent.say("Hello")
        assert len(agent.history) == 2  # user + assistant

    def test_say_api_error_returns_error_message(self):
        from core.agent import Agent
        adapter       = MagicMock()
        adapter.model = "gpt-4o-mini"
        adapter.chat  = MagicMock(side_effect=Exception("API down"))
        agent = Agent(name="Err", role="Tester", adapter=adapter)
        result = agent.say("Hello")
        assert "API error" in result
        assert len(agent.history) == 0  # failed message removed

    def test_reset_history(self):
        agent = self._make_agent()
        agent.say("Hello")
        agent.reset_history()
        assert agent.history == []

    def test_history_capped_at_max(self):
        from core.agent import Agent, MAX_HISTORY
        adapter       = MagicMock()
        adapter.model = "gpt-4o-mini"
        adapter.chat  = MagicMock(return_value="ok")
        agent = Agent(name="A", role="R", adapter=adapter)
        for _ in range(MAX_HISTORY + 10):
            agent.say("msg")
        assert len(agent.history) <= MAX_HISTORY + 2  # +2 for last user+assistant

    def test_repr(self):
        agent = self._make_agent("Alice")
        assert "Alice" in repr(agent)
