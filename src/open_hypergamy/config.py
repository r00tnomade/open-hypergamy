"""Configuration loading: defaults < settings.yaml < environment < CLI (LLD §2)."""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from open_hypergamy.clock import set_local_timezone
from open_hypergamy.errors import ConfigurationError

DEFAULT_HOME = "~/Library/Application Support/OpenHypergamy"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class _Section(BaseModel):
    # Unknown keys are tolerated but reported as warnings in the MVP (LLD §2.1).
    model_config = ConfigDict(extra="allow")


class AppSettings(_Section):
    timezone: str = "Europe/Berlin"
    horizon_months: int = 24
    actionable_horizon_months: int = 12
    log_level: str = "INFO"
    user_agent: str = "OpenHypergamy/0.1 (+local research opportunity monitor)"
    max_response_bytes: int = 8_000_000
    request_timeout_seconds: float = 25
    max_redirects: int = 5
    max_retries: int = 2
    per_host_min_interval_seconds: float = 3.0
    max_concurrent_hosts: int = 4
    max_pages_per_source_run: int = 40
    max_crawl_depth: int = 2
    default_source_poll_interval_hours: int = 168


class DatabaseSettings(_Section):
    path: str | None = None  # default: <home>/open_hypergamy.sqlite3
    journal_mode: str = "WAL"
    busy_timeout_ms: int = 5000
    backup_keep_daily: int = 7
    backup_keep_weekly: int = 4


class CacheSettings(_Section):
    enabled: bool = True
    body_retention_days: int = 180
    llm_retention_days: int = 365


class FreeLLMAPISettings(_Section):
    base_url: str = "http://127.0.0.1:3001/v1"
    model: str = "auto:ohg-free"
    api_key_env: str = "OHG_FREELLMAPI_API_KEY"
    required_profile_name: str = "ohg-free"
    require_loopback: bool = True
    free_tier_only: bool = True
    max_input_chars: int = 12_000


class LocalLLMSettings(_Section):
    base_url: str = "http://127.0.0.1:3000/v1"
    model: str = "REPLACE_WITH_LOADED_LOCAL_MODEL_ID"
    manual_mode_only: bool = True
    max_input_chars: int = 12_000


class LLMSettings(_Section):
    enabled: bool = True
    provider: Literal["freellmapi", "local"] = "freellmapi"
    timeout_seconds: float = 90
    max_concurrency: int = 1
    temperature: float = 0.0
    max_output_tokens: int = 4000
    allow_remote_public_content: bool = True
    extraction_cache: bool = True
    max_calls_per_run: int = 20
    max_retries: int = 2  # malformed-output retries; bounded (LLD §17)
    freellmapi: FreeLLMAPISettings = FreeLLMAPISettings()
    local: LocalLLMSettings = LocalLLMSettings()

    @property
    def active(self) -> FreeLLMAPISettings | LocalLLMSettings:
        return self.freellmapi if self.provider == "freellmapi" else self.local

    @model_validator(mode="after")
    def _loopback_only(self) -> LLMSettings:
        # Non-loopback gateways are prohibited in the MVP (LLD §17).
        for name, block in (("freellmapi", self.freellmapi), ("local", self.local)):
            host = urlparse(block.base_url).hostname
            if host not in LOOPBACK_HOSTS:
                raise ValueError(f"llm.{name}.base_url must be loopback, got host {host!r}")
        return self


class BrowserSettings(_Section):
    enable_playwright: bool = False
    playwright_allowed_source_ids: list[str] = []


class TelegramSettings(_Section):
    enabled: bool = True
    digest_enabled: bool = True
    deadline_offsets_days: list[int] = [30, 14, 7, 2]
    minimum_fit_score_for_immediate_alert: int = 75
    maximum_messages_per_run: int = 10
    retry_limit: int = 3
    send_delay_seconds: float = 1.0


class ScheduleSettings(_Section):
    """Launchd run times (local time) and how stale a job may get before it is called overdue."""

    sentinel_time: str = "07:30"
    discovery_time: str = "06:00"
    discovery_weekday: int = 1  # launchd: 0/7 = Sunday, 1 = Monday
    digest_time: str = "08:30"
    digest_weekday: int = 1
    backup_time: str = "03:00"
    sentinel_max_age_hours: int = 36
    backup_max_age_hours: int = 36
    discovery_max_age_days: int = 9
    digest_max_age_days: int = 9

    @model_validator(mode="after")
    def _times(self) -> ScheduleSettings:
        for name in ("sentinel_time", "discovery_time", "digest_time", "backup_time"):
            h, _, m = getattr(self, name).partition(":")
            if not (h.isdigit() and m.isdigit() and 0 <= int(h) < 24 and 0 <= int(m) < 60):
                raise ValueError(f"schedule.{name} must be HH:MM")
        return self


class CrawlingSettings(_Section):
    require_source_policy_review: bool = True
    discover_outbound_sources_as_unverified: bool = True
    allow_login_pages: bool = False
    allow_captcha_bypass: bool = False
    allow_paywall_bypass: bool = False
    permitted_schemes: list[str] = ["https", "http"]

    @model_validator(mode="after")
    def _no_circumvention(self) -> CrawlingSettings:
        if self.allow_captcha_bypass or self.allow_paywall_bypass or self.allow_login_pages:
            raise ValueError("login, CAPTCHA and paywall circumvention are not permitted")
        return self


class ScoringWeights(_Section):
    career_alignment: int = 30
    technical_research_value: int = 25
    eligibility_feasibility: int = 20
    funding_accessibility: int = 15
    time_cost: int = 10


class ScoringSettings(_Section):
    weights: ScoringWeights = ScoringWeights()


class Settings(_Section):
    app: AppSettings = AppSettings()
    database: DatabaseSettings = DatabaseSettings()
    cache: CacheSettings = CacheSettings()
    llm: LLMSettings = LLMSettings()
    browser: BrowserSettings = BrowserSettings()
    telegram: TelegramSettings = TelegramSettings()
    crawling: CrawlingSettings = CrawlingSettings()
    schedule: ScheduleSettings = ScheduleSettings()
    scoring: ScoringSettings = ScoringSettings()


@dataclass(frozen=True)
class AppPaths:
    home: Path
    db: Path

    @property
    def backups(self) -> Path:
        return self.home / "backups"

    @property
    def cache(self) -> Path:
        return self.home / "cache"

    @property
    def bodies(self) -> Path:
        return self.cache / "bodies"

    @property
    def llm_cache(self) -> Path:
        return self.cache / "llm"

    @property
    def reports(self) -> Path:
        return self.home / "reports"

    @property
    def logs(self) -> Path:
        return self.home / "logs"

    @property
    def tmp(self) -> Path:
        return self.home / "tmp"

    @property
    def llm_ack(self) -> Path:
        return self.home / "llm_ack.json"

    def ensure(self) -> None:
        """Create the data directory tree with user-only permissions."""
        for d in (
            self.home,
            self.backups,
            self.cache,
            self.bodies,
            self.llm_cache,
            self.reports,
            self.logs,
            self.tmp,
        ):
            d.mkdir(parents=True, exist_ok=True)
            d.chmod(stat.S_IRWXU)


@dataclass(frozen=True)
class LoadedConfig:
    settings: Settings
    paths: AppPaths
    config_file: Path | None
    warnings: list[str]


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _env_overrides(env: dict[str, str]) -> dict[str, Any]:
    o: dict[str, Any] = {}

    def put(path: str, value: str) -> None:
        cur = o
        *parents, leaf = path.split(".")
        for p in parents:
            cur = cur.setdefault(p, {})
        cur[leaf] = value

    simple = {
        "OHG_LOG_LEVEL": "app.log_level",
        "OHG_LLM_ENABLED": "llm.enabled",
        "OHG_LLM_PROVIDER": "llm.provider",
        "OHG_LLM_ALLOW_REMOTE_PUBLIC_CONTENT": "llm.allow_remote_public_content",
        "OHG_FREELLMAPI_BASE_URL": "llm.freellmapi.base_url",
        "OHG_FREELLMAPI_MODEL": "llm.freellmapi.model",
        "OHG_TELEGRAM_ENABLED": "telegram.enabled",
        "OHG_TELEGRAM_SEND_DELAY_SECONDS": "telegram.send_delay_seconds",
    }
    for var, path in simple.items():
        if env.get(var):
            put(path, env[var])
    # OHG_LLM_BASE_URL / OHG_LLM_MODEL target the active provider's block.
    provider = env.get("OHG_LLM_PROVIDER") or "freellmapi"
    for var, leaf in (("OHG_LLM_BASE_URL", "base_url"), ("OHG_LLM_MODEL", "model")):
        if env.get(var) and provider in ("freellmapi", "local"):
            put(f"llm.{provider}.{leaf}", env[var])
    return o


def _unknown_keys(model: BaseModel, prefix: str = "") -> list[str]:
    found = [f"{prefix}{k}" for k in (model.model_extra or {})]
    for name in type(model).model_fields:
        child = getattr(model, name)
        if isinstance(child, BaseModel):
            found += _unknown_keys(child, f"{prefix}{name}.")
    return found


def resolve_home(home: Path | None = None, env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    raw = home or env.get("OHG_HOME") or DEFAULT_HOME
    return Path(raw).expanduser().resolve()


def load_config(
    *,
    home: Path | None = None,
    config: Path | None = None,
    env: dict[str, str] | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> LoadedConfig:
    env = dict(os.environ) if env is None else env
    explicit = config or (Path(env["OHG_CONFIG"]) if env.get("OHG_CONFIG") else None)
    config_file: Path | None = None
    data: dict[str, Any] = {}
    if explicit is not None:
        config_file = explicit.expanduser().resolve()
        if not config_file.is_file():
            raise ConfigurationError(f"config file not found: {config_file}")
    elif Path("config/settings.yaml").is_file():
        config_file = Path("config/settings.yaml").resolve()
    elif (resolve_home(home, env) / "settings.yaml").is_file():
        # The GUI-managed file (ADR-014); a hand-written one above always wins.
        config_file = resolve_home(home, env) / "settings.yaml"
    if config_file is not None:
        try:
            loaded = yaml.safe_load(config_file.read_text()) or {}
        except yaml.YAMLError as e:
            raise ConfigurationError(f"invalid YAML in {config_file}: {e}") from e
        if not isinstance(loaded, dict):
            raise ConfigurationError(f"{config_file} must contain a mapping at top level")
        data = loaded
    data = _deep_merge(data, _env_overrides(env))
    data = _deep_merge(data, cli_overrides or {})
    try:
        settings = Settings.model_validate(data)
    except ValidationError as e:
        raise ConfigurationError(f"invalid configuration:\n{e}") from e
    try:
        set_local_timezone(settings.app.timezone)
    except ValueError as e:
        raise ConfigurationError(str(e)) from e

    home_path = resolve_home(home, env)
    db_path = (
        Path(settings.database.path).expanduser()
        if settings.database.path
        else home_path / "open_hypergamy.sqlite3"
    )
    warnings = [f"unknown config key: {k}" for k in _unknown_keys(settings)]
    return LoadedConfig(settings, AppPaths(home_path, db_path), config_file, warnings)
