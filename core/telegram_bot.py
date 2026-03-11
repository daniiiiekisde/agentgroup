"""Telegram relay – forwards agent messages to a Telegram chat."""
from __future__ import annotations
import requests


class TelegramRelay:
    """Sends messages to a Telegram bot chat.

    Args:
        token:   Bot token from @BotFather  (e.g. '123456:ABC-...')
        chat_id: Target chat/group/channel ID (e.g. '-1001234567890')
    """

    API = "https://api.telegram.org"

    def __init__(self, token: str, chat_id: str):
        self.token   = token.strip()
        self.chat_id = chat_id.strip()
        self._ok     = bool(self.token and self.chat_id)

    def send(self, text: str) -> bool:
        """Send *text* to the configured chat. Returns True on success."""
        if not self._ok:
            return False
        url  = f"{self.API}/bot{self.token}/sendMessage"
        data = {
            "chat_id":    self.chat_id,
            "text":       text[:4096],   # Telegram limit
            "parse_mode": "Markdown",
        }
        try:
            r = requests.post(url, json=data, timeout=10)
            return r.status_code == 200
        except Exception:
            return False

    def send_agent_message(self, agent_name: str, position: str, emoji: str, text: str) -> bool:
        formatted = f"{emoji} *{agent_name}* `{position}`\n{text[:3800]}"
        return self.send(formatted)
