"""Logging with secret redaction (LLD §16, §17)."""

from __future__ import annotations

import logging
import os
import re

_TELEGRAM_TOKEN = re.compile(r"(bot)?\d{6,}:[A-Za-z0-9_-]{20,}")
_SECRET_ENV = ("TELEGRAM_BOT_TOKEN", "RADAR_FREELLMAPI_API_KEY")


def redact(text: str) -> str:
    text = _TELEGRAM_TOKEN.sub("[REDACTED]", text)
    for var in _SECRET_ENV:
        secret = os.environ.get(var)
        if secret and len(secret) >= 8:
            text = text.replace(secret, "[REDACTED]")
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        return True


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()  # stderr: stdout is reserved for --json output
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
