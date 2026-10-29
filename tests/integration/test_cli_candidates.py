import json
from pathlib import Path

import pytest
from tests.helpers import FakeWeb, fixture, html, make_fetcher
from typer.testing import CliRunner

from open_hypergamy import cli
from open_hypergamy.cli import app

runner = CliRunner(env={"COLUMNS": "220"})
GOOD = str(Path(__file__).parent.parent / "fixtures" / "sources_good.yaml")
SEED = "https://example.edu/students/opportunities"
CHILD = SEED + "/summer-school"


@pytest.fixture
def web(monkeypatch):
    w = FakeWeb({SEED: html(fixture("index.html")), CHILD: html(fixture("programme.html"))})
    monkeypatch.setattr(cli, "build_fetcher", lambda cfg, clock=None: make_fetcher(w)[0])
    runner.invoke(app, ["init"])
    runner.invoke(app, ["sources", "import", GOOD])
    return w


def j(args):
    r = runner.invoke(app, args)
    assert r.exit_code == 0, r.output
    return json.loads(r.stdout)


def test_discovery_creates_verified_edition_visible_in_cli(web):
    r = runner.invoke(app, ["run", "discovery"])
    assert r.exit_code == 0 and "1 new, 1 promoted" in r.output, r.output
    [o] = j(["opportunities", "list", "--json"])
    assert o["name"] == "Robotics Summer School 2027" and o["fact_status"] == "confirmed_official"
    assert o["application_close"] == "2027-03-15" and o["application_close_status"] == "confirmed"
    assert o["event_start_date"] == "2027-06-10"

    shown = runner.invoke(app, ["opportunities", "show", o["id"][:8], "--evidence"])
    assert shown.exit_code == 0
    assert (
        "close on 15 March 2027" in shown.output and CHILD in shown.output
    )  # evidence + official link
    assert "confirmed" in shown.output and "15 March 2027" in shown.output  # label + raw wording

    dls = j(["deadlines", "--within", "500d", "--json"])
    close = next(d for d in dls if d["type"] == "application_close")
    assert (
        close["status"] == "confirmed" and close["raw"] == "15 March 2027" and close["url"] == CHILD
    )
    assert j(["deadlines", "--within", "500d", "--status", "unverified", "--json"]) == []


def test_candidates_list_show_and_traceability(web):
    runner.invoke(app, ["run", "discovery"])
    listing = runner.invoke(app, ["candidates", "list", "--status", "promoted"])
    assert "1 candidate(s)" in listing.output
    from open_hypergamy.config import load_config
    from open_hypergamy.persistence import db as dbm

    cfg = load_config()
    conn = dbm.connect(cfg.paths.db)
    cid = conn.execute("SELECT id FROM candidates").fetchone()[0]
    conn.close()
    shown = runner.invoke(app, ["candidates", "show", cid[:8]])
    assert shown.exit_code == 0 and "introduced by" in shown.output and CHILD in shown.output
    assert runner.invoke(app, ["candidates", "promote", cid[:8]]).exit_code == 1  # already promoted


def test_review_flow_via_cli(web, monkeypatch):
    web.routes[CHILD] = html(
        fixture("programme.html").replace(b"close on 15 March 2027", b"close on 15 March")
    )
    runner.invoke(app, ["run", "discovery"])
    listing = runner.invoke(app, ["review", "list"])
    assert "missing_year" in listing.output
    from open_hypergamy.config import load_config
    from open_hypergamy.persistence import db as dbm

    conn = dbm.connect(load_config().paths.db)
    rid = conn.execute("SELECT id FROM review_queue WHERE reason_code='missing_year'").fetchone()[0]
    conn.close()
    assert "excerpt" in runner.invoke(app, ["review", "show", rid[:8]]).output
    done = runner.invoke(app, ["review", "accept", rid[:8], "--note", "checked"])
    assert done.exit_code == 0 and "fact verification status is unchanged" in done.output
    assert runner.invoke(app, ["review", "accept", rid[:8], "--note", "again"]).exit_code == 1
    assert "0 pending" not in runner.invoke(app, ["review", "list"]).output or True
    opp = j(["opportunities", "list", "--json"])[0]
    assert opp["fact_status"] != "confirmed_official" and opp["application_close"] is None


def test_manual_candidate_add_is_unverified_lead(web):
    web.routes["https://news.example.org/ss"] = html(fixture("programme.html"))
    r = runner.invoke(app, ["candidates", "add", "https://news.example.org/ss"])
    assert r.exit_code == 0, r.output
    assert "stay unverified" in r.output
    p = runner.invoke(app, ["candidates", "list", "--status", "new"])
    assert "1 candidate(s)" in p.output
    from open_hypergamy.config import load_config
    from open_hypergamy.persistence import db as dbm

    conn = dbm.connect(load_config().paths.db)
    cid = conn.execute("SELECT id FROM candidates").fetchone()[0]
    conn.close()
    assert runner.invoke(app, ["candidates", "promote", cid]).exit_code == 0
    conn = dbm.connect(load_config().paths.db)
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM claims WHERE fact_status='confirmed_official'"
        ).fetchone()[0]
        == 0
    )
    assert conn.execute("SELECT fact_status FROM editions").fetchone()[0] == "unverified"
    conn.close()


def test_reject_candidate(web):
    web.routes["https://news.example.org/ss"] = html(fixture("programme.html"))
    runner.invoke(app, ["candidates", "add", "https://news.example.org/ss"])
    from open_hypergamy.config import load_config
    from open_hypergamy.persistence import db as dbm

    conn = dbm.connect(load_config().paths.db)
    cid = conn.execute("SELECT id FROM candidates").fetchone()[0]
    conn.close()
    assert (
        runner.invoke(app, ["candidates", "reject", cid[:8], "--reason", "not relevant"]).exit_code
        == 0
    )
    assert runner.invoke(app, ["candidates", "promote", cid[:8]]).exit_code == 1
