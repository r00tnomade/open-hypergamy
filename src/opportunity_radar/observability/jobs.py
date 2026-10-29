"""Run tracking for every scheduled job, so `radar status` can show last runs and gaps."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from opportunity_radar.clock import Clock
from opportunity_radar.persistence.repositories.jobs import JobRepository

_TRIGGERS = {"manual", "launchd", "recovery"}


def current_trigger() -> str:
    """`launchd` when a scheduled job set RADAR_TRIGGER; anything unrecognised counts as manual."""
    trigger = os.environ.get("RADAR_TRIGGER", "manual")
    return trigger if trigger in _TRIGGERS else "manual"


@dataclass
class JobHandle:
    status: str = "success"  # callers set "partial"/"failed" before exiting non-zero
    summary: dict[str, Any] = field(default_factory=dict)


@contextmanager
def tracked_job(conn: sqlite3.Connection, clock: Clock, job_type: str) -> Iterator[JobHandle]:
    jobs = JobRepository(conn, clock)
    job_id = jobs.start(job_type, current_trigger())
    handle = JobHandle()
    try:
        yield handle
    except BaseException as e:
        # typer.Exit/SystemExit are BaseExceptions: a handler that chose a status keeps it.
        status = handle.status if handle.status != "success" else "failed"
        jobs.finish(
            job_id,
            status,
            summary=handle.summary,
            error_code=type(e).__name__,
            error_summary=str(e)[:300],
        )
        raise
    jobs.finish(job_id, handle.status, summary=handle.summary)
