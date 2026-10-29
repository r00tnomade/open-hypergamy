"""Redaction applied to every excerpt before it can leave the machine (LLD §9.2).

Dates and ordinary prose are left intact so quote grounding still works; anything that looks
like contact data, a credential, a tracking parameter or a local path is replaced.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_RULES: list[tuple[str, re.Pattern[str], str]] = [
    ("email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[EMAIL]"),
    ("bearer", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"), "[REDACTED]"),
    (
        "secret_kv",
        re.compile(
            r"(?i)\b(?:api[_-]?key|access[_-]?token|token|secret|password|passwd|authorization)\b"
            r"\s*[:=]\s*\S+"
        ),
        "[REDACTED]",
    ),
    ("sk_key", re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"), "[REDACTED]"),
    ("telegram", re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b"), "[REDACTED]"),
    (
        "long_token",
        re.compile(r"\b(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{32,}\b"),
        "[TOKEN]",
    ),
    ("phone_intl", re.compile(r"(?<![\w/])(?:\+|00)\d[\d\s().-]{6,}\d"), "[PHONE]"),
    ("phone_paren", re.compile(r"\(\d{2,5}\)\s?\d[\d\s.-]{4,}\d"), "[PHONE]"),
    (
        "phone_label",
        re.compile(r"(?i)\b(?:tel|phone|fon|fax|mobile)\.?\s*:?\s*[\d\s()./+-]{7,}"),
        "[PHONE]",
    ),
    (
        "path",
        re.compile(r"(?:/Users|/home|/var/folders|/private)/[^\s\"']+|[A-Za-z]:\\Users\\[^\s\"']+"),
        "[PATH]",
    ),
    (
        "tracking",
        re.compile(r"(?i)([?&])(?:utm_[a-z]+|fbclid|gclid|msclkid|mc_[a-z]+|igshid)=[^&\s#]*"),
        r"\1",
    ),
]


@dataclass(frozen=True)
class Redacted:
    text: str
    counts: dict[str, int]


def redact(text: str) -> Redacted:
    counts: dict[str, int] = {}
    for name, pat, repl in _RULES:
        text, n = pat.subn(repl, text)
        if n:
            counts[name] = n
    text = text.replace("?&", "?").replace("&&", "&")
    text = re.sub(r"[?&]+(?=[\s)\]>,.]|$)", "", text)  # dangling separators after tracking removal
    return Redacted(text, counts)
