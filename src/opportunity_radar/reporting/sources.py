"""`radar report sources`: real coverage, never the 200-source target as a count (LLD §6.3)."""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from typing import Any

from opportunity_radar.clock import Clock, iso_z
from opportunity_radar.sources.registry import PORTFOLIO_TARGETS


def build_sources_report(conn: sqlite3.Connection, clock: Clock) -> dict[str, Any]:
    now = clock.now_utc()
    since30 = iso_z(now - timedelta(days=30))

    def n(sql: str, *a: Any) -> int:
        return int(conn.execute(sql, a).fetchone()[0] or 0)

    healthy_sql = "enabled=1 AND state='active' AND failure_streak < 2 AND last_success_at >= ?"
    portfolio = []
    for name, target in PORTFOLIO_TARGETS.items():
        portfolio.append(
            {
                "portfolio": name,
                "target": target,
                "configured": n("SELECT COUNT(*) FROM sources WHERE portfolio=?", name),
                "enabled": n(
                    "SELECT COUNT(*) FROM sources WHERE portfolio=? AND enabled=1 AND state='active'",
                    name,
                ),
                "healthy": n(
                    f"SELECT COUNT(*) FROM sources WHERE portfolio=? AND {healthy_sql}",
                    name,
                    since30,
                ),
            }
        )
    per_source = []
    for r in conn.execute(
        "SELECT s.*, (SELECT COUNT(*) FROM candidates c WHERE c.discovered_by_source_id=s.id) AS candidates, "
        "(SELECT COUNT(*) FROM candidates c WHERE c.discovered_by_source_id=s.id AND c.status='promoted') AS promoted "
        "FROM sources s ORDER BY s.priority DESC, s.name"
    ).fetchall():
        stale = bool(r["enabled"]) and (
            r["last_success_at"] is None
            or r["last_success_at"] < iso_z(now - timedelta(hours=2 * r["fetch_interval_hours"]))
        )
        per_source.append(
            {
                "key": r["source_key"],
                "name": r["name"],
                "tier": r["trust_tier"],
                "state": r["state"],
                "portfolio": r["portfolio"],
                "discovery_only": bool(r["discovery_only"]),
                "last_success_at": r["last_success_at"],
                "failure_streak": r["failure_streak"],
                "stale": stale,
                "candidates": r["candidates"],
                "promoted": r["promoted"],
                "policy_reviewed": bool(r["robots_policy_checked_at"] and r["terms_review_note"]),
            }
        )
    return {
        "generated_at": iso_z(now),
        "target": sum(PORTFOLIO_TARGETS.values()),
        "configured": n("SELECT COUNT(*) FROM sources"),
        "enabled": n("SELECT COUNT(*) FROM sources WHERE enabled=1 AND state='active'"),
        "healthy_30d": n(f"SELECT COUNT(*) FROM sources WHERE {healthy_sql}", since30),
        "review_required": n("SELECT COUNT(*) FROM sources WHERE state='review_required'"),
        "official_t1_t2": n(
            "SELECT COUNT(*) FROM sources WHERE trust_tier IN ('t1_official_program','t2_official_org')"
        ),
        "discovery_only": n("SELECT COUNT(*) FROM sources WHERE discovery_only=1"),
        "failing_2plus": n("SELECT COUNT(*) FROM sources WHERE failure_streak >= 2"),
        "never_checked": n(
            "SELECT COUNT(*) FROM sources WHERE enabled=1 AND last_success_at IS NULL"
        ),
        "unassigned_portfolio": n("SELECT COUNT(*) FROM sources WHERE portfolio IS NULL"),
        "portfolio": portfolio,
        "sources": per_source,
    }


def render_markdown(r: dict[str, Any]) -> str:
    out = [
        "# Source coverage report",
        "",
        f"_Generated {r['generated_at']}._",
        "",
        f"**Target:** ~{r['target']} curated sources. **Actual:** {r['configured']} configured, "
        f"{r['enabled']} enabled, {r['healthy_30d']} healthy (successful check in the last 30 days, "
        f"fewer than 2 consecutive failures).",
        "",
        f"- Awaiting policy review: {r['review_required']}",
        f"- Official (T1/T2): {r['official_t1_t2']} · discovery-only: {r['discovery_only']}",
        f"- Failing 2+ checks in a row: {r['failing_2plus']} · enabled but never checked: {r['never_checked']}",
        f"- Not assigned to a portfolio: {r['unassigned_portfolio']}",
        "",
        "## Portfolio vs target",
        "",
        "| Portfolio | Target | Configured | Enabled | Healthy |",
        "|---|---:|---:|---:|---:|",
        *[
            f"| {p['portfolio']} | {p['target']} | {p['configured']} | {p['enabled']} | {p['healthy']} |"
            for p in r["portfolio"]
        ],
        "",
        "## Sources",
        "",
    ]
    if r["sources"]:
        out += [
            "| Source | Tier | State | Last success | Streak | Candidates | Promoted | Flags |",
            "|---|---|---|---|---:|---:|---:|---|",
        ]
        for s in r["sources"]:
            flags = ", ".join(
                f
                for f, on in (
                    ("stale", s["stale"]),
                    ("no policy review", not s["policy_reviewed"]),
                    ("discovery-only", s["discovery_only"]),
                )
                if on
            )
            out.append(
                f"| {s['name']} | {s['tier'].split('_')[0]} | {s['state']} | {s['last_success_at'] or 'never'} | {s['failure_streak']} | {s['candidates']} | {s['promoted']} | {flags} |"
            )
    else:
        out.append("_No sources registered yet._")
    return "\n".join(out) + "\n"
