"""Discovery orchestration for the fetch pipeline (LLD §4, §7). Candidate extraction is M3.

Network I/O happens outside DB transactions; each source's outcome is persisted in one short
transaction. A failure in one source never aborts the run.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field

from open_hypergamy.clock import Clock, iso_z
from open_hypergamy.config import LoadedConfig
from open_hypergamy.discovery.pipeline import PipelineStats, process_observations
from open_hypergamy.egress.pool import EgressReport, egress_scope
from open_hypergamy.errors import FetchError, OhgError, ParseError, SourcePolicyDenied
from open_hypergamy.extraction.llm_extractor import LLMExtractionService
from open_hypergamy.observability.jobs import current_trigger
from open_hypergamy.persistence.repositories.jobs import JobRepository
from open_hypergamy.persistence.repositories.sources import CheckOutcome, SourceRepository
from open_hypergamy.sources.base import (
    FetchContext,
    PageObservation,
    SourceAdapter,
    SourceRecord,
)
from open_hypergamy.sources.fetch import BodyCache, Fetcher
from open_hypergamy.sources.health import HealthPolicy, in_cooldown
from open_hypergamy.sources.html import HtmlAdapter
from open_hypergamy.sources.ical import IcalAdapter
from open_hypergamy.sources.json_feed import JsonFeedAdapter
from open_hypergamy.sources.rss_atom import RssAtomAdapter
from open_hypergamy.sources.sitemap import SitemapAdapter

log = logging.getLogger(__name__)

ADAPTERS: dict[str, SourceAdapter] = {
    a.adapter_type: a
    for a in (RssAtomAdapter(), HtmlAdapter(), SitemapAdapter(), IcalAdapter(), JsonFeedAdapter())
}  # the playwright adapter is not implemented; such sources are recorded as skipped


@dataclass
class RunSummary:
    job_id: str | None = None
    considered: int = 0
    results: list[dict[str, object]] = field(default_factory=list)
    pipeline: PipelineStats = field(default_factory=PipelineStats)
    llm: dict[str, int] = field(default_factory=dict)

    def count(self, *statuses: str) -> int:
        return sum(1 for r in self.results if r["status"] in statuses)

    @property
    def status(self) -> str:
        bad = self.count("failed", "blocked_policy", "partial")
        if bad == 0:
            return "success"
        return "failed" if bad == self.considered and self.count("partial") == 0 else "partial"


def health_policy(cfg: LoadedConfig) -> HealthPolicy:
    c = cfg.settings.crawling
    return HealthPolicy(
        cooldown_after_failures=c.cooldown_after_failures,
        not_found_review_after=c.not_found_review_after,
        max_cooldown_hours=c.max_cooldown_hours,
        max_tracked_pages=cfg.settings.app.max_tracked_pages_per_source,
    )


def check_source(
    source: SourceRecord,
    *,
    fetcher: Fetcher,
    repo: SourceRepository,
    cfg: LoadedConfig,
    clock: Clock,
    job_id: str | None,
    new_observations: list[tuple[str, PageObservation]] | None = None,
) -> dict[str, object]:
    started = iso_z(clock.now_utc())
    adapter = ADAPTERS.get(source.adapter_type)
    egress = EgressReport()

    def finish(status: str, **kw: object) -> dict[str, object]:
        outcome = CheckOutcome(
            status=status,
            started_at=started,
            finished_at=iso_z(clock.now_utc()),
            egress=_egress_json(fetcher, egress),
            **kw,  # type: ignore[arg-type]
        )
        stored = repo.record_check(source, outcome, job_id)
        if new_observations is not None:
            new_observations.extend(stored)
        return {
            "source": source.source_key or source.id,
            "status": status,
            "pages": len(outcome.observations),
            "error_code": outcome.error_code,
            "error": outcome.error_detail,
        }

    if adapter is None:
        return finish(
            "skipped",
            error_code="adapter_unavailable",
            error_detail=f"adapter {source.adapter_type!r} is not implemented",
        )

    ctx = FetchContext(
        fetcher=fetcher,
        settings=cfg.settings.app,
        cache=BodyCache(cfg.paths.cache) if cfg.settings.cache.enabled else None,
        validators=repo.latest_validators,
        tracked_pages=lambda: repo.tracked_pages(source.id),
        clock=clock,
        selector_storage=cfg.paths.cache / "selectors.sqlite3",
    )
    try:
        with egress_scope(source.source_key, egress):
            observations = adapter.fetch(source, ctx)
    except SourcePolicyDenied as e:
        return finish("blocked_policy", error_code=e.code, error_detail=str(e))
    except FetchError as e:
        return finish(
            "failed",
            error_code=e.code,
            error_detail=str(e),
            http_status=e.http_status,
            retry_after_seconds=e.retry_after,
        )
    except ParseError as e:
        return finish("failed", error_code=e.code, error_detail=str(e))
    except OhgError as e:
        return finish("failed", error_code=e.code, error_detail=str(e))
    except Exception as e:  # noqa: BLE001 - parser bugs must not abort the whole run
        log.exception("unexpected error checking %s", source.source_key)
        return finish(
            "failed", error_code="unexpected_error", error_detail=f"{type(e).__name__}: {e}"
        )

    seed = observations[0]
    detail = None
    if ctx.failures:
        status = "partial"
        detail = "; ".join(f"{f.url}: {f.error_code}" for f in ctx.failures[:5])
    elif seed.not_modified:
        status = "not_modified"
    else:
        status = "success"
    # A 304 carries no body: keep the validators we already hold for the index.
    etag = (seed.etag or source.etag) if seed.not_modified else seed.etag
    last_modified = (
        (seed.last_modified or source.last_modified) if seed.not_modified else seed.last_modified
    )
    return finish(
        status,
        http_status=seed.http_status,
        final_url=seed.final_url,
        content_hash=seed.content_sha256 or None,
        text_hash=seed.text_sha256,
        etag=etag,
        last_modified=last_modified,
        page_updates=tuple(ctx.page_updates),
        elapsed_ms=seed.elapsed_ms,
        retry_count=seed.retry_count,
        bytes_received=sum(o.bytes_received or 0 for o in observations),
        observations=tuple(observations),
        error_code="child_pages_failed" if detail else None,
        error_detail=detail,
    )


def _egress_json(fetcher: Fetcher, report: EgressReport) -> dict[str, object] | None:
    """Diagnostics for this check, or None when it used no proxy (direct connection)."""
    pool = fetcher.egress
    if pool is None or not report.used:
        return None
    for name, st in pool.snapshot().items():
        report.health.setdefault(name, str(st.health))
    return report.as_json()


def run_discovery(
    conn: sqlite3.Connection,
    cfg: LoadedConfig,
    fetcher: Fetcher,
    clock: Clock,
    *,
    source_ref: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    trigger: str = "manual",
    llm: LLMExtractionService | None = None,
    only_ids: set[str] | None = None,
) -> RunSummary:
    repo = SourceRepository(conn, clock, health_policy(cfg))
    if source_ref:
        src = repo.get(source_ref)
        if src is None:
            raise OhgError(f"unknown source: {source_ref}")
        if not src.enabled or src.state != "active":
            raise OhgError(f"source {source_ref} is not enabled (state={src.state})")
        if src.blocked_reason:
            raise OhgError(
                f"source {source_ref} is held for review ({src.blocked_reason}); check it by "
                f"hand, then `ohg sources unblock {source_ref}`"
            )
        if in_cooldown(src, clock.now_utc()):
            raise OhgError(
                f"source {source_ref} is cooling down until {src.cooldown_until} after "
                f"{src.last_error_category}; `ohg sources unblock {source_ref}` to override"
            )
        due = [src]
    else:
        due = repo.list_due(iso_z(clock.now_utc()), None)
        if only_ids is not None:
            due = [s for s in due if s.id in only_ids]
        if limit:
            due = due[:limit]
    summary = RunSummary(considered=len(due))
    if dry_run:
        summary.results = [{"source": s.source_key or s.id, "status": "would_check"} for s in due]
        return summary

    jobs = JobRepository(conn, clock)
    summary.job_id = job_id = jobs.start(
        "discovery", current_trigger() if trigger == "manual" else trigger
    )
    try:
        for source in due:
            fresh: list[tuple[str, PageObservation]] = []
            result = check_source(
                source,
                fetcher=fetcher,
                repo=repo,
                cfg=cfg,
                clock=clock,
                job_id=job_id,
                new_observations=fresh,
            )
            summary.results.append(result)
            if fresh:
                before = summary.pipeline.errors
                process_observations(
                    conn, cfg, fetcher, clock, source, fresh, summary.pipeline, llm
                )
                if summary.pipeline.errors > before and result["status"] == "success":
                    result["status"] = "partial"  # candidate processing failed for this source
    except BaseException as e:
        jobs.finish(job_id, "failed", error_code=type(e).__name__, error_summary=str(e)[:300])
        raise
    ok = summary.count("success", "not_modified")
    jobs.finish(
        job_id,
        summary.status,
        counters={
            "considered": summary.considered,
            "succeeded": ok,
            "candidates": summary.pipeline.created,
            "failed": summary.count("failed", "blocked_policy"),
        },
        summary={
            "results": summary.results,
            "candidates": vars(summary.pipeline),
            "llm": llm.stats.as_dict() if llm else {},
        },
    )
    return summary
