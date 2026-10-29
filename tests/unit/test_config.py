from pathlib import Path

import pytest

from open_hypergamy.config import load_config
from open_hypergamy.errors import ConfigurationError


def test_defaults_match_lld(tmp_path):
    cfg = load_config(home=tmp_path)
    s = cfg.settings
    assert s.llm.provider == "freellmapi"
    assert s.llm.freellmapi.base_url == "http://127.0.0.1:3001/v1"
    assert s.llm.freellmapi.model == "auto:ohg-free"
    assert s.app.per_host_min_interval_seconds == 3.0
    assert cfg.paths.db == tmp_path.resolve() / "open_hypergamy.sqlite3"


def test_precedence_yaml_then_env_then_cli(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text("app:\n  log_level: DEBUG\n  max_retries: 5\n")
    env = {"OHG_LOG_LEVEL": "WARNING"}
    cfg = load_config(config=f, env=env, cli_overrides={"app": {"max_retries": 7}})
    assert cfg.settings.app.log_level == "WARNING"  # env beats yaml
    assert cfg.settings.app.max_retries == 7  # cli beats all


def test_llm_base_url_env_targets_active_provider():
    cfg = load_config(
        env={"OHG_LLM_PROVIDER": "local", "OHG_LLM_BASE_URL": "http://localhost:1234/v1"}
    )
    assert cfg.settings.llm.local.base_url == "http://localhost:1234/v1"
    assert cfg.settings.llm.freellmapi.base_url == "http://127.0.0.1:3001/v1"


def test_non_loopback_llm_rejected():
    with pytest.raises(ConfigurationError, match="loopback"):
        load_config(env={"OHG_FREELLMAPI_BASE_URL": "https://api.example.com/v1"})


def test_circumvention_flags_rejected(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text("crawling:\n  allow_captcha_bypass: true\n")
    with pytest.raises(ConfigurationError):
        load_config(config=f, env={})


def test_unknown_keys_warn_not_fail(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text("app:\n  bogus: 1\nmystery: {}\n")
    cfg = load_config(config=f, env={})
    assert "unknown config key: app.bogus" in cfg.warnings
    assert "unknown config key: mystery" in cfg.warnings


def test_missing_explicit_config_is_error(tmp_path):
    with pytest.raises(ConfigurationError):
        load_config(config=Path(tmp_path / "nope.yaml"), env={})


def test_paths_ensure_is_user_only(tmp_path):
    cfg = load_config(home=tmp_path / "h", env={})
    cfg.paths.ensure()
    assert (cfg.paths.home.stat().st_mode & 0o777) == 0o700
    assert (cfg.paths.cache.stat().st_mode & 0o777) == 0o700
    assert cfg.paths.bodies.is_dir() and cfg.paths.llm_cache.is_dir()
