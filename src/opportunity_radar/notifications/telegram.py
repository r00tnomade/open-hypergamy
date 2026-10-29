"""Telegram Bot API sink (LLD §13). Plain-text, outbound-only; the token never leaves env/args."""

from __future__ import annotations

import httpx

from opportunity_radar.errors import ConfigurationError
from opportunity_radar.keychain import get_secret
from opportunity_radar.notifications.base import NotificationMessage, SendResult

API = "https://api.telegram.org"
MAX_LEN = 4096
_PERMANENT = {400, 401, 403, 404}


def split_message(text: str, limit: int = 3800) -> list[str]:
    """Split on paragraph/line boundaries so long digests stay readable."""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    cur = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if cur:
                parts.append(cur.rstrip())
                cur = ""
            parts.append(line[:limit])
            line = line[limit:]
        if len(cur) + len(line) + 1 > limit:
            parts.append(cur.rstrip())
            cur = ""
        cur += line + "\n"
    if cur.strip():
        parts.append(cur.rstrip())
    return parts


class TelegramSink:
    def __init__(
        self,
        token: str,
        chat_id: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 15.0,
    ) -> None:
        if not token or not chat_id:
            raise ConfigurationError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")
        self._token, self._chat = token, chat_id
        self._http = httpx.Client(transport=transport, timeout=timeout, follow_redirects=False)

    @classmethod
    def from_env(cls, *, transport: httpx.BaseTransport | None = None) -> TelegramSink:
        return cls(
            get_secret("TELEGRAM_BOT_TOKEN"),
            get_secret("TELEGRAM_CHAT_ID"),
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def _clean(self, text: str) -> str:
        return text.replace(self._token, "[REDACTED]")[:300]

    def send(self, message: NotificationMessage, idempotency_key: str) -> SendResult:
        _ = idempotency_key  # local dedupe only; Telegram offers no idempotency token
        body = {
            "chat_id": self._chat,
            "text": message.text[:MAX_LEN],
            "disable_web_page_preview": True,
        }
        try:
            r = self._http.post(f"{API}/bot{self._token}/sendMessage", json=body)
        except httpx.TimeoutException:
            return SendResult(False, error="timeout")
        except httpx.HTTPError as e:  # exception text can embed the URL (and so the token)
            return SendResult(False, error=f"network error ({type(e).__name__})")
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code == 200 and data.get("ok"):
            return SendResult(True, message_id=str(data.get("result", {}).get("message_id", "")))
        desc = self._clean(str(data.get("description", r.reason_phrase or "")))
        if r.status_code == 429:
            retry = data.get("parameters", {}).get("retry_after") or r.headers.get("retry-after")
            return SendResult(
                False, error=f"rate limited: {desc}", retry_after=float(retry) if retry else 30.0
            )
        if r.status_code in _PERMANENT:
            return SendResult(False, error=f"HTTP {r.status_code}: {desc}", permanent=True)
        return SendResult(False, error=f"HTTP {r.status_code}: {desc}")
