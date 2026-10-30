"""Operations commands (M6): reports, .ics export, launchd, secrets, source audit/probe.

Registered onto the main app by `cli.py`; helpers are taken from that module at registration
time so tests can keep monkeypatching `open_hypergamy.cli.*`.
"""

from __future__ import annotations

import getpass
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Annotated, Any

import typer
from rich.table import Table

from open_hypergamy import keychain
from open_hypergamy.cli_common import ConfigOpt, HomeOpt, JsonOpt
from open_hypergamy.clock import SystemClock
from open_hypergamy.config import LoadedConfig
from open_hypergamy.errors import EXIT_PARTIAL, ConfigurationError, OhgError
from open_hypergamy.reporting import changes as changes_report
from open_hypergamy.reporting import sources as sources_report
from open_hypergamy.reporting import weekly as weekly_report
from open_hypergamy.reporting.calendar import build_ics
from open_hypergamy.scheduling import launchd


def register(cli: ModuleType) -> None:
    app: typer.Typer = cli.app
    out, guard = cli.out, cli.guard
    sources_app: typer.Typer = cli.sources_app

    report_app = typer.Typer(help="Markdown reports.", no_args_is_help=True)
    launchd_app = typer.Typer(help="Scheduled jobs (macOS launchd).", no_args_is_help=True)
    secrets_app = typer.Typer(help="Tokens in the macOS Keychain.", no_args_is_help=True)
    app.add_typer(report_app, name="report")
    app.add_typer(launchd_app, name="launchd")
    app.add_typer(secrets_app, name="secrets")

    def _write(cfg: LoadedConfig, text: str, output: Path | None, default_name: str) -> Path:
        path = (output or cfg.paths.reports / default_name).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        path.chmod(0o600)
        return path

    # -- reports ---------------------------------------------------------------------------
    @report_app.command("weekly")
    def report_weekly(
        output: Annotated[Path | None, typer.Option("--output")] = None,
        json_out: JsonOpt = False,
        stdout: Annotated[
            bool, typer.Option("--stdout", help="Print instead of writing a file.")
        ] = False,
        home: HomeOpt = None,
        config: ConfigOpt = None,
    ) -> None:
        """Weekly report: actions, new, openings, deadlines, changes, health."""
        with guard():
            cfg = cli._load(home, config)
            conn = cli._open(cfg)
            clock = SystemClock()
            try:
                data = weekly_report.gather(conn, cfg, clock)
            finally:
                conn.close()
            if json_out:
                sys.stdout.write(json.dumps(data, indent=2, default=str) + "\n")
                return
            md = weekly_report.render_markdown(data)
            if stdout:
                sys.stdout.write(md)
                return
            path = _write(cfg, md, output, f"weekly-{data['date']}.md")
            out.print(f"Weekly report written: {path}", soft_wrap=True)

    @report_app.command("changes")
    def report_changes(
        since: Annotated[str, typer.Option("--since")] = "7d",
        json_out: JsonOpt = False,
        home: HomeOpt = None,
        config: ConfigOpt = None,
    ) -> None:
        """What changed since a date: new editions, moved deadlines, priority changes."""
        with guard():
            cfg = cli._load(home, config)
            conn = cli._open(cfg)
            try:
                data = changes_report.build_changes(conn, SystemClock(), cli._duration(since))
            finally:
                conn.close()
            sys.stdout.write(
                json.dumps(data, indent=2, default=str) + "\n"
                if json_out
                else changes_report.render_markdown(data)
            )

    @report_app.command("sources")
    def report_sources(
        output: Annotated[Path | None, typer.Option("--output")] = None,
        json_out: JsonOpt = False,
        home: HomeOpt = None,
        config: ConfigOpt = None,
    ) -> None:
        """Real source coverage vs the ~200 target, per portfolio and per source."""
        with guard():
            cfg = cli._load(home, config)
            conn = cli._open(cfg)
            try:
                data = sources_report.build_sources_report(conn, SystemClock())
            finally:
                conn.close()
            if json_out:
                sys.stdout.write(json.dumps(data, indent=2, default=str) + "\n")
                return
            md = sources_report.render_markdown(data)
            if output is None:
                sys.stdout.write(md)
                return
            out.print(
                f"Source report written: {_write(cfg, md, output, 'sources.md')}", soft_wrap=True
            )

    # -- calendar ----------------------------------------------------------------------------
    @app.command("export-ics")
    def export_ics(
        output: Annotated[Path, typer.Option("--output")],
        action: Annotated[
            str, typer.Option("--action", help="Comma-separated tracked states.")
        ] = "apply,prepare",
        include_estimates: Annotated[
            bool, typer.Option("--include-estimates/--no-include-estimates")
        ] = False,
        include_unverified: Annotated[
            bool, typer.Option("--include-unverified/--no-include-unverified")
        ] = False,
        home: HomeOpt = None,
        config: ConfigOpt = None,
    ) -> None:
        """Export event dates, application windows, deadlines and prep tasks as .ics."""
        with guard():
            cfg = cli._load(home, config)
            conn = cli._open(cfg)
            try:
                text, n = build_ics(
                    conn,
                    SystemClock(),
                    actions={a.strip() for a in action.split(",") if a.strip()},
                    include_estimates=include_estimates,
                    include_unverified=include_unverified,
                )
            finally:
                conn.close()
            path = output.expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode())
            out.print(f"{n} calendar item(s) written to {path}", soft_wrap=True)

    # -- launchd ---------------------------------------------------------------------------------
    @launchd_app.command("install")
    def launchd_install(
        dry_run: Annotated[
            bool, typer.Option("--dry-run", help="Print the plists; write nothing.")
        ] = False,
        no_load: Annotated[
            bool, typer.Option("--no-load", help="Write plists but do not load them.")
        ] = False,
        agents_dir: Annotated[Path | None, typer.Option("--dir")] = None,
        home: HomeOpt = None,
        config: ConfigOpt = None,
    ) -> None:
        """Install one LaunchAgent per job (sentinel, discovery, digest, backup)."""
        with guard():
            cfg = cli._load(home, config)
            if dry_run:
                for spec in launchd.job_specs(cfg.settings.schedule):
                    out.print(f"# {spec.label}", highlight=False, markup=False)
                    out.print(
                        launchd.render_plist(spec, cfg, config_file=cfg.config_file).decode(),
                        highlight=False,
                        markup=False,
                    )
                return
            for job, path, msg in launchd.install(
                cfg, agents_dir=agents_dir, load=not no_load, config_file=cfg.config_file
            ):
                out.print(f"{job}: {msg} ({path})", soft_wrap=True)
            out.print(
                "Secrets are not stored in the plists. Store them with `ohg secrets set NAME`."
            )

    @launchd_app.command("uninstall")
    def launchd_uninstall(
        agents_dir: Annotated[Path | None, typer.Option("--dir")] = None,
        no_unload: Annotated[bool, typer.Option("--no-unload")] = False,
    ) -> None:
        """Unload and remove the LaunchAgents this tool installed."""
        with guard():
            removed = launchd.uninstall(agents_dir=agents_dir, unload=not no_unload)
            out.print(f"Removed: {', '.join(removed) if removed else 'nothing installed'}")

    @launchd_app.command("status")
    def launchd_status(
        agents_dir: Annotated[Path | None, typer.Option("--dir")] = None,
        home: HomeOpt = None,
        config: ConfigOpt = None,
    ) -> None:
        """Which jobs are installed, and when each last succeeded."""
        from open_hypergamy.monitoring.catchup import last_success

        with guard():
            cfg = cli._load(home, config)
            installed = launchd.installed_jobs(agents_dir)
            conn = cli._open(cfg)
            try:
                table = Table("job", "installed", "last success")
                for job in launchd.JOB_COMMANDS:
                    table.add_row(
                        job, "yes" if job in installed else "no", last_success(conn, job) or "never"
                    )
            finally:
                conn.close()
            out.print(table)

    # -- secrets ---------------------------------------------------------------------------------
    @secrets_app.command("set")
    def secrets_set(name: str) -> None:
        """Store a secret in the Keychain (prompted; never echoed or written to disk)."""
        with guard():
            if name not in keychain.KNOWN:
                raise ConfigurationError(
                    f"unknown secret {name!r}; use one of {list(keychain.KNOWN)}"
                )
            if not keychain.keychain_enabled():
                raise ConfigurationError(
                    "the macOS Keychain is not available here; use environment variables"
                )
            value = getpass.getpass(f"{name}: ").strip()
            if not value:
                raise ConfigurationError("empty value; nothing stored")
            try:
                keychain.set_secret(name, value)
            except RuntimeError as e:
                raise ConfigurationError(str(e)) from None
            out.print(f"{name} stored in the Keychain (service {keychain.SERVICE}).")

    @secrets_app.command("status")
    def secrets_status() -> None:
        """Where each secret comes from (values are never shown)."""
        with guard():
            table = Table("secret", "source")
            for name in keychain.KNOWN:
                table.add_row(name, keychain.source_of(name))
            out.print(table)

    @secrets_app.command("delete")
    def secrets_delete(name: str) -> None:
        """Remove a secret from the Keychain."""
        with guard():
            if name not in keychain.KNOWN:
                raise ConfigurationError(f"unknown secret {name!r}")
            out.print("Deleted." if keychain.delete_secret(name) else "Not found in the Keychain.")

    # -- source audit / probe ------------------------------------------------------------------------
    @sources_app.command("audit")
    def sources_audit(
        json_out: JsonOpt = False, home: HomeOpt = None, config: ConfigOpt = None
    ) -> None:
        """Quality and health gaps: policy review, holds, cooldowns, failures, staleness, portfolio."""
        with guard():
            cfg = cli._load(home, config)
            conn = cli._open(cfg)
            try:
                data = sources_report.build_sources_report(conn, SystemClock())
            finally:
                conn.close()
            issues: list[str] = []
            for s in data["sources"]:
                if not s["policy_reviewed"]:
                    issues.append(f"{s['key']}: no recorded robots/terms review")
                if s["state"] == "review_required":
                    issues.append(f"{s['key']}: disabled until policy review is complete")
                if s["blocked_reason"]:
                    issues.append(
                        f"{s['key']}: held for manual review since {s['blocked_at']} "
                        f"({s['blocked_reason']}); `ohg sources unblock` after checking"
                    )
                elif s["cooldown_until"]:
                    issues.append(
                        f"{s['key']}: cooling down until {s['cooldown_until']} "
                        f"({s['last_error_category']})"
                    )
                if s["failure_streak"] >= 2:
                    issues.append(f"{s['key']}: {s['failure_streak']} consecutive failures")
                for label, count in (
                    ("missing", s["pages_missing"]),
                    ("held for review", s["pages_held"]),
                    ("invalid or out of scope", s["pages_invalid"]),
                ):
                    if count:
                        issues.append(
                            f"{s['key']}: {count} followed page(s) {label}; their opportunities are "
                            "kept and age into stale"
                        )
                if s["stale_opportunities"]:
                    issues.append(
                        f"{s['key']}: {s['stale_opportunities']} opportunit"
                        f"{'y' if s['stale_opportunities'] == 1 else 'ies'} with stale evidence"
                    )
                if s["stale"]:
                    issues.append(f"{s['key']}: not successfully checked within twice its interval")
                if s["portfolio"] is None:
                    issues.append(f"{s['key']}: no portfolio assigned")
            data["issues"] = issues
            health_keys = (
                "key", "health", "state", "last_attempt_at", "last_success_at",
                "last_successful_ingestion_at", "last_content_change_at", "last_http_status",
                "failure_streak", "last_error_category", "cooldown_until", "blocked_reason",
                "checks_30d", "retrieval_success_rate", "extraction_success_rate",
                "http_status_counts", "avg_latency_ms", "content_changes_30d",
                "stale_opportunities", "pages_tracked", "pages_due", "pages_missing",
                "pages_held", "pages_invalid",
            )  # fmt: skip
            if json_out:
                body = {k: v for k, v in data.items() if k != "sources"}
                body["source_health"] = [{k: s[k] for k in health_keys} for s in data["sources"]]
                sys.stdout.write(json.dumps(body, indent=2) + "\n")
                return
            table = Table("portfolio", "target", "configured", "enabled", "healthy")
            for p in data["portfolio"]:
                table.add_row(
                    p["portfolio"],
                    str(p["target"]),
                    str(p["configured"]),
                    str(p["enabled"]),
                    str(p["healthy"]),
                )
            out.print(table)
            if data["sources"]:
                health = Table(
                    "source", "health", "last ok", "streak", "last error", "ok rate 30d",
                    "avg ms", "http", "changes 30d", "stale opps",
                )  # fmt: skip
                for s in data["sources"]:
                    rate = s["retrieval_success_rate"]
                    health.add_row(
                        str(s["key"]),
                        s["health"],
                        str(s["last_success_at"] or "never"),
                        str(s["failure_streak"]),
                        str(s["last_error_category"] or ""),
                        "–" if rate is None else f"{rate:.0%}",
                        str(s["avg_latency_ms"] if s["avg_latency_ms"] is not None else "–"),
                        " ".join(f"{k}×{v}" for k, v in s["http_status_counts"].items()),
                        str(s["content_changes_30d"]),
                        str(s["stale_opportunities"]),
                    )
                out.print(health)
            states = " · ".join(f"{k} {v}" for k, v in data["health_states"].items() if v)
            out.print(
                f"Target ~{data['target']} sources · configured {data['configured']} · enabled {data['enabled']} "
                f"· healthy {data['healthy_30d']}. Quality matters more than reaching the target."
            )
            if states:
                out.print(f"Health: {states}.")
            for line in issues:
                out.print(f"  - {line}", highlight=False, markup=False)
            if issues:
                raise typer.Exit(EXIT_PARTIAL)

    @sources_app.command("probe")
    def sources_probe(
        file: Path,
        limit: Annotated[int | None, typer.Option("--limit")] = None,
        home: HomeOpt = None,
        config: ConfigOpt = None,
    ) -> None:
        """Live-check the entries of a YAML batch (fetch, parse; robots.txt is informational). Writes nothing."""
        from open_hypergamy.discovery.orchestrator import ADAPTERS
        from open_hypergamy.errors import FetchError, SourcePolicyDenied
        from open_hypergamy.sources.base import FetchContext
        from open_hypergamy.sources.policy import robots_agent_token
        from open_hypergamy.sources.registry import load_source_files, record_from_config

        with guard():
            cfg = cli._load(home, config)
            configs = load_source_files(
                [file], playwright_allowed=cfg.settings.browser.playwright_allowed_source_ids
            )[:limit]
            fetcher = cli.build_fetcher(cfg)
            table = Table("source", "result", "detail")
            problems = 0
            try:
                for c in configs:
                    adapter = ADAPTERS.get(c.adapter_type.value)
                    if adapter is None:
                        table.add_row(
                            c.source_key,
                            "skipped",
                            f"adapter {c.adapter_type.value} not implemented",
                        )
                        continue
                    ctx = FetchContext(fetcher=fetcher, settings=cfg.settings.app)
                    try:
                        obs = adapter.fetch(record_from_config(c), ctx)
                        o = obs[0]
                        detail = f"{o.http_status}, {len(o.text)} chars, {len(o.links)} links, {len(o.entries)} entries"
                        info = fetcher.robots_info(c.canonical_url)
                        token = robots_agent_token(cfg.settings.app.user_agent)
                        if info is not None and info.disallows(token, c.canonical_url):
                            detail += "; note: robots.txt disallows this URL (informational only)"
                        table.add_row(c.source_key, "ok", detail)
                    except SourcePolicyDenied as e:
                        problems += 1
                        table.add_row(c.source_key, "blocked", str(e)[:90])
                    except (FetchError, OhgError) as e:
                        problems += 1
                        table.add_row(c.source_key, "FAILED", f"{e.code}: {str(e)[:80]}")
            finally:
                fetcher.close()
            out.print(table)
            out.print(
                f"{len(configs)} entr{'y' if len(configs) == 1 else 'ies'} probed; nothing was imported or stored."
            )
            if problems:
                raise typer.Exit(EXIT_PARTIAL)


_ = Any
