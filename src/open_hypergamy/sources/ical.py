"""iCalendar adapter (RFC 5545). Official calendars are an authorized, stable channel.

Event dates here are discovery hints (`feed_metadata`), never application-deadline evidence:
DTSTART is the event itself and is kept apart from any deadline (invariant 4). Events without a
URL cannot be followed to an evidence page and are skipped.
"""

from __future__ import annotations

from open_hypergamy.errors import ParseError
from open_hypergamy.sources.base import FeedEntry, FetchContext, PageObservation, SourceRecord
from open_hypergamy.sources.common import build_observation, decode_body
from open_hypergamy.sources.urls import canonicalize_url

MAX_EVENTS = 200
ICAL_TYPES = frozenset({"text/calendar", "text/plain", "application/ics"})


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _unescape(value: str) -> str:
    out, i = [], 0
    while i < len(value):
        c = value[i]
        if c == "\\" and i + 1 < len(value):
            n = value[i + 1]
            out.append("\n" if n in "nN" else n)
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def parse_events(text: str) -> list[dict[str, str]]:
    """VEVENT property dicts (upper-case names, first value wins, parameters dropped)."""
    lines = _unfold(text)
    if not any(ln.strip().upper() == "BEGIN:VCALENDAR" for ln in lines):
        raise ParseError("not an iCalendar document")
    events: list[dict[str, str]] = []
    cur: dict[str, str] | None = None
    for ln in lines:
        u = ln.strip().upper()
        if u == "BEGIN:VEVENT":
            cur = {}
        elif u == "END:VEVENT":
            if cur is not None:
                events.append(cur)
            cur = None
        elif cur is not None and ":" in ln:
            head, _, value = ln.partition(":")
            name = head.split(";", 1)[0].strip().upper()
            cur.setdefault(name, _unescape(value.strip()))
        if len(events) >= MAX_EVENTS:
            break
    return events


class IcalAdapter:
    adapter_type = "ical"

    def fetch(self, source: SourceRecord, ctx: FetchContext) -> list[PageObservation]:
        resp = ctx.fetcher.fetch(
            source.canonical_url,
            source.scope,
            etag=source.etag,
            last_modified=source.last_modified,
            accept=ICAL_TYPES,
        )
        if resp.not_modified:
            return [build_observation(source, resp, ctx)]
        events = parse_events(decode_body(resp.body))
        entries: list[FeedEntry] = []
        for ev in events:
            link = None
            if ev.get("URL"):
                try:
                    link = canonicalize_url(ev["URL"], base=resp.final_url)
                except Exception:  # noqa: BLE001 - one bad URL must not discard the event
                    link = None
            entries.append(
                FeedEntry(
                    entry_id=ev.get("UID"),
                    title=ev.get("SUMMARY", ""),
                    link=link,
                    published=ev.get("DTSTART"),
                    summary=ev.get("DESCRIPTION", "")[:2000],
                )
            )
        text = "\n\n".join(f"{x.title}\n{x.link or ''}\n{x.summary}".strip() for x in entries)
        return [
            build_observation(
                source,
                resp,
                ctx,
                title=source.name,
                text=text,
                links=[x.link for x in entries if x.link],
                entries=entries,
                suffix="ics",
            )
        ]
