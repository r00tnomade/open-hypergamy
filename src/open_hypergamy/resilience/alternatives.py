"""Alternative official channels for a source that became unavailable (ADR-013).

Offline by construction: it reads only what is already stored (registry rows and the cached
body of the source's last successful observation). It suggests; it never registers, enables or
fetches anything. Every suggestion still needs a terms review and `ohg sources` import.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from open_hypergamy.discovery.normalize import registrable_domain
from open_hypergamy.sources.base import SourceRecord
from open_hypergamy.sources.urls import canonicalize_url

_FEED_TYPES = {
    "application/rss+xml": "rss_atom",
    "application/atom+xml": "rss_atom",
    "application/feed+json": "json_feed",
    "application/json": "json_feed",
    "text/calendar": "ical",
}
_HREF_HINT = re.compile(
    r"\.(ics|rss|atom)(\?|$)|/(feed|rss|atom|calendar|events\.ics)/?(\?|$)", re.I
)


@dataclass(frozen=True)
class Alternative:
    kind: str  # declared_feed | linked_channel | registered_sibling
    adapter_type: str
    url: str
    origin: str
    note: str = "unverified suggestion: review terms, then add it to a sources YAML batch"


def _same_site(url: str, domain: str) -> bool:
    host = urlsplit(url).hostname or ""
    return registrable_domain(host) == registrable_domain(domain)


def _guess_adapter(url: str) -> str:
    low = url.lower()
    if ".ics" in low or "calendar" in low:
        return "ical"
    if "json" in low:
        return "json_feed"
    return "rss_atom"


def from_cached_page(source: SourceRecord, html: str, base_url: str) -> list[Alternative]:
    """Channels the publisher itself advertises on a page we already hold."""
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, Alternative] = {}
    for link in soup.find_all("link", href=True):
        rel = " ".join(link.get("rel") or []).lower()
        typ = str(link.get("type") or "").lower()
        if "alternate" in rel and typ in _FEED_TYPES:
            try:
                url = canonicalize_url(str(link["href"]), base=base_url)
            except Exception:  # noqa: BLE001
                continue
            if _same_site(url, source.domain):
                found.setdefault(
                    url,
                    Alternative(
                        "declared_feed", _FEED_TYPES[typ], url, "<link rel=alternate> on the page"
                    ),
                )
    for a in soup.find_all("a", href=True):
        href = str(a["href"])
        if not _HREF_HINT.search(href):
            continue
        try:
            url = canonicalize_url(href, base=base_url)
        except Exception:  # noqa: BLE001
            continue
        if _same_site(url, source.domain):
            found.setdefault(
                url, Alternative("linked_channel", _guess_adapter(url), url, "link on the page")
            )
    return list(found.values())


def siblings(conn: sqlite3.Connection, source: SourceRecord) -> list[Alternative]:
    """Other registered sources of the same organization or site with a different channel."""
    rows = conn.execute(
        "SELECT source_key, canonical_url, adapter_type, enabled, state, blocked_reason, "
        "organization_id FROM sources WHERE id != ? ORDER BY source_key",
        (source.id,),
    ).fetchall()
    out: list[Alternative] = []
    for r in rows:
        same_org = bool(source.organization_id and r["organization_id"] == source.organization_id)
        if not (same_org or _same_site(r["canonical_url"], source.domain)):
            continue
        status = (
            "held"
            if r["blocked_reason"]
            else "enabled"
            if r["enabled"] and r["state"] == "active"
            else "disabled"
        )
        out.append(
            Alternative(
                "registered_sibling",
                r["adapter_type"],
                r["canonical_url"],
                f"already registered as {r['source_key']} ({status})",
                note="registered: no action needed if enabled; otherwise review and enable",
            )
        )
    return out


def alternatives_for(
    conn: sqlite3.Connection, source: SourceRecord, cache_root: Path
) -> list[Alternative]:
    out = siblings(conn, source)
    row = conn.execute(
        "SELECT body_cache_relpath, canonical_url FROM source_observations "
        "WHERE source_id=? AND body_cache_relpath IS NOT NULL AND http_status=200 "
        "ORDER BY retrieved_at DESC LIMIT 1",
        (source.id,),
    ).fetchone()
    if row:
        path = cache_root / row["body_cache_relpath"]
        if path.is_file():
            html = path.read_bytes().decode("utf-8", "replace")
            known = {a.url for a in out}
            out += [
                a
                for a in from_cached_page(source, html, row["canonical_url"])
                if a.url not in known
            ]
    return out
