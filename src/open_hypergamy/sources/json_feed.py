"""JSON Feed adapter (https://www.jsonfeed.org/version/1.1/): an official machine-readable
channel. Like RSS/Atom, entry dates are discovery hints and never evidence (LLD §7.4)."""

from __future__ import annotations

import json
from typing import Any

from bs4 import BeautifulSoup

from open_hypergamy.errors import ParseError
from open_hypergamy.sources.base import FeedEntry, FetchContext, PageObservation, SourceRecord
from open_hypergamy.sources.common import build_observation, decode_body
from open_hypergamy.sources.urls import canonicalize_url

MAX_ITEMS = 200
JSON_FEED_TYPES = frozenset({"application/feed+json", "application/json", "text/plain"})


def _summary(item: dict[str, Any]) -> str:
    if isinstance(item.get("summary"), str):
        return str(item["summary"])
    if isinstance(item.get("content_text"), str):
        return str(item["content_text"])[:2000]
    if isinstance(item.get("content_html"), str):
        return BeautifulSoup(item["content_html"], "html.parser").get_text(" ", strip=True)[:2000]
    return ""


class JsonFeedAdapter:
    adapter_type = "json_feed"

    def fetch(self, source: SourceRecord, ctx: FetchContext) -> list[PageObservation]:
        resp = ctx.fetcher.fetch(
            source.canonical_url,
            source.scope,
            etag=source.etag,
            last_modified=source.last_modified,
            accept=JSON_FEED_TYPES,
        )
        if resp.not_modified:
            return [build_observation(source, resp, ctx)]
        try:
            doc = json.loads(decode_body(resp.body))
        except ValueError as e:
            raise ParseError(f"not valid JSON: {e}") from None
        version = doc.get("version") if isinstance(doc, dict) else None
        if not isinstance(version, str) or "jsonfeed.org/version/" not in version:
            raise ParseError("not a JSON Feed document")
        items = doc.get("items")
        entries: list[FeedEntry] = []
        for item in (items if isinstance(items, list) else [])[:MAX_ITEMS]:
            if not isinstance(item, dict):
                continue
            link = None
            raw = item.get("url") or item.get("external_url")
            if isinstance(raw, str):
                try:
                    link = canonicalize_url(raw, base=resp.final_url)
                except Exception:  # noqa: BLE001
                    link = None
            entries.append(
                FeedEntry(
                    entry_id=str(item["id"]) if item.get("id") is not None else None,
                    title=str(item.get("title") or ""),
                    link=link,
                    published=str(item.get("date_published") or item.get("date_modified") or "")
                    or None,
                    summary=_summary(item),
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
                title=str(doc.get("title") or source.name),
                text=text,
                links=[x.link for x in entries if x.link],
                entries=entries,
                suffix="json",
            )
        ]
