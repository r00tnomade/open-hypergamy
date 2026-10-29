import json

from typer.testing import CliRunner

from open_hypergamy.cli import app

runner = CliRunner()


def test_init_is_idempotent_and_prints_checklist():
    r = runner.invoke(app, ["init"])
    assert r.exit_code == 0, r.output
    assert "Created database" in r.output and "ohg-free" in r.output
    r2 = runner.invoke(app, ["init"])
    assert r2.exit_code == 0 and "Opened database" in r2.output and "applied 0" in r2.output


def test_status_json_is_valid_and_honest_about_empty_registry():
    runner.invoke(app, ["init"])
    r = runner.invoke(app, ["status", "--json"])
    assert r.exit_code == 0
    data = json.loads(r.stdout)
    assert data["schema_version"] == 5
    assert data["sources_configured"] == 0 and data["last_jobs"] == {}
    assert data["latest_backup"] is None


def test_status_before_init_is_database_error():
    r = runner.invoke(app, ["status"])
    assert r.exit_code == 3


def test_doctor_strict_fails_when_gateway_down(monkeypatch):
    runner.invoke(app, ["init"])
    monkeypatch.setenv("OHG_FREELLMAPI_BASE_URL", "http://127.0.0.1:1/v1")  # nothing listens
    assert runner.invoke(app, ["doctor"]).exit_code == 0
    assert runner.invoke(app, ["doctor", "--strict"]).exit_code == 5


def test_doctor_strict_ok_when_llm_disabled(monkeypatch):
    runner.invoke(app, ["init"])
    monkeypatch.setenv("OHG_LLM_ENABLED", "false")
    assert runner.invoke(app, ["doctor", "--strict"]).exit_code == 0


def test_doctor_missing_db_exit_3():
    assert runner.invoke(app, ["doctor"]).exit_code == 3


def test_backup_then_restore_check_then_integrity():
    runner.invoke(app, ["init"])
    r = runner.invoke(app, ["db", "backup"])
    assert r.exit_code == 0, r.output
    status = json.loads(runner.invoke(app, ["status", "--json"]).stdout)
    assert status["latest_backup"].startswith("ohg-")
    backup = next(
        (__import__("pathlib").Path(__import__("os").environ["OHG_HOME"]) / "backups").glob("ohg-*")
    )
    assert runner.invoke(app, ["db", "restore", "--check", str(backup)]).exit_code == 0
    assert runner.invoke(app, ["db", "restore", str(backup)]).exit_code == 2
    assert runner.invoke(app, ["db", "integrity-check"]).exit_code == 0


def test_restore_check_rejects_garbage(tmp_path):
    junk = tmp_path / "junk.sqlite3"
    junk.write_text("not a database")
    assert runner.invoke(app, ["db", "restore", "--check", str(junk)]).exit_code == 3


def test_migrate_dry_run_reports_nothing_pending():
    runner.invoke(app, ["init"])
    r = runner.invoke(app, ["db", "migrate", "--dry-run"])
    assert r.exit_code == 0 and "Would apply 0" in r.output
