"""Sitemap adapter. `lastmod` only prioritizes fetches; it is not evidence of changed facts."""

from __future__ import annotations

import logging

from defusedxml import ElementTree as ET

from open_hypergamy.errors import FetchError, ParseError, SourcePolicyDenied
from open_hypergamy.sources.base import (
    FeedEntry,
    FetchContext,
    FetchFailure,
    PageObservation,
    SourceRecord,
)
from open_hypergamy.sources.common import build_observation
from open_hypergamy.sources.urls import canonicalize_url

log = logging.getLogger(__name__)
MAX_URLS = 1000
MAX_CHILD_SITEMAPS = 5
SITEMAP_TYPES = frozenset({"application/xml", "text/xml", "text/plain"})


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_sitemap(body: bytes) -> tuple[str, list[tuple[str, str | None]]]:
    """Return ("urlset"|"sitemapindex", [(loc, lastmod)]). Uses defusedxml (no entity attacks)."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        raise ParseError(f"invalid sitemap XML: {e}") from e
    kind = _local(root.tag)
    if kind not in ("urlset", "sitemapindex"):
        raise ParseError(f"unexpected sitemap root element: {kind}")
    items: list[tuple[str, str | None]] = []
    for child in root:
        loc = lastmod = None
        for f in child:
            if _local(f.tag) == "loc" and f.text:
                loc = f.text.strip()
            elif _local(f.tag) == "lastmod" and f.text:
                lastmod = f.text.strip()
        if loc:
            items.append((loc, lastmod))
    return kind, items


class SitemapAdapter:
    adapter_type = "sitemap"

    def fetch(self, source: SourceRecord, ctx: FetchContext) -> list[PageObservation]:
        resp = ctx.fetcher.fetch(
            source.canonical_url,
            source.scope,
            etag=source.etag,
            last_modified=source.last_modified,
            accept=SITEMAP_TYPES,
        )
        if resp.not_modified:
            return [build_observation(source, resp, ctx)]
        kind, items = parse_sitemap(resp.body)
        if kind == "sitemapindex":
            urls: list[tuple[str, str | None]] = []
            for loc, _ in items[:MAX_CHILD_SITEMAPS]:
                try:
                    child = ctx.fetcher.fetch(
                        canonicalize_url(loc, resp.final_url), source.scope, accept=SITEMAP_TYPES
                    )
                    ckind, citems = parse_sitemap(child.body)
                    if ckind == "urlset":
                        urls += citems
                except (FetchError, SourcePolicyDenied, ParseError) as e:
                    ctx.failures.append(
                        FetchFailure(loc, e.code, str(e), getattr(e, "http_status", None))
                    )
        else:
            urls = items
        scope = source.scope
        entries: list[FeedEntry] = []
        for loc, lastmod in urls:
            try:
                url = canonicalize_url(loc, resp.final_url)
            except Exception:  # noqa: BLE001
                continue
            if scope.link_in_scope(url):
                entries.append(FeedEntry(link=url, published=lastmod))
        entries.sort(key=lambda e: e.published or "", reverse=True)
        entries = entries[:MAX_URLS]
        return [
            build_observation(
                source,
                resp,
                ctx,
                links=[e.link for e in entries if e.link],
                entries=entries,
                meta={"sitemap_urls": str(len(entries))},
                suffix="xml",
            )
        ]
