"""CLI surface of source health (ADR-009): audit, list, unblock."""

import json

import httpx
from tests.integration.test_cli_m5 import SEED, setup  # noqa: F401, F811
from tests.integration.test_cli_m6 import db, runner

from open_hypergamy.cli import app

KEY = "example-student-programmes"


def test_audit_reports_hold_and_unblock_clears_it(setup):
    web, _ = setup
    assert runner.invoke(app, ["run", "discovery", "--no-alerts"]).exit_code in (0, 4)
    c = db()
    c.execute("UPDATE sources SET next_due_at=NULL")
    c.commit()
    c.close()
    web.routes[SEED] = httpx.Response(403)
    runner.invoke(app, ["run", "discovery", "--no-alerts"])

    r = runner.invoke(app, ["sources", "audit"])
    assert (
        r.exit_code == 4 and "held for manual review" in r.output and "blocked_review" in r.output
    )
    data = json.loads(runner.invoke(app, ["sources", "audit", "--json"]).stdout)
    [h] = data["source_health"]
    assert h["health"] == "blocked_review" and h["last_http_status"] == 403
    assert h["http_status_counts"]["403"] == 1 and h["checks_30d"] == 2
    assert h["retrieval_success_rate"] == 0.5 and h["last_successful_ingestion_at"]
    assert data["health_states"]["blocked_review"] == 1

    [row] = json.loads(runner.invoke(app, ["sources", "list", "--json"]).stdout)
    assert row["health"] == "blocked_review" and row["blocked_reason"].startswith("access_denied")
    held = runner.invoke(app, ["run", "discovery", "--source-id", KEY, "--no-alerts"])
    assert held.exit_code != 0 and "held for review" in held.output

    u = runner.invoke(app, ["sources", "unblock", KEY])
    assert u.exit_code == 0 and "cleared" in u.output
    [row] = json.loads(runner.invoke(app, ["sources", "list", "--json"]).stdout)
    assert row["blocked_reason"] is None and row["health"] != "blocked_review"
    assert runner.invoke(app, ["sources", "unblock", "nope"]).exit_code == 2
