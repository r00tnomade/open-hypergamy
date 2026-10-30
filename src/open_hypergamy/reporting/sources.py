"""`ohg report sources`: real coverage, never the 200-source target as a count (LLD §6.3).

Per-source health (ADR-009) is derived from the source row plus the last 30 days of
`source_check_runs`; nothing here is a stored aggregate.
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from typing import Any

from open_hypergamy.clock import Clock, iso_z
from open_hypergamy.domain.enums import SourceHealthState
from open_hypergamy.sources.base import SourceRecord
from open_hypergamy.sources.health import health_state
from open_hypergamy.sources.registry import PORTFOLIO_TARGETS

_OK_RUNS = "('success','not_modified','partial')"


def source_metrics(
    conn: sqlite3.Connection, source_id: str, since: str, now: str
) -> dict[str, Any]:
    """Retrieval/extraction rates, HTTP status mix, latency, changes, staleness for one source."""
    runs = conn.execute(
        f"SELECT COUNT(*) AS n, SUM(status IN {_OK_RUNS}) AS ok, "
        "SUM(http_status = 200) AS got200, SUM(http_status = 200 AND status IN ('success','partial')) AS extracted, "
        "AVG(elapsed_ms) AS avg_ms, MAX(elapsed_ms) AS max_ms "
        "FROM source_check_runs WHERE source_id=? AND started_at >= ? AND status != 'skipped'",
        (source_id, since),
    ).fetchone()
    statuses = {
        str(r["code"] if r["code"] is not None else "none"): r["n"]
        for r in conn.execute(
            "SELECT http_status AS code, COUNT(*) AS n FROM source_check_runs WHERE source_id=? "
            "AND started_at >= ? AND status != 'skipped' GROUP BY http_status ORDER BY http_status",
            (source_id, since),
        )
    }
    pages = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(status='active' AND next_check_at <= ?), 0) AS due, "
        "COALESCE(SUM(status='missing'), 0) AS missing, COALESCE(SUM(status='held'), 0) AS held, "
        "COALESCE(SUM(status='invalid'), 0) AS invalid FROM source_pages WHERE source_id=?",
        (now, source_id),
    ).fetchone()
    n, ok, got200 = runs["n"] or 0, runs["ok"] or 0, runs["got200"] or 0
    return {
        "checks_30d": n,
        "pages_tracked": pages["n"],
        "pages_due": pages["due"],
        "pages_missing": pages["missing"],
        "pages_held": pages["held"],
        "pages_invalid": pages["invalid"],
        "retrieval_success_rate": round(ok / n, 3) if n else None,
        "extraction_success_rate": round((runs["extracted"] or 0) / got200, 3) if got200 else None,
        "http_status_counts": statuses,
        "avg_latency_ms": round(runs["avg_ms"]) if runs["avg_ms"] is not None else None,
        "max_latency_ms": runs["max_ms"],
        "content_changes_30d": conn.execute(
            "SELECT COUNT(*) FROM source_observations o JOIN sources s ON s.id=o.source_id "
            "WHERE o.source_id=? AND o.canonical_url=s.canonical_url AND o.retrieved_at >= ?",
            (source_id, since),
        ).fetchone()[0],
        "last_successful_ingestion_at": conn.execute(
            "SELECT MAX(started_at) FROM source_check_runs WHERE source_id=? AND status IN ('success','partial')",
            (source_id,),
        ).fetchone()[0],
        "stale_opportunities": conn.execute(
            "SELECT COUNT(DISTINCT e.id) FROM editions e JOIN candidates c ON c.promoted_edition_id=e.id "
            "WHERE c.discovered_by_source_id=? AND ((e.source_fresh_until IS NOT NULL AND e.source_fresh_until < ?) "
            "OR EXISTS (SELECT 1 FROM deadlines d WHERE d.edition_id=e.id AND d.fact_status='stale'))",
            (source_id, now),
        ).fetchone()[0],
    }


def build_sources_report(conn: sqlite3.Connection, clock: Clock) -> dict[str, Any]:
    now = clock.now_utc()
    since30 = iso_z(now - timedelta(days=30))

    def n(sql: str, *a: Any) -> int:
        return int(conn.execute(sql, a).fetchone()[0] or 0)

    healthy_sql = (
        "enabled=1 AND state='active' AND failure_streak < 2 AND last_success_at >= ? "
        "AND blocked_reason IS NULL AND (cooldown_until IS NULL OR cooldown_until <= ?)"
    )
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
                    iso_z(now),
                ),
            }
        )
    per_source = []
    states = dict.fromkeys((s.value for s in SourceHealthState), 0)
    for r in conn.execute(
        "SELECT s.*, (SELECT COUNT(*) FROM candidates c WHERE c.discovered_by_source_id=s.id) AS candidates, "
        "(SELECT COUNT(*) FROM candidates c WHERE c.discovered_by_source_id=s.id AND c.status='promoted') AS promoted "
        "FROM sources s ORDER BY s.priority DESC, s.name"
    ).fetchall():
        stale = bool(r["enabled"]) and (
            r["last_success_at"] is None
            or r["last_success_at"] < iso_z(now - timedelta(hours=2 * r["fetch_interval_hours"]))
        )
        health = health_state(SourceRecord.from_row(r), now)
        states[health.value] += 1
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
                "health": health.value,
                "last_attempt_at": r["last_attempt_at"],
                "last_http_status": r["last_http_status"],
                "last_error_category": r["last_error_category"],
                "cooldown_until": r["cooldown_until"]
                if health is SourceHealthState.COOLDOWN
                else None,
                "blocked_reason": r["blocked_reason"],
                "blocked_at": r["blocked_at"],
                "last_content_change_at": r["last_content_change_at"],
                **source_metrics(conn, r["id"], since30, iso_z(now)),
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
        "healthy_30d": n(f"SELECT COUNT(*) FROM sources WHERE {healthy_sql}", since30, iso_z(now)),
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
        "health_states": states,
        "stale_opportunities": sum(s["stale_opportunities"] for s in per_source),
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
        "- Health: " + " · ".join(f"{k} {v}" for k, v in r["health_states"].items()),
        f"- Opportunities whose source evidence is stale: {r['stale_opportunities']}",
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
            "| Source | Tier | State | Health | Last success | Streak | OK rate (30d) | Avg ms | Candidates | Promoted | Flags |",
            "|---|---|---|---|---|---:|---:|---:|---:|---:|---|",
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
                f"| {s['name']} | {s['tier'].split('_')[0]} | {s['state']} | {s['health']} | {s['last_success_at'] or 'never'} | {s['failure_streak']} | {_pct(s['retrieval_success_rate'])} | {s['avg_latency_ms'] if s['avg_latency_ms'] is not None else '–'} | {s['candidates']} | {s['promoted']} | {flags} |"
            )
    else:
        out.append("_No sources registered yet._")
    return "\n".join(out) + "\n"


def _pct(rate: float | None) -> str:
    return "–" if rate is None else f"{rate:.0%}"
