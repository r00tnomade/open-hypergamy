"""`radar` command line interface (LLD §14). M1 scope: init, doctor, status, db."""

from __future__ import annotations

import json
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
from opportunity_radar.discovery.orchestrator import ADAPTERS, run_discovery
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
from opportunity_radar.observability.health import collect_status, run_doctor
from opportunity_radar.observability.logging import redact, setup_logging
from opportunity_radar.persistence import db as dbm
from opportunity_radar.persistence import migrations as mig
from opportunity_radar.persistence.repositories.sources import SourceRepository
from opportunity_radar.sources.base import FetchContext, SourceRecord
from opportunity_radar.sources.fetch import BodyCache, build_fetcher
from opportunity_radar.sources.registry import load_source_files

app = typer.Typer(
    help="Opportunity Radar: local opportunity-intelligence CLI.", no_args_is_help=True
)
db_app = typer.Typer(help="Database maintenance.", no_args_is_help=True)
sources_app = typer.Typer(help="Source registry.", no_args_is_help=True)
run_app = typer.Typer(help="Run jobs.", no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(sources_app, name="sources")
app.add_typer(run_app, name="run")

out = Console()
err = Console(stderr=True)

HomeOpt = Annotated[
    Path | None, typer.Option("--home", help="Data directory (default: $RADAR_HOME).")
]
ConfigOpt = Annotated[Path | None, typer.Option("--config", help="settings.yaml path.")]
JsonOpt = Annotated[bool, typer.Option("--json", help="Machine-readable output on stdout.")]

EXTERNAL_PROCESSING_CHECKLIST = """\
External-processing and zero-cost checklist (LLM route: FreeLLMAPI)
  1. FreeLLMAPI runs locally but may forward redacted PUBLIC page excerpts to upstream providers.
     Inference is not local-only. Your profile, CV, database content, paths, secrets and
     Telegram identifiers are never sent.
  2. Configure a gateway chain named `radar-free` containing ONLY genuinely free-tier routes.
     Do not add billing-enabled provider credentials, paid routes, or the Premium catalog.
  3. Bind the gateway to 127.0.0.1 only and set RADAR_FREELLMAPI_API_KEY (dedicated unified key).
  4. Free quotas can change. If the gateway or quota is unavailable, LLM work is queued and
     deterministic processing continues; no other provider is ever used automatically.
  5. If you cannot establish free-only operation, set llm.provider: local (LM Studio) or
     RADAR_LLM_ENABLED=false.
The acknowledgement is recorded on the first LLM request (Milestone 4), not by `radar init`."""


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
        out.print(
            f"{'[dry run] ' if dry_run else ''}{summary.considered} source(s) considered; "
            f"run status: {summary.status if not dry_run else 'n/a'}"
        )
        if not dry_run and summary.status == "partial":
            raise typer.Exit(EXIT_PARTIAL)
        if not dry_run and summary.status == "failed":
            raise typer.Exit(EXIT_FAILURE)


if __name__ == "__main__":
    app()
    sys.exit(EXIT_OK)
