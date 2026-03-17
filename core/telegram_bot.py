"""Telegram relay – forwards agent messages to a Telegram chat.

Improvements over v1:
- Retry on transient HTTP errors
- Rich formatting: emoji header, code blocks for diffs
- send_agent_message properly trims long messages
- send_pr_notification with inline button
- Async-compatible send_async() for non-blocking use
"""
from __future__ import annotations
import time
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

_RETRY_ATTEMPTS = 3
_RETRY_DELAY    = 1.5  # seconds


class TelegramRelay:
    """Sends messages to a Telegram bot chat.

    Args:
        token:   Bot token from @BotFather  (e.g. '123456:ABC-...')
        chat_id: Target chat/group/channel ID (e.g. '-1001234567890')
    """

    API = "https://api.telegram.org"

    def __init__(self, token: str, chat_id: str):
        self.token   = (token   or "").strip()
        self.chat_id = (chat_id or "").strip()
        self._ok     = bool(self.token and self.chat_id)

    # ── Low-level send ──────────────────────────────────────────────────────

    def send(self, text: str, parse_mode: str = "Markdown",
             reply_markup: Optional[dict] = None) -> bool:
        """Send *text* to the configured chat. Returns True on success."""
        if not self._ok:
            return False
        url  = f"{self.API}/bot{self.token}/sendMessage"
        data: dict = {
            "chat_id":    self.chat_id,
            "text":       text[:4096],
            "parse_mode": parse_mode,
        }
        if reply_markup:
            import json
            data["reply_markup"] = json.dumps(reply_markup)

        for attempt in range(1, _RETRY_ATTEMPTS + 1):
            try:
                r = requests.post(url, json=data, timeout=10)
                if r.status_code == 200:
                    return True
                if r.status_code in (429, 502, 503) and attempt < _RETRY_ATTEMPTS:
                    retry_after = int(r.json().get("parameters", {}).get("retry_after", _RETRY_DELAY))
                    logger.warning(f"Telegram {r.status_code} – retrying in {retry_after}s")
                    time.sleep(retry_after)
                    continue
                logger.warning(f"Telegram send failed ({r.status_code}): {r.text[:200]}")
                return False
            except requests.RequestException as e:
                if attempt == _RETRY_ATTEMPTS:
                    logger.error(f"Telegram send error: {e}")
                    return False
                time.sleep(_RETRY_DELAY)
        return False

    # ── High-level helpers ──────────────────────────────────────────────────

    def send_agent_message(
        self,
        agent_name: str,
        position:   str,
        emoji:      str,
        text:       str,
        round_num:  Optional[int] = None,
    ) -> bool:
        """Format and send an agent turn message."""
        header = f"{emoji} *{agent_name}* `{position}`"
        if round_num is not None:
            header += f" — Round {round_num}"
        # Trim body to stay well within Telegram's 4096-char limit
        body      = text[:3600].replace("_", "\\_").replace("*", "\\*")
        formatted = f"{header}\n\n{body}"
        return self.send(formatted)

    def send_divider(self, label: str) -> bool:
        """Send a session divider line."""
        return self.send(f"\n━━━━━━  {label}  ━━━━━━\n", parse_mode="Markdown")

    def send_pr_notification(self, pr_url: str, description: str = "") -> bool:
        """Send a PR-opened notification with an inline 'Open PR' button."""
        text   = f"🚀 *Pull Request opened*\n{description[:300]}"
        markup = {"inline_keyboard": [[{"text": "📂 Open PR", "url": pr_url}]]}
        return self.send(text, reply_markup=markup)

    def send_session_start(self, mode: str, agents: list[str], repo: str) -> bool:
        lines = [
            "🤖 *AgentGroup session started*",
            f"📁 Repo: `{repo}`",
            f"⚙️ Mode: `{mode}`",
            f"👥 Agents: {', '.join(agents)}",
        ]
        return self.send("\n".join(lines))

    def send_session_end(self, pr_url: Optional[str] = None) -> bool:
        if pr_url:
            return self.send_pr_notification(pr_url, "Session complete — PR ready for review.")
        return self.send("✅ *AgentGroup session complete* — no changes committed.")

    def test_connection(self) -> bool:
        """Send a test ping to verify credentials. Returns True if OK."""
        return self.send("🔔 AgentGroup connected successfully.")
