"""Typer option aliases shared by the CLI modules."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

HomeOpt = Annotated[
    Path | None, typer.Option("--home", help="Data directory (default: $RADAR_HOME).")
]
ConfigOpt = Annotated[Path | None, typer.Option("--config", help="settings.yaml path.")]
JsonOpt = Annotated[bool, typer.Option("--json", help="Machine-readable output on stdout.")]
