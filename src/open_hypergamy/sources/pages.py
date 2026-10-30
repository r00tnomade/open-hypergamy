"""Per-URL state for child pages behind a source index (ADR-011).

Pure functions only. Adapters report what happened as `PageUpdate`s; `SourceRepository` applies
`plan_page` inside the check's transaction. Nothing here deletes a page or an observation: a
child that disappears becomes `missing`, one that refuses us becomes `held`, and the
opportunities discovered from it stay exactly as they were (they age into `stale` through the
normal freshness rules).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal

from open_hypergamy.clock import iso_z
from open_hypergamy.domain.enums import ErrorCategory
from open_hypergamy.sources.health import HealthPolicy, categorize

PageState = Literal["active", "missing", "held", "invalid"]
UpdateKind = Literal["discovered", "fetched", "not_modified", "failed", "invalid"]


@dataclass(frozen=True)
class TrackedPage:
    source_id: str
    url: str
    depth: int
    status: PageState
    status_reason: str | None
    first_seen_at: str
    last_listed_at: str | None
    last_attempt_at: str | None
    last_checked_at: str | None
    last_changed_at: str | None
    next_check_at: str
    consecutive_failures: int
    last_http_status: int | None
    last_error_code: str | None
    etag: str | None
    last_modified: str | None
    content_hash: str | None

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> TrackedPage:
        return cls(
            source_id=r["source_id"],
            url=r["canonical_url"],
            depth=r["depth"],
            status=r["status"],
            status_reason=r["status_reason"],
            first_seen_at=r["first_seen_at"],
            last_listed_at=r["last_listed_at"],
            last_attempt_at=r["last_attempt_at"],
            last_checked_at=r["last_checked_at"],
            last_changed_at=r["last_changed_at"],
            next_check_at=r["next_check_at"],
            consecutive_failures=r["consecutive_failures"],
            last_http_status=r["last_http_status"],
            last_error_code=r["last_error_code"],
            etag=r["etag"],
            last_modified=r["last_modified"],
            content_hash=r["content_hash"],
        )

    def is_due(self, now: datetime) -> bool:
        return self.status == "active" and self.next_check_at <= iso_z(now)


@dataclass(frozen=True)
class PageUpdate:
    """What an adapter observed about one child URL during a run."""

    url: str
    depth: int
    kind: UpdateKind
    http_status: int | None = None
    etag: str | None = None
    last_modified: str | None = None
    content_hash: str | None = None
    error_code: str | None = None
    retry_after_seconds: float | None = None
    detail: str | None = None


def plan_page(
    prev: TrackedPage | None,
    u: PageUpdate,
    *,
    source_id: str,
    now: datetime,
    interval: timedelta,
    policy: HealthPolicy,
) -> TrackedPage:
    """The page row after applying `u`. `interval` is the child's own freshness window."""
    stamp = iso_z(now)
    page = prev or TrackedPage(
        source_id, u.url, u.depth, "active", None, stamp, None, None, None, None,
        stamp, 0, None, None, None, None, None,
    )  # fmt: skip
    page = replace(page, depth=min(page.depth, u.depth))
    if u.kind == "discovered":
        page = replace(page, last_listed_at=stamp)
        if page.status == "missing":  # the index lists it again: give it another chance
            page = replace(
                page,
                status="active",
                status_reason=None,
                consecutive_failures=0,
                next_check_at=stamp,
            )
        return page
    page = replace(page, last_attempt_at=stamp, last_http_status=u.http_status)
    if u.kind == "invalid":
        return replace(
            page,
            status="invalid",
            status_reason=(u.detail or u.error_code or "invalid")[:200],
            last_error_code=u.error_code,
            next_check_at=iso_z(now + interval),
        )
    if u.kind in ("fetched", "not_modified"):
        if u.kind == "fetched":
            changed = u.content_hash != page.content_hash
            etag, last_modified, content_hash = u.etag, u.last_modified, u.content_hash
        else:  # a 304 may omit validators; keep the ones we sent
            changed = False
            etag = u.etag or page.etag
            last_modified = u.last_modified or page.last_modified
            content_hash = page.content_hash
        return replace(
            page,
            status="active",
            status_reason=None,
            last_checked_at=stamp,
            last_changed_at=stamp if changed or not page.last_changed_at else page.last_changed_at,
            next_check_at=iso_z(now + interval),
            consecutive_failures=0,
            last_error_code=None,
            etag=etag,
            last_modified=last_modified,
            content_hash=content_hash,
        )
    # failed: a failure never clears validators, hashes or the previous successful check
    failures = page.consecutive_failures + 1
    category = categorize("failed", u.error_code, u.http_status)
    page = replace(page, consecutive_failures=failures, last_error_code=u.error_code)
    reason = f"{category}: {u.detail}"[:200] if u.detail else str(category)
    if category is ErrorCategory.GONE or (
        category is ErrorCategory.NOT_FOUND and failures >= policy.not_found_review_after
    ):
        return replace(
            page, status="missing", status_reason=reason, next_check_at=iso_z(now + interval)
        )
    if category in (
        ErrorCategory.ACCESS_DENIED,
        ErrorCategory.ACCESS_BARRIER,
        ErrorCategory.RENDERING_REQUIRED,
    ):
        return replace(
            page, status="held", status_reason=reason, next_check_at=iso_z(now + interval)
        )
    backoff = timedelta(hours=min(2 ** (failures - 1), max(1, interval.total_seconds() // 3600)))
    if u.retry_after_seconds is not None:
        backoff = max(backoff, timedelta(seconds=u.retry_after_seconds))
    backoff = min(backoff, timedelta(hours=policy.max_cooldown_hours))
    return replace(page, next_check_at=iso_z(now + backoff))
