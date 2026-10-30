"""Detect access barriers served with HTTP 200: challenges, CAPTCHAs, logins, WAF denials.

Detection only (ADR-009): a hit stops the fetch and holds the source for manual review. Nothing
here tries to solve, evade or route around a barrier. Heuristics are deliberately conservative
because official pages legitimately mention "login" or embed a CAPTCHA in a contact form: a
generic word alone never triggers, only vendor challenge markers or a page whose *title* is the
barrier.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

_SCAN_BYTES = 64 * 1024
_HTML_TYPES = ("text/html", "application/xhtml+xml")

# Markers that only appear on interstitial challenge / block pages. Vendor scripts injected into
# *normal* pages (Cloudflare's /cdn-cgi/challenge-platform/ beacon, Imperva's _Incapsula_Resource)
# are intentionally absent: they would flag ordinary protected sites.
_CHALLENGE_MARKERS = (
    "cf-browser-verification",
    "cf_chl_opt",
    "captcha-delivery.com",  # DataDome block page
    "px-captcha",  # PerimeterX block page
    "sucuri website firewall - access denied",
)
_TITLE = re.compile(rb"<title[^>]*>(.*?)</title>", re.I | re.S)
_CHALLENGE_TITLES = re.compile(
    r"^(just a moment|attention required|please wait|checking your browser|"
    r"verify(ing)? you are (a )?human|are you a robot|security check|captcha|"
    r"ddos protection|one more step)\b",
    re.I,
)
_DENIED_TITLES = re.compile(
    r"^(access denied|403 forbidden|forbidden|request rejected|unauthori[sz]ed|"
    r"you have been blocked|web page blocked|error 1020)\b",
    re.I,
)
_LOGIN_TITLES = re.compile(r"\b(log ?in|sign ?in|single sign-on|authentication required)\b", re.I)
_PASSWORD_INPUT = re.compile(rb"<input[^>]+type=[\"']?password", re.I)
_LOGIN_PATHS = re.compile(
    r"/(login|log-in|signin|sign-in|sso|cas/login|oauth2?/authorize|auth/realms|adfs/ls|"
    r"idp/profile|saml2?|shibboleth\.sso)(/|$|\?)",
    re.I,
)


def _title(head: bytes) -> str:
    m = _TITLE.search(head)
    if not m:
        return ""
    return " ".join(m[1].decode("utf-8", "replace").split())


def detect_barrier(requested_url: str, final_url: str, mime: str | None, body: bytes) -> str | None:
    """Return a short reason if this 200 response is an access barrier, else None."""
    if _LOGIN_PATHS.search(urlsplit(final_url).path) and not _LOGIN_PATHS.search(
        urlsplit(requested_url).path
    ):
        return f"redirected to a login page ({urlsplit(final_url).path})"
    looks_html = (mime or "") in _HTML_TYPES or body.lstrip()[:15].lower().startswith(
        (b"<!doctype html", b"<html")
    )
    if not looks_html:
        return None
    head = body[:_SCAN_BYTES]
    lowered = head.lower().decode("utf-8", "replace")
    title = _title(head)
    for marker in _CHALLENGE_MARKERS:
        if marker in lowered:
            return f"bot-management challenge page ({marker})"
    if _CHALLENGE_TITLES.search(title):
        return f"challenge page (title: {title[:60]!r})"
    if _DENIED_TITLES.search(title):
        return f"access-denied page (title: {title[:60]!r})"
    if _PASSWORD_INPUT.search(head) and _LOGIN_TITLES.search(title):
        return f"login page (title: {title[:60]!r})"
    return None


_MOUNT_IDS = ("root", "app", "__next", "__nuxt", "svelte", "q-app")
_SHELL_TEXT_CHARS = 150


def detect_js_shell(mime: str | None, body: bytes) -> str | None:
    """Return a reason if this 200 HTML page is an empty application shell (content needs JS).

    Detection only: nothing here executes scripts. Deliberately conservative: a page is a shell
    only when it has almost no visible text, loads scripts, AND either asks for JavaScript in a
    <noscript> block or contains an empty framework mount point. Ordinary pages with scripts
    and real text are never flagged.
    """
    if (mime or "") not in _HTML_TYPES:
        return None
    soup = BeautifulSoup(body[: 256 * 1024], "html.parser")
    scripts = soup.find_all("script")
    if not scripts:
        return None
    noscript_says_js = any(
        "javascript" in n.get_text(" ", strip=True).lower() for n in soup.find_all("noscript")
    )
    empty_mount = any(
        (el := soup.find(id=mid)) is not None and not el.get_text(strip=True) and not el.find("a")
        for mid in _MOUNT_IDS
    )
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    visible = " ".join(soup.get_text(" ", strip=True).split())
    if len(visible) >= _SHELL_TEXT_CHARS or not (noscript_says_js or empty_mount):
        return None
    return (
        f"JavaScript application shell ({len(visible)} visible characters, {len(scripts)} scripts)"
    )
