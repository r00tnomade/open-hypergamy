"""Telegram Bot API sink (LLD §13). Plain-text, outbound-only; the token never leaves env/args."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from open_hypergamy.errors import ConfigurationError
from open_hypergamy.keychain import get_secret
from open_hypergamy.notifications.base import NotificationMessage, SendResult

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
        self._http = httpx.Client(
            transport=transport, timeout=timeout, follow_redirects=False, trust_env=False
        )

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


# --- setup checks (onboarding GUI, ADR-014). Neither function sends a message. -----------------

TOKEN_SHAPE = r"^\d{5,12}:[A-Za-z0-9_-]{30,64}$"


@dataclass(frozen=True)
class BotCheck:
    ok: bool
    username: str | None = None
    error: str | None = None
    rejected: bool = False  # Telegram says the token is invalid (vs. unreachable)


@dataclass(frozen=True)
class ChatRef:
    chat_id: str
    label: str
    kind: str


def _setup_client(transport: httpx.BaseTransport | None, timeout: float) -> httpx.Client:
    return httpx.Client(
        transport=transport, timeout=timeout, follow_redirects=False, trust_env=False
    )


def _scrub(token: str, text: str) -> str:
    return text.replace(token, "[REDACTED]")[:300] if token else text[:300]


def check_bot(
    token: str, *, transport: httpx.BaseTransport | None = None, timeout: float = 10.0
) -> BotCheck:
    """`getMe`: proves the token works without contacting any chat."""
    with _setup_client(transport, timeout) as http:
        try:
            r = http.get(f"{API}/bot{token}/getMe")
        except httpx.TimeoutException:
            return BotCheck(False, error="Telegram did not answer in time")
        except httpx.HTTPError as e:
            return BotCheck(False, error=f"could not reach Telegram ({type(e).__name__})")
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code == 200 and data.get("ok"):
        return BotCheck(True, username=str(data.get("result", {}).get("username") or "") or None)
    desc = _scrub(token, str(data.get("description", r.reason_phrase or "")))
    return BotCheck(
        False, error=f"HTTP {r.status_code}: {desc}", rejected=r.status_code in (401, 404)
    )


def recent_chats(
    token: str, *, transport: httpx.BaseTransport | None = None, timeout: float = 10.0
) -> list[ChatRef]:
    """Chats that recently messaged the bot (`getUpdates`), newest first, deduplicated."""
    with _setup_client(transport, timeout) as http:
        try:
            r = http.get(f"{API}/bot{token}/getUpdates", params={"limit": 50, "timeout": 0})
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise ConfigurationError(f"could not read bot updates ({type(e).__name__})") from None
    if not (r.status_code == 200 and data.get("ok")):
        raise ConfigurationError(
            f"Telegram refused getUpdates: {_scrub(token, str(data.get('description', '')))}"
        )
    seen: dict[str, ChatRef] = {}
    for upd in reversed(data.get("result", [])):
        msg = upd.get("message") or upd.get("channel_post") or upd.get("my_chat_member") or {}
        chat = msg.get("chat") if isinstance(msg, dict) else None
        if not isinstance(chat, dict) or "id" not in chat:
            continue
        cid = str(chat["id"])
        name = chat.get("title") or " ".join(
            x for x in (chat.get("first_name"), chat.get("last_name")) if x
        )
        if chat.get("username"):
            name = f"{name} (@{chat['username']})".strip()
        seen.setdefault(cid, ChatRef(cid, name or "unnamed chat", str(chat.get("type", "?"))))
    return list(seen.values())
