"""Turn fetched observations into candidate drafts (LLD §8.1). Pure functions: no I/O."""

from __future__ import annotations

from dataclasses import dataclass, field

from open_hypergamy.discovery.normalize import (
    APPLICATION_PHRASE_RE,
    OPPORTUNITY_RE,
    URL_KEYWORD_RE,
    title_from_url,
)
from open_hypergamy.domain.models import CandidateFact, ExtractionMethod
from open_hypergamy.extraction.deterministic import extract_date_facts
from open_hypergamy.sources.base import PageObservation, SourceRecord

# Adapters whose entries are discovery hints (dates can never confirm): feeds and calendars.
FEED_ADAPTERS = frozenset({"rss_atom", "ical", "json_feed"})

# A registered source page of these types *is* a programme/call page (not just an index).
PAGE_SOURCE_TYPES = frozenset(
    {"official_programme_page", "official_call_page", "official_event_page"}
)


@dataclass
class CandidateDraft:
    title: str
    url: str
    kind: str  # page | feed_entry | sitemap_url
    text: str
    facts: list[CandidateFact] = field(default_factory=list)
    method: ExtractionMethod = "rule"
    observation_url: str = ""


def _qualifies(title: str, text: str, facts: list[CandidateFact]) -> bool:
    """LLD §8.1: opportunity wording plus a meaningful date or application phrase."""
    head = f"{title}\n{text[:2000]}"
    if not OPPORTUNITY_RE.search(head):
        return False
    return bool(facts) or bool(APPLICATION_PHRASE_RE.search(head))


def drafts_from_observation(
    source: SourceRecord, obs: PageObservation, observation_id: str | None
) -> list[CandidateDraft]:
    """Generic institutional index pages stay sources; only identifiable opportunities qualify."""
    if obs.not_modified:
        return []
    out: list[CandidateDraft] = []
    if source.adapter_type == "sitemap":
        for e in obs.entries:
            if e.link and URL_KEYWORD_RE.search(e.link):
                out.append(
                    CandidateDraft(
                        title_from_url(e.link), e.link, "sitemap_url", "", [], "rule", obs.final_url
                    )
                )
        return out
    if source.adapter_type in FEED_ADAPTERS:
        for e in obs.entries:
            if not e.link or not e.title:
                continue
            text = f"{e.title}\n{e.summary}".strip()
            # Feed dates are discovery hints: methods other than 'rule' can never confirm.
            facts = extract_date_facts(
                text,
                source_url=obs.final_url,
                method="feed_metadata",
                observation_id=observation_id,
            )
            if _qualifies(e.title, e.summary, facts):
                out.append(
                    CandidateDraft(
                        e.title, e.link, "feed_entry", text, facts, "feed_metadata", obs.final_url
                    )
                )
        return out
    if obs.depth >= 1 or source.source_type in PAGE_SOURCE_TYPES:
        title = obs.title or title_from_url(obs.final_url)
        facts = extract_date_facts(
            obs.text, source_url=obs.final_url, method="rule", observation_id=observation_id
        )
        if _qualifies(title, obs.text, facts):
            out.append(
                CandidateDraft(title, obs.final_url, "page", obs.text, facts, "rule", obs.final_url)
            )
    return out
