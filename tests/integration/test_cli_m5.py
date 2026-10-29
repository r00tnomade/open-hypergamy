import json
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from tests.helpers import FakeWeb, fixture, html, make_fetcher
from tests.helpers_tg import RecordingSink
from typer.testing import CliRunner

from open_hypergamy import cli
from open_hypergamy.cli import app
from open_hypergamy.clock import local_today
from open_hypergamy.errors import ConfigurationError
from open_hypergamy.notifications.base import SendResult

runner = CliRunner(env={"COLUMNS": "220"})
FIX = Path(__file__).parent.parent / "fixtures"
SEED = "https://example.edu/students/opportunities"
CHILD = SEED + "/summer-school"


def d(dt: date) -> str:
    return f"{dt.day} {dt.strftime('%B %Y')}"


def live_page() -> bytes:
    """A programme page whose dates are relative to today, so system-clock CLI runs are stable."""
    t = local_today(datetime.now(UTC))  # the app's notion of today (configured timezone), not UTC
    close, opens, start = t + timedelta(days=10), t - timedelta(days=5), t + timedelta(days=70)
    end = start + timedelta(days=4)
    page = fixture("programme.html").decode()
    page = (page.replace("10 to 14 June 2027", f"{start.day} to {end.day} {end.strftime('%B %Y')}")
            .replace("1 January 2027", d(opens)).replace("15 March 2027", d(close))
            .replace("1 May 2027", d(close - timedelta(days=3))).replace("2027", str(start.year)))  # fmt: skip
    return page.encode()


@pytest.fixture
def setup(monkeypatch):
    web = FakeWeb({SEED: html(fixture("index.html")), CHILD: html(live_page())})
    sink = RecordingSink()
    monkeypatch.setattr(cli, "build_fetcher", lambda cfg, clock=None: make_fetcher(web)[0])
    monkeypatch.setattr(cli, "build_sink", lambda: sink)
    runner.invoke(app, ["init"])
    runner.invoke(app, ["sources", "import", str(FIX / "sources_good.yaml")])
    return web, sink


def add_profile():
    import os

    shutil.copy(FIX / "profile.yaml", Path(os.environ["OHG_HOME"]) / "profile.yaml")


def j(args):
    r = runner.invoke(app, args)
    assert r.exit_code == 0, r.output
    return json.loads(r.stdout)


def test_no_profile_means_no_scoring_and_a_clear_hint(setup):
    r = runner.invoke(app, ["run", "discovery"])
    assert "No profile found" in r.output
    assert runner.invoke(app, ["run", "score"]).exit_code == 2
    assert runner.invoke(app, ["profile", "show"]).exit_code == 2
    assert j(["opportunities", "list", "--json"])[0]["fit"] is None


def test_run_discovery_scores_and_sends_alerts_once(setup):
    web, sink = setup
    add_profile()
    r = runner.invoke(app, ["run", "discovery"])
    assert r.exit_code == 0, r.output
    assert "scored 1 edition(s)" in r.output and "telegram: 2 sent" in r.output
    kinds = [m.notification_type for m, _ in sink.sent]
    assert sorted(kinds) == ["application_opened", "deadline_reminder"]
    assert all(CHILD in m.text for m, _ in sink.sent)
    [o] = j(["opportunities", "list", "--json"])
    assert (
        o["fit"]
        and o["band"] == "high"
        and o["action"] == "apply"
        and o["eligibility"] == "possibly_eligible"
    )
    again = runner.invoke(app, ["run", "score"])
    assert "no new alerts" in again.output and len(sink.sent) == 2
    assert runner.invoke(app, ["run", "discovery"]).exit_code == 0 and len(sink.sent) == 2


def test_list_filters(setup):
    add_profile()
    runner.invoke(app, ["run", "discovery"])
    assert len(j(["opportunities", "list", "--json", "--action", "apply"])) == 1
    assert j(["opportunities", "list", "--json", "--action", "archived"]) == []
    assert j(["opportunities", "list", "--json", "--min-fit", "99"]) == []
    assert len(j(["opportunities", "list", "--json", "--within", "30d"])) == 1
    assert j(["opportunities", "list", "--json", "--within", "1d"]) == []


def test_show_includes_score_eligibility_and_actions(setup):
    add_profile()
    runner.invoke(app, ["run", "discovery"])
    eid = j(["opportunities", "list", "--json"])[0]["id"][:8]
    shown = runner.invoke(app, ["opportunities", "show", eid])
    assert shown.exit_code == 0
    for needle in (
        "score",
        "reasons",
        "HIGH_CAREER_ALIGNMENT",
        "eligibility",
        "submit_application",
        "confirmed",
    ):
        assert needle in shown.output


def test_set_action_locks_planner_and_auto_returns_control(setup):
    add_profile()
    runner.invoke(app, ["run", "discovery"])
    eid = j(["opportunities", "list", "--json"])[0]["id"][:8]
    assert runner.invoke(app, ["opportunities", "set-action", eid, "bogus"]).exit_code == 2
    ok = runner.invoke(
        app, ["opportunities", "set-action", eid, "applied", "--note", "sent on Monday"]
    )
    assert ok.exit_code == 0
    runner.invoke(app, ["run", "score"])
    [o] = j(["opportunities", "list", "--json"])
    assert o["action"] == "applied"
    assert runner.invoke(app, ["actions", "list"]).output.count("submit_application") == 0
    assert "sent on Monday" in runner.invoke(app, ["opportunities", "show", eid]).output
    runner.invoke(app, ["opportunities", "set-action", eid, "auto"])
    runner.invoke(app, ["opportunities", "set-action", eid, "monitor"])  # explicit again
    assert j(["opportunities", "list", "--json"])[0]["action"] == "monitor"
    runner.invoke(app, ["opportunities", "set-action", eid, "auto"])
    runner.invoke(app, ["run", "score"])
    assert j(["opportunities", "list", "--json"])[0]["action"] == "apply"


def test_actions_done_and_dismiss_are_final(setup):
    add_profile()
    runner.invoke(app, ["run", "discovery"])
    listing = runner.invoke(app, ["actions", "list"])
    assert "submit_application" in listing.output
    import os

    from open_hypergamy.config import load_config
    from open_hypergamy.persistence import db as dbm

    conn = dbm.connect(load_config(home=Path(os.environ["OHG_HOME"])).paths.db)
    ids = {r["action_type"]: r["id"] for r in conn.execute("SELECT * FROM action_items")}
    conn.close()
    assert runner.invoke(app, ["actions", "done", ids["submit_application"][:8]]).exit_code == 0
    assert runner.invoke(app, ["actions", "dismiss", ids["prepare_materials"][:8]]).exit_code == 0
    runner.invoke(app, ["run", "score"])
    assert "0 open action(s)" in runner.invoke(app, ["actions", "list"]).output
    assert "1 done action(s)" in runner.invoke(app, ["actions", "list", "--status", "done"]).output
    assert runner.invoke(app, ["actions", "done", "zzzz"]).exit_code == 2


def test_profile_commands(setup):
    add_profile()
    assert runner.invoke(app, ["profile", "validate"]).exit_code == 0
    shown = runner.invoke(app, ["profile", "show"])
    assert "bachelor" in shown.output
    import os

    (Path(os.environ["OHG_HOME"]) / "profile.yaml").write_text(
        "version: 1\nprofile_version: x\nacademic: {country: DE}\n"
    )
    assert runner.invoke(app, ["profile", "validate"]).exit_code == 2


def test_sentinel_dry_run_previews_without_writing(setup):
    web, sink = setup
    add_profile()
    runner.invoke(app, ["run", "discovery", "--no-alerts"])
    r = runner.invoke(app, ["run", "sentinel", "--dry-run"])
    assert (
        r.exit_code == 0
        and "Applications are open" in r.output
        and "⏳ Deadline in 10 days" in r.output
    )
    assert sink.sent == []
    assert j(["status", "--json"])["notifications_pending"] == 0


def test_sentinel_rechecks_and_alerts(setup):
    web, sink = setup
    add_profile()
    runner.invoke(app, ["run", "discovery", "--no-alerts"])
    r = runner.invoke(app, ["run", "sentinel"])
    assert r.exit_code == 0, r.output
    assert "edition(s) to re-verify" in r.output and "telegram: 2 sent" in r.output


def test_sentinel_recheck_failure_is_partial_exit_4(setup):
    web, sink = setup
    add_profile()
    runner.invoke(app, ["run", "discovery", "--no-alerts"])
    import os

    from open_hypergamy.config import load_config
    from open_hypergamy.persistence import db as dbm

    conn = dbm.connect(load_config(home=Path(os.environ["OHG_HOME"])).paths.db)
    conn.execute("UPDATE editions SET source_fresh_until='2000-01-01T00:00:00Z'")
    conn.close()
    web.routes[CHILD] = httpx.Response(503)
    r = runner.invoke(app, ["run", "sentinel"])
    assert r.exit_code == 4 and "failed 1" in r.output


def test_digest_dry_run_and_send(setup):
    web, sink = setup
    add_profile()
    runner.invoke(app, ["run", "discovery", "--no-alerts"])
    dry = runner.invoke(app, ["run", "digest", "--dry-run"])
    assert dry.exit_code == 0 and "weekly digest" in dry.output and "1. Top actions" in dry.output
    assert sink.sent == []
    sent = runner.invoke(app, ["run", "digest"])
    assert sent.exit_code == 0 and "digest queued" in sent.output
    assert [m.notification_type for m, _ in sink.sent] == ["digest"]
    runner.invoke(app, ["run", "digest"])
    assert len(sink.sent) == 1  # one digest per ISO week


def test_run_all_and_dry_run(setup):
    web, sink = setup
    add_profile()
    assert "1 source(s) due" in runner.invoke(app, ["run", "all", "--dry-run"]).output
    r = runner.invoke(app, ["run", "all"])
    assert r.exit_code == 0 and "discovery: 1 source(s)" in r.output and "scored 1" in r.output


def test_notify_test_and_retry(setup, monkeypatch):
    web, sink = setup
    ok = runner.invoke(app, ["notify", "test"])
    assert ok.exit_code == 0 and sink.sent[0][0].notification_type == "test"
    bad = RecordingSink([SendResult(False, error="HTTP 401: Unauthorized", permanent=True)])
    monkeypatch.setattr(cli, "build_sink", lambda: bad)
    r = runner.invoke(app, ["notify", "test"])
    assert r.exit_code == 1 and "Unauthorized" in r.output

    def missing():
        raise ConfigurationError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")

    monkeypatch.setattr(cli, "build_sink", missing)
    assert runner.invoke(app, ["notify", "test"]).exit_code == 2


def test_failed_deliveries_show_in_status_and_can_be_requeued(setup, monkeypatch):
    web, sink = setup
    add_profile()
    broken = RecordingSink(
        [SendResult(False, error="HTTP 403: bot was blocked", permanent=True)] * 2
    )
    monkeypatch.setattr(cli, "build_sink", lambda: broken)
    runner.invoke(app, ["run", "discovery"])
    st = j(["status", "--json"])
    assert st["notifications_failed"] == 2 and "bot was blocked" in st["last_notification_error"]
    monkeypatch.setattr(cli, "build_sink", lambda: sink)
    r = runner.invoke(app, ["notify", "retry", "--include-failed"])
    assert r.exit_code == 0 and "re-queued 2" in r.output and "2 sent" in r.output
    assert j(["status", "--json"])["notifications_failed"] == 0


def test_telegram_disabled_switch(setup, monkeypatch):
    web, sink = setup
    add_profile()
    monkeypatch.setenv("OHG_TELEGRAM_ENABLED", "false")
    runner.invoke(app, ["run", "discovery"])
    assert sink.sent == [] and j(["status", "--json"])["notifications_pending"] == 0
    assert runner.invoke(app, ["notify", "test"]).exit_code == 2
