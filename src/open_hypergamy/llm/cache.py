"""Response cache over the `llm_cache` table (LLD §9.7). Only validated responses are reused."""

from __future__ import annotations

import json
import sqlite3

from open_hypergamy.clock import Clock, iso_z
from open_hypergamy.persistence.db import transaction


class LLMCache:
    def __init__(self, conn: sqlite3.Connection, clock: Clock, backend: str) -> None:
        self.conn, self.clock, self.backend = conn, clock, backend

    def get(self, key: str) -> dict[str, object] | None:
        row = self.conn.execute(
            "SELECT response_json FROM llm_cache WHERE cache_key=? AND validation_status='valid'",
            (key,),
        ).fetchone()
        if row is None:
            return None
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE llm_cache SET use_count=use_count+1, last_used_at=? WHERE cache_key=?",
                (iso_z(self.clock.now_utc()), key),
            )
        parsed: dict[str, object] = json.loads(row["response_json"])
        return parsed

    def put(
        self,
        key: str,
        *,
        model: str,
        prompt_version: str,
        input_sha256: str,
        response: dict[str, object],
        status: str,
    ) -> None:
        now = iso_z(self.clock.now_utc())
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO llm_cache(cache_key, backend, model_name, prompt_version, input_sha256, "
                "response_json, validation_status, created_at, last_used_at) VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(cache_key) DO UPDATE SET response_json=excluded.response_json, "
                "validation_status=excluded.validation_status, last_used_at=excluded.last_used_at",
                (
                    key,
                    self.backend,
                    model,
                    prompt_version,
                    input_sha256,
                    json.dumps(response, sort_keys=True, separators=(",", ":")),
                    status,
                    now,
                    now,
                ),
            )

    def stats(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT validation_status, COUNT(*) FROM llm_cache GROUP BY validation_status"
        ).fetchall()
        return {r[0]: r[1] for r in rows}
