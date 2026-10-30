"""HTML adapter with bounded same-scope link crawling (LLD §7.4, §7.5)."""

from __future__ import annotations

import logging
from collections import deque

import trafilatura
from bs4 import BeautifulSoup

from open_hypergamy.errors import FetchError, HostCoolingDown, OhgError, SourcePolicyDenied
from open_hypergamy.extraction.selectors import apply_selectors, parse_hints
from open_hypergamy.sources.base import FetchContext, FetchFailure, PageObservation, SourceRecord
from open_hypergamy.sources.common import build_observation, decode_body
from open_hypergamy.sources.fetch import FetchResponse
from open_hypergamy.sources.pages import PageUpdate, TrackedPage, UpdateKind
from open_hypergamy.sources.urls import canonicalize_url

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
        except OhgError:
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


def _canonical_links(hrefs: list[str], base_url: str) -> list[str]:
    out: list[str] = []
    for href in hrefs:
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        try:
            url = canonicalize_url(href.strip(), base=base_url)
        except OhgError:
            continue
        if url not in out:
            out.append(url)
    return out


def _int(value: object, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


class HtmlAdapter:
    adapter_type = "html"

    def _observe(
        self, source: SourceRecord, resp: FetchResponse, ctx: FetchContext, depth: int
    ) -> PageObservation:
        if resp.not_modified:
            return build_observation(source, resp, ctx, depth=depth)
        html = decode_body(resp.body, resp.mime_type)
        title, text, links, meta = parse_html(html, resp.final_url)
        hints = parse_hints(source.extraction_hints)
        if hints is not None:  # per-source CSS/XPath override (ADR-010); a miss raises ParseError
            sel = apply_selectors(
                html,
                url=resp.final_url,
                hints=hints,
                source_key=source.source_key or source.id,
                storage_file=ctx.selector_storage,
            )
            title = sel.title or title
            text = sel.text or text
            if sel.link_hrefs is not None:
                links = _canonical_links(sel.link_hrefs, resp.final_url)
            meta["selectors"] = "relocated:" + ",".join(sel.relocated) if sel.relocated else "ok"
        return build_observation(
            source, resp, ctx, title=title, text=text, links=links, meta=meta, depth=depth
        )

    def fetch(self, source: SourceRecord, ctx: FetchContext) -> list[PageObservation]:
        resp = ctx.fetcher.fetch(
            source.canonical_url, source.scope, etag=source.etag, last_modified=source.last_modified
        )
        seed = self._observe(source, resp, ctx, 0)
        policy = source.discovery_policy
        if not policy.get("follow_internal_links"):
            return [seed]
        max_depth = min(_int(policy.get("max_depth"), 1), ctx.settings.max_crawl_depth)
        max_pages = min(
            _int(policy.get("max_pages_per_run"), 20), ctx.settings.max_pages_per_source_run
        )
        scope = source.scope
        now = ctx.now()
        tracked = {p.url: p for p in ctx.tracked_pages()}
        out = [seed]
        requests = 1  # every request counts towards the page limit, including 304s and failures
        visited = {seed.requested_url, seed.final_url}
        queue: deque[tuple[str, int]] = deque()

        def enqueue_links(links: list[str], depth: int) -> None:
            if depth > max_depth:
                return
            for link in links:
                if scope.link_in_scope(link):
                    ctx.page_updates.append(PageUpdate(link, depth, "discovered"))
                    queue.append((link, depth))

        # An unchanged index (304) lists nothing new, but its known children still age on their
        # own clocks (ADR-011): everything that is due is revalidated below.
        if not seed.not_modified:
            enqueue_links(seed.links, 1)
        due = sorted((p for p in tracked.values() if p.is_due(now)), key=_oldest_first)
        queue.extend((p.url, p.depth) for p in due)
        while queue and requests < max_pages:
            url, depth = queue.popleft()
            if url in visited or depth > max_depth:
                continue
            visited.add(url)
            page = tracked.get(url)
            if not scope.link_in_scope(url):
                if page is not None and page.status != "invalid":  # scope was tightened
                    ctx.page_updates.append(
                        PageUpdate(url, depth, "invalid", error_code="out_of_scope",
                                   detail="outside the source's current scope")
                    )  # fmt: skip
                continue
            if page is not None and (
                page.status in ("held", "invalid")
                or (page.status == "active" and not page.is_due(now))
            ):
                continue  # held/invalid wait for an operator; fresh pages are not re-fetched
            etag, lm = (page.etag, page.last_modified) if page else (None, None)
            if not (etag or lm):
                etag, lm = ctx.validators(url)
            requests += 1
            try:
                child = ctx.fetcher.fetch(url, scope, etag=etag, last_modified=lm)
                if child.not_modified:
                    ctx.page_updates.append(
                        PageUpdate(url, depth, "not_modified", http_status=304,
                                   etag=child.etag, last_modified=child.last_modified)
                    )  # fmt: skip
                    continue
                obs = self._observe(source, child, ctx, depth)
            except HostCoolingDown as e:  # the host asked for quiet: stop, leave pages due
                ctx.failures.append(FetchFailure(url, e.code, str(e)))
                break
            except (FetchError, OhgError) as e:
                status = getattr(e, "http_status", None)
                ctx.failures.append(FetchFailure(url, e.code, str(e), status))
                kind: UpdateKind = "invalid" if isinstance(e, SourcePolicyDenied) else "failed"
                ctx.page_updates.append(
                    PageUpdate(
                        url, depth, kind, http_status=status, error_code=e.code,
                        retry_after_seconds=getattr(e, "retry_after", None), detail=str(e),
                    )
                )  # fmt: skip
                continue
            visited.add(obs.final_url)
            out.append(obs)
            ctx.page_updates.append(
                PageUpdate(url, depth, "fetched", http_status=obs.http_status, etag=obs.etag,
                           last_modified=obs.last_modified, content_hash=obs.content_sha256)
            )  # fmt: skip
            enqueue_links(obs.links, depth + 1)
        return out


def _oldest_first(page: TrackedPage) -> tuple[str, str]:
    return (page.last_checked_at or "", page.url)
