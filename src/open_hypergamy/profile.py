"""User profile: minimal, versioned, local only (LLD §11.1). Never leaves the machine."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from open_hypergamy.config import LoadedConfig
from open_hypergamy.errors import ConfigurationError


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# Programme categories as `discovery/normalize.py` assigns them; `preferences.categories`
# narrows ranking to these (empty = everything relevant). See ADR-014.
OpportunityCategory = Literal[
    "research_programme",
    "internship",
    "fellowship",
    "scholarship",
    "grant",
    "summer_school",
    "conference",
    "workshop",
    "call_for_papers",
    "hackathon",
    "challenge",
    "other",
]


class Academic(_Strict):
    country: str
    institution_type: str = "unknown"
    institution: str | None = None  # display only; never used for eligibility
    degree_level: Literal["bachelor", "master", "phd"]
    subject_tags: list[str] = []
    current_year: int | None = None
    expected_graduation_year: int | None = None


class Preferences(_Strict):
    primary_regions: list[str] = []
    international_when_funded: bool = True
    needs_funding_or_low_cost: bool = True
    budget_limit_eur: float | None = None
    formats: list[str] = []
    career_goals: list[str] = []
    categories: list[OpportunityCategory] = []


class Profile(_Strict):
    version: Literal[1]
    profile_id: str = "primary"
    profile_version: str
    display_name: str | None = None  # greeting in the GUI only
    academic: Academic
    skills: list[str] = []
    research_tags: list[str] = []
    preferences: Preferences = Preferences()


def profile_path(cfg: LoadedConfig, env: dict[str, str] | None = None) -> Path | None:
    env = dict(os.environ) if env is None else env
    candidates = [
        Path(env["OHG_PROFILE"]).expanduser() if env.get("OHG_PROFILE") else None,
        cfg.paths.home / "profile.yaml",
        Path("config/profile.yaml"),
    ]
    return next((c for c in candidates if c and c.is_file()), None)


def load_profile(path: Path) -> Profile:
    try:
        return Profile.model_validate(yaml.safe_load(path.read_text()) or {})
    except (OSError, yaml.YAMLError) as e:
        raise ConfigurationError(f"cannot read profile {path}: {e}") from e
    except ValidationError as e:
        raise ConfigurationError(f"invalid profile {path}:\n{e}") from e


def load_profile_for(cfg: LoadedConfig) -> Profile | None:
    p = profile_path(cfg)
    return load_profile(p) if p else None


_HEADER = (
    "# OpenHypergamy profile. Written by `ohg onboard`; safe to edit by hand.\n"
    "# Local only: never sent to any LLM or to Telegram.\n"
)


def writable_profile_path(cfg: LoadedConfig, env: dict[str, str] | None = None) -> Path:
    """Save target: `OHG_PROFILE` if set, else the profile in use, else `<home>/profile.yaml`."""
    env = dict(os.environ) if env is None else env
    if env.get("OHG_PROFILE"):
        return Path(env["OHG_PROFILE"]).expanduser()
    return profile_path(cfg, env) or cfg.paths.home / "profile.yaml"


def save_profile(cfg: LoadedConfig, profile: Profile) -> Path:
    """Atomically write the profile (0600), keeping the previous file as `profile.yaml.bak`."""
    path = writable_profile_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = _HEADER + yaml.safe_dump(
        profile.model_dump(mode="json"), sort_keys=False, allow_unicode=True
    )
    if path.is_file():
        bak = path.with_name(path.name + ".bak")
        bak.write_bytes(path.read_bytes())
        bak.chmod(0o600)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(body)
    tmp.chmod(0o600)
    os.replace(tmp, path)
    return path
