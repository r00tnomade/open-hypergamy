"""Authorized-access resilience commands (ADR-013): alternatives, permission requests,
newsletter import and recall measurement. Offline except `import newsletter`, which fetches
each lead once like `ohg candidates add`."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Annotated

import typer
from rich.table import Table

from open_hypergamy.cli_common import ConfigOpt, HomeOpt, JsonOpt
from open_hypergamy.errors import EXIT_PARTIAL, ConfigurationError
from open_hypergamy.persistence.repositories.sources import SourceRepository
from open_hypergamy.resilience import alternatives, newsletter, permission, recall


def register(cli: ModuleType) -> None:
    app: typer.Typer = cli.app
    out, guard = cli.out, cli.guard
    sources_app: typer.Typer = cli.sources_app
    import_app = typer.Typer(help="User-provided material.", no_args_is_help=True)
    measure_app = typer.Typer(help="Measurements.", no_args_is_help=True)
    app.add_typer(import_app, name="import")
    app.add_typer(measure_app, name="measure")

    def _source(repo: SourceRepository, ref: str):  # type: ignore[no-untyped-def]
        source = repo.get(ref)
        if source is None:
            raise ConfigurationError(f"unknown source: {ref}")
        return source

    @sources_app.command("alternatives")
    def sources_alternatives(
        source: str, json_out: JsonOpt = False, home: HomeOpt = None, config: ConfigOpt = None
    ) -> None:
        """Official alternative channels for a source (feeds, calendars, siblings). Offline."""
        with guard():
            cfg = cli._load(home, config)
            conn = cli._open(cfg)
            try:
                src = _source(SourceRepository(conn, cli.SystemClock()), source)
                found = alternatives.alternatives_for(conn, src, cfg.paths.cache)
            finally:
                conn.close()
            if json_out:
                sys.stdout.write(
                    json.dumps([a.__dict__ for a in found], indent=2, sort_keys=True) + "\n"
                )
                return
            table = Table("kind", "adapter", "url", "origin")
            for a in found:
                table.add_row(a.kind, a.adapter_type, a.url, a.origin)
            out.print(table)
            out.print(
                f"{len(found)} suggestion(s) for {src.source_key}. Nothing was fetched, "
                "registered or enabled."
            )

    @sources_app.command("permission-request")
    def sources_permission_request(
        source: str, home: HomeOpt = None, config: ConfigOpt = None
    ) -> None:
        """Draft a permission / allowlisting request for a publisher. Prints it; sends nothing."""
        with guard():
            cfg = cli._load(home, config)
            conn = cli._open(cfg)
            try:
                src = _source(SourceRepository(conn, cli.SystemClock()), source)
            finally:
                conn.close()
            s = cfg.settings.proxy
            addrs: dict[str, list[str]] = {}
            for name in s.assignments.get(src.source_key or "", []):
                ips = s.profile(name).egress_ips
                if ips:
                    addrs[name] = ips
            sys.stdout.write(permission.render_request(cfg, src, addrs))

    @import_app.command("newsletter")
    def import_newsletter(
        file: Path,
        dry_run: Annotated[bool, typer.Option("--dry-run", help="List leads only.")] = False,
        home: HomeOpt = None,
        config: ConfigOpt = None,
    ) -> None:
        """Turn the opportunity links of a newsletter (.eml/.html/.txt) into manual leads."""
        with guard():
            if not file.is_file() or file.stat().st_size > 5_000_000:
                raise ConfigurationError("newsletter file missing or larger than 5 MB")
            leads = newsletter.extract_leads(file.read_bytes())
            out.print(f"{len(leads)} opportunity link(s) found in {file.name}.")
            if dry_run or not leads:
                for lead in leads:
                    out.print(f"  {lead.url}  {lead.text[:60]}")
                return
            failed = 0
            for lead in leads:
                try:
                    cli.candidates_add(lead.url, home, config)
                except typer.Exit:
                    failed += 1
            if failed:
                out.print(f"{failed} lead(s) could not be added (see messages above).")
                raise typer.Exit(EXIT_PARTIAL)

    @measure_app.command("recall")
    def measure_recall(
        truth: Annotated[Path, typer.Option("--truth", help="Independent ground-truth YAML.")],
        target: Annotated[float, typer.Option("--target")] = 0.97,
        json_out: JsonOpt = False,
        home: HomeOpt = None,
        config: ConfigOpt = None,
    ) -> None:
        """Network-wide capture recall against an operator-supplied ground-truth set."""
        with guard():
            cfg = cli._load(home, config)
            ts = recall.load_truth(truth)
            conn = cli._open(cfg)
            try:
                rep = recall.measure(conn, ts, target=target)
            finally:
                conn.close()
            if json_out:
                sys.stdout.write(json.dumps(rep.as_json(), indent=2) + "\n")
                return
            out.print(
                f"Truth set {rep.truth_id}: captured {rep.captured}/{rep.n} "
                f"= {rep.recall:.1%} (95 % interval {rep.low:.1%}-{rep.high:.1%})."
            )
            out.print(f"Verdict: {rep.verdict}")
            for ch, n in sorted(rep.by_channel.items()):
                out.print(f"  via {ch}: {n}")
            for title in rep.missed[:20]:
                out.print(f"  missed: {title}")
            for c in rep.caveats:
                out.print(f"[dim]{c}[/dim]")
