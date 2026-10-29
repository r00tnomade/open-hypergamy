"""Rescoring: eligibility assessment, fit/urgency snapshot, action state and action items.

Each step is append-only or idempotent, so re-running a job never creates duplicates and an
unchanged result writes nothing (LLD §12.2).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field

from open_hypergamy.clock import Clock, iso_z, local_today
from open_hypergamy.config import LoadedConfig
from open_hypergamy.domain.enums import EligibilityStatus
from open_hypergamy.persistence.db import transaction
from open_hypergamy.persistence.repositories.opportunities import OpportunityRepository, j
from open_hypergamy.profile import Profile
from open_hypergamy.scoring.actions import (
    ACTION_POLICY_VERSION,
    MANAGED_ACTIONS,
    ActionSpec,
    plan_actions,
    priority_band,
    recommended_action,
)
from open_hypergamy.scoring.fit import SCORING_VERSION, compute_fit
from open_hypergamy.scoring.urgency import compute_urgency
from open_hypergamy.verification.eligibility import Eligibility, assess

log = logging.getLogger(__name__)
FINAL_ACTIONS = ("applied", "accepted", "rejected", "withdrawn")


@dataclass
class ScoreOutcome:
    edition_id: str
    name: str = ""
    fit: float = 0.0
    urgency: float = 0.0
    band: str = "low"
    eligibility: str = "possibly_eligible"
    action: str = "monitor"
    reasons: list[str] = field(default_factory=list)
    problem: str | None = None
    distance_days: int | None = None
    snapshot_written: bool = False
    action_changed: bool = False
    year_blocked: bool = False


def _latest(claims: list[sqlite3.Row], field_name: str) -> dict[str, object] | None:
    found = [c for c in claims if c["field_name"] == field_name]
    if not found:
        return None
    last = found[-1]
    value = json.loads(last["proposed_value_json"])
    return (
        {**value, "_confirmed": last["fact_status"] == "confirmed_official"}
        if isinstance(value, dict)
        else None
    )


def _requirements(claims: list[sqlite3.Row]) -> list[tuple[str, str, str | None]]:
    seen: dict[str, tuple[str, str, str | None]] = {}
    for c in claims:
        if c["field_name"] != "eligibility":
            continue
        v = json.loads(c["proposed_value_json"])
        text = str(v.get("value", "")).strip()
        if text and text.lower() not in seen:
            seen[text.lower()] = (text, str(v.get("blocking", "unknown")), c["id"])
    return list(seen.values())


def _persist_eligibility(
    conn: sqlite3.Connection, now: str, eid: str, profile: Profile, e: Eligibility
) -> None:
    criteria = j([c.as_dict() for c in e.criteria])
    last = conn.execute(
        "SELECT status, criteria_json, profile_version FROM eligibility_assessments WHERE edition_id=? "
        "ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (eid,),
    ).fetchone()
    if last and (last["status"], last["criteria_json"], last["profile_version"]) == (
        e.status.value,
        criteria,
        profile.profile_version,
    ):
        return
    conn.execute(
        "INSERT INTO eligibility_assessments(id, edition_id, profile_version, status, blocking_count, "
        "unresolved_count, assessment_summary, criteria_json, assessed_by, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            str(uuid.uuid4()),
            eid,
            profile.profile_version,
            e.status.value,
            e.blocking_count,
            e.unresolved_count,
            e.summary[:500],
            criteria,
            "llm_assisted" if e.criteria else "rules",
            now,
        ),
    )


def _sync_actions(
    conn: sqlite3.Connection, now: str, eid: str, specs: list[ActionSpec], priority_ok: bool
) -> None:
    keys = set()
    for s in specs:
        k = s.key(eid)
        keys.add(k)
        row = conn.execute(
            "SELECT id, status FROM action_items WHERE idempotency_key=?", (k,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO action_items(id, edition_id, deadline_id, action_type, title, description, "
                "due_date_local, status, priority, idempotency_key, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?, 'open', ?,?,?,?)",
                (
                    str(uuid.uuid4()),
                    eid,
                    s.deadline_id,
                    s.action_type,
                    s.title,
                    s.description,
                    s.due_date_local,
                    s.priority,
                    k,
                    now,
                    now,
                ),
            )
        elif row["status"] == "open":  # completed/dismissed items are left alone
            conn.execute(
                "UPDATE action_items SET title=?, description=?, due_date_local=?, priority=?, "
                "updated_at=? WHERE id=?",
                (s.title, s.description, s.due_date_local, s.priority, now, row["id"]),
            )
    pattern = f"action:{eid}:%:{ACTION_POLICY_VERSION}"
    for row in conn.execute(
        "SELECT id, idempotency_key FROM action_items WHERE idempotency_key LIKE ? "
        "AND status='open'",
        (pattern,),
    ).fetchall():
        if row["idempotency_key"] not in keys:
            conn.execute(
                "UPDATE action_items SET status='dismissed', updated_at=?, description="
                "description || ' (auto-dismissed: no longer applicable)' WHERE id=?",
                (now, row["id"]),
            )
    _ = priority_ok


def rescore_edition(
    conn: sqlite3.Connection, cfg: LoadedConfig, clock: Clock, profile: Profile, edition_id: str
) -> ScoreOutcome:
    repo = OpportunityRepository(conn, clock)
    ed = repo.get_edition(edition_id)
    assert ed is not None
    prog = repo.get_program(ed["program_id"])
    assert prog is not None
    claims, deadlines = repo.claims_for_edition(edition_id), repo.deadlines_for(edition_id)
    now_dt = clock.now_utc()
    today, now = local_today(now_dt), iso_z(now_dt)

    elig = assess(_requirements(claims), profile)
    urg = compute_urgency(ed, deadlines, today, now_dt)
    topic = " ".join(
        [ed["display_name"], prog["canonical_name"], prog["category"] or ""]
        + [c["excerpt"] for c in claims if c["field_name"] not in ("deadline",)]
    )
    funding, fee = _latest(claims, "funding"), _latest(claims, "fee")
    fmt, loc = _latest(claims, "format"), _latest(claims, "location")
    fit = compute_fit(
        topic=topic,
        category=prog["category"],
        eligibility=elig.status,
        funding_status=str(funding["status"]) if funding else None,
        funding_confirmed=bool(funding and funding["_confirmed"]),
        fee_max=float(fee["max"] or fee["min"] or 0) if fee else None,  # type: ignore[arg-type]
        fmt=str(fmt["value"]) if fmt else None,
        location=str(loc["value"]) if loc else None,
        profile=profile,
        weights=cfg.settings.scoring.weights,
    )
    reasons = list(dict.fromkeys(fit.reasons + urg.reasons))
    if (
        elig.status in (EligibilityStatus.NEEDS_REVIEW, EligibilityStatus.POSSIBLY_ELIGIBLE)
        and elig.unresolved_count
    ):
        reasons.append("ELIGIBILITY_UNCLEAR")
    if elig.year_blocked and (profile.academic.current_year or 0) <= 1:
        reasons.append("FIRST_YEAR_INELIGIBLE")
    unresolved_critical = any(
        c.assessment == "unclear" and c.blocking_flag != "false" for c in elig.criteria
    )
    app_status = ed["application_status"]
    band = priority_band(fit.fit, urg.score, elig.status, app_status, unresolved_critical)
    rec = recommended_action(elig.status, band, app_status, urg, today)
    if urg.problem == "stale" and ed["user_action"] in ("apply", "prepare") and rec == "monitor":
        rec = ed["user_action"]  # a lapsed date must not silently demote an actionable opportunity

    out = ScoreOutcome(
        edition_id,
        ed["display_name"],
        fit.fit,
        urg.score,
        band,
        elig.status.value,
        rec,
        reasons,
        urg.problem,
        urg.distance_days,
        year_blocked=elig.year_blocked,
    )
    components = {**fit.components, "urgency": urg.score}
    with transaction(conn):
        _persist_eligibility(conn, now, edition_id, profile, elig)
        last = conn.execute(
            "SELECT * FROM score_snapshots WHERE edition_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (edition_id,),
        ).fetchone()
        same = last and (
            last["scoring_version"],
            last["profile_version"],
            last["fit_score"],
            last["urgency_score"],
            last["priority_band"],
            last["reason_codes_json"],
            last["eligibility_status"],
            last["deadline_distance_days"],
        ) == (
            SCORING_VERSION,
            profile.profile_version,
            fit.fit,
            urg.score,
            band,
            j(reasons),
            elig.status.value,
            urg.distance_days,
        )
        if not same:
            conn.execute(
                "INSERT INTO score_snapshots(id, edition_id, scoring_version, fit_score, urgency_score, "
                "priority_band, component_scores_json, reason_codes_json, eligibility_status, "
                "deadline_distance_days, created_at, profile_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(uuid.uuid4()),
                    edition_id,
                    SCORING_VERSION,
                    fit.fit,
                    urg.score,
                    band,
                    j(components),
                    j(reasons),
                    elig.status.value,
                    urg.distance_days,
                    now,
                    profile.profile_version,
                ),
            )
            out.snapshot_written = True
        current = ed["user_action"]
        revive = (
            current == "archived"
            and last is not None
            and last["eligibility_status"] == "ineligible"
        )
        managed = not ed["action_locked"] and (current in MANAGED_ACTIONS or revive)
        if managed and rec != current:
            conn.execute(
                "UPDATE editions SET user_action=?, updated_at=? WHERE id=?", (rec, now, edition_id)
            )
            out.action_changed = True
        effective = rec if managed else current
        specs: list[ActionSpec] = []
        if effective in MANAGED_ACTIONS:
            rec_dl = next(
                (
                    d
                    for d in deadlines
                    if d["deadline_type"] == "recommendation_letter"
                    and d["due_date_local"]
                    and d["due_date_local"] >= today.isoformat()
                ),
                None,
            )
            close = next((d for d in deadlines if d["deadline_type"] == "application_close"), None)
            specs = plan_actions(
                name=ed["display_name"],
                action=effective,
                elig=elig.status,
                unresolved=unresolved_critical,
                urg=urg,
                reasons=reasons,
                today=today,
                recommendation_deadline=(rec_dl["id"], rec_dl["due_date_local"])
                if rec_dl
                else None,
                close_status=close["fact_status"] if close else None,
            )
        _sync_actions(conn, now, edition_id, specs, managed)
    out.action = effective
    return out


def rescore_all(
    conn: sqlite3.Connection, cfg: LoadedConfig, clock: Clock, profile: Profile
) -> list[ScoreOutcome]:
    ids = [r["id"] for r in conn.execute("SELECT id FROM editions ORDER BY created_at").fetchall()]
    out = []
    for eid in ids:
        try:
            out.append(rescore_edition(conn, cfg, clock, profile, eid))
        except Exception:  # noqa: BLE001 - one edition must not block the rest
            log.exception("rescoring failed for edition %s", eid)
    return out
