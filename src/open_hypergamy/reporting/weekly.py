"""Weekly report data (HLD §15) with Markdown and plain-text (Telegram digest) renderers.

One query layer feeds both renderers so the digest and the report cannot drift apart.
Only officially confirmed (or visibly stale) dates appear in the deadline sections; every date
carries its verification label and every item its official link.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Any

from open_hypergamy.clock import Clock, iso_z, local_today
from open_hypergamy.config import LoadedConfig
from open_hypergamy.monitoring.catchup import job_gaps
from open_hypergamy.notifications import templates as T

FINAL = "('applied','accepted','rejected','withdrawn','archived')"


def _rows(conn: sqlite3.Connection, sql: str, *args: Any) -> list[sqlite3.Row]:
    return conn.execute(sql, args).fetchall()


def gather(conn: sqlite3.Connection, cfg: LoadedConfig, clock: Clock) -> dict[str, Any]:
    now_dt = clock.now_utc()
    today = local_today(now_dt)
    week_ago = iso_z(now_dt - timedelta(days=7))
    d = today.isoformat()

    top = _rows(
        conn,
        "SELECT a.title, a.due_date_local, a.priority, e.official_url, e.display_name FROM action_items a "
        "JOIN editions e ON e.id=a.edition_id WHERE a.status='open' ORDER BY "
        "CASE a.priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, "
        "a.due_date_local IS NULL, a.due_date_local LIMIT 3",
    )
    new = _rows(
        conn,
        "SELECT e.display_name, e.official_url, e.fact_status, s.fit_score FROM editions e JOIN score_snapshots s "
        "ON s.edition_id=e.id AND s.rowid=(SELECT MAX(rowid) FROM score_snapshots WHERE edition_id=e.id) "
        "WHERE e.first_seen_at >= ? AND s.priority_band != 'excluded' ORDER BY s.fit_score DESC LIMIT 5",
        week_ago,
    )
    opening = _rows(
        conn,
        "SELECT e.display_name, e.official_url, d.raw_date_text, d.fact_status FROM deadlines d "
        "JOIN editions e ON e.id=d.edition_id WHERE d.deadline_type='application_open' "
        f"AND d.due_date_local BETWEEN ? AND ? AND e.user_action NOT IN {FINAL} ORDER BY d.due_date_local",
        d,
        (today + timedelta(days=90)).isoformat(),
    )
    soon = _rows(
        conn,
        "SELECT e.display_name, e.official_url, d.raw_date_text, d.fact_status, d.due_date_local FROM deadlines d "
        "JOIN editions e ON e.id=d.edition_id WHERE d.deadline_type='application_close' AND "
        f"d.fact_status IN ('confirmed_official','stale') AND d.due_date_local BETWEEN ? AND ? "
        f"AND e.user_action NOT IN {FINAL} ORDER BY d.due_date_local",
        d,
        (today + timedelta(days=30)).isoformat(),
    )
    deadlines = []
    for r in soon:
        days = (date.fromisoformat(r["due_date_local"]) - today).days
        bucket = next(b for b in (2, 7, 14, 30) if days <= b)
        deadlines.append(
            {
                "name": r["display_name"],
                "url": r["official_url"],
                "raw": r["raw_date_text"],
                "status": r["fact_status"],
                "days": days,
                "bucket": bucket,
            }
        )
    changed = _rows(
        conn,
        "SELECT display_name, official_url FROM editions WHERE last_material_change_at >= ?",
        week_ago,
    )
    future = _rows(
        conn,
        "SELECT display_name, official_url FROM editions WHERE user_action='future_cycle' LIMIT 5",
    )
    failing = _rows(
        conn, "SELECT name, failure_streak, last_success_at FROM sources WHERE failure_streak >= 2"
    )
    cov = conn.execute(
        "SELECT COUNT(*), SUM(enabled), SUM(last_success_at >= ?) FROM sources", (week_ago,)
    ).fetchone()
    last_jobs = _rows(
        conn,
        "SELECT job_type, MAX(started_at) FROM job_runs WHERE status IN ('success','partial') GROUP BY job_type",
    )
    return {
        "generated_at": iso_z(now_dt),
        "date": d,
        "top_actions": [
            {
                "priority": r["priority"],
                "title": r["title"],
                "due": r["due_date_local"],
                "url": r["official_url"],
                "name": r["display_name"],
            }
            for r in top
        ],
        "new": [
            {
                "name": r["display_name"],
                "fit": r["fit_score"],
                "status": r["fact_status"],
                "url": r["official_url"],
            }
            for r in new
        ],
        "opening": [
            {
                "name": r["display_name"],
                "raw": r["raw_date_text"],
                "status": r["fact_status"],
                "url": r["official_url"],
            }
            for r in opening
        ],
        "deadlines": deadlines,
        "changes": [{"name": r["display_name"], "url": r["official_url"]} for r in changed],
        "future_cycle": [{"name": r["display_name"], "url": r["official_url"]} for r in future],
        "verification": {
            "review_pending": conn.execute(
                "SELECT COUNT(*) FROM review_queue WHERE state='pending'"
            ).fetchone()[0],
            "conflicts": conn.execute(
                "SELECT COUNT(*) FROM review_queue WHERE state='pending' AND reason_code LIKE '%conflict'"
            ).fetchone()[0],
            "stale_deadlines": conn.execute(
                "SELECT COUNT(*) FROM deadlines WHERE fact_status='stale'"
            ).fetchone()[0],
            "failing_sources": [
                {
                    "name": r["name"],
                    "streak": r["failure_streak"],
                    "last_success_at": r["last_success_at"],
                }
                for r in failing
            ],
        },
        "monitoring": {
            "sources_configured": cov[0] or 0,
            "sources_enabled": cov[1] or 0,
            "sources_checked_7d": cov[2] or 0,
            "last_jobs": {r[0]: r[1] for r in last_jobs},
            "overdue_jobs": [g.describe() for g in job_gaps(conn, cfg, clock)],
        },
    }


def render_text(r: dict[str, Any]) -> str:
    lines = [f"📋 OpenHypergamy weekly digest · {r['date']}", ""]

    def section(title: str, items: list[str]) -> None:
        lines.append(title)
        lines.extend(items or ["  – none"])
        lines.append("")

    section(
        "1. Top actions",
        [
            f"  – [{a['priority']}] {a['title']}"
            + (f" (by {a['due']})" if a["due"] else "")
            + f"\n    {a['url']}"
            for a in r["top_actions"]
        ],
    )
    section(
        "2. New this week",
        [
            f"  – {n['name']} · fit {n['fit']:g} · {T.label(n['status'])}\n    {n['url']}"
            for n in r["new"]
        ],
    )
    section(
        "3. Applications opening within 90 days",
        [f"  – {o['name']}: {o['raw']} ({T.label(o['status'])})" for o in r["opening"]],
    )
    section(
        "4. Deadlines within 30 days",
        [
            f"  – {x['name']}: {x['raw']} ({T.label(x['status'])}, {x['days']} d)"
            for x in r["deadlines"]
        ],
    )
    section("5. Material changes", [f"  – {c['name']}" for c in r["changes"]])
    section("6. Future-cycle opportunities", [f"  – {f['name']}" for f in r["future_cycle"]])
    v, m = r["verification"], r["monitoring"]
    section(
        "7. Verification & monitoring",
        [
            f"  – review queue: {v['review_pending']} pending ({v['conflicts']} conflicts)",
            f"  – stale deadlines: {v['stale_deadlines']}",
            f"  – sources failing: {len(v['failing_sources'])}",
        ],
    )
    section(
        "8. Monitoring health",
        [
            f"  – sources: {m['sources_configured']} configured, {m['sources_enabled']} enabled, {m['sources_checked_7d']} checked this week",
            *[f"  – last {k}: {v_}" for k, v_ in m["last_jobs"].items()],
            *[f"  – OVERDUE {g}" for g in m["overdue_jobs"]],
        ],
    )
    return "\n".join(lines).rstrip()


def render_markdown(r: dict[str, Any]) -> str:
    def link(name: str, url: str) -> str:
        return f"[{name}]({url})"

    out = [
        f"# OpenHypergamy — weekly report ({r['date']})",
        "",
        f"_Generated {r['generated_at']}. Dates are shown with their verification status; only "
        "officially confirmed dates are treated as facts._",
        "",
    ]

    def section(title: str, items: list[str]) -> None:
        out.extend([f"## {title}", ""])
        out.extend(items or ["_None._"])
        out.append("")

    section(
        "1. Top actions",
        [
            f"- **[{a['priority']}]** {a['title']}"
            + (f" — by **{a['due']}**" if a["due"] else "")
            + f" ({link('official page', a['url'])})"
            for a in r["top_actions"]
        ],
    )
    section(
        "2. New high-value opportunities",
        [
            f"- {link(n['name'], n['url'])} — fit {n['fit']:g}, {T.label(n['status'])}"
            for n in r["new"]
        ],
    )
    section(
        "3. Applications opening within 90 days",
        [
            f"- {link(o['name'], o['url'])} — opens {o['raw']} ({T.label(o['status'])})"
            for o in r["opening"]
        ],
    )
    rows = ["| Within | Programme | Deadline (as written) | Status | In |", "|---|---|---|---|---|"]
    rows += [
        f"| {x['bucket']} d | {link(x['name'], x['url'])} | {x['raw']} | {T.label(x['status'])} | {x['days']} d |"
        for x in r["deadlines"]
    ]
    section("4. Deadlines within 30, 14, 7 and 2 days", rows if r["deadlines"] else [])
    section(
        "5. Material deadline or eligibility changes",
        [f"- {link(c['name'], c['url'])}" for c in r["changes"]],
    )
    section(
        "6. Future-cycle opportunities worth preparing for",
        [f"- {link(f['name'], f['url'])}" for f in r["future_cycle"]],
    )
    v, m = r["verification"], r["monitoring"]
    section(
        "7. Conflicts, review queue, stale facts, failed sources",
        [
            f"- Review queue: **{v['review_pending']}** pending ({v['conflicts']} conflicts)",
            f"- Stale deadlines: **{v['stale_deadlines']}**",
            *[
                f"- Failing source: {s['name']} (streak {s['streak']}, last success {s['last_success_at'] or 'never'})"
                for s in v["failing_sources"]
            ],
        ],
    )
    section(
        "8. Monitoring health",
        [
            f"- Sources: {m['sources_configured']} configured, {m['sources_enabled']} enabled, {m['sources_checked_7d']} checked in the last 7 days",
            *[f"- Last successful `{k}`: {v_}" for k, v_ in m["last_jobs"].items()],
            *[f"- **Overdue:** {g}" for g in m["overdue_jobs"]],
        ],
    )
    return "\n".join(out).rstrip() + "\n"
