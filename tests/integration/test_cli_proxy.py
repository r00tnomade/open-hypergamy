"""`ohg proxy`: listings never reveal credentials; the default is direct and disabled."""

import json

from typer.testing import CliRunner

from open_hypergamy.cli import app

runner = CliRunner()

CONFIG = """
proxy:
  enabled: true
  trusted_endpoint_hosts: [edge1.proxy.example.net]
  health_check_url: https://health.example.org/ok
  profiles:
    - name: edge1
      url: https://edge1.proxy.example.net:8443
      trusted: true
      username_secret: OHG_PROXY_EDGE1_USER
      password_secret: OHG_PROXY_EDGE1_PASS
  assignments:
    some-source: [edge1]
"""


def test_default_listing_is_disabled_and_direct():
    r = runner.invoke(app, ["proxy", "list", "--json"])
    assert r.exit_code == 0, r.output
    data = json.loads(r.stdout)
    assert data["proxy_enabled"] is False and data["default"] == "direct" and data["profiles"] == []


def test_listing_shows_credential_state_but_never_values(tmp_path, monkeypatch):
    cfg = tmp_path / "settings.yaml"
    cfg.write_text(CONFIG)
    monkeypatch.setenv("OHG_PROXY_EDGE1_USER", "alice-the-user")
    monkeypatch.setenv("OHG_PROXY_EDGE1_PASS", "pa55-VALUE-SECRET")
    r = runner.invoke(app, ["proxy", "list", "--json", "--config", str(cfg)])
    assert r.exit_code == 0, r.output
    assert "alice-the-user" not in r.output and "pa55" not in r.output
    [row] = json.loads(r.stdout)["profiles"]
    assert row["credentials"] == "configured" and row["trusted"] is True
    human = runner.invoke(app, ["proxy", "list", "--config", str(cfg)])
    assert "pa55" not in human.output and "alice-the-user" not in human.output


def test_missing_secrets_are_reported_as_missing(tmp_path):
    cfg = tmp_path / "settings.yaml"
    cfg.write_text(CONFIG)
    r = runner.invoke(app, ["proxy", "list", "--json", "--config", str(cfg)])
    assert json.loads(r.stdout)["profiles"][0]["credentials"] == "missing"


def test_check_refuses_when_proxies_are_disabled():
    r = runner.invoke(app, ["proxy", "check"])
    assert r.exit_code == 2 and "nothing to check" in r.output
