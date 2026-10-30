"""`ohg onboard` and the `ohg init` hint. The server loop is stubbed; no browser is opened."""

from typer.testing import CliRunner

from open_hypergamy.cli import app
from open_hypergamy.config import resolve_home
from open_hypergamy.gui import server as gui_server

runner = CliRunner()


def _stub_server(monkeypatch, opened: list[str]):
    monkeypatch.setattr(
        gui_server.GuiServer,
        "serve_forever",
        lambda self: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    monkeypatch.setattr(gui_server, "open_browser", lambda url: opened.append(url) or True)


def test_onboard_initializes_then_serves_on_loopback(monkeypatch):
    opened: list[str] = []
    _stub_server(monkeypatch, opened)
    r = runner.invoke(app, ["onboard"])
    assert r.exit_code == 0, r.output
    assert "Initialised the database" in r.output
    assert (resolve_home() / "open_hypergamy.sqlite3").exists()
    assert (
        len(opened) == 1
        and opened[0].startswith("http://127.0.0.1:")
        and "/launch?code=" in opened[0]
    )
    assert "code=" not in r.output  # the one-time link isn't printed when the browser opened


def test_onboard_on_existing_install_does_not_reinitialize(monkeypatch):
    assert runner.invoke(app, ["init"]).exit_code == 0
    _stub_server(monkeypatch, [])
    r = runner.invoke(app, ["onboard"])
    assert r.exit_code == 0 and "Initialised" not in r.output


def test_onboard_no_browser_prints_the_one_time_link(monkeypatch):
    opened: list[str] = []
    _stub_server(monkeypatch, opened)
    r = runner.invoke(app, ["onboard", "--no-browser"])
    assert r.exit_code == 0 and opened == []
    assert "/launch?code=" in r.output and "valid for 5 minutes" in r.output


def test_onboard_starts_in_recovery_mode_for_a_broken_managed_settings_file(monkeypatch):
    home = resolve_home()
    home.mkdir(parents=True)
    (home / "settings.yaml").write_text("app: [broken\n")
    _stub_server(monkeypatch, [])
    r = runner.invoke(app, ["onboard"])
    assert r.exit_code == 0 and "can reset this file" in r.output


def test_onboard_refuses_a_broken_hand_written_settings_file(tmp_path, monkeypatch):
    bad = tmp_path / "mine.yaml"
    bad.write_text("app: [broken\n")
    _stub_server(monkeypatch, [])
    r = runner.invoke(app, ["onboard", "--config", str(bad)])
    assert r.exit_code != 0


def test_init_semantics_unchanged_and_hints_at_onboarding():
    r = runner.invoke(app, ["init"])
    assert r.exit_code == 0 and "Created database" in r.output and "Schema v" in r.output
    assert "ohg onboard" in r.output
    r = runner.invoke(app, ["init"])
    assert "Opened database" in r.output and "applied 0 migration(s)" in r.output
