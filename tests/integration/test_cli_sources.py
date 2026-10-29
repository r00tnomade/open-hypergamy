import json
from pathlib import Path

import httpx
import pytest
from tests.helpers import FakeWeb, fixture, html, make_fetcher
from typer.testing import CliRunner

from open_hypergamy import cli
from open_hypergamy.cli import app

runner = CliRunner(env={"COLUMNS": "200"})  # keep Rich tables from truncating cells
GOOD = str(Path(__file__).parent.parent / "fixtures" / "sources_good.yaml")
SEED = "https://example.edu/students/opportunities"


@pytest.fixture
def web(monkeypatch):
    w = FakeWeb({SEED: html(fixture("index.html"))})
    monkeypatch.setattr(cli, "build_fetcher", lambda cfg, clock=None: make_fetcher(w)[0])
    runner.invoke(app, ["init"])
    return w


def test_import_dry_run_then_real_then_list(web):
    r = runner.invoke(app, ["sources", "import", GOOD, "--dry-run"])
    assert r.exit_code == 0 and "created 1" in r.output
    assert json.loads(runner.invoke(app, ["sources", "list", "--json"]).stdout) == []
    assert runner.invoke(app, ["sources", "import", GOOD]).exit_code == 0
    rows = json.loads(runner.invoke(app, ["sources", "list", "--json"]).stdout)
    assert rows[0]["key"] == "example-student-programmes" and rows[0]["state"] == "active"
    r2 = runner.invoke(app, ["sources", "import", GOOD])
    assert "created 0, updated 1" in r2.output


def test_invalid_yaml_exit_2(web, tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: 1\nsources:\n  - source_key: ab\n")
    assert runner.invoke(app, ["sources", "import", str(bad)]).exit_code == 2


def test_run_discovery_partial_then_not_due(web):
    runner.invoke(
        app, ["sources", "import", GOOD]
    )  # fixture follows links; children 404 -> partial
    r = runner.invoke(app, ["run", "discovery"])
    assert r.exit_code == 4, r.output
    assert "partial" in r.output
    st = json.loads(runner.invoke(app, ["status", "--json"]).stdout)
    assert st["last_jobs"]["discovery"]["status"] == "partial" and st["sources_enabled"] == 1
    again = runner.invoke(app, ["run", "discovery"])
    assert again.exit_code == 0 and "0 source(s) considered" in again.output


def test_run_discovery_total_failure_exit_1(web, monkeypatch):
    web.routes[SEED] = httpx.Response(500)
    runner.invoke(app, ["sources", "import", GOOD])
    assert runner.invoke(app, ["run", "discovery"]).exit_code == 1
    out = runner.invoke(app, ["sources", "failures"])
    assert "http_error" in out.output and "example-student-programmes" in out.output


def test_coverage_is_honest(web):
    cov0 = json.loads(runner.invoke(app, ["sources", "coverage", "--json"]).stdout)
    assert cov0["configured"] == 0 and cov0["enabled"] == 0
    runner.invoke(app, ["sources", "import", GOOD])
    runner.invoke(app, ["run", "discovery"])
    cov = json.loads(runner.invoke(app, ["sources", "coverage", "--json"]).stdout)
    assert cov["configured"] == 1 and cov["enabled"] == 1 and cov["checked_ok_last_30d"] == 1
    assert cov["t1_t2"] == 1 and cov["discovery_only"] == 0


def test_add_enable_disable_flow(web):
    r = runner.invoke(app, ["sources", "add", "https://news.example.org/feed"])
    assert r.exit_code == 0 and "review_required" in r.output
    key = json.loads(runner.invoke(app, ["sources", "list", "--json"]).stdout)[0]["key"]
    assert runner.invoke(app, ["sources", "enable", key]).exit_code == 2
    assert runner.invoke(app, ["sources", "enable", key, "--override-policy-review"]).exit_code == 0
    assert runner.invoke(app, ["sources", "disable", key, "--reason", "noisy"]).exit_code == 0
    shown = json.loads(runner.invoke(app, ["sources", "show", key, "--json"]).stdout)
    assert shown["enabled"] is False and shown["discovery_only"] is True


def test_add_rejects_private_target(web):
    assert runner.invoke(app, ["sources", "add", "http://192.168.0.1/admin"]).exit_code == 1


def test_sources_test_inspects_without_persisting(web):
    runner.invoke(app, ["sources", "import", GOOD])
    r = runner.invoke(app, ["sources", "test", "example-student-programmes"])
    assert r.exit_code == 0 and "Student Opportunities" in r.output
    st = json.loads(runner.invoke(app, ["status", "--json"]).stdout)
    assert st["last_jobs"] == {}
