"""Manual review decisions (LLD §14.3).

Accepting a review records that a human looked at it. It never sets `confirmed_official`
(invariant 1); only `resolve_conflict` may choose between claims that are *already* official.
"""

from __future__ import annotations

import sqlite3

from opportunity_radar.clock import Clock, iso_z
from opportunity_radar.discovery.promotion import CONFIRMED, refresh_edition
from opportunity_radar.errors import RadarError
from opportunity_radar.persistence.db import transaction
from opportunity_radar.persistence.repositories.opportunities import OpportunityRepository


def _pending(repo: OpportunityRepository, ref: str) -> sqlite3.Row:
    rev = repo.get_review(ref)
    if rev is None:
        raise RadarError(f"unknown or ambiguous review id: {ref}")
    if rev["state"] != "pending":
        raise RadarError(f"review is already {rev['state']}")
    return rev


def decide(
    conn: sqlite3.Connection, clock: Clock, ref: str, *, accept: bool, note: str
) -> sqlite3.Row:
    repo = OpportunityRepository(conn, clock)
    rev = _pending(repo, ref)
    if accept and rev["reason_code"].endswith("conflict"):
        raise RadarError("conflicts must be settled with `radar review resolve --claim CLAIM_ID`")
    now = iso_z(clock.now_utc())
    with transaction(conn):
        conn.execute(
            "UPDATE review_queue SET state=?, reviewer_notes=?, reviewed_at=?, updated_at=? WHERE id=?",
            ("accepted" if accept else "rejected", note, now, now, rev["id"]),
        )
        if rev["claim_id"]:  # records the human look only; fact_status is untouched
            conn.execute("UPDATE claims SET reviewed_at=? WHERE id=?", (now, rev["claim_id"]))
    result = repo.get_review(rev["id"])
    assert result is not None
    return result


def resolve_conflict(
    conn: sqlite3.Connection, clock: Clock, ref: str, *, claim_id: str, note: str
) -> None:
    """Pick the winning value among official claims of a deadline/event-date conflict."""
    repo = OpportunityRepository(conn, clock)
    rev = _pending(repo, ref)
    if not rev["reason_code"].endswith("conflict"):
        raise RadarError("only conflict reviews can be resolved")
    claim = conn.execute(
        "SELECT * FROM claims WHERE id = ? OR id LIKE ?", (claim_id, claim_id + "%")
    ).fetchone()
    if claim is None or claim["fact_status"] != CONFIRMED:
        raise RadarError("the chosen claim must exist and be backed by an official source")
    import json

    value = json.loads(claim["proposed_value_json"]).get("date")
    now_dt = clock.now_utc()
    with transaction(conn):
        if claim["deadline_id"]:
            dl = conn.execute(
                "SELECT * FROM deadlines WHERE id=?", (claim["deadline_id"],)
            ).fetchone()
            if dl is None or dl["edition_id"] != rev["edition_id"]:
                raise RadarError("claim does not belong to this review's edition")
            repo.update_deadline_tx(dl["id"], due_date=value, status=CONFIRMED, verified=True)
        elif (
            claim["field_name"] in ("event_start_date", "event_end_date")
            and claim["edition_id"] == rev["edition_id"]
        ):
            conn.execute(
                f"UPDATE editions SET {claim['field_name']}=?, updated_at=? WHERE id=?",
                (value, iso_z(now_dt), rev["edition_id"]),
            )
        else:
            raise RadarError("claim does not belong to this review's edition")
        conn.execute(
            "UPDATE review_queue SET state='accepted', reviewer_notes=?, reviewed_at=?, updated_at=? "
            "WHERE id=?",
            (f"resolved with claim {claim['id']}: {note}", iso_z(now_dt), iso_z(now_dt), rev["id"]),
        )
        conn.execute(
            "UPDATE editions SET last_material_change_at=? WHERE id=?",
            (iso_z(now_dt), rev["edition_id"]),
        )
        refresh_edition(
            repo, conn, rev["edition_id"], now_dt.date(), now_dt, False, verified_now=False
        )
