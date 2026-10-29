"""Logging with secret redaction (LLD §16, §17)."""

from __future__ import annotations

import logging
import re
import sys

from opportunity_radar.keychain import get_secret

_TELEGRAM_TOKEN = re.compile(r"(bot)?\d{6,}:[A-Za-z0-9_-]{20,}")
_SECRET_ENV = ("TELEGRAM_BOT_TOKEN", "RADAR_FREELLMAPI_API_KEY")


def redact(text: str) -> str:
    text = _TELEGRAM_TOKEN.sub("[REDACTED]", text)
    for var in _SECRET_ENV:
        secret = get_secret(var)
        if secret and len(secret) >= 8:
            text = text.replace(secret, "[REDACTED]")
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        return True


class _StderrHandler(logging.StreamHandler):  # type: ignore[type-arg,unused-ignore]
    """Writes to the *current* sys.stderr (stdout is reserved for --json output) and never lets
    a closed or redirected stream turn a log line into an error."""

    def __init__(self) -> None:
        super().__init__()

    @property  # type: ignore[override,unused-ignore]
    def stream(self):  # type: ignore[no-untyped-def]
        return sys.stderr

    @stream.setter
    def stream(self, _value) -> None:  # type: ignore[no-untyped-def]
        pass

    def handleError(self, record: logging.LogRecord) -> None:
        pass


def setup_logging(level: str = "INFO") -> None:
    handler = _StderrHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # httpx logs every request URL at INFO (query strings can carry secrets); keep it quiet.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
