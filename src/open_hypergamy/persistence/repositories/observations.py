"""source_observations persistence shared by health recording and candidate follow-ups."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from open_hypergamy.clock import iso_z
from open_hypergamy.sources.base import PageObservation


def insert_observation(
    conn: sqlite3.Connection,
    obs: PageObservation,
    *,
    source_id: str | None,
    check_run_id: str | None,
    now_iso: str,
) -> tuple[str, bool]:
    """Insert unless (canonical_url, content_hash) is already stored. Returns (id, inserted)."""
    new_id = str(uuid.uuid4())
    cur = conn.execute(
        "INSERT OR IGNORE INTO source_observations(id, source_id, source_check_run_id, "
        "canonical_url, retrieved_at, http_status, mime_type, etag, last_modified, content_hash, "
        "extracted_text_hash, body_cache_relpath, text_cache_relpath, title, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            new_id,
            source_id,
            check_run_id,
            obs.final_url,
            iso_z(obs.fetched_at),
            obs.http_status,
            obs.mime_type,
            obs.etag,
            obs.last_modified,
            obs.content_sha256,
            obs.text_sha256,
            obs.body_cache_relpath,
            obs.text_cache_relpath,
            obs.title,
            now_iso,
        ),
    )
    if cur.rowcount:
        return new_id, True
    row = conn.execute(
        "SELECT id FROM source_observations WHERE canonical_url=? AND content_hash=?",
        (obs.final_url, obs.content_sha256),
    ).fetchone()
    return str(row["id"]), False


def load_text(conn: sqlite3.Connection, cache_root: Path, observation_id: str) -> tuple[str, str]:
    """(title, text) of a stored observation from the local text cache."""
    row = conn.execute(
        "SELECT title, text_cache_relpath FROM source_observations WHERE id=?", (observation_id,)
    ).fetchone()
    if row is None or not row["text_cache_relpath"]:
        raise FileNotFoundError(f"no cached text for observation {observation_id}")
    path = cache_root / row["text_cache_relpath"]
    return row["title"] or "", path.read_text()
