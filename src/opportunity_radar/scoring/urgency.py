"""Urgency from *verified* deadlines only (LLD §11.4). Independent of fit."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class UrgencyResult:
    score: float
    distance_days: int | None
    reasons: list[str] = field(default_factory=list)
    open_date: date | None = None
    close_date: date | None = None
    close_deadline_id: str | None = None
    problem: str | None = None  # stale | conflict | None


def _d(v: str | None) -> date | None:
    return date.fromisoformat(v) if v else None


def _by_days(days: int) -> float:
    if days <= 2:
        return 100.0
    if days <= 7:
        return 90.0
    if days <= 14:
        return 75.0
    if days <= 30:
        return 55.0
    if days <= 90:
        return 30.0
    return 15.0


def compute_urgency(
    edition: sqlite3.Row, deadlines: list[sqlite3.Row], today: date, now: datetime
) -> UrgencyResult:
    by_type = {d["deadline_type"]: d for d in deadlines}
    close, opened = by_type.get("application_close"), by_type.get("application_open")
    res = UrgencyResult(10.0, None)
    if (
        any(d["fact_status"] == "conflicting_sources" for d in deadlines)
        or edition["fact_status"] == "conflicting_sources"
    ):
        res.score, res.problem = 40.0, "conflict"
        res.reasons.append("OFFICIAL_SOURCE_CONFLICT")
        return res
    fresh_until = edition["source_fresh_until"]
    stale_ts = bool(fresh_until) and fresh_until < now.strftime("%Y-%m-%dT%H:%M:%SZ")
    close_d = _d(close["due_date_local"]) if close is not None else None
    if close is not None and close_d is not None and close_d < today:
        # A deadline that has passed is closed, not "stale": nothing to recheck or remind about.
        res.close_date, res.close_deadline_id = close_d, close["id"]
        res.distance_days = (close_d - today).days
        res.score = 0.0
        return res
    if close is not None and (
        close["fact_status"] == "stale"
        or (close["fact_status"] == "confirmed_official" and stale_ts)
    ):
        res.score, res.problem = 40.0, "stale"
        res.close_date, res.close_deadline_id = _d(close["due_date_local"]), close["id"]
        res.reasons.append("CRITICAL_FACT_STALE")
        return res
    if close is not None and close["fact_status"] == "confirmed_official":
        cd = _d(close["due_date_local"])
        res.close_date, res.close_deadline_id = cd, close["id"]
        assert cd is not None
        od = (
            _d(opened["due_date_local"])
            if opened is not None and opened["fact_status"] == "confirmed_official"
            else None
        )
        res.open_date = od
        days = (cd - today).days
        if days < 0:
            res.score, res.distance_days = 0.0, days
            return res
        res.distance_days = days
        if od is not None and today < od:
            wait = (od - today).days
            res.score = 50.0 if wait <= 30 else 20.0
            return res
        res.score = _by_days(days)
        res.reasons.append("APPLICATION_OPEN")
        if days <= 14:
            res.reasons.append("DEADLINE_WITHIN_14_DAYS")
        return res
    if opened is not None and opened["fact_status"] == "confirmed_official":
        od = _d(opened["due_date_local"])
        res.open_date = od
        if od is not None:
            wait = (od - today).days
            res.distance_days = wait
            res.score = 50.0 if 0 <= wait <= 30 else (20.0 if wait > 30 else 30.0)
    return res
