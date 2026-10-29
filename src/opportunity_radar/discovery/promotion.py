"""Candidate -> programme/edition/deadline promotion in one transaction (LLD §8.4, §10).

Nothing here talks to the network. Statuses come only from `verification.rules.verify_fact`;
conflicts between authority-equivalent official sources are preserved, never silently resolved.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime
from urllib.parse import urlsplit

from opportunity_radar.clock import Clock, iso_z
from opportunity_radar.discovery.normalize import (
    edition_year,
    normalize_title,
    registrable_domain,
)
from opportunity_radar.domain.enums import DeadlineType, FactStatus
from opportunity_radar.domain.models import CandidateFact
from opportunity_radar.extraction.deterministic import DEADLINE_PREFIX
from opportunity_radar.persistence.db import transaction
from opportunity_radar.persistence.repositories.opportunities import OpportunityRepository
from opportunity_radar.verification.chronology import (
    check_chronology,
    derive_application_status,
    freshness_window,
)
from opportunity_radar.verification.evidence import ground_facts
from opportunity_radar.verification.rules import VerificationResult, verify_fact

_DEADLINE_TYPES = {t.value for t in DeadlineType}
CONFIRMED = FactStatus.CONFIRMED_OFFICIAL.value


@dataclass(frozen=True)
class Authority:
    """What the evidence's source may establish (LLD §10.1)."""

    trust_tier: str
    discovery_only: bool
    allowed_domains: tuple[str, ...]

    def covers(self, url: str) -> bool:
        host = (urlsplit(url).hostname or "").lower()
        return any(host == d or host.endswith("." + d) for d in self.allowed_domains)


@dataclass
class PromotionInput:
    candidate_id: str
    title: str
    official_url: str
    evidence_url: str
    observation_id: str | None
    text: str
    facts: list[CandidateFact]
    category: str | None
    edition_key: str | None
    announced_not_open: bool
    source_id: str | None
    source_org_id: str | None
    authority: Authority


@dataclass
class PromotionOutcome:
    status: str = "promoted"  # promoted | needs_review
    edition_id: str | None = None
    program_id: str | None = None
    claims_added: int = 0
    rejected: int = 0
    reviews_added: int = 0
    reasons: list[str] = field(default_factory=list)


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _same_publisher(a: str, b: str) -> bool:
    return registrable_domain(_host(a)) == registrable_domain(_host(b))


def promote_candidate(
    conn: sqlite3.Connection,
    clock: Clock,
    inp: PromotionInput,
    *,
    program_id: str | None = None,
    new_program: bool = False,
) -> PromotionOutcome:
    repo = OpportunityRepository(conn, clock)
    now_dt = clock.now_utc()
    today = now_dt.date()
    out = PromotionOutcome()
    cid = inp.candidate_id

    def hold(reason: str, title: str, details: str = "") -> PromotionOutcome:
        with transaction(conn):
            added = repo.add_review_tx(
                reason=reason, priority="high", title=title, details=details, candidate_id=cid
            )
            repo.set_candidate_status_tx(cid, "needs_review", reason=reason)
        out.status, out.reasons, out.reviews_added = "needs_review", [reason], int(added)
        return out

    if not inp.edition_key:
        return hold(
            "edition_key_unknown",
            f"Edition/year unknown: {inp.title}",
            "No explicit year or cycle in title, URL or event dates; supply --edition-key.",
        )

    norm = normalize_title(inp.title)
    with transaction(conn):
        org_id = repo.ensure_org_tx(inp.source_org_id, registrable_domain(_host(inp.official_url)))
        prog = (
            repo.get_program(program_id)
            if program_id
            else repo.find_program(org_id, norm, inp.official_url)
        )
        if prog is None and not new_program:
            similar = repo.similar_programs(org_id, norm)
            if similar:
                names = ", ".join(
                    f"{r['canonical_name']} ({ratio:.2f})" for r, ratio in similar[:3]
                )
                repo.add_review_tx(
                    reason="possible_duplicate_program",
                    priority="high",
                    title=f"Possible duplicate programme: {inp.title}",
                    details=f"Similar existing programmes: {names}",
                    candidate_id=cid,
                )
                repo.set_candidate_status_tx(
                    cid, "needs_review", reason="possible_duplicate_program"
                )
                out.status, out.reasons, out.reviews_added = (
                    "needs_review",
                    ["possible_duplicate_program"],
                    1,
                )
                return out
        pid = (
            prog["id"]
            if prog
            else repo.create_program_tx(org_id, inp.title, norm, inp.category, inp.official_url)
        )
        ed = repo.get_edition_tx(pid, inp.edition_key)
        eid = (
            ed["id"]
            if ed
            else repo.create_edition_tx(pid, inp.edition_key, inp.title, inp.official_url)
        )
        out.program_id, out.edition_id = pid, eid
        _apply_facts(repo, inp, eid, today, out)
        _enforce_chronology(repo, eid, out)
        refresh_edition(repo, conn, eid, today, now_dt, inp.announced_not_open)
        repo.set_candidate_status_tx(cid, "promoted", promoted_edition_id=eid)
    return out


# ----------------------------------------------------------------------------------------
def _priority(reason: str, field_name: str) -> str:
    if reason.endswith("conflict"):
        return "critical"
    if field_name in (f"{DEADLINE_PREFIX}application_close", f"{DEADLINE_PREFIX}application_open"):
        return "high"
    return "medium"


def _apply_facts(
    repo: OpportunityRepository, inp: PromotionInput, eid: str, today: date, out: PromotionOutcome
) -> None:
    a = inp.authority
    in_scope = a.covers(inp.evidence_url) and _same_publisher(inp.evidence_url, inp.official_url)
    haystack = f"{inp.title}\n{inp.text}"
    facts = ground_facts(inp.facts, haystack)
    values: dict[str, set[str]] = {}
    for f in facts:
        if f.date_value:
            values.setdefault(f.field_name, set()).add(f.date_value)
    year = edition_year(inp.edition_key)

    def claim(
        f: CandidateFact, v: VerificationResult, *, deadline_id: str | None = None
    ) -> str | None:
        q = f.evidence[0]
        cid, inserted = repo.insert_claim_tx(
            edition_id=eid,
            deadline_id=deadline_id,
            field_name=f.field_name,
            value=f.proposed_value,
            status=v.status.value,
            source_id=inp.source_id,
            observation_id=inp.observation_id,
            source_url=q.source_url,
            trust_tier=a.trust_tier,
            excerpt=q.excerpt,
            method=f.extraction_method,
            note=";".join(v.reasons),
        )
        out.claims_added += int(inserted)
        if v.needs_review and inserted:
            reason = v.reasons[0] if v.reasons else "needs_review"
            out.reviews_added += int(
                repo.add_review_tx(
                    reason=reason,
                    priority=_priority(reason, f.field_name),
                    claim_id=cid,
                    edition_id=eid,
                    title=f"{f.field_name}: {f.raw_text or ''}".strip(),
                    details=f"{reason}; excerpt: {q.excerpt[:300]}",
                )
            )
        return cid

    # Edition-level descriptive claims (never critical).
    unverified = VerificationResult(FactStatus.UNVERIFIED)
    if inp.title and not repo.has_claim_tx(eid, "title"):
        out.claims_added += int(
            repo.insert_claim_tx(
                edition_id=eid,
                field_name="title",
                value={"value": inp.title},
                status="unverified",
                source_id=inp.source_id,
                observation_id=inp.observation_id,
                source_url=inp.evidence_url,
                trust_tier=a.trust_tier,
                excerpt=inp.title,
                method="structured_page",
            )[1]
        )

    for f in facts:
        if f.grounded is not True:
            out.rejected += 1  # unsupported claim: rejected, never stored (LLD §9.5)
            continue
        if f.field_name == "application_status":
            claim(f, unverified)
            continue
        v = verify_fact(
            f,
            source_trust_tier=a.trust_tier,
            discovery_only=a.discovery_only,
            url_in_scope=in_scope,
            today=today,
            edition_year=year,
            distinct_values_for_field=len(values.get(f.field_name, ())),
        )
        if f.field_name.startswith(DEADLINE_PREFIX):
            dtype = f.field_name[len(DEADLINE_PREFIX) :]
            if dtype in _DEADLINE_TYPES and f.date_value:
                _apply_deadline(repo, inp, eid, dtype, f, v, claim)
            else:
                claim(f, v)
        elif f.field_name in ("event_start_date", "event_end_date"):
            _apply_event(repo, inp, eid, f, v, claim)
        else:
            claim(f, v)


def _apply_deadline(repo, inp, eid, dtype, f, v, claim) -> None:  # type: ignore[no-untyped-def]
    new_date, confirmed = f.date_value, v.status is FactStatus.CONFIRMED_OFFICIAL
    cur = repo.get_deadline_tx(eid, dtype)
    if cur is None:
        did = repo.insert_deadline_tx(
            eid, dtype, new_date, f.raw_text or "", v.status.value, confirmed
        )
        claim(f, v, deadline_id=did)
        return
    did = cur["id"]
    old_confirmed = cur["fact_status"] == CONFIRMED
    if cur["due_date_local"] == new_date:
        claim(f, v, deadline_id=did)
        if confirmed:
            keep = cur["fact_status"] if cur["fact_status"] == "conflicting_sources" else CONFIRMED
            repo.update_deadline_tx(did, status=keep, verified=True)
        return
    # Different date.
    if cur["fact_status"] == "conflicting_sources":
        claim(f, v, deadline_id=did)  # stays conflicting until a reviewer resolves it
    elif confirmed and old_confirmed:
        prev = repo.last_confirmed_claim_tx(did)
        if prev is not None and _same_publisher(prev["source_url"], inp.evidence_url):
            cid = claim(
                f, v, deadline_id=did
            )  # the publisher changed its own date: material change
            repo.update_deadline_tx(
                did, due_date=new_date, raw=f.raw_text, status=CONFIRMED, verified=True
            )
            repo.conn.execute(
                "UPDATE editions SET last_material_change_at=?, updated_at=? WHERE id=?",
                (repo.now, repo.now, eid),
            )
            _ = cid
        else:
            cid = claim(f, v, deadline_id=did)
            repo.update_deadline_tx(did, status="conflicting_sources")
            repo.add_review_tx(
                reason="deadline_conflict",
                priority="critical",
                claim_id=cid,
                edition_id=eid,
                title=f"Conflicting {dtype}: {cur['due_date_local']} vs {new_date}",
                details=f"Existing {cur['due_date_local']} ({cur['raw_date_text']}); "
                f"new {new_date} from {inp.evidence_url}",
            )
            repo.conn.execute(
                "UPDATE editions SET last_material_change_at=?, updated_at=? WHERE id=?",
                (repo.now, repo.now, eid),
            )
    elif confirmed and not old_confirmed:
        claim(f, v, deadline_id=did)  # official evidence replaces an unverified value
        repo.update_deadline_tx(
            did, due_date=new_date, raw=f.raw_text, status=CONFIRMED, verified=True
        )
    else:
        cid = claim(f, v, deadline_id=did)  # weaker evidence never overrides the stored value
        if old_confirmed:
            repo.add_review_tx(
                reason="unverified_source_disagrees",
                priority="medium",
                claim_id=cid,
                edition_id=eid,
                title=f"Unverified {dtype} {new_date} vs confirmed {cur['due_date_local']}",
                details=f"Source: {inp.evidence_url}",
            )


def _apply_event(repo, inp, eid, f, v, claim) -> None:  # type: ignore[no-untyped-def]
    col = f.field_name
    cid = claim(f, v)
    if not (v.status is FactStatus.CONFIRMED_OFFICIAL and f.date_value):
        return  # critical fields are materialized only once confirmed
    ed = repo.conn.execute(f"SELECT {col} FROM editions WHERE id=?", (eid,)).fetchone()
    cur = ed[col]
    if cur == f.date_value:
        return
    if cur is not None:
        prev = repo.last_confirmed_edition_claim_tx(eid, col)
        # `claim` just inserted the new one; compare with the newest *other* confirmed claim.
        rows = repo.conn.execute(
            "SELECT source_url FROM claims WHERE edition_id=? AND field_name=? AND "
            "fact_status='confirmed_official' AND id != ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (eid, col, cid),
        ).fetchone()
        _ = prev
        if rows is not None and not _same_publisher(rows["source_url"], inp.evidence_url):
            repo.add_review_tx(
                reason="event_date_conflict",
                priority="critical",
                claim_id=cid,
                edition_id=eid,
                title=f"Conflicting {col}: {cur} vs {f.date_value}",
                details=f"New value from {inp.evidence_url}",
            )
            return
        repo.conn.execute(
            "UPDATE editions SET last_material_change_at=? WHERE id=?", (repo.now, eid)
        )
    repo.conn.execute(
        f"UPDATE editions SET {col}=?, updated_at=? WHERE id=?", (f.date_value, repo.now, eid)
    )


def _confirmed_date(repo: OpportunityRepository, eid: str, dtype: str) -> date | None:
    row = repo.get_deadline_tx(eid, dtype)
    if row and row["fact_status"] == CONFIRMED and row["due_date_local"]:
        return date.fromisoformat(row["due_date_local"])
    return None


def _enforce_chronology(repo: OpportunityRepository, eid: str, out: PromotionOutcome) -> None:
    ed = repo.conn.execute(
        "SELECT event_start_date, event_end_date FROM editions WHERE id=?", (eid,)
    ).fetchone()
    problems = check_chronology(
        open_date=_confirmed_date(repo, eid, "application_open"),
        close_date=_confirmed_date(repo, eid, "application_close"),
        event_start=date.fromisoformat(ed["event_start_date"]) if ed["event_start_date"] else None,
        event_end=date.fromisoformat(ed["event_end_date"]) if ed["event_end_date"] else None,
    )
    if not problems:
        return
    for dtype in ("application_open", "application_close"):  # demote: logic does not hold
        row = repo.get_deadline_tx(eid, dtype)
        if row and row["fact_status"] == CONFIRMED:
            repo.update_deadline_tx(row["id"], status="unverified")
    out.reasons += problems
    out.reviews_added += int(
        repo.add_review_tx(
            reason="chronology_invalid",
            priority="high",
            edition_id=eid,
            title="Dates fail chronology checks",
            details=", ".join(problems),
        )
    )


def refresh_edition(
    repo: OpportunityRepository,
    conn: sqlite3.Connection,
    eid: str,
    today: date,
    now_dt: datetime,
    announced_now: bool,
) -> None:
    rows = repo.deadlines_for(eid)
    conflicting = any(r["fact_status"] == "conflicting_sources" for r in rows) or bool(
        conn.execute(
            "SELECT 1 FROM review_queue WHERE edition_id=? AND state='pending' "
            "AND reason_code LIKE '%conflict'",
            (eid,),
        ).fetchone()
    )
    open_d = _confirmed_date(repo, eid, "application_open")
    close_d = _confirmed_date(repo, eid, "application_close")
    announced = announced_now or repo.has_claim_tx(eid, "application_status")
    app_status = derive_application_status(
        open_date=open_d,
        close_date=close_d,
        today=today,
        announced_not_open=announced,
        conflicting=conflicting,
    )
    if conflicting:
        fact = "conflicting_sources"
    elif close_d is not None:
        fact = CONFIRMED
    elif announced and open_d is None:
        fact = "announced_not_open"
    else:
        fact = "unverified"
    lifecycle = {"open": "applications_open", "closed": "applications_closed"}.get(
        app_status, "announced"
    )
    confirmed_any = any(r["fact_status"] == CONFIRMED for r in rows) or bool(
        conn.execute(
            "SELECT 1 FROM editions WHERE id=? AND event_start_date IS NOT NULL", (eid,)
        ).fetchone()
    )
    fresh_until = iso_z(now_dt + freshness_window(close_d, today)) if confirmed_any else None
    conn.execute(
        "UPDATE editions SET fact_status=?, application_status=?, lifecycle_status=?, "
        "last_seen_at=?, last_verified_at=CASE WHEN ? THEN ? ELSE last_verified_at END, "
        "source_fresh_until=COALESCE(?, source_fresh_until), updated_at=? WHERE id=?",
        (
            fact,
            app_status,
            lifecycle,
            iso_z(now_dt),
            int(confirmed_any),
            iso_z(now_dt),
            fresh_until,
            iso_z(now_dt),
            eid,
        ),
    )
