"""iCalendar (RFC 5545) export (LLD §15). Hand-rolled: it is small and dependency-free.

Event dates, application windows, deadlines and preparation tasks are separate items. Dates
are all-day (`VALUE=DATE`): a date-only deadline is never turned into 23:59 or any timezone.
Only officially confirmed dates are exported by default; stale ones are labelled, conflicting
ones are omitted, and estimates/unverified dates appear only when asked for and are labelled.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta

from open_hypergamy.clock import Clock

PRODID = "-//OpenHypergamy//Local export//EN"
_HARD = {
    "application_close",
    "early_application_close",
    "abstract_submission",
    "paper_submission",
    "registration_close",
    "recommendation_letter",
    "travel_grant",
    "scholarship",
    "team_formation",
}


def esc(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def fold(line: str) -> str:
    """Fold at 75 octets without splitting a UTF-8 sequence; continuation lines start with a space."""
    out: list[str] = []
    cur, size = "", 0
    for ch in line:
        w = len(ch.encode())
        limit = 75 if not out else 74
        if size + w > limit:
            out.append(cur)
            cur, size = "", 0
        cur += ch
        size += w
    out.append(cur)
    return "\r\n ".join(out)


def _d(v: date) -> str:
    return v.strftime("%Y%m%d")


@dataclass
class Cal:
    stamp: str
    lines: list[str] = field(default_factory=list)
    count: int = 0

    def event(
        self,
        uid: str,
        start: date,
        end_inclusive: date,
        summary: str,
        desc: str,
        url: str,
        category: str,
        status: str,
        alarm_days: int | None = None,
    ) -> None:
        self.count += 1
        self.lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}@openhypergamy.local",
            f"DTSTAMP:{self.stamp}",
            f"DTSTART;VALUE=DATE:{_d(start)}",
            f"DTEND;VALUE=DATE:{_d(end_inclusive + timedelta(days=1))}",
            f"SUMMARY:{esc(summary)}",
            f"DESCRIPTION:{esc(desc)}",
            f"URL:{url}",
            f"CATEGORIES:{category}",
            f"STATUS:{status}",
            "TRANSP:TRANSPARENT",
        ]
        if alarm_days is not None:
            self.lines += [
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{esc(summary)}",
                f"TRIGGER:-P{alarm_days}D",
                "END:VALARM",
            ]
        self.lines.append("END:VEVENT")

    def todo(self, uid: str, due: date, summary: str, desc: str, url: str) -> None:
        self.count += 1
        self.lines += [
            "BEGIN:VTODO",
            f"UID:{uid}@openhypergamy.local",
            f"DTSTAMP:{self.stamp}",
            f"DUE;VALUE=DATE:{_d(due)}",
            f"SUMMARY:{esc(summary)}",
            f"DESCRIPTION:{esc(desc)}",
            f"URL:{url}",
            "CATEGORIES:PREPARATION",
            "STATUS:NEEDS-ACTION",
            "END:VTODO",
        ]

    def render(self) -> str:
        head = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            f"PRODID:{PRODID}",
            "CALSCALE:GREGORIAN",
            "X-WR-CALNAME:OpenHypergamy",
        ]
        return "\r\n".join(fold(line) for line in [*head, *self.lines, "END:VCALENDAR"]) + "\r\n"


def build_ics(
    conn: sqlite3.Connection,
    clock: Clock,
    *,
    actions: set[str],
    include_estimates: bool = False,
    include_unverified: bool = False,
) -> tuple[str, int]:
    cal = Cal(clock.now_utc().strftime("%Y%m%dT%H%M%SZ"))
    for e in conn.execute("SELECT * FROM editions ORDER BY display_name").fetchall():
        if e["user_action"] not in actions:
            continue
        name, url = e["display_name"], e["official_url"]
        if e["event_start_date"]:
            start = date.fromisoformat(e["event_start_date"])
            end = date.fromisoformat(e["event_end_date"]) if e["event_end_date"] else start
            cal.event(
                f"event-{e['id']}",
                start,
                end,
                f"Event: {name}",
                f"Event dates confirmed by an official source.\nOfficial page: {url}",
                url,
                "EVENT",
                "CONFIRMED",
            )
        by_type: dict[str, tuple[date, sqlite3.Row, str]] = {}
        for d in conn.execute(
            "SELECT * FROM deadlines WHERE edition_id=? AND due_date_local IS NOT NULL", (e["id"],)
        ):
            status = d["fact_status"]
            label = {
                "confirmed_official": "",
                "stale": " (stale: recheck)",
                "estimated_recurring": " [ESTIMATE – not confirmed]",
                "unverified": " [UNVERIFIED]",
            }.get(status)
            if (
                label is None
                or (status == "estimated_recurring" and not include_estimates)
                or (status == "unverified" and not include_unverified)
            ):
                continue  # conflicting, cancelled, unknown: never exported as a date
            due = date.fromisoformat(d["due_date_local"])
            by_type[d["deadline_type"]] = (due, d, label)
            kind = d["deadline_type"].replace("_", " ")
            desc = f"As written: {d['raw_date_text'] or d['due_date_local']}\nStatus: {status}\nOfficial page: {url}"
            if d["deadline_type"] == "application_open":
                continue  # exported as part of the application window below
            cal.event(
                f"deadline-{d['id']}",
                due,
                due,
                f"Deadline ({kind}): {name}{label}",
                desc,
                url,
                "DEADLINE",
                "CONFIRMED" if status == "confirmed_official" else "TENTATIVE",
                alarm_days=2 if d["deadline_type"] in _HARD else None,
            )
        opened, closed = by_type.get("application_open"), by_type.get("application_close")
        if opened and closed and opened[0] <= closed[0]:
            cal.event(
                f"window-{e['id']}",
                opened[0],
                closed[0],
                f"Applications open: {name}{''.join(dict.fromkeys(x for x in (opened[2], closed[2]) if x))}",
                f"Application window {opened[0].isoformat()} to {closed[0].isoformat()}.\nOfficial page: {url}",
                url,
                "APPLICATION-WINDOW",
                "CONFIRMED" if closed[1]["fact_status"] == "confirmed_official" else "TENTATIVE",
            )
        elif opened:
            cal.event(
                f"window-{e['id']}",
                opened[0],
                opened[0],
                f"Applications open: {name}{opened[2]}",
                f"Official page: {url}",
                url,
                "APPLICATION-WINDOW",
                "CONFIRMED" if opened[1]["fact_status"] == "confirmed_official" else "TENTATIVE",
            )
        for a in conn.execute(
            "SELECT * FROM action_items WHERE edition_id=? AND status='open' AND due_date_local IS NOT NULL",
            (e["id"],),
        ):
            cal.todo(
                f"action-{a['id']}",
                date.fromisoformat(a["due_date_local"]),
                a["title"],
                a["description"],
                url,
            )
    return cal.render(), cal.count
