"""Deadline sentinel, alert generation and weekly digest (LLD §13, §14, §15).

`prepare` is database-only (marks stale facts, recomputes states, picks sources to recheck);
fetching happens in the caller. `queue_alerts` turns the resulting state into deduplicated
outbox rows. Estimates are never alerted as confirmed dates.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from opportunity_radar.clock import Clock, iso_z
from opportunity_radar.config import LoadedConfig
from opportunity_radar.discovery.promotion import refresh_edition
from opportunity_radar.notifications import templates as T
from opportunity_radar.notifications.base import NotificationMessage
from opportunity_radar.notifications.outbox import Outbox
from opportunity_radar.notifications.telegram import split_message
from opportunity_radar.persistence.db import transaction
from opportunity_radar.persistence.repositories.opportunities import OpportunityRepository
from opportunity_radar.scoring.service import FINAL_ACTIONS, ScoreOutcome

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
    today, now = now_dt.date(), _fmt_ts(now_dt)
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
    today = now_dt.date()
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
    now_dt = clock.now_utc()
    today = now_dt.date()
    week_ago = _fmt_ts(now_dt - timedelta(days=7))
    lines = [f"📋 Opportunity Radar weekly digest · {today.isoformat()}", ""]

    def section(title: str, items: list[str]) -> None:
        lines.append(title)
        lines.extend(items or ["  – none"])
        lines.append("")

    acts = conn.execute(
        "SELECT a.title, a.due_date_local, a.priority, e.official_url FROM action_items a "
        "JOIN editions e ON e.id=a.edition_id WHERE a.status='open' ORDER BY "
        "CASE a.priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, "
        "a.due_date_local IS NULL, a.due_date_local LIMIT 3"
    ).fetchall()
    section(
        "1. Top actions",
        [
            f"  – [{a['priority']}] {a['title']}"
            + (f" (by {a['due_date_local']})" if a["due_date_local"] else "")
            + f"\n    {a['official_url']}"
            for a in acts
        ],
    )
    new = conn.execute(
        "SELECT e.display_name, e.official_url, e.fact_status, s.fit_score FROM editions e JOIN score_snapshots s "
        "ON s.edition_id=e.id AND s.rowid=(SELECT MAX(rowid) FROM score_snapshots WHERE edition_id=e.id) "
        "WHERE e.first_seen_at >= ? AND s.priority_band != 'excluded' ORDER BY s.fit_score DESC LIMIT 5",
        (week_ago,),
    ).fetchall()
    section(
        "2. New this week",
        [
            f"  – {n['display_name']} · fit {n['fit_score']:g} · {T.label(n['fact_status'])}\n    {n['official_url']}"
            for n in new
        ],
    )
    opening = conn.execute(
        "SELECT e.display_name, d.raw_date_text, d.fact_status FROM deadlines d JOIN editions e ON e.id=d.edition_id "
        "WHERE d.deadline_type='application_open' AND d.due_date_local BETWEEN ? AND ? ORDER BY d.due_date_local",
        (today.isoformat(), (today + timedelta(days=90)).isoformat()),
    ).fetchall()
    section(
        "3. Applications opening within 90 days",
        [
            f"  – {r['display_name']}: {r['raw_date_text']} ({T.label(r['fact_status'])})"
            for r in opening
        ],
    )
    soon = conn.execute(
        "SELECT e.display_name, d.raw_date_text, d.fact_status, d.due_date_local FROM deadlines d "
        "JOIN editions e ON e.id=d.edition_id WHERE d.deadline_type='application_close' AND "
        "d.fact_status IN ('confirmed_official','stale') AND d.due_date_local BETWEEN ? AND ? "
        "AND e.user_action NOT IN ('applied','accepted','rejected','withdrawn','archived') ORDER BY d.due_date_local",
        (today.isoformat(), (today + timedelta(days=30)).isoformat()),
    ).fetchall()
    section(
        "4. Deadlines within 30 days",
        [
            f"  – {r['display_name']}: {r['raw_date_text']} ({T.label(r['fact_status'])}, "
            f"{(date.fromisoformat(r['due_date_local']) - today).days} d)"
            for r in soon
        ],
    )
    changed = conn.execute(
        "SELECT display_name FROM editions WHERE last_material_change_at >= ?", (week_ago,)
    ).fetchall()
    section("5. Material changes", [f"  – {r['display_name']}" for r in changed])
    future = conn.execute(
        "SELECT display_name FROM editions WHERE user_action='future_cycle' LIMIT 5"
    ).fetchall()
    section("6. Future-cycle opportunities", [f"  – {r['display_name']}" for r in future])
    pending = conn.execute("SELECT COUNT(*) FROM review_queue WHERE state='pending'").fetchone()[0]
    conflicts = conn.execute(
        "SELECT COUNT(*) FROM review_queue WHERE state='pending' AND reason_code LIKE '%conflict'"
    ).fetchone()[0]
    stale = conn.execute("SELECT COUNT(*) FROM deadlines WHERE fact_status='stale'").fetchone()[0]
    failing = conn.execute("SELECT COUNT(*) FROM sources WHERE failure_streak >= 2").fetchone()[0]
    section(
        "7. Verification & monitoring",
        [
            f"  – review queue: {pending} pending ({conflicts} conflicts)",
            f"  – stale deadlines: {stale}",
            f"  – sources failing: {failing}",
        ],
    )
    cov = conn.execute(
        "SELECT COUNT(*), SUM(enabled), SUM(last_success_at >= ?) FROM sources", (week_ago,)
    ).fetchone()
    last = conn.execute(
        "SELECT job_type, MAX(started_at) FROM job_runs WHERE status IN ('success','partial') GROUP BY job_type"
    ).fetchall()
    section(
        "8. Monitoring health",
        [
            f"  – sources: {cov[0]} configured, {cov[1] or 0} enabled, {cov[2] or 0} checked this week",
            *[f"  – last {r[0]}: {r[1]}" for r in last],
        ],
    )
    return "\n".join(lines).rstrip()


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
