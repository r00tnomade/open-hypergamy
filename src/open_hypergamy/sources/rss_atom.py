"""RSS/Atom adapter. Feed dates are discovery hints, never evidence (LLD §7.4)."""

from __future__ import annotations

import feedparser

from open_hypergamy.errors import ParseError
from open_hypergamy.sources.base import FeedEntry, FetchContext, PageObservation, SourceRecord
from open_hypergamy.sources.common import build_observation
from open_hypergamy.sources.urls import canonicalize_url

MAX_ENTRIES = 200
FEED_TYPES = frozenset(
    {
        "application/rss+xml",
        "application/atom+xml",
        "application/xml",
        "text/xml",
        "application/rdf+xml",
        "text/plain",
    }
)


class RssAtomAdapter:
    adapter_type = "rss_atom"

    def fetch(self, source: SourceRecord, ctx: FetchContext) -> list[PageObservation]:
        resp = ctx.fetcher.fetch(
            source.canonical_url,
            source.scope,
            etag=source.etag,
            last_modified=source.last_modified,
            accept=FEED_TYPES,
        )
        if resp.not_modified:
            return [build_observation(source, resp, ctx)]
        parsed = feedparser.parse(resp.body)
        if not parsed.get("version"):  # feedparser sets no version when the body isn't a feed
            raise ParseError(f"not a parseable feed: {parsed.get('bozo_exception', 'no entries')}")
        entries: list[FeedEntry] = []
        for e in parsed.entries[:MAX_ENTRIES]:
            link = None
            if e.get("link"):
                try:
                    link = canonicalize_url(e["link"], base=resp.final_url)
                except Exception:  # noqa: BLE001 - one bad link must not discard the entry
                    link = None
            entries.append(
                FeedEntry(
                    entry_id=e.get("id"),
                    title=e.get("title", ""),
                    link=link,
                    published=e.get("published") or e.get("updated"),
                    summary=e.get("summary", ""),
                )
            )
        text = "\n\n".join(
            f"{x.title}\n{x.link or ''}\n{x.published or ''}\n{x.summary}".strip() for x in entries
        )
        return [
            build_observation(
                source,
                resp,
                ctx,
                title=parsed.feed.get("title"),
                text=text,
                links=[x.link for x in entries if x.link],
                entries=entries,
                suffix="xml",
            )
        ]
