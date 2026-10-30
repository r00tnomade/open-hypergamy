"""Extract opportunity leads from a user-provided newsletter (.eml, .html or text) (ADR-013).

The user supplies the message; nothing is fetched here. Leads are links with their anchor text.
Downstream they enter the pipeline as manual leads (`candidates add` semantics): never
auto-verified, SSRF-checked, and deduplicated against everything already known.
"""

from __future__ import annotations

import email
import email.policy
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

from open_hypergamy.discovery.normalize import OPPORTUNITY_RE
from open_hypergamy.sources.urls import canonicalize_url

MAX_LEADS = 50
_URL = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
_UNSUBSCRIBE = re.compile(
    r"unsubscribe|manage[-_ ]preferences|view[-_ ]in[-_ ]browser|optout|mailto", re.I
)


@dataclass(frozen=True)
class Lead:
    url: str
    text: str


def _message_parts(raw: bytes) -> tuple[str, str]:
    """(html, plain) of an RFC 5322 message, or the raw text when it is not one."""
    head = raw[:2000].lower()
    if not (b"\nsubject:" in b"\n" + head or b"\nfrom:" in b"\n" + head or b"mime-version" in head):
        return "", raw.decode("utf-8", "replace")
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    html = plain = ""
    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        try:
            body = part.get_content()
        except (LookupError, UnicodeError):
            continue
        if ctype == "text/html" and isinstance(body, str):
            html += body
        elif ctype == "text/plain" and isinstance(body, str):
            plain += body
    return html, plain


def extract_leads(raw: bytes) -> list[Lead]:
    html, plain = _message_parts(raw)
    if not html and "<a " in plain.lower():
        html, plain = plain, ""
    leads: dict[str, str] = {}

    def add(href: str, text: str) -> None:
        if _UNSUBSCRIBE.search(href) or len(leads) >= MAX_LEADS:
            return
        try:
            url = canonicalize_url(href)
        except Exception:  # noqa: BLE001 - unusable URLs are simply not leads
            return
        label = " ".join(text.split())
        # Keep only links that look like opportunities, by anchor text or by URL.
        if OPPORTUNITY_RE.search(label) or OPPORTUNITY_RE.search(url):
            leads.setdefault(url, label)

    if html:
        for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
            add(str(a["href"]), a.get_text(" ", strip=True))
    for m in _URL.finditer(plain):
        # Plain text: the surrounding line is the best available label.
        line_start = plain.rfind("\n", 0, m.start()) + 1
        line = plain[line_start : plain.find("\n", m.end()) if "\n" in plain[m.end() :] else None]
        add(m.group(0).rstrip(".,;"), line)
    return [Lead(u, t) for u, t in leads.items()]
