"""Shared value objects and the adapter protocol (LLD §5.1, §5.2)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, Field

from opportunity_radar.config import AppSettings
from opportunity_radar.sources.policy import Scope

if TYPE_CHECKING:
    from opportunity_radar.sources.fetch import BodyCache, Fetcher


class FeedEntry(BaseModel):
    entry_id: str | None = None
    title: str = ""
    link: str | None = None
    published: str | None = None
    summary: str = ""


class PageObservation(BaseModel):
    """Normalized fetch result. URLs are canonical strings (HttpUrl would re-normalize them)."""

    source_id: str | None
    requested_url: str
    final_url: str
    fetched_at: datetime
    http_status: int
    mime_type: str | None = None
    title: str | None = None
    text: str = ""
    links: list[str] = Field(default_factory=list)
    entries: list[FeedEntry] = Field(default_factory=list)
    meta: dict[str, str] = Field(default_factory=dict)
    etag: str | None = None
    last_modified: str | None = None
    content_sha256: str
    text_sha256: str
    not_modified: bool = False
    body_cache_relpath: str | None = None
    text_cache_relpath: str | None = None
    depth: int = 0


@dataclass(frozen=True)
class FetchFailure:
    url: str
    error_code: str
    detail: str
    http_status: int | None = None


@dataclass(frozen=True)
class SourceRecord:
    id: str
    source_key: str | None
    name: str
    canonical_url: str
    domain: str
    source_type: str
    adapter_type: str
    trust_tier: str
    authority_scope: str
    allowed_domains: tuple[str, ...]
    allow_paths: tuple[str, ...]
    deny_paths: tuple[str, ...]
    fetch_interval_hours: int
    priority: int
    enabled: bool
    state: str
    discovery_only: bool
    discovery_policy: dict[str, object]
    failure_streak: int
    etag: str | None
    last_modified: str | None
    last_content_hash: str | None
    next_due_at: str | None
    last_success_at: str | None
    last_attempt_at: str | None
    last_content_change_at: str | None
    robots_policy_checked_at: str | None
    terms_review_note: str
    organization_id: str | None = None

    @property
    def scope(self) -> Scope:
        return Scope(self.allowed_domains or (self.domain,), self.allow_paths, self.deny_paths)

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> SourceRecord:
        def lst(col: str) -> tuple[str, ...]:
            return tuple(json.loads(r[col]))

        return cls(
            id=r["id"], source_key=r["source_key"], name=r["name"],
            canonical_url=r["canonical_url"], domain=r["domain"],
            source_type=r["source_type"], adapter_type=r["adapter_type"],
            trust_tier=r["trust_tier"], authority_scope=r["authority_scope"],
            allowed_domains=lst("allowed_domains_json"), allow_paths=lst("allow_paths_json"),
            deny_paths=lst("deny_paths_json"), fetch_interval_hours=r["fetch_interval_hours"],
            priority=r["priority"], enabled=bool(r["enabled"]), state=r["state"],
            discovery_only=bool(r["discovery_only"]),
            discovery_policy=json.loads(r["discovery_policy_json"]),
            failure_streak=r["failure_streak"], etag=r["etag"], last_modified=r["last_modified"],
            last_content_hash=r["last_content_hash"], next_due_at=r["next_due_at"],
            last_success_at=r["last_success_at"], last_attempt_at=r["last_attempt_at"],
            last_content_change_at=r["last_content_change_at"],
            robots_policy_checked_at=r["robots_policy_checked_at"],
            terms_review_note=r["terms_review_note"], organization_id=r["organization_id"],
        )  # fmt: skip


Validators = Callable[[str], tuple[str | None, str | None]]


@dataclass
class FetchContext:
    """Everything an adapter needs; adapters never touch the database or Telegram."""

    fetcher: Fetcher
    settings: AppSettings
    cache: BodyCache | None = None
    validators: Validators = lambda url: (None, None)  # (etag, last_modified) from prior runs
    failures: list[FetchFailure] = field(default_factory=list)  # non-fatal child-page failures


class SourceAdapter(Protocol):
    adapter_type: str

    def fetch(self, source: SourceRecord, ctx: FetchContext) -> list[PageObservation]: ...
