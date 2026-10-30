"""`ohg proxy`: inspect and test operator-configured egress proxies (ADR-012).

Listings show profile names, scheme, health and whether credentials are present: never the
credentials, and never the endpoint address of a failing proxy in an error message.
"""

from __future__ import annotations

import json
import sys
import time
from types import ModuleType
from typing import Annotated

import typer
from rich.table import Table

from open_hypergamy.cli_common import ConfigOpt, HomeOpt, JsonOpt
from open_hypergamy.egress.security import (
    EndpointRejected,
    check_endpoint_addresses,
    credential_state,
)
from open_hypergamy.egress.settings import ProxySettings
from open_hypergamy.errors import EXIT_PARTIAL, ConfigurationError, OhgError
from open_hypergamy.sources.fetch import Fetcher, build_fetcher
from open_hypergamy.sources.urls import default_resolver


def register(cli: ModuleType) -> None:
    app: typer.Typer = cli.app
    out, guard = cli.out, cli.guard
    proxy_app = typer.Typer(help="Operator-controlled egress proxies.", no_args_is_help=True)
    app.add_typer(proxy_app, name="proxy")

    @proxy_app.command("list")
    def proxy_list(
        json_out: JsonOpt = False, home: HomeOpt = None, config: ConfigOpt = None
    ) -> None:
        """Configured profiles and assignments. Secrets are never shown."""
        with guard():
            cfg = cli._load(home, config)
            s = cfg.settings.proxy
            rows = [
                {
                    "name": p.name,
                    "scheme": p.scheme,
                    "enabled": p.enabled and s.enabled,
                    "trusted": p.trusted,
                    "credentials": credential_state(p),
                    "endpoint": f"{p.host}:{p.port}",
                }
                for p in s.profiles
            ]
            summary = {
                "proxy_enabled": s.enabled,
                "default": "direct",
                "selection": s.selection,
                "affinity": s.affinity,
                "profiles": rows,
                "assignments": {k: v for k, v in sorted(s.assignments.items())},
                "default_profiles": s.default_profiles,
            }
            if json_out:
                sys.stdout.write(json.dumps(summary, indent=2) + "\n")
                return
            out.print(
                f"Egress proxies: {'ENABLED' if s.enabled else 'disabled (direct connections)'}; "
                f"{len(rows)} profile(s), {len(s.assignments)} source assignment(s)."
            )
            table = Table("profile", "scheme", "enabled", "trusted", "credentials", "endpoint")
            for r in rows:
                table.add_row(
                    str(r["name"]), str(r["scheme"]), str(r["enabled"]), str(r["trusted"]),
                    str(r["credentials"]), str(r["endpoint"]),
                )  # fmt: skip
            out.print(table)

    @proxy_app.command("check")
    def proxy_check(
        profile: Annotated[
            str | None, typer.Option("--profile", help="Only this profile (manual selection).")
        ] = None,
        json_out: JsonOpt = False,
        home: HomeOpt = None,
        config: ConfigOpt = None,
    ) -> None:
        """Health-check profiles: endpoint address policy, then one probe via health_check_url."""
        with guard():
            cfg = cli._load(home, config)
            s = cfg.settings.proxy
            if not s.enabled:
                raise ConfigurationError("proxy.enabled is false; nothing to check")
            names = [profile] if profile else [p.name for p in s.profiles if p.enabled]
            fetcher = build_fetcher(cfg)
            results: list[dict[str, object]] = []
            try:
                for name in names:
                    results.append(_check_one(s, fetcher, name))
            finally:
                fetcher.close()
            if json_out:
                sys.stdout.write(json.dumps(results, indent=2) + "\n")
            else:
                table = Table("profile", "endpoint policy", "probe", "latency ms")
                for r in results:
                    table.add_row(
                        str(r["profile"]), str(r["endpoint"]), str(r["probe"]), str(r["latency_ms"])
                    )
                out.print(table)
            if any(r["probe"] != "ok" for r in results):
                raise typer.Exit(EXIT_PARTIAL)


def _check_one(settings: ProxySettings, fetcher: Fetcher, name: str) -> dict[str, object]:
    try:
        profile = settings.profile(name)
    except KeyError:
        raise ConfigurationError(f"unknown proxy profile {name!r}") from None
    row: dict[str, object] = {
        "profile": name,
        "endpoint": "ok",
        "probe": "skipped",
        "latency_ms": "-",
    }
    try:
        check_endpoint_addresses(profile, default_resolver)
    except EndpointRejected as e:
        row["endpoint"] = f"rejected: {e}"
        row["probe"] = "not attempted"
        return row
    except OhgError:
        row["endpoint"] = "unresolvable"
        row["probe"] = "not attempted"
        return row
    t0 = time.monotonic()
    ok = fetcher._probe_profile(profile)
    row["probe"] = "ok" if ok else "failed"
    row["latency_ms"] = int((time.monotonic() - t0) * 1000) if ok else "-"
    return row
