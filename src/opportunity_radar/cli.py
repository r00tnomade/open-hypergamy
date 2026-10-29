"""`radar` command line interface (LLD §14). M1 scope: init, doctor, status, db."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from opportunity_radar import __version__
from opportunity_radar.clock import SystemClock, iso_compact
from opportunity_radar.config import LoadedConfig, load_config
from opportunity_radar.errors import (
    EXIT_DATABASE,
    EXIT_DEPENDENCY,
    EXIT_FAILURE,
    EXIT_OK,
    DatabaseInitializationError,
    RadarError,
)
from opportunity_radar.observability.health import collect_status, run_doctor
from opportunity_radar.observability.logging import redact, setup_logging
from opportunity_radar.persistence import db as dbm
from opportunity_radar.persistence import migrations as mig

app = typer.Typer(
    help="Opportunity Radar: local opportunity-intelligence CLI.", no_args_is_help=True
)
db_app = typer.Typer(help="Database maintenance.", no_args_is_help=True)
app.add_typer(db_app, name="db")

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


if __name__ == "__main__":
    app()
    sys.exit(EXIT_OK)
