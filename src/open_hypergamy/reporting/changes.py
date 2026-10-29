"""`ohg report changes`: what moved since a date. Read-only."""

from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from typing import Any

from open_hypergamy.clock import Clock, iso_z


def build_changes(conn: sqlite3.Connection, clock: Clock, since: timedelta) -> dict[str, Any]:
    cutoff = iso_z(clock.now_utc() - since)

    def rows(sql: str, *a: Any) -> list[sqlite3.Row]:
        return conn.execute(sql, a).fetchall()

    new_editions = rows(
        "SELECT display_name, official_url, fact_status FROM editions WHERE first_seen_at >= ?",
        cutoff,
    )
    moved = []
    for d in rows(
        "SELECT d.id, d.deadline_type, d.due_date_local, e.display_name, e.official_url FROM deadlines d "
        "JOIN editions e ON e.id=d.edition_id WHERE d.fact_status IN ('confirmed_official','stale')"
    ):
        claims = rows(
            "SELECT proposed_value_json, created_at FROM claims WHERE deadline_id=? AND "
            "fact_status='confirmed_official' ORDER BY created_at, rowid",
            d["id"],
        )
        dates = [json.loads(c[0]).get("date") for c in claims]
        if len(set(dates)) >= 2 and claims[-1]["created_at"] >= cutoff:
            old = next((x for x in reversed(dates) if x != dates[-1]), None)
            moved.append(
                {
                    "name": d["display_name"],
                    "type": d["deadline_type"],
                    "from": old,
                    "to": dates[-1],
                    "url": d["official_url"],
                }
            )
    band_changes = []
    for e in rows("SELECT id, display_name FROM editions"):
        latest = rows(
            "SELECT priority_band, fit_score FROM score_snapshots WHERE edition_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
            e["id"],
        )
        before = rows(
            "SELECT priority_band FROM score_snapshots WHERE edition_id=? AND created_at < ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
            e["id"],
            cutoff,
        )
        if latest and before and latest[0]["priority_band"] != before[0]["priority_band"]:
            band_changes.append(
                {
                    "name": e["display_name"],
                    "from": before[0]["priority_band"],
                    "to": latest[0]["priority_band"],
                }
            )
    return {
        "since": cutoff,
        "new_editions": [dict(r) for r in new_editions],
        "moved_deadlines": moved,
        "priority_changes": band_changes,
        "reviews_opened": [
            dict(r)
            for r in rows(
                "SELECT reason_code, priority, title FROM review_queue WHERE created_at >= ?",
                cutoff,
            )
        ],
        "alerts_sent": {
            r[0]: r[1]
            for r in rows(
                "SELECT notification_type, COUNT(*) FROM notification_log WHERE status='sent' AND sent_at >= ? GROUP BY 1",
                cutoff,
            )
        },
        "sources_failed": [
            dict(r)
            for r in rows(
                "SELECT s.name, COUNT(*) AS failures FROM source_check_runs r JOIN sources s ON s.id=r.source_id WHERE r.status IN ('failed','blocked_policy') AND r.started_at >= ? GROUP BY s.id",
                cutoff,
            )
        ],
    }


def render_markdown(c: dict[str, Any]) -> str:
    out = [f"# Changes since {c['since']}", ""]

    def section(title: str, items: list[str]) -> None:
        out.extend([f"## {title}", "", *(items or ["_None._"]), ""])

    section(
        "New editions",
        [
            f"- [{e['display_name']}]({e['official_url']}) ({e['fact_status']})"
            for e in c["new_editions"]
        ],
    )
    section(
        "Moved deadlines",
        [
            f"- [{m['name']}]({m['url']}): {m['type']} {m['from']} → **{m['to']}**"
            for m in c["moved_deadlines"]
        ],
    )
    section(
        "Priority changes",
        [f"- {p['name']}: {p['from']} → {p['to']}" for p in c["priority_changes"]],
    )
    section(
        "Review items opened",
        [f"- [{r['priority']}] {r['reason_code']}: {r['title']}" for r in c["reviews_opened"]],
    )
    section("Alerts sent", [f"- {k}: {v}" for k, v in c["alerts_sent"].items()])
    section(
        "Source failures",
        [f"- {s['name']}: {s['failures']} failed check(s)" for s in c["sources_failed"]],
    )
    return "\n".join(out).rstrip() + "\n"
