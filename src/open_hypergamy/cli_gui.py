"""`ohg onboard`: initialise if needed, then run the local onboarding GUI (ADR-014)."""

from __future__ import annotations

from types import ModuleType
from typing import Annotated

import typer

from open_hypergamy import settings_store
from open_hypergamy.cli_common import ConfigOpt, HomeOpt
from open_hypergamy.errors import ConfigurationError


def register(cli: ModuleType) -> None:
    app: typer.Typer = cli.app
    out, err = cli.out, cli.err

    @app.command()
    def onboard(
        port: Annotated[
            int, typer.Option("--port", help="Loopback port (default: any free port).")
        ] = 0,
        no_browser: Annotated[
            bool, typer.Option("--no-browser", help="Print the link instead of opening a browser.")
        ] = False,
        home: HomeOpt = None,
        config: ConfigOpt = None,
    ) -> None:
        """Set up your profile, preferences and optional integrations in the browser."""
        from open_hypergamy.gui.server import GuiServer, open_browser
        from open_hypergamy.gui.service import OnboardingService

        with cli.guard():
            service = OnboardingService(home, config)
            try:
                cli._load(home, config)
            except ConfigurationError as e:
                # Only the app-managed file can be repaired from the GUI; anything else is fatal.
                if settings_store.hand_written_active(config):
                    raise
                if not (service.home / settings_store.FILENAME).is_file():
                    raise
                err.print(f"[yellow]warning[/yellow]: {e}\nThe setup page can reset this file.")
            else:
                init = service.start()
                if init is not None:
                    out.print(f"Initialised the database (schema v{init.schema_version}).")
            try:
                server = GuiServer(service, port)
            except OSError as e:
                err.print(f"[red]error[/red]: cannot listen on 127.0.0.1:{port} ({e.strerror})")
                raise typer.Exit(cli.EXIT_FAILURE) from None
            url = server.launch_url()
            out.print(f"OpenHypergamy setup is running at http://127.0.0.1:{server.port}/")
            if no_browser or not open_browser(url):
                out.print("Open this one-time link in your browser (valid for 5 minutes):")
                out.print(url, soft_wrap=True, markup=False, highlight=False)
            out.print("Press Ctrl+C to stop.")
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                out.print("\nStopped.")
            finally:
                server.httpd.server_close()
