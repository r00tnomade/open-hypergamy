"""Message templates (LLD §13.3). Every alert carries the official link and a certainty label.

Templates receive edition/score facts only: never profile contents, prompts, raw page text or
local paths. Dates that are not officially confirmed are never presented as confirmed.
"""

from __future__ import annotations

from datetime import date

_REASON_PHRASES = {
    "HIGH_CAREER_ALIGNMENT": "strong match with your focus areas",
    "RESEARCH_OUTPUT_LIKELY": "research output is likely",
    "FUNDING_CONFIRMED": "funding is confirmed",
    "APPLICATION_OPEN": "applications are open",
    "DEADLINE_WITHIN_14_DAYS": "deadline within 14 days",
}
_LABELS = {
    "confirmed_official": "confirmed",
    "conflicting_sources": "conflict",
    "stale": "stale",
    "estimated_recurring": "estimated (NOT confirmed)",
    "announced_not_open": "announced",
    "unverified": "unverified",
    "unknown": "unknown",
    "cancelled_official": "cancelled",
}


def label(status: str) -> str:
    return _LABELS.get(status, status)


def evidence_label(edition_fact_status: str, deadline_status: str | None) -> str:
    if "conflicting_sources" in (edition_fact_status, deadline_status):
        return "conflict"
    if deadline_status == "confirmed_official" or edition_fact_status == "confirmed_official":
        return "confirmed"
    if edition_fact_status == "announced_not_open":
        return "partial"
    return "unverified"


def why(reasons: list[str]) -> str:
    phrases = [_REASON_PHRASES[r] for r in reasons if r in _REASON_PHRASES]
    return "; ".join(phrases[:3]) or "relevant to your profile"


def new_opportunity(
    *,
    name: str,
    fit: float,
    eligibility: str,
    event: str | None,
    application: str,
    funding: str,
    reasons: list[str],
    evidence: str,
    next_action: str,
    url: str,
) -> str:
    return (
        f"🎯 New opportunity: {name}\n"
        f"Fit: {fit:g}/100 · Eligibility: {eligibility}\n"
        f"When: {event or 'unknown'}\n"
        f"Application: {application}\n"
        f"Funding: {funding}\n"
        f"Why it fits: {why(reasons)}\n"
        f"Evidence: {evidence}\n"
        f"Next action: {next_action}\n"
        f"Official source: {url}"
    )


def deadline_reminder(
    *, days: int, name: str, raw: str, status: str, eligibility: str, still_needed: str, url: str
) -> str:
    when = "today" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
    return (
        f"⏳ Deadline {when}: {name}\n"
        f"Deadline: {raw} ({label(status)})\n"
        f"Eligibility: {eligibility}\n"
        f"Still needed: {still_needed}\n"
        f"Official source: {url}"
    )


def application_opened(*, name: str, raw_close: str, status: str, url: str) -> str:
    return (
        f"📬 Applications are open: {name}\n"
        f"Closes: {raw_close} ({label(status)})\n"
        f"Official source: {url}"
    )


def deadline_changed(
    *, name: str, deadline_type: str, old: str, new: str, status: str, url: str
) -> str:
    return (
        f"🔄 Deadline changed: {name}\n"
        f"{deadline_type.replace('_', ' ').title()}: {old} → {new} ({label(status)})\n"
        f"Official source: {url}"
    )


def fact_problem(*, kind: str, name: str, raw: str, url: str) -> str:
    head = (
        "⚠️ Conflicting official sources"
        if kind == "conflict"
        else "⚠️ Deadline needs rechecking (stale)"
    )
    return f"{head}: {name}\nDate on record: {raw} ({'conflict' if kind == 'conflict' else 'stale'})\nOfficial source: {url}"


def source_health(*, source: str, streak: int, last_ok: str | None, impact: str) -> str:
    return (
        f"⚠️ Monitoring issue: {source}\n"
        f"Failure streak: {streak}\n"
        f"Last successful check: {last_ok or 'never'}\n"
        f"Impact: {impact}\n"
        "Action: inspect source status with `radar sources failures`"
    )


def monitoring_gap(*, job: str, last_success: str, overdue_hours: int) -> str:
    return (
        f"⏸ Monitoring gap: `{job}` has not completed since {last_success} "
        f"({overdue_hours} h overdue).\n"
        "The machine may have been asleep or offline. Deadlines were recalculated from the current "
        "time and overdue checks are running now.\n"
        "Action: inspect with `radar status`"
    )


def days_between(a: date, b: date) -> int:
    return (b - a).days
