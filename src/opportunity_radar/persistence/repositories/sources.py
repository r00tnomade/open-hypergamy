"""Source registry persistence: idempotent import, due selection, health recording."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import timedelta

from opportunity_radar.clock import Clock, iso_z
from opportunity_radar.errors import ConfigurationError
from opportunity_radar.observability.logging import redact
from opportunity_radar.persistence.db import transaction
from opportunity_radar.persistence.repositories.observations import insert_observation
from opportunity_radar.sources.base import PageObservation, SourceRecord
from opportunity_radar.sources.registry import SourceConfig


def _j(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


@dataclass
class ImportReport:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    review_required: list[str] = field(default_factory=list)
    overridden: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CheckOutcome:
    status: str  # SourceRunStatus value
    started_at: str
    finished_at: str
    http_status: int | None = None
    final_url: str | None = None
    elapsed_ms: int | None = None
    bytes_received: int | None = None
    retry_count: int = 0
    content_hash: str | None = None
    text_hash: str | None = None
    error_code: str | None = None
    error_detail: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    observations: tuple[PageObservation, ...] = ()


class SourceRepository:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn, self.clock = conn, clock

    # -- queries --------------------------------------------------------------------------
    def get(self, ref: str) -> SourceRecord | None:
        row = self.conn.execute(
            "SELECT * FROM sources WHERE id = ? OR source_key = ?", (ref, ref)
        ).fetchone()
        return SourceRecord.from_row(row) if row else None

    def list_sources(
        self, *, enabled: bool | None = None, trust_tier: str | None = None
    ) -> list[SourceRecord]:
        sql = "SELECT * FROM sources WHERE 1=1"
        args: list[object] = []
        if enabled is not None:
            sql += " AND enabled = ?"
            args.append(int(enabled))
        if trust_tier:
            sql += " AND trust_tier = ?"
            args.append(trust_tier)
        rows = self.conn.execute(sql + " ORDER BY priority DESC, name", args).fetchall()
        return [SourceRecord.from_row(r) for r in rows]

    def list_due(self, now_iso: str, limit: int | None = None) -> list[SourceRecord]:
        sql = (
            "SELECT * FROM sources WHERE enabled = 1 AND state = 'active' "
            "AND (next_due_at IS NULL OR next_due_at <= ?) ORDER BY priority DESC, next_due_at"
        )
        args: list[object] = [now_iso]
        if limit:
            sql += " LIMIT ?"
            args.append(limit)
        return [SourceRecord.from_row(r) for r in self.conn.execute(sql, args)]

    def latest_validators(self, url: str) -> tuple[str | None, str | None]:
        row = self.conn.execute(
            "SELECT etag, last_modified FROM source_observations WHERE canonical_url = ? "
            "ORDER BY retrieved_at DESC LIMIT 1",
            (url,),
        ).fetchone()
        return (row["etag"], row["last_modified"]) if row else (None, None)

    def failures(self, since_iso: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT s.id, s.source_key, s.name, s.failure_streak, s.last_success_at, "
            "r.started_at, r.status, r.http_status, r.error_code, r.error_detail_redacted "
            "FROM sources s JOIN source_check_runs r ON r.source_id = s.id "
            "WHERE r.status IN ('failed','blocked_policy') AND r.started_at >= ? "
            "ORDER BY r.started_at DESC",
            (since_iso,),
        ).fetchall()

    def coverage(self) -> dict[str, int]:
        since = iso_z(self.clock.now_utc() - timedelta(days=30))

        def n(sql: str, *a: object) -> int:
            return int(self.conn.execute(sql, a).fetchone()[0])

        return {
            "configured": n("SELECT COUNT(*) FROM sources"),
            "enabled": n("SELECT COUNT(*) FROM sources WHERE enabled=1 AND state='active'"),
            "review_required": n("SELECT COUNT(*) FROM sources WHERE state='review_required'"),
            "checked_ok_last_30d": n(
                "SELECT COUNT(*) FROM sources WHERE last_success_at >= ?", since
            ),
            "t1_t2": n(
                "SELECT COUNT(*) FROM sources WHERE trust_tier IN "
                "('t1_official_program','t2_official_org')"
            ),
            "discovery_only": n("SELECT COUNT(*) FROM sources WHERE discovery_only=1"),
            "failing_2plus": n("SELECT COUNT(*) FROM sources WHERE failure_streak >= 2"),
        }

    # -- registry import ------------------------------------------------------------------
    def import_configs(
        self,
        configs: list[SourceConfig],
        *,
        override_policy_review: bool = False,
        dry_run: bool = False,
    ) -> ImportReport:
        report = ImportReport()
        now = iso_z(self.clock.now_utc())
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            for c in configs:
                self._import_one(c, now, override_policy_review, report)
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("ROLLBACK" if dry_run else "COMMIT")
        return report

    def _org_id(self, c: SourceConfig, now: str) -> str | None:
        o = c.organization
        if o is None:
            return None
        row = self.conn.execute(
            "SELECT id FROM organizations WHERE name = ? AND canonical_domain IS ?",
            (o.name, o.canonical_domain),
        ).fetchone()
        if row:
            return str(row["id"])
        oid = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO organizations(id,name,canonical_domain,country_code,organization_type,"
            "homepage_url,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                oid,
                o.name,
                o.canonical_domain,
                o.country_code,
                o.organization_type,
                f"https://{o.canonical_domain}/" if o.canonical_domain else None,
                now,
                now,
            ),
        )
        return oid

    def _import_one(self, c: SourceConfig, now: str, override: bool, report: ImportReport) -> None:
        existing = self.conn.execute(
            "SELECT * FROM sources WHERE source_key = ? OR canonical_url = ?",
            (c.source_key, c.canonical_url),
        ).fetchone()
        satisfied = c.policy_review_satisfied
        overridden = override and not satisfied
        activate = satisfied or override
        robots = c.robots_policy_checked_at.isoformat() if c.robots_policy_checked_at else None
        fields = {
            "source_key": c.source_key,
            "organization_id": self._org_id(c, now),
            "name": c.name,
            "canonical_url": c.canonical_url,
            "domain": c.domain,
            "source_type": c.source_type,
            "adapter_type": c.adapter_type.value,
            "trust_tier": c.trust_tier.value,
            "authority_scope": c.authority_scope,
            "topic_tags_json": _j(c.topic_tags),
            "geographic_scope_json": _j(c.geographic_scope),
            "language_codes_json": _j(c.language_codes),
            "allowed_domains_json": _j(c.allowed_domains),
            "allow_paths_json": _j(c.allow_paths),
            "deny_paths_json": _j(c.deny_paths),
            "terms_review_note": c.terms_review_note,
            "robots_policy_checked_at": robots,
            "fetch_interval_hours": c.fetch_interval_hours,
            "priority": c.priority,
            "discovery_policy_json": _j(c.discovery_policy.model_dump()),
            "extraction_hints_json": _j(c.extraction_hints),
            "discovery_only": int(c.discovery_only),
            "updated_at": now,
        }
        if existing is None:
            enabled = int(c.enabled and activate)
            state = "active" if activate else "review_required"
            fields |= {
                "id": str(uuid.uuid4()),
                "enabled": enabled,
                "state": state,
                "created_at": now,
                "policy_override_at": now if overridden else None,
            }
            cols = ", ".join(fields)
            self.conn.execute(
                f"INSERT INTO sources({cols}) VALUES ({', '.join('?' * len(fields))})",
                list(fields.values()),
            )
            report.created.append(c.source_key)
        else:
            # Configuration only: health fields (streak, etag, hashes, timestamps) are untouched.
            if existing["state"] == "review_required" and activate:
                fields |= {"state": "active", "enabled": int(c.enabled)}
                if overridden:
                    fields["policy_override_at"] = now
            sets = ", ".join(f"{k} = ?" for k in fields)
            self.conn.execute(
                f"UPDATE sources SET {sets} WHERE id = ?", [*fields.values(), existing["id"]]
            )
            report.updated.append(c.source_key)
        if not activate:
            report.review_required.append(c.source_key)
        if overridden:
            report.overridden.append(c.source_key)

    def add_manual(
        self, url: str, *, trust_tier: str, discovery_only: bool, name: str | None
    ) -> str:
        """`radar sources add`: always review-required and disabled until policy review."""
        from opportunity_radar.sources.urls import canonicalize_url, check_static_host, host_of

        canonical = canonicalize_url(url)
        host = host_of(canonical)
        check_static_host(host)
        now = iso_z(self.clock.now_utc())
        sid = str(uuid.uuid4())
        key = "manual-" + sid[:8]
        with transaction(self.conn):
            if self.conn.execute(
                "SELECT 1 FROM sources WHERE canonical_url=?", (canonical,)
            ).fetchone():
                raise ConfigurationError(f"source already registered: {canonical}")
            self.conn.execute(
                "INSERT INTO sources(id, source_key, name, canonical_url, domain, source_type, "
                "adapter_type, trust_tier, allowed_domains_json, enabled, state, discovery_only, "
                "created_at, updated_at) VALUES (?,?,?,?,?,'manual_url','html',?,?,0,"
                "'review_required',?,?,?)",
                (
                    sid,
                    key,
                    name or host,
                    canonical,
                    host,
                    trust_tier,
                    _j([host]),
                    int(discovery_only),
                    now,
                    now,
                ),
            )
        return key

    # -- state changes --------------------------------------------------------------------
    def set_enabled(
        self, ref: str, enabled: bool, *, override_policy_review: bool = False
    ) -> SourceRecord:
        src = self.get(ref)
        if src is None:
            raise ConfigurationError(f"unknown source: {ref}")
        now = iso_z(self.clock.now_utc())
        with transaction(self.conn):
            if enabled:
                if src.state == "review_required":
                    if not override_policy_review:
                        raise ConfigurationError(
                            f"{src.source_key} has not passed policy review; complete "
                            "robots/terms review in its YAML and re-import, or pass "
                            "--override-policy-review (audited)"
                        )
                    self.conn.execute(
                        "UPDATE sources SET policy_override_at=? WHERE id=?", (now, src.id)
                    )
                self.conn.execute(
                    "UPDATE sources SET enabled=1, state='active', updated_at=? WHERE id=?",
                    (now, src.id),
                )
            else:
                self.conn.execute(
                    "UPDATE sources SET enabled=0, state='paused', updated_at=? WHERE id=?",
                    (now, src.id),
                )
        updated = self.get(src.id)
        assert updated is not None
        return updated

    # -- health recording -----------------------------------------------------------------
    def record_check(
        self, source: SourceRecord, outcome: CheckOutcome, job_run_id: str | None
    ) -> list[tuple[str, PageObservation]]:
        """Persist one check atomically; returns the newly stored (id, observation) pairs. A failure never touches facts or last-known content."""
        ok = outcome.status in ("success", "not_modified", "partial")
        blocked = outcome.status == "blocked_policy"
        now = self.clock.now_utc()
        interval = timedelta(hours=source.fetch_interval_hours)
        if ok:
            streak, next_due = 0, now + interval
        elif blocked or outcome.status == "skipped":  # not a source failure; retry next interval
            streak, next_due = source.failure_streak, now + interval
        else:
            streak = source.failure_streak + 1
            backoff = timedelta(hours=min(2 ** (streak - 1), source.fetch_interval_hours))
            next_due = now + backoff
        run_id = str(uuid.uuid4())
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO source_check_runs(id, source_id, job_run_id, started_at, finished_at, "
                "status, http_status, final_url, elapsed_ms, bytes_received, retry_count, "
                "content_hash, extracted_text_hash, error_code, error_detail_redacted) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    source.id,
                    job_run_id,
                    outcome.started_at,
                    outcome.finished_at,
                    outcome.status,
                    outcome.http_status,
                    outcome.final_url,
                    outcome.elapsed_ms,
                    outcome.bytes_received,
                    outcome.retry_count,
                    outcome.content_hash,
                    outcome.text_hash,
                    outcome.error_code,
                    redact(outcome.error_detail)[:500] if outcome.error_detail else None,
                ),
            )
            changed = False
            inserted: list[tuple[str, PageObservation]] = []
            for obs in outcome.observations:
                if obs.not_modified:
                    continue
                obs_id, was_new = insert_observation(
                    self.conn, obs, source_id=source.id, check_run_id=run_id, now_iso=iso_z(now)
                )
                if was_new:
                    inserted.append((obs_id, obs))
                    changed = changed or obs.depth == 0
            sets = [
                "last_attempt_at = ?",
                "failure_streak = ?",
                "next_due_at = ?",
                "last_http_status = ?",
                "updated_at = ?",
            ]
            args: list[object] = [
                iso_z(now),
                streak,
                iso_z(next_due),
                outcome.http_status,
                iso_z(now),
            ]
            if ok:
                sets.append("last_success_at = ?")
                args.append(iso_z(now))
            if ok and outcome.status != "not_modified":
                sets += ["etag = ?", "last_modified = ?", "last_content_hash = ?"]
                args += [outcome.etag, outcome.last_modified, outcome.content_hash]
                if changed:
                    sets.append("last_content_change_at = ?")
                    args.append(iso_z(now))
            self.conn.execute(
                f"UPDATE sources SET {', '.join(sets)} WHERE id = ?", [*args, source.id]
            )
        return inserted
