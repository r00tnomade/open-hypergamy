"""Observation -> candidates -> (follow official page) -> verified promotion (LLD §4.2, §8).

Network access (following a candidate's link) happens outside any DB transaction and goes
through the same policy-aware `Fetcher` as discovery.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from typing import Any

from opportunity_radar.clock import Clock, iso_z
from opportunity_radar.config import LoadedConfig
from opportunity_radar.discovery.candidates import CandidateDraft, drafts_from_observation
from opportunity_radar.discovery.normalize import (
    clean_title,
    fingerprint,
    guess_category,
    guess_edition_key,
    normalize_title,
    organizer_domain,
    registrable_domain,
)
from opportunity_radar.discovery.promotion import (
    Authority,
    PromotionInput,
    PromotionOutcome,
    promote_candidate,
)
from opportunity_radar.domain.enums import TrustTier
from opportunity_radar.domain.models import CandidateFact, ExtractionMethod
from opportunity_radar.errors import LLMInvalidResponse, LLMUnavailable, RadarError
from opportunity_radar.extraction.deterministic import detect_not_open, extract_date_facts
from opportunity_radar.extraction.llm_extractor import LLMExtractionService
from opportunity_radar.persistence.db import transaction
from opportunity_radar.persistence.repositories.observations import insert_observation, load_text
from opportunity_radar.persistence.repositories.opportunities import OpportunityRepository
from opportunity_radar.persistence.repositories.sources import SourceRepository
from opportunity_radar.sources.base import FetchContext, PageObservation, SourceRecord
from opportunity_radar.sources.common import build_observation, decode_body
from opportunity_radar.sources.fetch import BodyCache, Fetcher
from opportunity_radar.sources.html import parse_html
from opportunity_radar.verification.rules import AUTHORITATIVE_TIERS

log = logging.getLogger(__name__)


@dataclass
class PipelineStats:
    created: int = 0
    duplicates: int = 0
    promoted: int = 0
    needs_review: int = 0
    leads: int = 0
    followed: int = 0
    follow_failed: int = 0
    errors: int = 0
    llm_done: int = 0
    llm_queued: int = 0
    llm_invalid: int = 0


def authority_of(source: SourceRecord | None) -> Authority:
    if source is None:
        return Authority(TrustTier.T5_COMMUNITY.value, True, ())
    return Authority(
        source.trust_tier, source.discovery_only, source.allowed_domains or (source.domain,)
    )


def _event_years(facts: list[CandidateFact]) -> set[int]:
    return {
        int(f.date_value[:4]) for f in facts if f.field_name == "event_start_date" and f.date_value
    }


def _identity(
    title: str, url: str, facts: list[CandidateFact]
) -> tuple[str, str, str | None, str, str]:
    key = guess_edition_key(title, url, _event_years(facts))
    norm = normalize_title(title)
    domain = organizer_domain(url)
    return (
        norm,
        domain,
        key,
        fingerprint(title, registrable_domain(domain), key),
        guess_category(title),
    )


def build_input(
    cand: sqlite3.Row,
    *,
    source: SourceRecord | None,
    title: str,
    text: str,
    evidence_url: str,
    observation_id: str | None,
    method: ExtractionMethod,
    edition_key: str | None,
    extra_facts: list[CandidateFact] | None = None,
) -> PromotionInput:
    facts = extract_date_facts(
        text, source_url=evidence_url, method=method, observation_id=observation_id
    )
    not_open = detect_not_open(
        text, source_url=evidence_url, method=method, observation_id=observation_id
    )
    if not_open:
        facts.append(not_open)
    facts += extra_facts or []  # advisory LLM facts: verify_fact caps them at `unverified`
    return PromotionInput(
        candidate_id=cand["id"],
        title=title,
        official_url=cand["canonical_url"],
        evidence_url=evidence_url,
        observation_id=observation_id,
        text=text,
        facts=facts,
        category=cand["candidate_type"],
        edition_key=edition_key or cand["edition_key"],
        announced_not_open=not_open is not None,
        source_id=source.id if source else None,
        source_org_id=source.organization_id if source else None,
        authority=authority_of(source),
    )


def promote_from_db(
    conn: sqlite3.Connection,
    cfg: LoadedConfig,
    clock: Clock,
    candidate_id: str,
    *,
    edition_key: str | None = None,
    program_id: str | None = None,
    new_program: bool = False,
) -> PromotionOutcome:
    """Re-extract from the cached observation text and promote (manual `candidates promote`)."""
    repo = OpportunityRepository(conn, clock)
    cand = repo.get_candidate(candidate_id)
    if cand is None:
        raise RadarError(f"unknown or ambiguous candidate id: {candidate_id}")
    if cand["status"] in ("promoted", "rejected", "duplicate"):
        raise RadarError(f"candidate is already {cand['status']}")
    meta = json.loads(cand["metadata_json"])
    obs_id = meta.get("page_observation_id") or cand["discovered_from_observation_id"]
    try:
        _, text = load_text(conn, cfg.paths.cache, obs_id)
    except (FileNotFoundError, TypeError) as e:
        raise RadarError("observation text is not cached; enable cache and re-run discovery") from e
    source = (
        SourceRepository(conn, clock).get(cand["discovered_by_source_id"])
        if cand["discovered_by_source_id"]
        else None
    )
    return promote_candidate(
        conn,
        clock,
        build_input(
            cand,
            source=source,
            title=meta.get("title", cand["normalized_title"] or ""),
            text=text,
            evidence_url=meta.get("evidence_url", cand["canonical_url"]),
            observation_id=obs_id,
            method=meta.get("method", "rule"),
            edition_key=edition_key,
        ),
        program_id=program_id,
        new_program=new_program,
    )


def _follow(
    conn: sqlite3.Connection,
    clock: Clock,
    cfg: LoadedConfig,
    fetcher: Fetcher,
    source: SourceRecord,
    url: str,
) -> tuple[PageObservation, str] | None:
    if not source.scope.link_in_scope(url):
        return None
    ctx = FetchContext(
        fetcher=fetcher,
        settings=cfg.settings.app,
        cache=BodyCache(cfg.paths.cache) if cfg.settings.cache.enabled else None,
    )
    try:
        resp = fetcher.fetch(url, source.scope)
    except RadarError as e:
        log.info("could not follow %s: %s", url, e)
        return None
    title, text, links, meta = parse_html(decode_body(resp.body, resp.mime_type), resp.final_url)
    obs = build_observation(
        source, resp, ctx, title=title, text=text, links=links, meta=meta, depth=1
    )
    with transaction(conn):
        obs_id, _ = insert_observation(
            conn, obs, source_id=source.id, check_run_id=None, now_iso=iso_z(clock.now_utc())
        )
    return obs, obs_id


def process_observations(
    conn: sqlite3.Connection,
    cfg: LoadedConfig,
    fetcher: Fetcher,
    clock: Clock,
    source: SourceRecord,
    new_obs: list[tuple[str, PageObservation]],
    stats: PipelineStats,
    llm: LLMExtractionService | None = None,
) -> None:
    repo = OpportunityRepository(conn, clock)
    budget = cfg.settings.app.max_pages_per_source_run
    # Index pages (hints: page_type=programme_index) stay sources; only their children qualify.
    for obs_id, obs in new_obs:
        for draft in drafts_from_observation(source, obs, obs_id):
            try:
                _process_draft(
                    conn, cfg, fetcher, clock, repo, source, obs_id, draft, stats, budget, llm
                )
            except Exception:  # noqa: BLE001 - one bad draft must not stop the run
                log.exception("candidate processing failed for %s", draft.url)
                stats.errors += 1


def _process_draft(
    conn: sqlite3.Connection,
    cfg: LoadedConfig,
    fetcher: Fetcher,
    clock: Clock,
    repo: OpportunityRepository,
    source: SourceRecord,
    obs_id: str,
    draft: CandidateDraft,
    stats: PipelineStats,
    budget: int,
    llm: LLMExtractionService | None = None,
) -> None:
    title = clean_title(draft.title)
    norm, domain, key, fp, category = _identity(title, draft.url, draft.facts)
    meta: dict[str, Any] = {
        "kind": draft.kind,
        "method": draft.method,
        "evidence_url": draft.observation_url,
        "page_observation_id": obs_id,
        "source_key": source.source_key,
    }
    cid, outcome = repo.upsert_candidate(
        source_id=source.id,
        observation_id=obs_id,
        url=draft.url,
        title=title,
        normalized_title=norm,
        organizer_domain=domain,
        category=category,
        edition_key=key,
        fingerprint=fp,
        metadata=meta,
    )
    official = source.trust_tier in AUTHORITATIVE_TIERS and not source.discovery_only
    if outcome == "seen":
        # A changed official page re-enters verification so moved deadlines are noticed.
        row = repo.get_candidate(cid)
        if not (
            draft.kind == "page"
            and official
            and row
            and row["status"] not in ("rejected", "duplicate")
        ):
            return
    elif outcome == "duplicate":
        stats.duplicates += 1
        return
    else:
        stats.created += 1

    text, evidence_url, page_obs_id, method = (
        draft.text,
        draft.observation_url,
        obs_id,
        draft.method,
    )
    if draft.kind != "page" and stats.followed + stats.follow_failed < budget:
        followed = _follow(conn, clock, cfg, fetcher, source, draft.url) if official else None
        if followed is None:
            stats.follow_failed += int(official)
        else:
            page, page_obs_id = followed
            stats.followed += 1
            title = clean_title(page.title or title)
            text, evidence_url, method = page.text, page.final_url, "rule"
    can_confirm = official and (draft.kind == "page" or method == "rule")

    facts = extract_date_facts(
        text, source_url=evidence_url, method=method, observation_id=page_obs_id
    )
    norm, domain, key, fp, category = _identity(title, draft.url, facts)
    meta.update(
        {
            "title": title,
            "method": method,
            "evidence_url": evidence_url,
            "page_observation_id": page_obs_id,
            "followed": method == "rule",
        }
    )
    repo.update_candidate_identity(
        cid,
        normalized_title=norm,
        category=category,
        edition_key=key,
        fingerprint=fp,
        metadata=meta,
    )
    if not can_confirm:
        stats.leads += 1  # kept as a lead; promote manually after official verification
        return
    cand = repo.get_candidate(cid)
    assert cand is not None
    extra = _llm_facts(
        llm,
        repo,
        conn,
        cid,
        source=source,
        title=title,
        text=text,
        evidence_url=evidence_url,
        obs_id=page_obs_id,
        edition_key=key,
        stats=stats,
    )
    result = promote_candidate(
        conn,
        clock,
        build_input(
            cand,
            source=source,
            title=title,
            text=text,
            evidence_url=evidence_url,
            observation_id=page_obs_id,
            method=method,
            edition_key=key,
            extra_facts=extra,
        ),
    )
    if result.status == "promoted":
        stats.promoted += 1
    else:
        stats.needs_review += 1


def _llm_facts(
    llm: LLMExtractionService | None,
    repo: OpportunityRepository,
    conn: sqlite3.Connection,
    cid: str,
    *,
    source: SourceRecord,
    title: str,
    text: str,
    evidence_url: str,
    obs_id: str,
    edition_key: str | None,
    stats: PipelineStats,
) -> list[CandidateFact]:
    """Advisory facts from the LLM, or [] with the candidate queued when the route is down.

    Deterministic promotion proceeds either way; an unavailable gateway never blocks it.
    """
    if llm is None:
        return []
    row = conn.execute(
        "SELECT content_hash, title FROM source_observations WHERE id=?", (obs_id,)
    ).fetchone()
    try:
        outcome = llm.extract(
            url=evidence_url,
            trust_tier=source.trust_tier,
            authority_scope=source.authority_scope,
            observation_id=obs_id,
            content_sha256=row["content_hash"] if row else "",
            title=(row["title"] if row else "") or title,
            text=text,
            candidate_title=title,
            known_edition_key=edition_key,
        )
    except LLMUnavailable as e:
        log.info("LLM unavailable, queueing %s: %s", cid, e)
        repo.merge_candidate_metadata(cid, {"llm_state": "pending", "llm_note": str(e)[:200]})
        stats.llm_queued += 1
        return []
    except LLMInvalidResponse as e:
        repo.merge_candidate_metadata(cid, {"llm_state": "invalid", "llm_note": str(e)[:200]})
        with transaction(conn):
            repo.add_review_tx(
                reason="llm_invalid_output",
                priority="medium",
                candidate_id=cid,
                title=f"LLM output unusable: {title}",
                details=str(e)[:300],
            )
        stats.llm_invalid += 1
        return []
    repo.merge_candidate_metadata(
        cid,
        {
            "llm_state": "done",
            "llm_rejected": outcome.rejected[:20],
            "llm_ambiguities": outcome.ambiguities,
        },
    )
    stats.llm_done += 1
    return outcome.facts


def run_llm_queue(
    conn: sqlite3.Connection,
    cfg: LoadedConfig,
    clock: Clock,
    llm: LLMExtractionService,
    *,
    limit: int,
    dry_run: bool = False,
) -> PipelineStats:
    """Process candidates whose LLM step was deferred. Stops at the first unavailability."""
    repo = OpportunityRepository(conn, clock)
    stats = PipelineStats()
    rows = conn.execute(
        "SELECT id FROM candidates WHERE json_extract(metadata_json, '$.llm_state') = 'pending' "
        "AND status NOT IN ('rejected','duplicate') ORDER BY last_seen_at LIMIT ?",
        (limit,),
    ).fetchall()
    for r in rows:
        if dry_run:
            stats.llm_queued += 1
            continue
        cand = repo.get_candidate(r["id"])
        assert cand is not None
        meta = json.loads(cand["metadata_json"])
        obs_id = meta.get("page_observation_id")
        try:
            obs_title, text = load_text(conn, cfg.paths.cache, obs_id)
        except (FileNotFoundError, TypeError):
            repo.merge_candidate_metadata(
                cand["id"], {"llm_state": "skipped", "llm_note": "text not cached"}
            )
            continue
        source = (
            SourceRepository(conn, clock).get(cand["discovered_by_source_id"])
            if cand["discovered_by_source_id"]
            else None
        )
        if source is None:
            continue
        title = meta.get("title", obs_title)
        before = stats.llm_queued
        extra = _llm_facts(
            llm,
            repo,
            conn,
            cand["id"],
            source=source,
            title=title,
            text=text,
            evidence_url=meta.get("evidence_url", cand["canonical_url"]),
            obs_id=obs_id,
            edition_key=cand["edition_key"],
            stats=stats,
        )
        if stats.llm_queued > before:
            break  # gateway/quota/ack problem: leave the rest queued
        if extra:
            result = promote_candidate(
                conn,
                clock,
                build_input(
                    cand,
                    source=source,
                    title=title,
                    text=text,
                    evidence_url=meta.get("evidence_url", cand["canonical_url"]),
                    observation_id=obs_id,
                    method=meta.get("method", "rule"),
                    edition_key=None,
                    extra_facts=extra,
                ),
            )
            stats.promoted += int(result.status == "promoted")
    return stats
