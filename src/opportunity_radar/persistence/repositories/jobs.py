"""job_runs tracking."""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from opportunity_radar.clock import Clock, iso_z
from opportunity_radar.persistence.db import transaction


class JobRepository:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn, self.clock = conn, clock

    def start(self, job_type: str, trigger: str = "manual") -> str:
        job_id = str(uuid.uuid4())
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO job_runs(id, job_type, trigger_type, started_at, status) "
                "VALUES (?,?,?,?, 'running')",
                (job_id, job_type, trigger, iso_z(self.clock.now_utc())),
            )
        return job_id

    def finish(
        self,
        job_id: str,
        status: str,
        *,
        counters: dict[str, int] | None = None,
        summary: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_summary: str | None = None,
    ) -> None:
        c = counters or {}
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE job_runs SET finished_at=?, status=?, sources_considered=?, "
                "sources_succeeded=?, sources_failed=?, candidates_found=?, summary_json=?, "
                "error_code=?, error_summary=? WHERE id=?",
                (
                    iso_z(self.clock.now_utc()),
                    status,
                    c.get("considered", 0),
                    c.get("succeeded", 0),
                    c.get("failed", 0),
                    c.get("candidates", 0),
                    json.dumps(summary or {}, sort_keys=True, separators=(",", ":")),
                    error_code,
                    error_summary,
                    job_id,
                ),
            )
