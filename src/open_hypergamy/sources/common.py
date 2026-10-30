"""Helpers shared by adapters."""

from __future__ import annotations

import hashlib

from bs4 import UnicodeDammit

from open_hypergamy.sources.base import (
    FeedEntry,
    FetchContext,
    PageObservation,
    SourceRecord,
)
from open_hypergamy.sources.fetch import FetchResponse


def decode_body(body: bytes, content_type: str | None = None) -> str:
    return str(
        UnicodeDammit(body, is_html=bool(content_type and "html" in content_type)).unicode_markup
    )


def build_observation(
    source: SourceRecord | None,
    resp: FetchResponse,
    ctx: FetchContext,
    *,
    title: str | None = None,
    text: str = "",
    links: list[str] | None = None,
    entries: list[FeedEntry] | None = None,
    meta: dict[str, str] | None = None,
    depth: int = 0,
    suffix: str = "html",
) -> PageObservation:
    body_rel = text_rel = None
    if resp.not_modified:
        content_sha = (source.last_content_hash if source else None) or ""
    elif ctx.cache is not None:
        body_rel, content_sha = ctx.cache.store(resp.body, suffix)
        if text:
            text_rel, _ = ctx.cache.store(text.encode(), "txt")
    else:
        content_sha = hashlib.sha256(resp.body).hexdigest()
    return PageObservation(
        source_id=source.id if source else None,
        requested_url=resp.requested_url,
        final_url=resp.final_url,
        fetched_at=resp.fetched_at,
        http_status=resp.status,
        mime_type=resp.mime_type,
        title=title,
        text=text,
        links=links or [],
        entries=entries or [],
        meta=meta or {},
        etag=resp.etag,
        last_modified=resp.last_modified,
        content_sha256=content_sha,
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        not_modified=resp.not_modified,
        body_cache_relpath=body_rel,
        text_cache_relpath=text_rel,
        depth=depth,
        elapsed_ms=resp.elapsed_ms,
        retry_count=resp.retry_count,
        bytes_received=len(resp.body),
    )
