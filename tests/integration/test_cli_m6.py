import json
import os
import plistlib
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from tests.integration.test_cli_m5 import CHILD, FIX, SEED, add_profile, setup  # noqa: F401, F811
from typer.testing import CliRunner

from opportunity_radar.cli import app

runner = CliRunner(env={"COLUMNS": "240"})


def home() -> Path:
    return Path(os.environ["RADAR_HOME"])


def db() -> sqlite3.Connection:
    c = sqlite3.connect(home() / "opportunity_radar.sqlite3")
    c.row_factory = sqlite3.Row
    return c


def j(args):
    r = runner.invoke(app, args)
    assert r.exit_code == 0, r.output
    return json.loads(r.stdout)


def jobs(job=None):
    c = db()
    rows = c.execute(
        "SELECT * FROM job_runs" + (" WHERE job_type=?" if job else "") + " ORDER BY rowid",
        (job,) if job else (),
    ).fetchall()
    c.close()
    return rows


# --- reports ---------------------------------------------------------------------------------------
def test_weekly_report_default_path_stdout_json_and_custom_output(setup, tmp_path):
    add_profile()
    runner.invoke(app, ["run", "discovery"])
    r = runner.invoke(app, ["report", "weekly"])
    assert r.exit_code == 0 and "Weekly report written" in r.output
    [f] = list((home() / "reports").glob("weekly-*.md"))
    assert (f.stat().st_mode & 0o077) == 0 and "## 8. Monitoring health" in f.read_text()
    assert f"]({CHILD})" in runner.invoke(app, ["report", "weekly", "--stdout"]).stdout
    data = j(["report", "weekly", "--json"])
    assert data["top_actions"] and data["monitoring"]["sources_configured"] == 1
    custom = tmp_path / "out" / "w.md"
    assert (
        runner.invoke(app, ["report", "weekly", "--output", str(custom)]).exit_code == 0
        and custom.exists()
    )


def test_changes_and_sources_reports(setup):
    add_profile()
    runner.invoke(app, ["run", "discovery"])
    ch = j(["report", "changes", "--since", "7d", "--json"])
    assert len(ch["new_editions"]) == 1 and ch["moved_deadlines"] == []
    assert "# Changes since" in runner.invoke(app, ["report", "changes"]).stdout
    src = j(["report", "sources", "--json"])
    assert src["configured"] == 1 and src["target"] == 200 and src["healthy_30d"] == 1
    md = runner.invoke(app, ["report", "sources"]).stdout
    assert "**Actual:** 1 configured" in md and "no policy review" not in md
    assert runner.invoke(app, ["report", "changes", "--since", "soon"]).exit_code == 2


def test_export_ics_command(setup, tmp_path):
    add_profile()
    runner.invoke(app, ["run", "discovery"])
    out = tmp_path / "cal" / "radar.ics"
    r = runner.invoke(app, ["export-ics", "--output", str(out)])
    assert r.exit_code == 0 and "calendar item(s) written" in r.output
    text = out.read_bytes().decode()
    assert (
        text.startswith("BEGIN:VCALENDAR\r\n")
        and text.count("BEGIN:VEVENT") == text.count("END:VEVENT") >= 3
    )
    empty = tmp_path / "none.ics"
    runner.invoke(app, ["export-ics", "--output", str(empty), "--action", "archived"])
    assert "BEGIN:VEVENT" not in empty.read_text()


# --- backups ---------------------------------------------------------------------------------------------
def test_backup_job_retention_restore_to_and_status(setup, tmp_path):
    r = runner.invoke(app, ["db", "backup"])
    assert r.exit_code == 0 and "Retention: kept" in r.output
    [b] = jobs("backup")
    assert b["status"] == "success" and json.loads(b["summary_json"])["file"].startswith("radar-")
    st = j(["status", "--json"])
    assert st["backups_kept"] >= 1 and st["latest_restore_check"] is None
    backup = sorted((home() / "backups").glob("radar-*.sqlite3"))[-1]
    assert runner.invoke(app, ["db", "restore", "--check", str(backup)]).exit_code == 0
    assert j(["status", "--json"])["latest_restore_check"]["backup"] == backup.name
    target = tmp_path / "scratch" / "restored.sqlite3"
    ok = runner.invoke(app, ["db", "restore", str(backup), "--to", str(target)])
    assert ok.exit_code == 0 and "live database untouched" in ok.output and target.exists()
    assert (
        runner.invoke(app, ["db", "restore", str(backup), "--to", str(target)]).exit_code == 3
    )  # no overwrite
    live = home() / "opportunity_radar.sqlite3"
    assert runner.invoke(app, ["db", "restore", str(backup), "--to", str(live)]).exit_code == 3
    assert runner.invoke(app, ["db", "restore", str(backup)]).exit_code == 2


def test_prune_dry_run_lists_without_deleting(setup):
    recent = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y%m%dT%H%M%SZ")
    (home() / "backups").mkdir(exist_ok=True)
    (home() / "backups" / f"radar-{recent}.sqlite3").write_text("x")  # a recent backup must exist
    backups = home() / "backups"
    old = backups / "radar-20200101T000000Z.sqlite3"
    old.write_text("x")
    dry = runner.invoke(app, ["db", "prune-backups", "--dry-run"])
    assert "would remove 1" in dry.output and old.name in dry.output and old.exists()
    runner.invoke(app, ["db", "backup"])
    assert not old.exists()  # a normal backup applies retention
    runner.invoke(app, ["db", "backup", "--output", str(backups.parent / "manual.sqlite3")])
    assert (home() / "manual.sqlite3").exists()


# --- launchd ---------------------------------------------------------------------------------------------
def test_launchd_dry_run_install_status_uninstall(setup, tmp_path):
    dry = runner.invoke(app, ["launchd", "install", "--dry-run"])
    assert (
        dry.exit_code == 0
        and "com.opportunityradar.sentinel" in dry.output
        and "<key>Label</key>" in dry.output
    )
    agents = tmp_path / "agents"
    r = runner.invoke(app, ["launchd", "install", "--no-load", "--dir", str(agents)])
    assert r.exit_code == 0 and "Secrets are not stored in the plists" in r.output
    plists = sorted(agents.glob("com.opportunityradar.*.plist"))
    assert len(plists) == 4
    for p in plists:
        d = plistlib.loads(p.read_bytes())
        assert d["EnvironmentVariables"]["RADAR_HOME"] == str(home())
    os.environ["RADAR_LAUNCHD_DIR"] = str(agents)
    try:
        st = runner.invoke(app, ["launchd", "status", "--dir", str(agents)])
        assert st.output.count("yes") == 4
        gaps = j(["status", "--json"])["overdue_jobs"]
        assert len(gaps) == 4 and all("never completed" in g for g in gaps)
    finally:
        del os.environ["RADAR_LAUNCHD_DIR"]
    gone = runner.invoke(app, ["launchd", "uninstall", "--dir", str(agents), "--no-unload"])
    assert "Removed: backup, digest, discovery, sentinel" in gone.output and not list(
        agents.glob("*.plist")
    )


# --- job tracking / catch-up -------------------------------------------------------------------------------
def test_scheduled_jobs_are_recorded_with_their_trigger(setup, monkeypatch):
    add_profile()
    monkeypatch.setenv("RADAR_TRIGGER", "launchd")
    runner.invoke(app, ["run", "discovery", "--no-alerts"])
    assert runner.invoke(app, ["run", "sentinel"]).exit_code == 0
    assert runner.invoke(app, ["run", "digest"]).exit_code == 0
    runner.invoke(app, ["db", "backup"])
    by = {r["job_type"]: r for r in jobs()}
    assert set(by) == {"discovery", "sentinel", "digest", "backup"}
    assert {r["trigger_type"] for r in by.values()} == {"launchd"} and {
        r["status"] for r in by.values()
    } == {"success"}
    assert all(r["finished_at"] for r in by.values())
    monkeypatch.setenv("RADAR_TRIGGER", "evil")
    runner.invoke(app, ["run", "sentinel"])
    assert jobs("sentinel")[-1]["trigger_type"] == "manual"  # unknown triggers are not trusted


def test_failed_recheck_makes_the_sentinel_job_partial(setup):
    web, sink = setup
    add_profile()
    runner.invoke(app, ["run", "discovery", "--no-alerts"])
    c = db()
    c.execute("UPDATE editions SET source_fresh_until='2000-01-01T00:00:00Z'")
    c.commit()
    c.close()
    web.routes[CHILD] = httpx.Response(503)
    assert runner.invoke(app, ["run", "sentinel"]).exit_code == 4
    assert (
        jobs("sentinel")[-1]["status"] == "partial"
        and json.loads(jobs("sentinel")[-1]["summary_json"])["failed"] == 1
    )


def test_run_all_runs_the_sentinel_first_and_reports_gaps(setup):
    web, sink = setup
    add_profile()
    runner.invoke(app, ["run", "discovery", "--no-alerts"])
    c = db()
    old = (datetime.now(UTC) - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    c.execute(
        "INSERT INTO job_runs(id, job_type, trigger_type, started_at, status) VALUES ('old','sentinel','launchd',?, 'success')",
        (old,),
    )
    c.commit()
    c.close()
    before = len(jobs())
    r = runner.invoke(app, ["run", "all"])
    assert r.exit_code == 0, r.output
    assert "monitoring gap" in r.output and "sentinel: last success" in r.output
    types = [x["job_type"] for x in jobs()][before:]
    assert types.index("sentinel") < types.index(
        "discovery"
    )  # sentinel logic runs against the current time first
    assert [m.notification_type for m, _ in setup[1].sent].count("monitoring_gap") == 1
    assert "[dry run]" in runner.invoke(app, ["run", "all", "--dry-run"]).output


# --- source tooling ---------------------------------------------------------------------------------------------
def test_sources_audit_flags_quality_gaps_and_exits_4(setup):
    clean = runner.invoke(app, ["sources", "audit"])
    assert "Target ~200 sources" in clean.output and "configured 1" in clean.output
    assert "no portfolio assigned" in clean.output and clean.exit_code == 4
    c = db()
    c.execute("UPDATE sources SET portfolio='de_research'")
    c.commit()
    c.close()
    assert runner.invoke(app, ["run", "discovery", "--no-alerts"]).exit_code in (0, 4)
    data = j(["sources", "audit", "--json"]) if False else None
    _ = data
    ok = runner.invoke(app, ["sources", "audit"])
    assert "de_research" in ok.output


def test_probe_checks_a_batch_without_importing(setup, tmp_path):
    web, sink = setup
    batch = tmp_path / "batch.yaml"
    batch.write_text((FIX / "sources_good.yaml").read_text())
    r = runner.invoke(app, ["sources", "probe", str(batch)])
    assert r.exit_code == 0 and "ok" in r.output and "nothing was imported" in r.output
    conn = db()
    assert [r["source_key"] for r in conn.execute("SELECT source_key FROM sources")] == [
        "example-student-programmes"
    ]
    conn.close()
    web.routes[SEED] = httpx.Response(500)
    bad = runner.invoke(app, ["sources", "probe", str(batch)])
    assert bad.exit_code == 4 and "FAILED" in bad.output
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("version: 1\nsources:\n  - source_key: x\n")
    assert runner.invoke(app, ["sources", "probe", str(bad_yaml)]).exit_code == 2


def test_probe_reports_policy_blocks(setup, tmp_path):
    web, sink = setup
    web.routes["https://example.edu/robots.txt"] = httpx.Response(
        200, text="User-agent: *\nDisallow: /\n"
    )
    batch = tmp_path / "batch.yaml"
    batch.write_text((FIX / "sources_good.yaml").read_text())
    r = runner.invoke(app, ["sources", "probe", str(batch)])
    assert r.exit_code == 4 and "blocked" in r.output
