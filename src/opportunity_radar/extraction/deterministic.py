"""Deterministic fact extraction from page text (LLD §9.1). Rules only; no LLM.

Facts carry a verbatim excerpt; `verification.evidence.ground_facts` re-checks it against the
observation text before verification. The date payload key is `date` (ISO, or None when the
mention is ambiguous), matching `CandidateFact.date_value`.
"""

from __future__ import annotations

import re

from opportunity_radar.domain.models import CandidateFact, EvidenceQuote, ExtractionMethod
from opportunity_radar.extraction.dates import (
    EVENT,
    DateMention,
    classify_context,
    find_dates,
    sentence_around,
)

DEADLINE_PREFIX = "deadline:"
_NOT_OPEN = re.compile(
    r"applications?\s+(?:will\s+)?(?:open|be\s+(?:announced|available))\s+(?:soon|later|in\s+\w+)"
    r"|call\s+for\s+applications\s+(?:will\s+be\s+)?(?:announced|published)|coming\s+soon"
    r"|not\s+yet\s+open|to\s+be\s+announced|\btba\b|wird\s+bekannt\s+gegeben|demn(?:ä|ae)chst",
    re.IGNORECASE,
)


def _fact(
    name: str,
    value: dict[str, object],
    excerpt: str,
    raw: str,
    *,
    url: str,
    obs_id: str | None,
    method: ExtractionMethod,
    review: str | None = None,
) -> CandidateFact:
    return CandidateFact(
        field_name=name,
        proposed_value=value,
        raw_text=raw,
        evidence=[
            EvidenceQuote(
                source_url=url, observation_id=obs_id, excerpt=excerpt[:2000], field_name=name
            )
        ],
        extraction_method=method,
        needs_review=review is not None,
        review_reason=review,
    )


def _payload(m: DateMention, iso: str | None, ctx: str) -> dict[str, object]:
    return {
        "date": iso,
        "raw": m.raw,
        "precision": m.precision,
        "context": ctx,
        "ambiguity": m.ambiguous,
    }


def extract_date_facts(
    text: str,
    *,
    source_url: str,
    method: ExtractionMethod,
    observation_id: str | None = None,
) -> list[CandidateFact]:
    """Event dates and typed deadlines found in `text`. Unclassified dates are ignored (pages
    contain many unrelated dates); classified-but-ambiguous ones are kept for review."""
    facts: list[CandidateFact] = []
    seen_event = False

    def add(
        name: str, value: dict[str, object], excerpt: str, raw: str, review: str | None
    ) -> None:
        facts.append(
            _fact(
                name,
                value,
                excerpt,
                raw,
                url=source_url,
                obs_id=observation_id,
                method=method,
                review=review,
            )
        )

    for mention in find_dates(text):
        ctx = classify_context(text, mention)
        if ctx is None:
            continue
        excerpt = sentence_around(text, mention.span)
        start = mention.start.isoformat() if mention.usable and mention.start else None
        end = mention.end.isoformat() if mention.usable and mention.end else None
        if ctx == EVENT:
            if not mention.usable:
                add(
                    "event_start_date",
                    _payload(mention, None, ctx),
                    excerpt,
                    mention.raw,
                    mention.ambiguous or "unusable_date",
                )
                continue
            review = "multiple_event_dates" if seen_event else None
            seen_event = True
            add("event_start_date", _payload(mention, start, ctx), excerpt, mention.raw, review)
            if end:
                add("event_end_date", _payload(mention, end, ctx), excerpt, mention.raw, review)
            continue
        review = mention.ambiguous or ("deadline_is_range" if end else None)
        add(
            f"{DEADLINE_PREFIX}{ctx}",
            _payload(mention, None if review else start, ctx),
            excerpt,
            mention.raw,
            review,
        )
    return facts


def detect_not_open(
    text: str, *, source_url: str, method: ExtractionMethod, observation_id: str | None = None
) -> CandidateFact | None:
    """'Applications open soon / TBA' wording: supports `announced_not_open`, never a date."""
    m = _NOT_OPEN.search(text)
    if not m:
        return None
    return _fact(
        "application_status",
        {"status": "not_open"},
        sentence_around(text, m.span()),
        m.group(0),
        url=source_url,
        obs_id=observation_id,
        method=method,
    )
