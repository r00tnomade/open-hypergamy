"""`radar` command line interface (LLD §14). M1 scope: init, doctor, status, db."""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from opportunity_radar import __version__
from opportunity_radar.clock import SystemClock, iso_compact, iso_z
from opportunity_radar.config import LoadedConfig, load_config
from opportunity_radar.discovery import review as review_svc
from opportunity_radar.discovery.normalize import clean_title
from opportunity_radar.discovery.orchestrator import ADAPTERS, run_discovery
from opportunity_radar.discovery.pipeline import promote_from_db
from opportunity_radar.errors import (
    EXIT_DATABASE,
    EXIT_DEPENDENCY,
    EXIT_FAILURE,
    EXIT_OK,
    EXIT_PARTIAL,
    ConfigurationError,
    DatabaseInitializationError,
    RadarError,
)
from opportunity_radar.extraction.llm_extractor import build_client, build_llm_service, llm_enabled
from opportunity_radar.llm.ack import CHECKLIST, ack_is_current, read_ack, write_ack
from opportunity_radar.llm.cache import LLMCache
from opportunity_radar.observability.health import collect_status, run_doctor
from opportunity_radar.observability.logging import redact, setup_logging
from opportunity_radar.persistence import db as dbm
from opportunity_radar.persistence import migrations as mig
from opportunity_radar.persistence.repositories.observations import insert_observation
from opportunity_radar.persistence.repositories.opportunities import OpportunityRepository
from opportunity_radar.persistence.repositories.sources import SourceRepository
from opportunity_radar.sources.base import FetchContext, SourceRecord
from opportunity_radar.sources.common import build_observation, decode_body
from opportunity_radar.sources.fetch import BodyCache, build_fetcher
from opportunity_radar.sources.html import parse_html
from opportunity_radar.sources.policy import Scope
from opportunity_radar.sources.registry import load_source_files

app = typer.Typer(
    help="Opportunity Radar: local opportunity-intelligence CLI.", no_args_is_help=True
)
db_app = typer.Typer(help="Database maintenance.", no_args_is_help=True)
sources_app = typer.Typer(help="Source registry.", no_args_is_help=True)
run_app = typer.Typer(help="Run jobs.", no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(sources_app, name="sources")
candidates_app = typer.Typer(help="Opportunity candidates.", no_args_is_help=True)
review_app = typer.Typer(help="Manual review queue.", no_args_is_help=True)
opps_app = typer.Typer(help="Verified opportunities.", no_args_is_help=True)
llm_app = typer.Typer(help="LLM route (FreeLLMAPI).", no_args_is_help=True)
app.add_typer(run_app, name="run")
app.add_typer(llm_app, name="llm")
app.add_typer(candidates_app, name="candidates")
app.add_typer(review_app, name="review")
app.add_typer(opps_app, name="opportunities")

out = Console()
err = Console(stderr=True)

HomeOpt = Annotated[
    Path | None, typer.Option("--home", help="Data directory (default: $RADAR_HOME).")
]
ConfigOpt = Annotated[Path | None, typer.Option("--config", help="settings.yaml path.")]
JsonOpt = Annotated[bool, typer.Option("--json", help="Machine-readable output on stdout.")]

EXTERNAL_PROCESSING_CHECKLIST = CHECKLIST


@contextmanager
def guard() -> Iterator[None]:
    """Translate typed errors into messages (stderr) and stable exit codes."""
    try:
        yield
    except RadarError as e:
        err.print(f"[red]error[/red] ({e.code}): {redact(str(e))}")
        raise typer.Exit(e.exit_code) from None


def _load(home: Path | None, config: Path | None) -> LoadedConfig:
    cfg = load_config(home=home, config=config)
    setup_logging(cfg.settings.app.log_level)
    for w in cfg.warnings:
        err.print(f"[yellow]warning[/yellow]: {w}")
    return cfg


def _open(cfg: LoadedConfig) -> Any:
    conn = dbm.connect(cfg.paths.db, cfg.settings.database.busy_timeout_ms)
    mig.verify_applied(conn, mig.discover())
    return conn


def _version(value: bool) -> None:
    if value:
        out.print(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[bool, typer.Option("--version", callback=_version, is_eager=True)] = False,
) -> None:
    pass


@app.command()
def init(home: HomeOpt = None, config: ConfigOpt = None) -> None:
    """Create the data directory and database, and apply migrations (idempotent)."""
    with guard():
        cfg = _load(home, config)
        cfg.paths.ensure()
        existed = cfg.paths.db.exists()
        conn = dbm.connect(cfg.paths.db, cfg.settings.database.busy_timeout_ms, create=True)
        try:
            dbm.enable_journal_mode(conn, cfg.settings.database.journal_mode)
            applied = mig.migrate(conn, mig.discover(), SystemClock(), backup_dir=cfg.paths.backups)
            problems = dbm.integrity_problems(conn)
            if problems:
                raise DatabaseInitializationError("integrity check failed: " + "; ".join(problems))
            version = mig.schema_version(conn)
        finally:
            conn.close()
        cfg.paths.db.chmod(0o600)
        out.print(f"{'Opened' if existed else 'Created'} database {cfg.paths.db}", soft_wrap=True)
        out.print(f"Schema v{version}; applied {len(applied)} migration(s).")
        if cfg.settings.llm.enabled and cfg.settings.llm.provider == "freellmapi":
            out.print()
            out.print(EXTERNAL_PROCESSING_CHECKLIST, markup=False, highlight=False)


@app.command()
def doctor(
    strict: Annotated[
        bool, typer.Option("--strict", help="Fail (exit 5) if a dependency is down.")
    ] = False,
    home: HomeOpt = None,
    config: ConfigOpt = None,
) -> None:
    """Verify configuration, database integrity and optional dependencies."""
    with guard():
        cfg = _load(home, config)
        checks = run_doctor(cfg)
        table = Table("check", "status", "detail")
        style = {"ok": "green", "warn": "yellow", "fail": "red"}
        for c in checks:
            table.add_row(
                c.name, f"[{style[c.level]}]{c.level}[/{style[c.level]}]", redact(c.detail)
            )
        out.print(table)
        if any(c.level == "fail" for c in checks):
            raise typer.Exit(
                EXIT_DATABASE
                if any(c.name == "database" and c.level == "fail" for c in checks)
                else EXIT_FAILURE
            )
        if strict and any(c.dependency and c.level != "ok" for c in checks):
            raise typer.Exit(EXIT_DEPENDENCY)


@app.command()
def status(json_out: JsonOpt = False, home: HomeOpt = None, config: ConfigOpt = None) -> None:
    """Show monitoring health: sources, jobs, review queue, notifications, backups."""
    with guard():
        cfg = _load(home, config)
        conn = _open(cfg)
        try:
            data = collect_status(conn, cfg)
        finally:
            conn.close()
        if json_out:
            sys.stdout.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
            return
        table = Table("metric", "value", show_header=False)
        for k, v in data.items():
            if k != "last_jobs":
                table.add_row(k, str(v))
        for job, info in data["last_jobs"].items():
            table.add_row(f"last {job}", f"{info['started_at']} ({info['status']})")
        if not data["last_jobs"]:
            table.add_row("last jobs", "none yet")
        out.print(table)


@db_app.command("backup")
def db_backup(
    output: Annotated[Path | None, typer.Option("--output")] = None,
    home: HomeOpt = None,
    config: ConfigOpt = None,
) -> None:
    """Create a consistent backup using the SQLite backup API and verify it."""
    with guard():
        cfg = _load(home, config)
        conn = _open(cfg)
        try:
            stamp = iso_compact(SystemClock().now_utc())
            dest = output or cfg.paths.backups / f"radar-{stamp}.sqlite3"
            problems = dbm.backup_to(conn, dest.expanduser())
        finally:
            conn.close()
        if problems:
            err.print(f"[red]backup failed integrity check[/red]: {'; '.join(problems)}")
            raise typer.Exit(EXIT_DATABASE)
        out.print(f"Backup written and verified: {dest}")


@db_app.command("integrity-check")
def db_integrity(home: HomeOpt = None, config: ConfigOpt = None) -> None:
    """Run SQLite integrity and foreign-key checks."""
    with guard():
        cfg = _load(home, config)
        conn = _open(cfg)
        try:
            problems = dbm.integrity_problems(conn)
        finally:
            conn.close()
        if problems:
            err.print("[red]integrity problems[/red]:\n" + "\n".join(problems))
            raise typer.Exit(EXIT_DATABASE)
        out.print("Integrity check passed.")


@db_app.command("migrate")
def db_migrate(
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    home: HomeOpt = None,
    config: ConfigOpt = None,
) -> None:
    """Apply pending migrations (a backup is taken first when the DB already has data)."""
    with guard():
        cfg = _load(home, config)
        conn = dbm.connect(cfg.paths.db, cfg.settings.database.busy_timeout_ms)
        try:
            todo = mig.migrate(
                conn, mig.discover(), SystemClock(), backup_dir=cfg.paths.backups, dry_run=dry_run
            )
        finally:
            conn.close()
        verb = "Would apply" if dry_run else "Applied"
        out.print(
            f"{verb} {len(todo)} migration(s)"
            + (": " + ", ".join(m.path.name for m in todo) if todo else ".")
        )


@db_app.command("restore")
def db_restore(
    backup_file: Annotated[Path, typer.Argument(help="Backup file to check.")],
    check: Annotated[
        bool, typer.Option("--check", help="Verify only; never touches the live DB.")
    ] = False,
) -> None:
    """Verify a backup file (restoring over the live database is not implemented in M1)."""
    with guard():
        if not check:
            err.print("Only `--check` is supported in this version.")
            raise typer.Exit(2)
        path = backup_file.expanduser().resolve()
        if not path.is_file():
            raise DatabaseInitializationError(f"backup not found: {path}")
        import sqlite3

        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            problems = dbm.integrity_problems(conn)
            migrations = mig.discover()
            mig.verify_applied(conn, migrations)
            version = mig.schema_version(conn)
        except sqlite3.Error as e:
            raise DatabaseInitializationError(f"not a valid SQLite backup: {e}") from e
        finally:
            conn.close()
        if problems:
            err.print("[red]backup is corrupt[/red]:\n" + "\n".join(problems))
            raise typer.Exit(EXIT_DATABASE)
        out.print(f"Backup OK: schema v{version} (latest known v{migrations[-1].version}).")


def _duration(text: str) -> timedelta:
    m = re.fullmatch(r"(\d+)([dh])", text.strip())
    if not m:
        raise ConfigurationError(f"invalid duration {text!r}; use e.g. 30d or 12h")
    n = int(m[1])
    return timedelta(days=n) if m[2] == "d" else timedelta(hours=n)


def _source_row(s: SourceRecord) -> dict[str, object]:
    return {
        "key": s.source_key,
        "id": s.id,
        "name": s.name,
        "url": s.canonical_url,
        "adapter": s.adapter_type,
        "trust_tier": s.trust_tier,
        "state": s.state,
        "enabled": s.enabled,
        "discovery_only": s.discovery_only,
        "priority": s.priority,
        "failure_streak": s.failure_streak,
        "last_success_at": s.last_success_at,
        "next_due_at": s.next_due_at,
    }


@sources_app.command("list")
def sources_list(
    enabled: Annotated[bool | None, typer.Option("--enabled/--disabled")] = None,
    trust_tier: Annotated[str | None, typer.Option("--trust-tier")] = None,
    json_out: JsonOpt = False,
    home: HomeOpt = None,
    config: ConfigOpt = None,
) -> None:
    """List registered sources."""
    with guard():
        cfg = _load(home, config)
        conn = _open(cfg)
        try:
            rows = [
                _source_row(s)
                for s in SourceRepository(conn, SystemClock()).list_sources(
                    enabled=enabled, trust_tier=trust_tier
                )
            ]
        finally:
            conn.close()
        if json_out:
            sys.stdout.write(json.dumps(rows, indent=2) + "\n")
            return
        table = Table("key", "tier", "adapter", "state", "streak", "last ok", "url")
        for r in rows:
            table.add_row(
                str(r["key"]),
                str(r["trust_tier"]).split("_")[0],
                str(r["adapter"]),
                str(r["state"]) + (" (discovery-only)" if r["discovery_only"] else ""),
                str(r["failure_streak"]),
                str(r["last_success_at"] or "never"),
                str(r["url"]),
            )
        out.print(table)
        out.print(f"{len(rows)} source(s).")


@sources_app.command("add")
def sources_add(
    url: str,
    trust_tier: Annotated[str, typer.Option("--trust-tier")] = "t4_aggregator",
    discovery_only: Annotated[bool, typer.Option("--discovery-only")] = False,
    home: HomeOpt = None,
    config: ConfigOpt = None,
) -> None:
    """Register a URL as a review-required, disabled source."""
    with guard():
        from opportunity_radar.domain.enums import TrustTier

        try:
            tier = TrustTier(trust_tier)
        except ValueError:
            raise ConfigurationError(
                f"unknown trust tier {trust_tier!r}; use one of {[t.value for t in TrustTier]}"
            ) from None
        cfg = _load(home, config)
        conn = _open(cfg)
        try:
            repo = SourceRepository(conn, SystemClock())
            key = repo.add_manual(
                url,
                trust_tier=tier.value,
                name=None,
                discovery_only=discovery_only
                or tier in (TrustTier.T4_AGGREGATOR, TrustTier.T5_COMMUNITY),
            )
        finally:
            conn.close()
        out.print(
            f"Added {key} (review_required, disabled). Complete policy review in a YAML "
            "entry and re-import, then `radar sources enable`."
        )


@sources_app.command("import")
def sources_import(
    files: Annotated[list[Path], typer.Argument(help="Source YAML files.")],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    override_policy_review: Annotated[bool, typer.Option("--override-policy-review")] = False,
    home: HomeOpt = None,
    config: ConfigOpt = None,
) -> None:
    """Idempotently import source YAML (health state is never reset)."""
    with guard():
        cfg = _load(home, config)
        configs = load_source_files(
            files, playwright_allowed=cfg.settings.browser.playwright_allowed_source_ids
        )
        conn = _open(cfg)
        try:
            rep = SourceRepository(conn, SystemClock()).import_configs(
                configs, override_policy_review=override_policy_review, dry_run=dry_run
            )
        finally:
            conn.close()
        out.print(
            f"{'[dry run] ' if dry_run else ''}created {len(rep.created)}, "
            f"updated {len(rep.updated)}, awaiting policy review {len(rep.review_required)}"
        )
        for key in rep.review_required:
            out.print(f"  review required: {key}")
        for key in rep.overridden:
            err.print(f"[yellow]policy review overridden (audited)[/yellow]: {key}")


@sources_app.command("show")
def sources_show(
    ref: str, json_out: JsonOpt = False, home: HomeOpt = None, config: ConfigOpt = None
) -> None:
    """Show one source by id or key."""
    with guard():
        cfg = _load(home, config)
        conn = _open(cfg)
        try:
            src = SourceRepository(conn, SystemClock()).get(ref)
        finally:
            conn.close()
        if src is None:
            raise ConfigurationError(f"unknown source: {ref}")
        data = {
            **_source_row(src),
            "allowed_domains": list(src.allowed_domains),
            "allow_paths": list(src.allow_paths),
            "deny_paths": list(src.deny_paths),
            "fetch_interval_hours": src.fetch_interval_hours,
            "robots_policy_checked_at": src.robots_policy_checked_at,
            "terms_review_note": src.terms_review_note,
            "discovery_policy": src.discovery_policy,
        }
        if json_out:
            sys.stdout.write(json.dumps(data, indent=2, default=str) + "\n")
            return
        table = Table("field", "value", show_header=False)
        for k, v in data.items():
            table.add_row(k, str(v))
        out.print(table)


@sources_app.command("test")
def sources_test(ref: str, home: HomeOpt = None, config: ConfigOpt = None) -> None:
    """Fetch a source once for inspection. Nothing is persisted; policy checks still apply."""
    with guard():
        cfg = _load(home, config)
        conn = _open(cfg)
        try:
            src = SourceRepository(conn, SystemClock()).get(ref)
        finally:
            conn.close()
        if src is None:
            raise ConfigurationError(f"unknown source: {ref}")
        adapter = ADAPTERS.get(src.adapter_type)
        if adapter is None:
            raise ConfigurationError(f"adapter {src.adapter_type!r} is not implemented")
        fetcher = build_fetcher(cfg)
        ctx = FetchContext(
            fetcher=fetcher,
            settings=cfg.settings.app,
            cache=None if not cfg.settings.cache.enabled else BodyCache(cfg.paths.cache),
        )
        try:
            # Inspection never sends validators, so a 304 can't hide the content.
            obs = adapter.fetch(
                src.__class__(**{**src.__dict__, "etag": None, "last_modified": None}), ctx
            )
        finally:
            fetcher.close()
        table = Table("url", "status", "title", "chars", "links", "entries")
        for o in obs:
            table.add_row(
                o.final_url,
                str(o.http_status),
                (o.title or "")[:50],
                str(len(o.text)),
                str(len(o.links)),
                str(len(o.entries)),
            )
        out.print(table)
        for f in ctx.failures:
            err.print(f"[yellow]child page failed[/yellow] {f.url}: {f.error_code}")


@sources_app.command("enable")
def sources_enable(
    ref: str,
    override_policy_review: Annotated[bool, typer.Option("--override-policy-review")] = False,
    home: HomeOpt = None,
    config: ConfigOpt = None,
) -> None:
    """Enable a source (review-required sources need --override-policy-review)."""
    with guard():
        cfg = _load(home, config)
        conn = _open(cfg)
        try:
            src = SourceRepository(conn, SystemClock()).set_enabled(
                ref, True, override_policy_review=override_policy_review
            )
        finally:
            conn.close()
        out.print(f"Enabled {src.source_key}.")


@sources_app.command("disable")
def sources_disable(
    ref: str,
    reason: Annotated[str, typer.Option("--reason")],
    home: HomeOpt = None,
    config: ConfigOpt = None,
) -> None:
    """Disable (pause) a source."""
    with guard():
        cfg = _load(home, config)
        conn = _open(cfg)
        try:
            src = SourceRepository(conn, SystemClock()).set_enabled(ref, False)
        finally:
            conn.close()
        out.print(f"Disabled {src.source_key}: {reason}")


@sources_app.command("failures")
def sources_failures(
    since: Annotated[str, typer.Option("--since")] = "30d",
    home: HomeOpt = None,
    config: ConfigOpt = None,
) -> None:
    """Show failed or policy-blocked checks."""
    with guard():
        cfg = _load(home, config)
        conn = _open(cfg)
        try:
            clock = SystemClock()
            rows = SourceRepository(conn, clock).failures(iso_z(clock.now_utc() - _duration(since)))
        finally:
            conn.close()
        table = Table("source", "when", "status", "code", "http", "streak", "last ok")
        for r in rows:
            table.add_row(
                r["source_key"] or r["name"],
                r["started_at"],
                r["status"],
                r["error_code"] or "",
                str(r["http_status"] or ""),
                str(r["failure_streak"]),
                r["last_success_at"] or "never",
            )
        out.print(table)
        out.print(f"{len(rows)} failed check(s) in the last {since}.")


@sources_app.command("coverage")
def sources_coverage(
    json_out: JsonOpt = False, home: HomeOpt = None, config: ConfigOpt = None
) -> None:
    """Real source counts. The 200-source figure is a target, never a reported value."""
    with guard():
        cfg = _load(home, config)
        conn = _open(cfg)
        try:
            data = SourceRepository(conn, SystemClock()).coverage()
        finally:
            conn.close()
        if json_out:
            sys.stdout.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
            return
        table = Table("metric", "count", show_header=False)
        for k, v in data.items():
            table.add_row(k, str(v))
        out.print(table)
        out.print("Target: ~200 curated sources; activate in batches after policy review.")


@run_app.command("discovery")
def run_discovery_cmd(
    limit_sources: Annotated[int | None, typer.Option("--limit-sources")] = None,
    source_id: Annotated[str | None, typer.Option("--source-id")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    home: HomeOpt = None,
    config: ConfigOpt = None,
) -> None:
    """Poll due sources and store observations (candidate extraction arrives in M3)."""
    with guard():
        cfg = _load(home, config)
        conn = _open(cfg)
        clock = SystemClock()
        fetcher = build_fetcher(cfg, clock)
        try:
            summary = run_discovery(
                conn,
                cfg,
                fetcher,
                clock,
                source_ref=source_id,
                limit=limit_sources,
                dry_run=dry_run,
                llm=None if dry_run else build_llm_service(conn, cfg, clock),
            )
        finally:
            fetcher.close()
            conn.close()
        table = Table("source", "status", "pages", "code")
        for r in summary.results:
            table.add_row(
                str(r["source"]),
                str(r["status"]),
                str(r.get("pages", "")),
                str(r.get("error_code") or ""),
            )
        out.print(table)
        p = summary.pipeline
        if p.llm_done or p.llm_queued or p.llm_invalid:
            out.print(
                f"llm: {p.llm_done} extracted, {p.llm_queued} queued (gateway/ack unavailable), "
                f"{p.llm_invalid} invalid"
            )
        if p.created or p.duplicates or p.errors:
            out.print(
                f"candidates: {p.created} new, {p.promoted} promoted, {p.needs_review} held for "
                f"review, {p.leads} leads, {p.duplicates} duplicates, {p.errors} errors"
            )
        out.print(
            f"{'[dry run] ' if dry_run else ''}{summary.considered} source(s) considered; "
            f"run status: {summary.status if not dry_run else 'n/a'}"
        )
        if not dry_run and summary.status == "partial":
            raise typer.Exit(EXIT_PARTIAL)
        if not dry_run and summary.status == "failed":
            raise typer.Exit(EXIT_FAILURE)


STATUS_LABELS = {
    "confirmed_official": "confirmed",
    "estimated_recurring": "estimated",
    "conflicting_sources": "conflict",
    "stale": "stale",
    "unverified": "unverified",
    "announced_not_open": "announced",
    "cancelled_official": "cancelled",
    "unknown": "unknown",
}


def _label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


@candidates_app.command("list")
def candidates_list(
    status: Annotated[str | None, typer.Option("--status")] = None,
    limit: Annotated[int, typer.Option("--limit")] = 50,
    home: HomeOpt = None,
    config: ConfigOpt = None,
) -> None:
    """List candidates (new = lead, needs_review, promoted, duplicate, rejected)."""
    with guard():
        cfg = _load(home, config)
        conn = _open(cfg)
        try:
            rows = OpportunityRepository(conn, SystemClock()).list_candidates(status, limit)
        finally:
            conn.close()
        table = Table("id", "status", "type", "edition", "title", "url")
        for r in rows:
            meta = json.loads(r["metadata_json"])
            table.add_row(
                r["id"][:8],
                r["status"],
                r["candidate_type"] or "",
                r["edition_key"] or "?",
                meta.get("title", "")[:48],
                r["canonical_url"],
            )
        out.print(table)
        out.print(f"{len(rows)} candidate(s).")


@candidates_app.command("show")
def candidates_show(cid: str, home: HomeOpt = None, config: ConfigOpt = None) -> None:
    """Show a candidate with the observation that introduced it."""
    with guard():
        cfg = _load(home, config)
        conn = _open(cfg)
        try:
            repo = OpportunityRepository(conn, SystemClock())
            c = repo.get_candidate(cid)
            if c is None:
                raise ConfigurationError(f"unknown or ambiguous candidate id: {cid}")
            obs = conn.execute(
                "SELECT canonical_url, retrieved_at, content_hash FROM source_observations "
                "WHERE id=?",
                (c["discovered_from_observation_id"],),
            ).fetchone()
        finally:
            conn.close()
        table = Table("field", "value", show_header=False)
        for k in (
            "id",
            "status",
            "canonical_url",
            "candidate_type",
            "edition_key",
            "organizer_domain",
            "normalized_fingerprint",
            "duplicate_of_candidate_id",
            "promoted_edition_id",
            "rejection_reason",
            "first_seen_at",
            "last_seen_at",
        ):
            table.add_row(k, str(c[k]))
        table.add_row(
            "introduced by", f"{obs['canonical_url']} @ {obs['retrieved_at']}" if obs else "?"
        )
        table.add_row("metadata", c["metadata_json"])
        out.print(table)


@candidates_app.command("promote")
def candidates_promote(
    cid: str,
    edition_key: Annotated[str | None, typer.Option("--edition-key")] = None,
    program: Annotated[
        str | None, typer.Option("--program", help="Merge into this programme id.")
    ] = None,
    new_program: Annotated[bool, typer.Option("--new-program")] = False,
    home: HomeOpt = None,
    config: ConfigOpt = None,
) -> None:
    """Promote a candidate. Claims from non-official sources stay unverified."""
    with guard():
        cfg = _load(home, config)
        conn = _open(cfg)
        try:
            res = promote_from_db(
                conn,
                cfg,
                SystemClock(),
                cid,
                edition_key=edition_key,
                program_id=program,
                new_program=new_program,
            )
        finally:
            conn.close()
        if res.status == "promoted":
            out.print(
                f"Promoted: edition {res.edition_id}, {res.claims_added} claim(s), "
                f"{res.reviews_added} review item(s)."
            )
        else:
            err.print(
                f"[yellow]Held for review[/yellow]: {', '.join(res.reasons)} "
                "(see `radar review list`)"
            )
            raise typer.Exit(EXIT_PARTIAL)


@candidates_app.command("reject")
def candidates_reject(
    cid: str,
    reason: Annotated[str, typer.Option("--reason")],
    home: HomeOpt = None,
    config: ConfigOpt = None,
) -> None:
    """Reject a candidate (kept for dedupe; never deleted)."""
    with guard():
        cfg = _load(home, config)
        conn = _open(cfg)
        try:
            repo = OpportunityRepository(conn, SystemClock())
            c = repo.get_candidate(cid)
            if c is None:
                raise ConfigurationError(f"unknown or ambiguous candidate id: {cid}")
            repo.set_candidate_status(c["id"], "rejected", reason=reason)
        finally:
            conn.close()
        out.print(f"Rejected {c['id'][:8]}: {reason}")


@candidates_app.command("add")
def candidates_add(url: str, home: HomeOpt = None, config: ConfigOpt = None) -> None:
    """Add a manual URL as a lead (fetched once; manual leads can never be auto-verified)."""
    with guard():
        cfg = _load(home, config)
        clock = SystemClock()
        conn = _open(cfg)
        fetcher = build_fetcher(cfg, clock)
        try:
            host = (url.split("//", 1)[-1].split("/", 1)[0]).split(":")[0].lower()
            resp = fetcher.fetch(url, Scope((host,)))
            title, text, links, meta = parse_html(
                decode_body(resp.body, resp.mime_type), resp.final_url
            )
            ctx = FetchContext(
                fetcher=fetcher,
                settings=cfg.settings.app,
                cache=BodyCache(cfg.paths.cache) if cfg.settings.cache.enabled else None,
            )
            obs = build_observation(
                None, resp, ctx, title=title, text=text, links=links, meta=meta, depth=1
            )
            repo = OpportunityRepository(conn, clock)
            with_tx = dbm.transaction(conn)
            with with_tx:
                obs_id, _ = insert_observation(
                    conn, obs, source_id=None, check_run_id=None, now_iso=iso_z(clock.now_utc())
                )
            from opportunity_radar.discovery.pipeline import _identity
            from opportunity_radar.extraction.deterministic import extract_date_facts

            page_title = clean_title(title or resp.final_url)
            facts = extract_date_facts(
                text, source_url=resp.final_url, method="rule", observation_id=obs_id
            )
            norm, domain, key, fp, category = _identity(page_title, resp.final_url, facts)
            cand_id, outcome = repo.upsert_candidate(
                source_id=None,
                observation_id=obs_id,
                url=resp.final_url,
                title=page_title,
                normalized_title=norm,
                organizer_domain=domain,
                category=category,
                edition_key=key,
                fingerprint=fp,
                metadata={
                    "kind": "manual",
                    "method": "rule",
                    "followed": True,
                    "evidence_url": resp.final_url,
                    "page_observation_id": obs_id,
                },
            )
        finally:
            fetcher.close()
            conn.close()
        out.print(
            f"Candidate {cand_id[:8]} ({outcome}); manual leads stay unverified until "
            "official sources confirm them."
        )


@review_app.command("list")
def review_list(
    priority: Annotated[str | None, typer.Option("--priority")] = None,
    state: Annotated[str, typer.Option("--state")] = "pending",
    home: HomeOpt = None,
    config: ConfigOpt = None,
) -> None:
    """List review items, most urgent first."""
    with guard():
        cfg = _load(home, config)
        conn = _open(cfg)
        try:
            rows = OpportunityRepository(conn, SystemClock()).list_reviews(state, priority)
        finally:
            conn.close()
        table = Table("id", "priority", "reason", "title")
        for r in rows:
            table.add_row(r["id"][:8], r["priority"], r["reason_code"], r["title"][:70])
        out.print(table)
        out.print(f"{len(rows)} {state} item(s).")


@review_app.command("show")
def review_show(rid: str, home: HomeOpt = None, config: ConfigOpt = None) -> None:
    """Show a review item with its claim and evidence."""
    with guard():
        cfg = _load(home, config)
        conn = _open(cfg)
        try:
            repo = OpportunityRepository(conn, SystemClock())
            r = repo.get_review(rid)
            if r is None:
                raise ConfigurationError(f"unknown or ambiguous review id: {rid}")
            claim = (
                conn.execute("SELECT * FROM claims WHERE id=?", (r["claim_id"],)).fetchone()
                if r["claim_id"]
                else None
            )
            others = (
                conn.execute(
                    "SELECT c.id, c.fact_status, c.proposed_value_json, c.source_url FROM claims c "
                    "WHERE c.deadline_id = ? OR (c.edition_id = ? AND c.field_name = ?)",
                    (
                        claim["deadline_id"] if claim else None,
                        r["edition_id"],
                        claim["field_name"] if claim else None,
                    ),
                ).fetchall()
                if claim
                else []
            )
        finally:
            conn.close()
        table = Table("field", "value", show_header=False)
        for k in ("id", "state", "priority", "reason_code", "title", "details", "reviewer_notes"):
            table.add_row(k, str(r[k]))
        if claim:
            table.add_row(
                "claim", f"{claim['id']} [{_label(claim['fact_status'])}] {claim['field_name']}"
            )
            table.add_row("excerpt", claim["excerpt"])
            table.add_row("source", claim["source_url"])
        for o in others:
            table.add_row(
                "related claim",
                f"{o['id']} [{_label(o['fact_status'])}] "
                f"{o['proposed_value_json']} <- {o['source_url']}",
            )
        out.print(table)


def _decide(rid: str, note: str, accept: bool, home: Path | None, config: Path | None) -> None:
    with guard():
        cfg = _load(home, config)
        conn = _open(cfg)
        try:
            row = review_svc.decide(conn, SystemClock(), rid, accept=accept, note=note)
        finally:
            conn.close()
        out.print(
            f"Review {row['id'][:8]} {row['state']}. "
            "(Recorded as a human decision; fact verification status is unchanged.)"
        )


@review_app.command("accept")
def review_accept(
    rid: str,
    note: Annotated[str, typer.Option("--note")],
    home: HomeOpt = None,
    config: ConfigOpt = None,
) -> None:
    """Mark an item as reviewed. Never marks a fact officially confirmed."""
    _decide(rid, note, True, home, config)


@review_app.command("reject")
def review_reject(
    rid: str,
    note: Annotated[str, typer.Option("--note")],
    home: HomeOpt = None,
    config: ConfigOpt = None,
) -> None:
    """Dismiss a review item."""
    _decide(rid, note, False, home, config)


@review_app.command("resolve")
def review_resolve(
    rid: str,
    claim: Annotated[str, typer.Option("--claim")],
    note: Annotated[str, typer.Option("--note")],
    home: HomeOpt = None,
    config: ConfigOpt = None,
) -> None:
    """Settle a conflict by choosing one of the official claims."""
    with guard():
        cfg = _load(home, config)
        conn = _open(cfg)
        try:
            review_svc.resolve_conflict(conn, SystemClock(), rid, claim_id=claim, note=note)
        finally:
            conn.close()
        out.print("Conflict resolved with the chosen official claim.")


@opps_app.command("list")
def opps_list(
    json_out: JsonOpt = False,
    limit: Annotated[int, typer.Option("--limit")] = 100,
    home: HomeOpt = None,
    config: ConfigOpt = None,
) -> None:
    """List editions with verification and application status."""
    with guard():
        cfg = _load(home, config)
        conn = _open(cfg)
        try:
            repo = OpportunityRepository(conn, SystemClock())
            data = []
            for e in repo.list_editions(limit):
                close = repo.deadlines_for(e["id"])
                close_row = next(
                    (d for d in close if d["deadline_type"] == "application_close"), None
                )
                data.append(
                    {
                        "id": e["id"],
                        "name": e["display_name"],
                        "edition": e["edition_key"],
                        "fact_status": e["fact_status"],
                        "application_status": e["application_status"],
                        "event_start_date": e["event_start_date"],
                        "event_end_date": e["event_end_date"],
                        "application_close": close_row["due_date_local"] if close_row else None,
                        "application_close_status": _label(close_row["fact_status"])
                        if close_row
                        else None,
                        "url": e["official_url"],
                    }
                )
        finally:
            conn.close()
        if json_out:
            sys.stdout.write(json.dumps(data, indent=2) + "\n")
            return
        table = Table("id", "name", "ed.", "facts", "applications", "closes", "event")
        for d in data:
            closes = (
                f"{d['application_close']} ({d['application_close_status']})"
                if d["application_close"]
                else "unknown"
            )
            event = (
                f"{d['event_start_date']}..{d['event_end_date']}"
                if d["event_start_date"]
                else "unknown"
            )
            table.add_row(
                d["id"][:8],
                d["name"][:40],
                d["edition"],
                _label(d["fact_status"]),
                d["application_status"],
                closes,
                event,
            )
        out.print(table)


@opps_app.command("show")
def opps_show(
    eid: str,
    evidence: Annotated[bool, typer.Option("--evidence")] = False,
    home: HomeOpt = None,
    config: ConfigOpt = None,
) -> None:
    """Show an edition; --evidence lists every claim with its excerpt and source."""
    with guard():
        cfg = _load(home, config)
        conn = _open(cfg)
        try:
            repo = OpportunityRepository(conn, SystemClock())
            e = repo.get_edition(eid)
            if e is None:
                raise ConfigurationError(f"unknown or ambiguous edition id: {eid}")
            dls, claims = repo.deadlines_for(e["id"]), repo.claims_for_edition(e["id"])
        finally:
            conn.close()
        table = Table("field", "value", show_header=False)
        for k in (
            "id",
            "display_name",
            "edition_key",
            "official_url",
            "fact_status",
            "application_status",
            "lifecycle_status",
            "event_start_date",
            "event_end_date",
            "last_verified_at",
            "source_fresh_until",
            "last_material_change_at",
        ):
            table.add_row(k, str(e[k]))
        out.print(table)
        dtable = Table("deadline", "date", "status", "as written")
        for d in dls:
            dtable.add_row(
                d["deadline_type"],
                d["due_date_local"] or "",
                _label(d["fact_status"]),
                d["raw_date_text"],
            )
        out.print(dtable)
        if evidence:
            ctable = Table("field", "status", "method", "tier", "excerpt", "source")
            for c in claims:
                ctable.add_row(
                    c["deadline_type"] and f"deadline:{c['deadline_type']}" or c["field_name"],
                    _label(c["fact_status"]),
                    c["extraction_method"],
                    c["source_trust_tier"].split("_")[0],
                    c["excerpt"][:90],
                    c["source_url"],
                )
            out.print(ctable)


@app.command()
def deadlines(
    within: Annotated[str, typer.Option("--within")] = "90d",
    status: Annotated[str | None, typer.Option("--status")] = None,
    json_out: JsonOpt = False,
    home: HomeOpt = None,
    config: ConfigOpt = None,
) -> None:
    """Upcoming deadlines, each with its verification label."""
    with guard():
        cfg = _load(home, config)
        conn = _open(cfg)
        clock = SystemClock()
        try:
            now = clock.now_utc()
            rows = OpportunityRepository(conn, clock).deadlines_between(
                now.date().isoformat(), (now + _duration(within)).date().isoformat()
            )
        finally:
            conn.close()
        if status:
            rows = [r for r in rows if r["fact_status"] == status]
        data = [
            {
                "date": r["due_date_local"],
                "type": r["deadline_type"],
                "status": _label(r["fact_status"]),
                "raw": r["raw_date_text"],
                "title": r["display_name"],
                "url": r["official_url"],
            }
            for r in rows
        ]
        if json_out:
            sys.stdout.write(json.dumps(data, indent=2) + "\n")
            return
        table = Table("date", "status", "type", "as written", "programme")
        for d in data:
            table.add_row(d["date"], d["status"], d["type"], d["raw"], d["title"][:50])
        out.print(table)


@llm_app.command("ack")
def llm_ack(
    yes: Annotated[bool, typer.Option("--yes", help="Acknowledge without prompting.")] = False,
    home: HomeOpt = None,
    config: ConfigOpt = None,
) -> None:
    """Record the one-time acknowledgement that public excerpts may reach upstream providers."""
    with guard():
        cfg = _load(home, config)
        s = cfg.settings.llm
        if s.provider == "local":
            out.print(
                "Provider is `local`: requests stay on this machine; no acknowledgement needed."
            )
            return
        out.print(CHECKLIST, markup=False, highlight=False)
        if not yes and not typer.confirm("\nI understand and accept this policy"):
            err.print("Not acknowledged; no LLM request will be made.")
            raise typer.Exit(EXIT_FAILURE)
        cfg.paths.ensure()
        a = write_ack(cfg.paths.llm_ack, SystemClock(), s.provider, s.freellmapi.model)
        out.print(f"Acknowledged at {a.acknowledged_at} (policy {a.policy_version}).")


@llm_app.command("status")
def llm_status(json_out: JsonOpt = False, home: HomeOpt = None, config: ConfigOpt = None) -> None:
    """Gateway, acknowledgement, cache and queue state. Makes no inference request."""
    with guard():
        cfg = _load(home, config)
        s = cfg.settings.llm
        data: dict[str, object] = {
            "enabled": llm_enabled(cfg),
            "provider": s.provider,
            "base_url": s.active.base_url,
            "model": s.active.model,
            "external_processing": s.provider == "freellmapi",
            "acknowledged": s.provider == "local" or ack_is_current(cfg.paths.llm_ack, s.provider),
            "acknowledged_at": (a.acknowledged_at if (a := read_ack(cfg.paths.llm_ack)) else None),
            "api_key_set": bool(os.environ.get(s.freellmapi.api_key_env)),
        }
        if data["enabled"]:
            client = build_client(cfg)
            try:
                data["reachable"] = client.healthy()
                if data["reachable"]:
                    try:
                        data["alias_listed"] = s.active.model in client.list_models()
                    except RadarError:
                        data["alias_listed"] = None
            finally:
                client.close()
        if cfg.paths.db.exists():
            conn = _open(cfg)
            try:
                data["cache"] = LLMCache(conn, SystemClock(), s.provider).stats()
                data["queued_candidates"] = conn.execute(
                    "SELECT COUNT(*) FROM candidates WHERE "
                    "json_extract(metadata_json, '$.llm_state') = 'pending'"
                ).fetchone()[0]
            finally:
                conn.close()
        data["note"] = "free-only routing is operator-attested; it cannot be verified from here"
        if json_out:
            sys.stdout.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
            return
        table = Table("field", "value", show_header=False)
        for k, v in data.items():
            table.add_row(k, str(v))
        out.print(table)


@run_app.command("llm")
def run_llm(
    limit: Annotated[int, typer.Option("--limit")] = 20,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    home: HomeOpt = None,
    config: ConfigOpt = None,
) -> None:
    """Process candidates whose LLM step was deferred (gateway down, quota, no acknowledgement)."""
    from opportunity_radar.discovery.pipeline import run_llm_queue

    with guard():
        cfg = _load(home, config)
        clock = SystemClock()
        conn = _open(cfg)
        try:
            svc = build_llm_service(conn, cfg, clock)
            if svc is None:
                out.print("LLM route is disabled; deterministic processing only.")
                return
            stats = run_llm_queue(conn, cfg, clock, svc, limit=limit, dry_run=dry_run)
        finally:
            conn.close()
        out.print(
            f"{'[dry run] ' if dry_run else ''}llm: {stats.llm_done} extracted, "
            f"{stats.llm_queued} still queued, {stats.llm_invalid} invalid"
        )
        if stats.llm_queued and not dry_run:
            raise typer.Exit(EXIT_PARTIAL)


if __name__ == "__main__":
    app()
    sys.exit(EXIT_OK)
