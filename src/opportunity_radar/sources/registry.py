"""Source registry YAML schema and validation (LLD §6)."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from opportunity_radar.domain.enums import AdapterType, TrustTier
from opportunity_radar.errors import ConfigurationError, SourcePolicyDenied
from opportunity_radar.sources.base import SourceRecord
from opportunity_radar.sources.urls import canonicalize_url, check_static_host, host_of

_KEY = re.compile(r"^[a-z0-9][a-z0-9-]{2,80}$")

# HLD §6.2 portfolio targets (~200). A target, never a reported count.
PORTFOLIO_TARGETS: dict[str, int] = {
    "de_research": 45,
    "europe_research": 40,
    "international_programmes": 20,
    "conferences_societies": 30,
    "industry_programmes": 25,
    "funding_fellowships": 20,
    "hackathons_challenges": 10,
    "discovery_only": 10,
}


class OrganizationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    canonical_domain: str | None = None
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    organization_type: str = "unknown"


class DiscoveryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    follow_internal_links: bool = False
    max_depth: int = Field(default=1, ge=0, le=5)
    max_pages_per_run: int = Field(default=20, ge=1, le=500)
    promote_outbound_links_automatically: bool = False

    @field_validator("promote_outbound_links_automatically")
    @classmethod
    def _never_auto_promote(cls, v: bool) -> bool:
        if v:
            raise ValueError("outbound links may never be promoted to sources automatically")
        return v


class SourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_key: str
    name: str
    organization: OrganizationConfig | None = None
    canonical_url: str
    domain: str
    source_type: str
    portfolio: str | None = None
    adapter_type: AdapterType
    trust_tier: TrustTier
    authority_scope: str = ""
    topic_tags: list[str] = []
    geographic_scope: list[str] = []
    language_codes: list[str] = []
    allowed_domains: list[str] = []
    allow_paths: list[str] = []
    deny_paths: list[str] = []
    fetch_interval_hours: int = Field(default=168, gt=0)
    priority: int = Field(default=50, ge=0, le=100)
    enabled: bool = True
    terms_review_note: str = ""
    robots_policy_checked_at: date | datetime | None = None
    discovery_policy: DiscoveryPolicy = DiscoveryPolicy()
    extraction_hints: dict[str, Any] = {}

    @field_validator("portfolio")
    @classmethod
    def _portfolio(cls, v: str | None) -> str | None:
        if v is not None and v not in PORTFOLIO_TARGETS:
            raise ValueError(f"portfolio must be one of {sorted(PORTFOLIO_TARGETS)}")
        return v

    @field_validator("source_key")
    @classmethod
    def _key(cls, v: str) -> str:
        if not _KEY.match(v):
            raise ValueError(
                "source_key must be lowercase letters, digits and hyphens (3-81 chars)"
            )
        return v

    @field_validator("canonical_url")
    @classmethod
    def _url(cls, v: str) -> str:
        try:
            url = canonicalize_url(v)
            check_static_host(host_of(url))
        except SourcePolicyDenied as e:
            raise ValueError(str(e)) from e
        return url

    @field_validator("allow_paths", "deny_paths")
    @classmethod
    def _paths(cls, v: list[str]) -> list[str]:
        for p in v:
            if not p.startswith("/"):
                raise ValueError(f"path rule must start with '/': {p!r}")
        return v

    @model_validator(mode="after")
    def _consistency(self) -> SourceConfig:
        host = host_of(self.canonical_url)
        self.domain = self.domain.lower()
        if host != self.domain:
            raise ValueError(f"domain {self.domain!r} does not match canonical_url host {host!r}")
        self.allowed_domains = [d.lower() for d in (self.allowed_domains or [self.domain])]
        for d in self.allowed_domains:
            try:
                check_static_host(d)
            except SourcePolicyDenied as e:
                raise ValueError(str(e)) from e
        if not any(host == d or host.endswith("." + d) for d in self.allowed_domains):
            raise ValueError("allowed_domains must cover the canonical_url host")
        return self

    @property
    def discovery_only(self) -> bool:
        """T4/T5 are discovery-only unless a field-specific authority is documented (LLD §6.2)."""
        return self.trust_tier in (TrustTier.T4_AGGREGATOR, TrustTier.T5_COMMUNITY) and not (
            self.authority_scope.strip()
        )

    @property
    def policy_review_satisfied(self) -> bool:
        return self.robots_policy_checked_at is not None and bool(self.terms_review_note.strip())


def load_source_files(
    paths: Iterable[Path], *, playwright_allowed: Iterable[str] = ()
) -> list[SourceConfig]:
    """Parse and validate YAML files; all problems are reported together."""
    allowed = set(playwright_allowed)
    configs: list[SourceConfig] = []
    problems: list[str] = []
    for path in paths:
        try:
            doc = yaml.safe_load(path.read_text()) or {}
        except (OSError, yaml.YAMLError) as e:
            problems.append(f"{path}: cannot read YAML: {e}")
            continue
        if (
            not isinstance(doc, dict)
            or doc.get("version") != 1
            or not isinstance(doc.get("sources"), list)
        ):
            problems.append(f"{path}: expected a mapping with `version: 1` and a `sources:` list")
            continue
        for i, raw in enumerate(doc["sources"]):
            label = f"{path.name}[{i}]" + (
                f" ({raw.get('source_key')})" if isinstance(raw, dict) else ""
            )
            try:
                cfg = SourceConfig.model_validate(raw)
            except ValidationError as e:
                problems += [
                    f"{label}: {'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()
                ]
                continue
            if cfg.adapter_type is AdapterType.PLAYWRIGHT and cfg.source_key not in allowed:
                problems.append(
                    f"{label}: playwright requires the source_key in "
                    "browser.playwright_allowed_source_ids"
                )
                continue
            configs.append(cfg)
    seen_keys: dict[str, int] = {}
    seen_urls: dict[str, str] = {}
    for c in configs:
        seen_keys[c.source_key] = seen_keys.get(c.source_key, 0) + 1
        if seen_keys[c.source_key] == 2:
            problems.append(f"duplicate source_key: {c.source_key}")
        if c.canonical_url in seen_urls and seen_urls[c.canonical_url] != c.source_key:
            problems.append(
                f"duplicate canonical_url {c.canonical_url} "
                f"({seen_urls[c.canonical_url]} and {c.source_key})"
            )
        seen_urls.setdefault(c.canonical_url, c.source_key)
    if problems:
        raise ConfigurationError("source registry validation failed:\n  " + "\n  ".join(problems))
    return configs


def record_from_config(c: SourceConfig) -> SourceRecord:
    """An in-memory SourceRecord for probing a YAML entry that is not (yet) in the database."""
    return SourceRecord(
        id=f"probe-{c.source_key}",
        source_key=c.source_key,
        name=c.name,
        canonical_url=c.canonical_url,
        domain=c.domain,
        source_type=c.source_type,
        adapter_type=c.adapter_type.value,
        trust_tier=c.trust_tier.value,
        authority_scope=c.authority_scope,
        allowed_domains=tuple(c.allowed_domains),
        allow_paths=tuple(c.allow_paths),
        deny_paths=tuple(c.deny_paths),
        fetch_interval_hours=c.fetch_interval_hours,
        priority=c.priority,
        enabled=True,
        state="active",
        discovery_only=c.discovery_only,
        discovery_policy=c.discovery_policy.model_dump(),
        failure_streak=0,
        etag=None,
        last_modified=None,
        last_content_hash=None,
        next_due_at=None,
        last_success_at=None,
        last_attempt_at=None,
        last_content_change_at=None,
        robots_policy_checked_at=c.robots_policy_checked_at.isoformat()
        if c.robots_policy_checked_at
        else None,
        terms_review_note=c.terms_review_note,
    )
