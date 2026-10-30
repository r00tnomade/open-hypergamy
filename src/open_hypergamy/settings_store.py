"""Writes to the app-managed settings file `<home>/settings.yaml` (ADR-014).

Only the onboarding GUI writes here, and only allowlisted keys. A hand-written settings file
(`--config`, `OHG_CONFIG` or `./config/settings.yaml`) takes precedence and is never rewritten:
when one is active the GUI reports settings as managed elsewhere. Secrets never go here.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from open_hypergamy.config import LoadedConfig, Settings, _deep_merge
from open_hypergamy.errors import ConfigurationError

FILENAME = "settings.yaml"
HEADER = (
    "# Managed by `ohg onboard`. Edit freely; unknown keys are reported as warnings.\n"
    "# Secrets never belong here: they live in the environment or the macOS Keychain.\n"
)
# Dotted keys the GUI may change. Anything else is rejected, so a bug cannot write arbitrary config.
WRITABLE = frozenset(
    {
        "app.timezone",
        "llm.enabled",
        "telegram.enabled",
        "telegram.digest_enabled",
        "telegram.deadline_offsets_days",
        "telegram.minimum_fit_score_for_immediate_alert",
        "schedule.digest_time",
        "schedule.digest_weekday",
    }
)


def managed_path(cfg: LoadedConfig) -> Path:
    return cfg.paths.home / FILENAME


def editable(cfg: LoadedConfig) -> bool:
    """False when a hand-written settings file outranks the managed one."""
    return cfg.config_file is None or cfg.config_file == managed_path(cfg).resolve()


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError) as e:
        raise ConfigurationError(f"cannot read {path.name}: {type(e).__name__}") from None
    if not isinstance(data, dict):
        raise ConfigurationError(f"{path.name} must contain a mapping at top level")
    return data


def _nest(changes: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for dotted, value in changes.items():
        if dotted not in WRITABLE:
            raise ConfigurationError(f"setting {dotted!r} cannot be changed from the GUI")
        cur = out
        *parents, leaf = dotted.split(".")
        for p in parents:
            cur = cur.setdefault(p, {})
        cur[leaf] = value
    return out


def update(cfg: LoadedConfig, changes: dict[str, Any]) -> None:
    """Merge `changes` (dotted keys) into the managed file after validating the result."""
    if not editable(cfg):
        raise ConfigurationError("settings are managed by a hand-written settings file")
    path = managed_path(cfg)
    merged = _deep_merge(_read(path), _nest(changes))
    try:
        Settings.model_validate(merged)
    except ValidationError as e:
        problems = "; ".join(
            f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}"
            for err in e.errors(include_input=False, include_url=False, include_context=False)
        )
        raise ConfigurationError(f"invalid settings: {problems}") from None
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(HEADER + yaml.safe_dump(merged, sort_keys=True, allow_unicode=True))
    tmp.chmod(0o600)
    os.replace(tmp, path)


def hand_written_active(config: Path | None, env: Mapping[str, str] | None = None) -> bool:
    """True when `--config`, `OHG_CONFIG` or `./config/settings.yaml` outranks the managed file.

    Mirrors the lookup order in `config.load_config`; usable when that file is unreadable."""
    env = os.environ if env is None else env
    return bool(config or env.get("OHG_CONFIG") or Path("config/settings.yaml").is_file())


def quarantine(cfg: LoadedConfig | None, home: Path, stamp: str) -> Path | None:
    """Move an unreadable managed settings file aside so defaults apply again."""
    path = (cfg.paths.home if cfg else home) / FILENAME
    if not path.is_file():
        return None
    target = path.with_name(f"{FILENAME}.broken-{stamp}")
    os.replace(path, target)
    return target
