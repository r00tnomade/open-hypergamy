"""Pure date rules: chronology and application-status arithmetic (LLD §9.6, §10.3).

Only dates already confirmed by an official source may be passed in.
"""

from __future__ import annotations

from datetime import date, timedelta


def check_chronology(
    *,
    open_date: date | None,
    close_date: date | None,
    event_start: date | None,
    event_end: date | None,
) -> list[str]:
    problems: list[str] = []
    if open_date and close_date and open_date > close_date:
        problems.append("application_open_after_close")
    if event_start and event_end and event_start > event_end:
        problems.append("event_start_after_end")
    last_event_day = event_end or event_start
    if close_date and last_event_day and close_date > last_event_day:
        problems.append("application_close_after_event")
    return problems


def derive_application_status(
    *,
    open_date: date | None,
    close_date: date | None,
    today: date,
    announced_not_open: bool,
    conflicting: bool,
) -> str:
    if conflicting:
        return "conflicting"
    if close_date and today > close_date:
        return "closed"
    if open_date and today < open_date:
        return "not_open"
    if close_date or open_date:
        return "open"
    return "not_open" if announced_not_open else "unknown"


def freshness_window(close_date: date | None, today: date) -> timedelta:
    """How long a confirmed deadline stays fresh (LLD §10.3)."""
    if close_date is None:
        return timedelta(days=30)
    days = (close_date - today).days
    if days <= 30:
        return timedelta(days=1)
    if days <= 90:
        return timedelta(days=7)
    return timedelta(days=30)
