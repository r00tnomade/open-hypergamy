"""Missed-run detection (LLD §15.2). The machine may sleep; gaps must be visible, not silent."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from open_hypergamy.clock import Clock, iso_z
from open_hypergamy.config import LoadedConfig
from open_hypergamy.scheduling.launchd import installed_jobs


@dataclass(frozen=True)
class Gap:
    job: str
    last_success_at: str | None
    allowed_hours: int
    overdue_hours: int | None  # None = never ran

    def describe(self) -> str:
        if self.overdue_hours is None:
            return f"{self.job}: scheduled but has never completed"
        return (
            f"{self.job}: last success {self.last_success_at}, "
            f"{self.overdue_hours} h past its {self.allowed_hours} h allowance"
        )


def allowed_hours(cfg: LoadedConfig) -> dict[str, int]:
    s = cfg.settings.schedule
    return {
        "sentinel": s.sentinel_max_age_hours,
        "backup": s.backup_max_age_hours,
        "discovery": s.discovery_max_age_days * 24,
        "digest": s.digest_max_age_days * 24,
    }


def last_success(conn: sqlite3.Connection, job: str) -> str | None:
    row = conn.execute(
        "SELECT MAX(started_at) FROM job_runs WHERE job_type=? AND status IN ('success','partial')",
        (job,),
    ).fetchone()
    return row[0] if row and row[0] else None


def job_gaps(
    conn: sqlite3.Connection, cfg: LoadedConfig, clock: Clock, agents_dir: Path | None = None
) -> list[Gap]:
    """Jobs that are expected (a LaunchAgent is installed, or the job has run before) but late."""
    limits = allowed_hours(cfg)
    ran = {r[0] for r in conn.execute("SELECT DISTINCT job_type FROM job_runs")}
    expected = (installed_jobs(agents_dir) | ran) & set(limits)
    now = clock.now_utc()
    gaps = []
    for job in sorted(expected):
        last = last_success(conn, job)
        if last is None:
            gaps.append(Gap(job, None, limits[job], None))
            continue
        age = now - datetime.fromisoformat(last.replace("Z", "+00:00"))
        if age > timedelta(hours=limits[job]):
            gaps.append(Gap(job, last, limits[job], int(age.total_seconds() // 3600) - limits[job]))
    return gaps


def gap_key(g: Gap) -> str:
    return f"gap:{g.job}:{(g.last_success_at or 'never')[:10]}"


def now_iso(clock: Clock) -> str:
    return iso_z(clock.now_utc())
