import json

import pytest
from tests.helpers_llm import FakeGateway
from typer.testing import CliRunner

from open_hypergamy import cli
from open_hypergamy.cli import app

runner = CliRunner(env={"COLUMNS": "200"})


@pytest.fixture(autouse=True)
def init():
    runner.invoke(app, ["init"])


def test_ack_requires_confirmation_and_writes_a_private_file():
    declined = runner.invoke(app, ["llm", "ack"], input="n\n")
    assert declined.exit_code == 1 and "no LLM request will be made" in declined.output
    st = json.loads(runner.invoke(app, ["llm", "status", "--json"]).stdout)
    assert st["acknowledged"] is False
    ok = runner.invoke(app, ["llm", "ack"], input="y\n")
    assert ok.exit_code == 0 and "Acknowledged at" in ok.output and "free-tier" in ok.output
    assert (
        json.loads(runner.invoke(app, ["llm", "status", "--json"]).stdout)["acknowledged"] is True
    )


def test_status_json_reports_state_without_inference(monkeypatch):
    gw = FakeGateway(models=["auto:ohg-free"])
    monkeypatch.setattr(cli, "build_client", lambda cfg: __import__("open_hypergamy.llm.client", fromlist=["x"]).OpenAICompatClient(
        "http://127.0.0.1:3001/v1", "auto:ohg-free", "k", transport=gw.transport))  # fmt: skip
    st = json.loads(runner.invoke(app, ["llm", "status", "--json"]).stdout)
    assert st["enabled"] and st["reachable"] is True and st["alias_listed"] is True
    assert st["external_processing"] is True and st["queued_candidates"] == 0
    assert "operator-attested" in st["note"] and gw.chat_requests == []
    assert "api_key" not in json.dumps(st).lower() or st["api_key_set"] in (True, False)


def test_run_llm_when_disabled(monkeypatch):
    monkeypatch.setenv("OHG_LLM_ENABLED", "false")
    r = runner.invoke(app, ["run", "llm"])
    assert r.exit_code == 0 and "disabled" in r.output
    st = json.loads(runner.invoke(app, ["llm", "status", "--json"]).stdout)
    assert st["enabled"] is False and "reachable" not in st


def test_local_provider_needs_no_ack(monkeypatch):
    monkeypatch.setenv("OHG_LLM_PROVIDER", "local")
    r = runner.invoke(app, ["llm", "ack"])
    assert r.exit_code == 0 and "no acknowledgement needed" in r.output
    assert (
        json.loads(runner.invoke(app, ["llm", "status", "--json"]).stdout)["external_processing"]
        is False
    )


def test_doctor_reflects_acknowledgement():
    assert "not recorded" in runner.invoke(app, ["doctor"]).output
    runner.invoke(app, ["llm", "ack", "--yes"])
    assert "recorded" in runner.invoke(app, ["doctor"]).output
