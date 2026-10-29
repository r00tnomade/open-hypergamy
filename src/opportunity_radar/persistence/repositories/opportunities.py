"""Candidates, programmes, editions, deadlines, claims and review items (LLD §4, §8).

Methods named `*_tx` run inside the caller's transaction; the others open their own.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from difflib import SequenceMatcher
from typing import Any

from opportunity_radar.clock import Clock, iso_z
from opportunity_radar.persistence.db import transaction
from opportunity_radar.verification.evidence import excerpt_sha256


def j(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _one(rows: list[sqlite3.Row]) -> sqlite3.Row | None:
    """A unique match, else None (ambiguous id prefixes resolve to nothing)."""
    return rows[0] if len(rows) == 1 else None


def new_id() -> str:
    return str(uuid.uuid4())


class OpportunityRepository:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn, self.clock = conn, clock

    def _fetchone(self, sql: str, args: tuple[Any, ...]) -> sqlite3.Row | None:
        row: sqlite3.Row | None = self.conn.execute(sql, args).fetchone()
        return row

    @property
    def now(self) -> str:
        return iso_z(self.clock.now_utc())

    # -- candidates (own transactions) ----------------------------------------------------
    def upsert_candidate(
        self,
        *,
        source_id: str | None,
        observation_id: str | None,
        url: str,
        title: str,
        normalized_title: str,
        organizer_domain: str,
        category: str | None,
        edition_key: str | None,
        fingerprint: str,
        metadata: dict[str, Any],
    ) -> tuple[str, str]:
        """Returns (candidate_id, outcome) with outcome created | seen | duplicate."""
        with transaction(self.conn):
            row = self.conn.execute(
                "SELECT id FROM candidates WHERE canonical_url = ? ORDER BY first_seen_at LIMIT 1",
                (url,),
            ).fetchone()
            if row:
                self.conn.execute(
                    "UPDATE candidates SET last_seen_at=? WHERE id=?", (self.now, row["id"])
                )
                return str(row["id"]), "seen"
            twin = self.conn.execute(
                "SELECT id FROM candidates WHERE normalized_fingerprint=? AND status != 'duplicate' "
                "ORDER BY first_seen_at LIMIT 1",
                (fingerprint,),
            ).fetchone()
            cid = new_id()
            self.conn.execute(
                "INSERT INTO candidates(id, discovered_by_source_id, discovered_from_observation_id, "
                "discovered_url, canonical_url, normalized_title, organizer_name_guess, "
                "candidate_type, event_year_guess, normalized_fingerprint, status, "
                "duplicate_of_candidate_id, first_seen_at, last_seen_at, metadata_json, "
                "organizer_domain, edition_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    cid,
                    source_id,
                    observation_id,
                    url,
                    url,
                    normalized_title,
                    organizer_domain,
                    category,
                    int(edition_key[:4]) if edition_key else None,
                    fingerprint,
                    "duplicate" if twin else "new",
                    twin["id"] if twin else None,
                    self.now,
                    self.now,
                    j({"title": title, **metadata}),
                    organizer_domain,
                    edition_key,
                ),
            )
            return cid, "duplicate" if twin else "created"

    def update_candidate_identity(
        self,
        cid: str,
        *,
        normalized_title: str,
        category: str | None,
        edition_key: str | None,
        fingerprint: str,
        metadata: dict[str, Any],
    ) -> None:
        with transaction(self.conn):
            old = self.conn.execute(
                "SELECT metadata_json FROM candidates WHERE id=?", (cid,)
            ).fetchone()
            merged = {**json.loads(old["metadata_json"]), **metadata}
            self.conn.execute(
                "UPDATE candidates SET normalized_title=?, candidate_type=?, edition_key=?, "
                "event_year_guess=?, normalized_fingerprint=?, metadata_json=? WHERE id=?",
                (
                    normalized_title,
                    category,
                    edition_key,
                    int(edition_key[:4]) if edition_key else None,
                    fingerprint,
                    j(merged),
                    cid,
                ),
            )

    def merge_candidate_metadata(self, cid: str, extra: dict[str, Any]) -> None:
        with transaction(self.conn):
            old = self.conn.execute(
                "SELECT metadata_json FROM candidates WHERE id=?", (cid,)
            ).fetchone()
            self.conn.execute(
                "UPDATE candidates SET metadata_json=? WHERE id=?",
                (j({**json.loads(old["metadata_json"]), **extra}), cid),
            )

    def get_candidate(self, cid: str) -> sqlite3.Row | None:
        row = self.conn.execute(
            "SELECT * FROM candidates WHERE id = ? OR id LIKE ?", (cid, cid + "%")
        ).fetchall()
        return _one(row)

    def list_candidates(self, status: str | None, limit: int) -> list[sqlite3.Row]:
        sql, args = "SELECT * FROM candidates", []
        if status:
            sql += " WHERE status = ?"
            args.append(status)
        return self.conn.execute(
            sql + " ORDER BY last_seen_at DESC LIMIT ?", [*args, limit]
        ).fetchall()

    def set_candidate_status(
        self,
        cid: str,
        status: str,
        *,
        reason: str | None = None,
        promoted_edition_id: str | None = None,
    ) -> None:
        with transaction(self.conn):
            self.set_candidate_status_tx(
                cid, status, reason=reason, promoted_edition_id=promoted_edition_id
            )

    def set_candidate_status_tx(
        self,
        cid: str,
        status: str,
        *,
        reason: str | None = None,
        promoted_edition_id: str | None = None,
    ) -> None:
        self.conn.execute(
            "UPDATE candidates SET status=?, processed_at=?, rejection_reason=COALESCE(?, "
            "rejection_reason), promoted_edition_id=COALESCE(?, promoted_edition_id) WHERE id=?",
            (status, self.now, reason, promoted_edition_id, cid),
        )

    # -- organizations / programmes / editions (in caller's transaction) -------------------
    def ensure_org_tx(self, source_org_id: str | None, domain: str) -> str:
        if source_org_id:
            return source_org_id
        row = self.conn.execute(
            "SELECT id FROM organizations WHERE canonical_domain = ?", (domain,)
        ).fetchone()
        if row:
            return str(row["id"])
        oid = new_id()
        self.conn.execute(
            "INSERT INTO organizations(id, name, canonical_domain, homepage_url, created_at, "
            "updated_at) VALUES (?,?,?,?,?,?)",
            (oid, domain, domain, f"https://{domain}/", self.now, self.now),
        )
        return oid

    def find_program(self, org_id: str, normalized_name: str, url: str) -> sqlite3.Row | None:
        return self._fetchone(
            "SELECT * FROM programs WHERE (canonical_url = ? AND normalized_name = ?) "
            "OR (organization_id = ? AND normalized_name = ?) LIMIT 1",
            (url, normalized_name, org_id, normalized_name),
        )

    def similar_programs(
        self, org_id: str, normalized_name: str, threshold: float = 0.88
    ) -> list[tuple[sqlite3.Row, float]]:
        out = []
        for r in self.conn.execute("SELECT * FROM programs WHERE organization_id = ?", (org_id,)):
            ratio = SequenceMatcher(None, normalized_name, r["normalized_name"]).ratio()
            if ratio >= threshold and r["normalized_name"] != normalized_name:
                out.append((r, ratio))
        return sorted(out, key=lambda x: -x[1])

    def create_program_tx(
        self, org_id: str, name: str, normalized_name: str, category: str | None, url: str
    ) -> str:
        pid = new_id()
        self.conn.execute(
            "INSERT INTO programs(id, organization_id, canonical_name, normalized_name, category, "
            "canonical_url, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (pid, org_id, name, normalized_name, category or "other", url, self.now, self.now),
        )
        return pid

    def get_edition_tx(self, program_id: str, edition_key: str) -> sqlite3.Row | None:
        return self._fetchone(
            "SELECT * FROM editions WHERE program_id=? AND edition_key=?", (program_id, edition_key)
        )

    def create_edition_tx(self, program_id: str, edition_key: str, name: str, url: str) -> str:
        eid = new_id()
        self.conn.execute(
            "INSERT INTO editions(id, program_id, edition_key, display_name, official_url, "
            "first_seen_at, last_seen_at, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (eid, program_id, edition_key, name, url, self.now, self.now, self.now, self.now),
        )
        return eid

    # -- claims / deadlines / reviews (in caller's transaction) ----------------------------
    def insert_claim_tx(
        self,
        *,
        edition_id: str | None = None,
        deadline_id: str | None = None,
        field_name: str,
        value: object,
        status: str,
        source_id: str | None,
        observation_id: str | None,
        source_url: str,
        trust_tier: str,
        excerpt: str,
        method: str,
        note: str = "",
        supersedes: str | None = None,
        model_name: str | None = None,
        prompt_version: str | None = None,
    ) -> tuple[str, bool]:
        """Append a claim unless an identical one already exists. Returns (id, inserted)."""
        target_col = "deadline_id" if deadline_id else "edition_id"
        target = deadline_id or edition_id
        sha = excerpt_sha256(excerpt)
        dup = self.conn.execute(
            f"SELECT id FROM claims WHERE {target_col}=? AND field_name=? AND proposed_value_json=? "
            "AND source_url=? AND excerpt_sha256=?",
            (target, field_name, j(value), source_url, sha),
        ).fetchone()
        if dup:
            return str(dup["id"]), False
        cid = new_id()
        self.conn.execute(
            "INSERT INTO claims(id, edition_id, deadline_id, field_name, proposed_value_json, "
            "normalized_value_json, fact_status, source_id, source_observation_id, source_url, "
            "source_trust_tier, excerpt, excerpt_sha256, extraction_method, verifier_note, "
            "supersedes_claim_id, created_at, model_name, prompt_version) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                cid,
                None if deadline_id else edition_id,
                deadline_id,
                field_name,
                j(value),
                j(value),
                status,
                source_id,
                observation_id,
                source_url,
                trust_tier,
                excerpt,
                sha,
                method,
                note,
                supersedes,
                self.now,
                model_name,
                prompt_version,
            ),
        )
        return cid, True

    def get_deadline_tx(self, edition_id: str, deadline_type: str) -> sqlite3.Row | None:
        return self._fetchone(
            "SELECT * FROM deadlines WHERE edition_id=? AND deadline_type=? "
            "ORDER BY created_at LIMIT 1",
            (edition_id, deadline_type),
        )

    def insert_deadline_tx(
        self,
        edition_id: str,
        deadline_type: str,
        due_date: str,
        raw: str,
        status: str,
        verified: bool,
    ) -> str:
        did = new_id()
        self.conn.execute(
            "INSERT INTO deadlines(id, edition_id, deadline_type, label, due_date_local, "
            "time_precision, raw_date_text, fact_status, is_hard_deadline, last_verified_at, "
            "created_at, updated_at) VALUES (?,?,?,?,?, 'date_only', ?,?,?,?,?,?)",
            (
                did,
                edition_id,
                deadline_type,
                deadline_type.replace("_", " ").title(),
                due_date,
                raw,
                status,
                0 if deadline_type == "application_open" else 1,
                self.now if verified else None,
                self.now,
                self.now,
            ),
        )
        return did

    def update_deadline_tx(
        self,
        did: str,
        *,
        due_date: str | None = None,
        raw: str | None = None,
        status: str | None = None,
        verified: bool = False,
    ) -> None:
        self.conn.execute(
            "UPDATE deadlines SET due_date_local=COALESCE(?, due_date_local), "
            "raw_date_text=COALESCE(?, raw_date_text), fact_status=COALESCE(?, fact_status), "
            "last_verified_at=CASE WHEN ? THEN ? ELSE last_verified_at END, updated_at=? WHERE id=?",
            (due_date, raw, status, int(verified), self.now, self.now, did),
        )

    def last_confirmed_claim_tx(self, deadline_id: str) -> sqlite3.Row | None:
        return self._fetchone(
            "SELECT * FROM claims WHERE deadline_id=? AND fact_status='confirmed_official' "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (deadline_id,),
        )

    def add_review_tx(
        self,
        *,
        reason: str,
        priority: str,
        title: str,
        details: str = "",
        claim_id: str | None = None,
        candidate_id: str | None = None,
        edition_id: str | None = None,
    ) -> bool:
        dup = self.conn.execute(
            "SELECT 1 FROM review_queue WHERE state='pending' AND reason_code=? AND claim_id IS ? "
            "AND candidate_id IS ? AND edition_id IS ?",
            (reason, claim_id, candidate_id, edition_id),
        ).fetchone()
        if dup:
            return False
        self.conn.execute(
            "INSERT INTO review_queue(id, claim_id, candidate_id, edition_id, reason_code, priority, "
            "title, details, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                new_id(),
                claim_id,
                candidate_id,
                edition_id,
                reason,
                priority,
                title,
                details[:1000],
                self.now,
                self.now,
            ),
        )
        return True

    # -- read side -------------------------------------------------------------------------
    def list_editions(self, limit: int = 100) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT e.*, p.canonical_name, o.name AS org_name FROM editions e "
            "JOIN programs p ON p.id = e.program_id LEFT JOIN organizations o ON o.id = p.organization_id "
            "ORDER BY e.last_seen_at DESC LIMIT ?",
            (limit,),
        ).fetchall()

    def get_edition(self, ref: str) -> sqlite3.Row | None:
        rows = self.conn.execute(
            "SELECT e.*, p.canonical_name FROM editions e JOIN programs p ON p.id=e.program_id "
            "WHERE e.id = ? OR e.id LIKE ?",
            (ref, ref + "%"),
        ).fetchall()
        return _one(rows)

    def deadlines_for(self, edition_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM deadlines WHERE edition_id=? ORDER BY due_date_local", (edition_id,)
        ).fetchall()

    def claims_for_edition(self, edition_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT c.*, d.deadline_type FROM claims c LEFT JOIN deadlines d ON d.id=c.deadline_id "
            "WHERE c.edition_id=? OR d.edition_id=? ORDER BY c.created_at, c.rowid",
            (edition_id, edition_id),
        ).fetchall()

    def deadlines_between(self, start_iso: str, end_iso: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT d.*, e.display_name, e.official_url FROM deadlines d JOIN editions e ON "
            "e.id=d.edition_id WHERE d.due_date_local BETWEEN ? AND ? ORDER BY d.due_date_local",
            (start_iso, end_iso),
        ).fetchall()

    def list_reviews(self, state: str, priority: str | None) -> list[sqlite3.Row]:
        sql, args = "SELECT * FROM review_queue WHERE state = ?", [state]
        if priority:
            sql += " AND priority = ?"
            args.append(priority)
        order = " ORDER BY CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, created_at"
        return self.conn.execute(sql + order, args).fetchall()

    def get_review(self, ref: str) -> sqlite3.Row | None:
        rows = self.conn.execute(
            "SELECT * FROM review_queue WHERE id = ? OR id LIKE ?", (ref, ref + "%")
        ).fetchall()
        return _one(rows)

    def last_confirmed_edition_claim_tx(
        self, edition_id: str, field_name: str
    ) -> sqlite3.Row | None:
        return self._fetchone(
            "SELECT * FROM claims WHERE edition_id=? AND field_name=? "
            "AND fact_status='confirmed_official' ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (edition_id, field_name),
        )

    def get_program(self, program_id: str) -> sqlite3.Row | None:
        return self._fetchone("SELECT * FROM programs WHERE id=?", (program_id,))

    def has_claim_tx(self, edition_id: str, field_name: str) -> bool:
        return (
            self._fetchone(
                "SELECT 1 FROM claims WHERE edition_id=? AND field_name=?", (edition_id, field_name)
            )
            is not None
        )
