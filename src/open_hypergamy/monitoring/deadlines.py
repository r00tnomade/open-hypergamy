"""Deadline sentinel, alert generation and weekly digest (LLD §13, §14, §15).

`prepare` is database-only (marks stale facts, recomputes states, picks sources to recheck);
fetching happens in the caller. `queue_alerts` turns the resulting state into deduplicated
outbox rows. Estimates are never alerted as confirmed dates.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from open_hypergamy.clock import Clock, iso_z, local_today
from open_hypergamy.config import LoadedConfig
from open_hypergamy.discovery.promotion import refresh_edition
from open_hypergamy.notifications import templates as T
from open_hypergamy.notifications.base import NotificationMessage
from open_hypergamy.notifications.outbox import Outbox
from open_hypergamy.notifications.telegram import split_message
from open_hypergamy.persistence.db import transaction
from open_hypergamy.persistence.repositories.opportunities import OpportunityRepository
from open_hypergamy.reporting.weekly import gather, render_text
from open_hypergamy.scoring.service import FINAL_ACTIONS, ScoreOutcome

ALERT_ACTIONS = ("apply", "prepare", "monitor")


@dataclass
class PrepareReport:
    marked_stale: int = 0
    editions_refreshed: int = 0
    editions_to_recheck: list[str] = field(default_factory=list)


@dataclass
class AlertReport:
    queued: dict[str, int] = field(default_factory=dict)
    skipped_duplicates: int = 0

    def add(self, kind: str, new: bool) -> None:
        if new:
            self.queued[kind] = self.queued.get(kind, 0) + 1
        else:
            self.skipped_duplicates += 1


def _fmt_ts(dt: datetime) -> str:
    return iso_z(dt)


def prepare(conn: sqlite3.Connection, cfg: LoadedConfig, clock: Clock) -> PrepareReport:
    """Mark lapsed confirmed deadlines stale (value kept), refresh edition states from `today`,
    and list editions whose imminent deadlines need re-verification (LLD §6.5, §10.3)."""
    rep = PrepareReport()
    now_dt = clock.now_utc()
    today, now = local_today(now_dt), _fmt_ts(now_dt)
    repo = OpportunityRepository(conn, clock)
    with transaction(conn):
        rep.marked_stale = conn.execute(
            "UPDATE deadlines SET fact_status='stale', updated_at=? WHERE fact_status='confirmed_official' "
            "AND edition_id IN (SELECT id FROM editions WHERE source_fresh_until IS NOT NULL AND source_fresh_until < ?) "
            "AND due_date_local >= ?",
            (now, now, today.isoformat()),
        ).rowcount
        for r in conn.execute("SELECT id FROM editions").fetchall():
            refresh_edition(repo, conn, r["id"], today, now_dt, False, verified_now=False)
            rep.editions_refreshed += 1
        horizon = (today + timedelta(days=90)).isoformat()
        rows = conn.execute(
            "SELECT DISTINCT e.id FROM editions e JOIN deadlines d ON d.edition_id=e.id "
            "WHERE d.deadline_type='application_close' AND d.fact_status IN ('confirmed_official','stale') "
            "AND d.due_date_local BETWEEN ? AND ? AND (e.source_fresh_until IS NULL OR e.source_fresh_until <= ?) "
            "AND e.user_action NOT IN ('applied','accepted','rejected','withdrawn','archived')",
            (today.isoformat(), horizon, now),
        ).fetchall()
        rep.editions_to_recheck = [r["id"] for r in rows]
    return rep


def _edition_url(row: sqlite3.Row) -> str:
    return str(row["official_url"])


def _close_row(conn: sqlite3.Connection, eid: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM deadlines WHERE edition_id=? AND deadline_type='application_close' "
        "ORDER BY created_at LIMIT 1",
        (eid,),
    ).fetchone()
    return row


def queue_alerts(
    conn: sqlite3.Connection,
    cfg: LoadedConfig,
    clock: Clock,
    outcomes: list[ScoreOutcome],
    outbox: Outbox,
) -> AlertReport:
    rep = AlertReport()
    if not cfg.settings.telegram.enabled:
        return rep
    now_dt = clock.now_utc()
    today = local_today(now_dt)
    tg = cfg.settings.telegram
    repo = OpportunityRepository(conn, clock)

    def put(kind: str, entity: str, text: str, key: str, etype: str = "edition") -> None:
        rep.add(kind, outbox.enqueue(NotificationMessage(text, kind, etype, entity), key))

    for o in outcomes:
        ed = repo.get_edition(o.edition_id)
        assert ed is not None
        if (
            o.band == "excluded"
            or ed["user_action"] in FINAL_ACTIONS
            or ed["user_action"] == "archived"
        ):
            continue
        close = _close_row(conn, o.edition_id)
        url = _edition_url(ed)
        elig = o.eligibility
        evidence = T.evidence_label(ed["fact_status"], close["fact_status"] if close else None)
        close_txt = (
            f"{close['raw_date_text']} ({T.label(close['fact_status'])})" if close else "unknown"
        )

        # New, verified, high-fit opportunity.
        if (
            ed["fact_status"] == "confirmed_official"
            and o.fit >= tg.minimum_fit_score_for_immediate_alert
            and o.action in ALERT_ACTIONS
            and o.eligibility in ("eligible", "possibly_eligible")
        ):
            funding = conn.execute(
                "SELECT proposed_value_json FROM claims WHERE edition_id=? AND "
                "field_name='funding' ORDER BY created_at DESC LIMIT 1",
                (o.edition_id,),
            ).fetchone()
            f_txt = "unknown"
            if funding:
                import json

                f_txt = f"{json.loads(funding[0]).get('status', 'unknown')} (unverified)"
            ev = (
                f"{ed['event_start_date']}..{ed['event_end_date']}"
                if ed["event_start_date"]
                else None
            )
            put(
                "new_opportunity",
                o.edition_id,
                T.new_opportunity(
                    name=o.name,
                    fit=o.fit,
                    eligibility=elig,
                    event=ev,
                    application=close_txt,
                    funding=f_txt,
                    reasons=o.reasons,
                    evidence=evidence,
                    next_action=o.action.replace("_", " "),
                    url=url,
                ),
                f"new:{o.edition_id}",
            )

        # Applications confirmed open.
        if (
            ed["application_status"] == "open"
            and close
            and close["fact_status"] == "confirmed_official"
            and o.action in ("apply", "prepare")
        ):
            put(
                "application_opened",
                o.edition_id,
                T.application_opened(
                    name=o.name,
                    raw_close=close["raw_date_text"],
                    status=close["fact_status"],
                    url=url,
                ),
                f"opened:{o.edition_id}:{close['due_date_local']}",
            )

        # Deadline reminders: 30/14/7/2 days, high priority, verified dates only.
        if (
            close
            and close["fact_status"] == "confirmed_official"
            and o.band in ("critical", "high")
            and o.action in ("apply", "prepare")
        ):
            days = (date.fromisoformat(close["due_date_local"]) - today).days
            crossed = sorted(x for x in tg.deadline_offsets_days if 0 <= days <= x)
            if crossed:  # catch-up: only the most urgent crossed threshold is sent
                open_actions = conn.execute(
                    "SELECT title FROM action_items WHERE edition_id=? AND status='open' "
                    "ORDER BY due_date_local LIMIT 2",
                    (o.edition_id,),
                ).fetchall()
                needed = (
                    "; ".join(r["title"].split(":")[0] for r in open_actions)
                    or "review the official page"
                )
                for off in crossed:
                    key = f"deadline:{o.edition_id}:{close['id']}:{off}:{close['due_date_local']}"
                    if off == crossed[0]:
                        put(
                            "deadline_reminder",
                            o.edition_id,
                            T.deadline_reminder(
                                days=days,
                                name=o.name,
                                raw=close["raw_date_text"],
                                status=close["fact_status"],
                                eligibility=elig,
                                still_needed=needed,
                                url=url,
                            ),
                            key,
                        )
                    else:
                        outbox.enqueue(
                            NotificationMessage("", "deadline_reminder", "edition", o.edition_id),
                            key,
                            status="suppressed",
                            note="superseded by a more urgent threshold",
                        )

        # Official deadline moved (two confirmed claims with different dates).
        for d in conn.execute(
            "SELECT * FROM deadlines WHERE edition_id=? AND fact_status='confirmed_official'",
            (o.edition_id,),
        ).fetchall():
            claims = conn.execute(
                "SELECT proposed_value_json FROM claims WHERE deadline_id=? AND "
                "fact_status='confirmed_official' ORDER BY created_at, rowid",
                (d["id"],),
            ).fetchall()
            import json

            dates = [json.loads(c[0]).get("date") for c in claims]
            if (
                len(set(dates)) >= 2
                and dates[-1] == d["due_date_local"]
                and d["due_date_local"] >= today.isoformat()
            ):
                old = next((x for x in reversed(dates) if x != d["due_date_local"]), "?")
                put(
                    "deadline_changed",
                    o.edition_id,
                    T.deadline_changed(
                        name=o.name,
                        deadline_type=d["deadline_type"],
                        old=str(old),
                        new=d["due_date_local"],
                        status=d["fact_status"],
                        url=url,
                    ),
                    f"moved:{d['id']}:{d['due_date_local']}",
                )

        # Conflicting or stale critical date on a high-priority opportunity.
        if o.problem and (o.band in ("critical", "high") or o.fit >= 70) and close:
            kind = "deadline_conflict" if o.problem == "conflict" else "deadline_stale"
            put(
                kind,
                o.edition_id,
                T.fact_problem(
                    kind="conflict" if o.problem == "conflict" else "stale",
                    name=o.name,
                    raw=close["raw_date_text"],
                    url=url,
                ),
                f"{o.problem}:{close['id']}:{close['due_date_local']}",
            )

    # Sources failing repeatedly that back an imminent deadline.
    horizon = (today + timedelta(days=60)).isoformat()
    for s in conn.execute(
        "SELECT DISTINCT s.id, s.name, s.failure_streak, s.last_success_at FROM sources s "
        "JOIN candidates c ON c.discovered_by_source_id=s.id JOIN deadlines d ON d.edition_id=c.promoted_edition_id "
        "WHERE s.failure_streak >= 2 AND d.deadline_type='application_close' AND d.due_date_local BETWEEN ? AND ?",
        (today.isoformat(), horizon),
    ).fetchall():
        bucket = 1 << (s["failure_streak"].bit_length() - 1)
        put(
            "source_health",
            s["id"],
            T.source_health(
                source=s["name"],
                streak=s["failure_streak"],
                last_ok=s["last_success_at"],
                impact="a verified application deadline within 60 days depends on this source",
            ),
            f"sourcefail:{s['id']}:{bucket}",
            etype="source",
        )
    return rep


# ----------------------------------------------------------------------------------------------
def build_digest(conn: sqlite3.Connection, cfg: LoadedConfig, clock: Clock) -> str:
    """Plain-text weekly digest; same data as `ohg report weekly`."""
    return render_text(gather(conn, cfg, clock))


def queue_digest(
    conn: sqlite3.Connection, cfg: LoadedConfig, clock: Clock, outbox: Outbox
) -> tuple[str, int]:
    text = build_digest(conn, cfg, clock)
    if not (cfg.settings.telegram.enabled and cfg.settings.telegram.digest_enabled):
        return text, 0
    iso = clock.now_utc().isocalendar()
    queued = 0
    for n, part in enumerate(split_message(text), start=1):
        queued += int(
            outbox.enqueue(
                NotificationMessage(part, "digest", "digest", f"{iso.year}-W{iso.week:02d}"),
                f"digest:{iso.year}-W{iso.week:02d}:{n}",
            )
        )
    return text, queued
