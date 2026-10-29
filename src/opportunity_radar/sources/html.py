"""HTML adapter with bounded same-scope link crawling (LLD §7.4, §7.5)."""

from __future__ import annotations

import logging
from collections import deque

import trafilatura
from bs4 import BeautifulSoup

from opportunity_radar.errors import FetchError, RadarError, SourcePolicyDenied
from opportunity_radar.sources.base import FetchContext, FetchFailure, PageObservation, SourceRecord
from opportunity_radar.sources.common import build_observation, decode_body
from opportunity_radar.sources.fetch import FetchResponse
from opportunity_radar.sources.urls import canonicalize_url

log = logging.getLogger(__name__)
MAX_LINKS_PER_PAGE = 300
_MIN_TRAFILATURA_CHARS = 200


def parse_html(html: str, base_url: str) -> tuple[str | None, str, list[str], dict[str, str]]:
    """Return (title, readable text, canonical absolute links, meta)."""
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else None
    meta: dict[str, str] = {}
    desc = soup.find("meta", attrs={"name": "description"})
    if desc and desc.get("content"):
        meta["description"] = str(desc["content"]).strip()
    canon = soup.find("link", rel="canonical")
    if canon and canon.get("href"):
        meta["canonical_link"] = str(canon["href"])

    links: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        try:
            url = canonicalize_url(href, base=base_url)
        except RadarError:
            continue
        if url not in seen:
            seen.add(url)
            links.append(url)
        if len(links) >= MAX_LINKS_PER_PAGE:
            break

    text = trafilatura.extract(html, include_comments=False, favor_recall=True) or ""
    if len(text) < _MIN_TRAFILATURA_CHARS:  # trafilatura can drop sparse index pages
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        fallback = "\n".join(s.strip() for s in soup.get_text("\n").splitlines() if s.strip())
        text = fallback if len(fallback) > len(text) else text
    return title, text, links, meta


def _int(value: object, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


class HtmlAdapter:
    adapter_type = "html"

    def _observe(
        self, source: SourceRecord, resp: FetchResponse, ctx: FetchContext, depth: int
    ) -> PageObservation:
        if resp.not_modified:
            return build_observation(source, resp, ctx, depth=depth)
        title, text, links, meta = parse_html(
            decode_body(resp.body, resp.mime_type), resp.final_url
        )
        return build_observation(source, resp, ctx, title=title, text=text, links=links,
                                 meta=meta, depth=depth)  # fmt: skip

    def fetch(self, source: SourceRecord, ctx: FetchContext) -> list[PageObservation]:
        resp = ctx.fetcher.fetch(source.canonical_url, source.scope, etag=source.etag,
                                 last_modified=source.last_modified)  # fmt: skip
        seed = self._observe(source, resp, ctx, 0)
        policy = source.discovery_policy
        if seed.not_modified or not policy.get("follow_internal_links"):
            return [seed]
        # An unchanged index page (304) is not re-crawled; changed child pages behind an
        # unchanged index are picked up when the index itself changes or on source reset.
        max_depth = min(_int(policy.get("max_depth"), 1), ctx.settings.max_crawl_depth)
        max_pages = min(
            _int(policy.get("max_pages_per_run"), 20), ctx.settings.max_pages_per_source_run
        )
        scope = source.scope
        out = [seed]
        visited = {seed.requested_url, seed.final_url}
        queue = deque((link, 1) for link in seed.links)
        while queue and len(out) < max_pages:
            url, depth = queue.popleft()
            if url in visited or depth > max_depth or not scope.link_in_scope(url):
                continue
            visited.add(url)
            etag, lm = ctx.validators(url)
            try:
                child = ctx.fetcher.fetch(url, scope, etag=etag, last_modified=lm)
                if child.not_modified:
                    continue
                obs = self._observe(source, child, ctx, depth)
            except SourcePolicyDenied as e:
                ctx.failures.append(FetchFailure(url, e.code, str(e)))
                continue
            except (FetchError, RadarError) as e:
                ctx.failures.append(
                    FetchFailure(url, e.code, str(e), getattr(e, "http_status", None))
                )
                continue
            visited.add(obs.final_url)
            out.append(obs)
            queue.extend((link, depth + 1) for link in obs.links)
        return out
