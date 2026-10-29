"""Direct re-verification of the official pages behind imminent deadlines (LLD §6.5, §10.3).

An unchanged page produces no new observation, so without this step confirmed deadlines would
simply go stale. A successful recheck renews freshness (and restores `stale` -> confirmed when
the content is identical); a failure leaves the fact stale and visible. A changed page goes
through the normal verification pipeline.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date

from opportunity_radar.clock import Clock, iso_z, local_today
from opportunity_radar.config import LoadedConfig
from opportunity_radar.discovery.pipeline import PipelineStats, process_observations
from opportunity_radar.discovery.promotion import refresh_edition
from opportunity_radar.errors import RadarError
from opportunity_radar.extraction.llm_extractor import LLMExtractionService
from opportunity_radar.persistence.db import transaction
from opportunity_radar.persistence.repositories.observations import insert_observation
from opportunity_radar.persistence.repositories.opportunities import OpportunityRepository
from opportunity_radar.persistence.repositories.sources import SourceRepository
from opportunity_radar.sources.base import FetchContext
from opportunity_radar.sources.common import build_observation, decode_body
from opportunity_radar.sources.fetch import BodyCache, Fetcher
from opportunity_radar.sources.html import parse_html
from opportunity_radar.verification.chronology import freshness_window

log = logging.getLogger(__name__)


@dataclass
class RecheckReport:
    reverified: int = 0
    changed: int = 0
    failed: int = 0
    failures: list[str] = field(default_factory=list)


def renew_freshness(conn: sqlite3.Connection, clock: Clock, edition_id: str) -> None:
    """The evidence page was read again and says the same thing: facts are fresh again."""
    now_dt = clock.now_utc()
    today, now = local_today(now_dt), iso_z(now_dt)
    close = conn.execute(
        "SELECT due_date_local FROM deadlines WHERE edition_id=? AND deadline_type='application_close' "
        "AND fact_status IN ('confirmed_official','stale') LIMIT 1",
        (edition_id,),
    ).fetchone()
    close_d = date.fromisoformat(close[0]) if close and close[0] else None
    with transaction(conn):
        conn.execute(
            "UPDATE deadlines SET fact_status='confirmed_official', last_verified_at=?, updated_at=? "
            "WHERE edition_id=? AND fact_status='stale'",
            (now, now, edition_id),
        )
        conn.execute(
            "UPDATE deadlines SET last_verified_at=? WHERE edition_id=? AND fact_status='confirmed_official'",
            (now, edition_id),
        )
        conn.execute(
            "UPDATE editions SET last_verified_at=?, source_fresh_until=?, updated_at=? WHERE id=?",
            (now, iso_z(now_dt + freshness_window(close_d, today)), now, edition_id),
        )
        refresh_edition(
            OpportunityRepository(conn, clock),
            conn,
            edition_id,
            today,
            now_dt,
            False,
            verified_now=False,
        )


def recheck_editions(
    conn: sqlite3.Connection,
    cfg: LoadedConfig,
    fetcher: Fetcher,
    clock: Clock,
    edition_ids: list[str],
    llm: LLMExtractionService | None = None,
) -> RecheckReport:
    rep = RecheckReport()
    repo = SourceRepository(conn, clock)
    seen: set[str] = set()
    for eid in edition_ids:
        cand = conn.execute(
            "SELECT canonical_url, discovered_by_source_id FROM candidates WHERE promoted_edition_id=? "
            "AND discovered_by_source_id IS NOT NULL ORDER BY first_seen_at LIMIT 1",
            (eid,),
        ).fetchone()
        source = repo.get(cand["discovered_by_source_id"]) if cand else None
        if cand is None or source is None or not source.enabled:
            continue
        url = cand["canonical_url"]
        if url in seen:
            renew_freshness(conn, clock, eid)
            continue
        seen.add(url)
        etag, lm = repo.latest_validators(url)
        try:
            resp = fetcher.fetch(url, source.scope, etag=etag, last_modified=lm)
        except RadarError as e:
            rep.failed += 1
            rep.failures.append(f"{url}: {e.code}")
            log.info("recheck failed for %s: %s", url, e)
            continue
        if resp.not_modified:
            rep.reverified += 1
            renew_freshness(conn, clock, eid)
            continue
        title, text, links, meta = parse_html(
            decode_body(resp.body, resp.mime_type), resp.final_url
        )
        ctx = FetchContext(
            fetcher=fetcher,
            settings=cfg.settings.app,
            cache=BodyCache(cfg.paths.cache) if cfg.settings.cache.enabled else None,
        )
        obs = build_observation(
            source, resp, ctx, title=title, text=text, links=links, meta=meta, depth=1
        )
        with transaction(conn):
            obs_id, is_new = insert_observation(
                conn, obs, source_id=source.id, check_run_id=None, now_iso=iso_z(clock.now_utc())
            )
        if not is_new:  # byte-identical to what we verified before
            rep.reverified += 1
            renew_freshness(conn, clock, eid)
            continue
        rep.changed += 1
        process_observations(
            conn, cfg, fetcher, clock, source, [(obs_id, obs)], PipelineStats(), llm
        )
    return rep
