import plistlib
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tests.integration.test_m5_flow import CHILD, Env

from opportunity_radar import keychain
from opportunity_radar.cli import app
from opportunity_radar.config import load_config
from opportunity_radar.monitoring.catchup import job_gaps
from opportunity_radar.persistence import backups as bk
from opportunity_radar.persistence import db as dbm
from opportunity_radar.persistence import migrations as mig
from opportunity_radar.reporting import changes as changes_report
from opportunity_radar.reporting import sources as sources_report
from opportunity_radar.reporting import weekly as weekly_report
from opportunity_radar.reporting.calendar import build_ics, esc, fold
from opportunity_radar.scheduling import launchd


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    yield e
    e.conn.close()


# --- .ics ------------------------------------------------------------------------------------------
def parse_ics(text: str) -> list[dict[str, list[str]]]:
    assert text.endswith("\r\n") and "\n" not in text.replace("\r\n", "")
    unfolded = text.replace("\r\n ", "").split("\r\n")[:-1]
    assert unfolded[0] == "BEGIN:VCALENDAR" and unfolded[-1] == "END:VCALENDAR"
    items, cur = [], None
    for line in unfolded[1:-1]:
        if line.startswith(("BEGIN:VEVENT", "BEGIN:VTODO")):
            cur = {"_type": [line[6:]]}
        elif line.startswith(("END:VEVENT", "END:VTODO")):
            items.append(cur)
            cur = None
        elif (
            cur is not None and ":" in line and not line.startswith(("BEGIN:VALARM", "END:VALARM"))
        ):
            k, _, v = line.partition(":")
            cur.setdefault(k, []).append(v)
    return items


def test_escaping_and_folding():
    assert esc("a,b;c\\d\ne") == "a\\,b\;c\\\\d\\ne"
    long = "SUMMARY:" + "ü" * 100
    folded = fold(long)
    assert all(len(seg.encode()) <= 75 for seg in folded.split("\r\n"))
    assert folded.replace("\r\n ", "") == long  # lossless, never splits a UTF-8 sequence


def test_export_separates_events_windows_deadlines_and_prep_tasks(env):
    env.discover()
    env.cycle()
    ics, n = build_ics(env.conn, env.clock, actions={"apply", "prepare"})
    items = parse_ics(ics)
    assert n == len(items) == 6
    kinds = {i["CATEGORIES"][0] for i in items}
    assert kinds == {"EVENT", "APPLICATION-WINDOW", "DEADLINE", "PREPARATION"}
    ev = next(i for i in items if i["CATEGORIES"] == ["EVENT"])
    assert ev["DTSTART;VALUE=DATE"] == ["20270610"] and ev["DTEND;VALUE=DATE"] == [
        "20270615"
    ]  # end is exclusive
    win = next(i for i in items if i["CATEGORIES"] == ["APPLICATION-WINDOW"])
    assert win["DTSTART;VALUE=DATE"] == ["20270101"] and win["DTEND;VALUE=DATE"] == ["20270316"]
    close = next(i for i in items if "Deadline (application close)" in i["SUMMARY"][0])
    assert close["DTSTART;VALUE=DATE"] == ["20270315"] and close["STATUS"] == ["CONFIRMED"]
    assert close["URL"] == [CHILD] and "As written: 15 March 2027" in close["DESCRIPTION"][
        0
    ].replace("\\n", "\n").replace("\\,", ",")
    assert "TRIGGER:-P2D" in ics
    todo = next(i for i in items if i["_type"] == ["VTODO"])
    assert todo["STATUS"] == ["NEEDS-ACTION"] and todo["DUE;VALUE=DATE"]
    assert (
        "T23:59" not in ics and "TZID" not in ics and "DTSTART:" not in ics
    )  # date-only stays date-only


def test_uids_are_stable_across_exports(env):
    env.discover()
    env.cycle()
    a = {i["UID"][0] for i in parse_ics(build_ics(env.conn, env.clock, actions={"apply"})[0])}
    env.clock.advance(hours=5)
    b = {i["UID"][0] for i in parse_ics(build_ics(env.conn, env.clock, actions={"apply"})[0])}
    assert a == b and all(u.endswith("@opportunityradar.local") for u in a)


def test_action_filter(env):
    env.discover()
    env.cycle()
    assert build_ics(env.conn, env.clock, actions={"monitor"})[1] == 0
    assert build_ics(env.conn, env.clock, actions={"apply"})[1] == 6


def test_only_confirmed_dates_unless_asked_and_always_labelled(env):
    env.discover()
    env.cycle()
    env.conn.execute(
        "UPDATE deadlines SET fact_status='unverified' WHERE deadline_type='abstract_submission'"
    )
    env.conn.execute(
        "UPDATE deadlines SET fact_status='stale' WHERE deadline_type='application_close'"
    )
    env.conn.execute(
        "UPDATE deadlines SET fact_status='estimated_recurring' WHERE deadline_type='application_open'"
    )
    text = build_ics(env.conn, env.clock, actions={"apply"})[0].replace("\r\n ", "")  # unfold
    assert (
        "Abstract" not in text and "ESTIMATE" not in text
    )  # unverified and estimates omitted by default
    assert "(stale: recheck)" in text and "STATUS:TENTATIVE" in text
    est = build_ics(
        env.conn, env.clock, actions={"apply"}, include_estimates=True, include_unverified=True
    )[0].replace("\r\n ", "")
    assert "[ESTIMATE – not confirmed]" in est and "[UNVERIFIED]" in est
    env.conn.execute(
        "UPDATE deadlines SET fact_status='conflicting_sources' WHERE deadline_type='application_close'"
    )
    assert (
        "Deadline (application close)"
        not in build_ics(env.conn, env.clock, actions={"apply"}, include_unverified=True)[0]
    )


# --- backups -----------------------------------------------------------------------------------------
def mk(day: str, hhmm="0300"):
    return bk.BackupFile(
        Path(f"radar-{day}T{hhmm}00Z.sqlite3"),
        datetime.strptime(f"{day}{hhmm}", "%Y%m%d%H%M").replace(tzinfo=UTC),
    )


def test_retention_policy_daily_then_weekly_then_nothing():
    now = datetime(2027, 3, 31, 12, tzinfo=UTC)
    files = [mk(f"202703{d:02d}", h) for d in range(1, 32) for h in ("0300", "1500")] + [
        mk("20270120")
    ]
    keep, remove = bk.plan_prune(files, now, keep_daily=7, keep_weekly=4)
    kept_days = {b.taken.date() for b in keep if b.taken.date() >= datetime(2027, 3, 24).date()}
    assert len(kept_days) == 8 and all(
        sum(1 for b in keep if b.taken.date() == d) == 1 for d in kept_days
    )
    assert all(
        b.taken.hour == 15 for b in keep if b.taken.date() >= datetime(2027, 3, 24).date()
    )  # newest per day
    older = [b for b in keep if b.taken.date() < datetime(2027, 3, 24).date()]
    weeks = {b.taken.isocalendar()[:2] for b in older}
    assert len(older) == len(weeks) <= 4 and not any(
        b.taken.year == 2027 and b.taken.month == 1 for b in keep
    )
    assert mk("20270120") in remove and len(keep) + len(remove) == len(files)


def test_newest_backup_is_never_pruned_even_when_ancient():
    old = [mk("20250101"), mk("20250102")]
    keep, remove = bk.plan_prune(old, datetime(2027, 1, 1, tzinfo=UTC), 7, 4)
    assert keep == [old[1]] and remove == [old[0]]


def test_prune_only_touches_radar_backups_and_removes_sidecars(tmp_path):
    for name in ("radar-20240101T000000Z.sqlite3", "radar-20240101T000000Z.sqlite3-wal", "radar-20270330T000000Z.sqlite3",
                 "pre-migration-20240101T000000Z.sqlite3", "notes.txt", "radar-bogus.sqlite3"):  # fmt: skip
        (tmp_path / name).write_text("x")
    kept, removed = bk.prune(tmp_path, datetime(2027, 3, 31, tzinfo=UTC), 7, 4)
    assert kept == 1 and [p.name for p in removed] == ["radar-20240101T000000Z.sqlite3"]
    left = {p.name for p in tmp_path.iterdir()}
    assert left == {
        "radar-20270330T000000Z.sqlite3",
        "pre-migration-20240101T000000Z.sqlite3",
        "notes.txt",
        "radar-bogus.sqlite3",
    }


def test_backup_is_standalone_and_restore_goes_to_a_new_path_only(env, tmp_path):
    dest = tmp_path / "b" / "radar-20270301T120000Z.sqlite3"
    assert dbm.backup_to(env.conn, dest) == []
    assert sorted(p.name for p in dest.parent.iterdir()) == [dest.name]  # no -wal/-shm sidecars
    ro = sqlite3.connect(f"file:{dest}?mode=ro", uri=True)
    assert ro.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    ro.close()
    assert bk.check_backup(dest) == mig.schema_version(env.conn)
    target = tmp_path / "restored" / "test.sqlite3"
    assert bk.restore_to(dest, target) == 5 and target.exists()
    restored = dbm.connect(target)
    assert restored.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1
    restored.close()
    with pytest.raises(Exception, match="overwrite"):
        bk.restore_to(dest, target)


def test_corrupt_backup_is_rejected(tmp_path):
    p = tmp_path / "radar-20270301T000000Z.sqlite3"
    p.write_bytes(b"SQLite format 3\x00" + b"\x00" * 200)
    with pytest.raises(Exception):  # noqa: B017
        bk.check_backup(p)


# --- launchd -------------------------------------------------------------------------------------------
def test_plists_are_absolute_secret_free_and_one_per_job(tmp_path):
    cfg = load_config(
        home=tmp_path / "home", env={"TELEGRAM_BOT_TOKEN": "1234567:SECRET-token-abcdefghijkl"}
    )
    specs = launchd.job_specs(cfg.settings.schedule)
    assert [s.job for s in specs] == ["sentinel", "discovery", "digest", "backup"]
    seen = {}
    for s in specs:
        d = plistlib.loads(launchd.render_plist(s, cfg))
        seen[s.job] = d
        assert d["Label"] == f"com.opportunityradar.{s.job}"
        assert all(Path(a).is_absolute() for a in d["ProgramArguments"][:1])
        assert (
            d["WorkingDirectory"] == str(cfg.paths.home)
            and Path(d["WorkingDirectory"]).is_absolute()
        )
        assert set(d["EnvironmentVariables"]) == {"PATH", "HOME", "RADAR_HOME", "RADAR_TRIGGER"}
        assert d["EnvironmentVariables"]["RADAR_TRIGGER"] == "launchd" and d["RunAtLoad"] is False
        assert d["StandardOutPath"].startswith(str(cfg.paths.home / "logs"))
        assert "SECRET" not in plistlib.dumps(d).decode()
    program = seen["sentinel"]["ProgramArguments"]
    assert (
        Path(program[0]).name == "radar" and Path(program[0]).is_file()
    )  # the venv's console script
    assert (
        ".venv" in program[0]
        or "site-packages" in program[0]
        or Path(program[0]).parent == Path(sys.executable).parent
    )
    assert seen["sentinel"]["ProgramArguments"][-2:] == ["run", "sentinel"]
    assert seen["backup"]["ProgramArguments"][-2:] == ["db", "backup"]
    assert seen["sentinel"]["StartCalendarInterval"] == {"Hour": 7, "Minute": 30}
    assert seen["discovery"]["StartCalendarInterval"] == {"Hour": 6, "Minute": 0, "Weekday": 1}


def test_custom_config_path_is_passed_as_absolute(tmp_path):
    cfg = load_config(home=tmp_path / "h", env={})
    spec = launchd.job_specs(cfg.settings.schedule)[0]
    f = tmp_path / "s.yaml"
    f.write_text("{}")
    assert plistlib.loads(launchd.render_plist(spec, cfg, config_file=f))["EnvironmentVariables"][
        "RADAR_CONFIG"
    ] == str(f.resolve())


def test_install_and_uninstall_manage_only_our_agents(tmp_path):
    cfg = load_config(home=tmp_path / "home", env={})
    calls: list[list[str]] = []
    agents = tmp_path / "LaunchAgents"
    agents.mkdir()
    (agents / "com.someoneelse.job.plist").write_text("keep me")
    res = launchd.install(cfg, agents_dir=agents, runner=lambda a: (calls.append(a), (0, ""))[1])
    assert {j for j, _, _ in res} == set(launchd.JOB_COMMANDS) and all(
        m == "loaded" for _, _, m in res
    )
    assert launchd.installed_jobs(agents) == set(launchd.JOB_COMMANDS)
    assert [c[0] for c in calls].count("bootstrap") == 4 and calls[0][0] == "bootout"
    assert oct((agents / "com.opportunityradar.sentinel.plist").stat().st_mode & 0o777) == "0o644"
    failed = launchd.install(
        cfg, agents_dir=agents, runner=lambda a: (1, "boom") if a[0] == "bootstrap" else (0, "")
    )
    assert all("load failed" in m for _, _, m in failed)
    removed = launchd.uninstall(agents_dir=agents, runner=lambda a: (0, ""))
    assert (
        removed == sorted(launchd.JOB_COMMANDS) and (agents / "com.someoneelse.job.plist").exists()
    )
    assert launchd.installed_jobs(agents) == set()


def test_no_load_writes_files_without_calling_launchctl(tmp_path):
    cfg = load_config(home=tmp_path / "home", env={})
    launchd.install(
        cfg, agents_dir=tmp_path / "a", load=False, runner=lambda a: pytest.fail("launchctl called")
    )
    assert launchd.installed_jobs(tmp_path / "a") == set(launchd.JOB_COMMANDS)


# --- keychain --------------------------------------------------------------------------------------------
@pytest.fixture
def fake_security(monkeypatch):
    store: dict[str, str] = {}
    calls: list[list[str]] = []

    def runner(args, stdin):
        calls.append(args)
        name = args[args.index("-a") + 1] if "-a" in args else ""
        if args[0] == "find-generic-password":
            return (0, store[name]) if name in store else (44, "")
        if args[0] == "add-generic-password":
            store[name] = args[args.index("-w") + 1]
            return 0, ""
        if args[0] == "delete-generic-password":
            return (0, "") if store.pop(name, None) is not None else (44, "")
        return 1, ""

    monkeypatch.setattr(keychain, "_runner", runner)
    monkeypatch.setattr(keychain.sys, "platform", "darwin")
    monkeypatch.setenv("RADAR_USE_KEYCHAIN", "1")
    keychain.clear_cache()
    yield store, calls
    keychain.clear_cache()


def test_environment_wins_then_keychain_and_unset_is_empty(fake_security, monkeypatch):
    store, calls = fake_security
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert (
        keychain.get_secret("TELEGRAM_BOT_TOKEN") == ""
        and keychain.source_of("TELEGRAM_BOT_TOKEN") == "unset"
    )
    keychain.set_secret("TELEGRAM_BOT_TOKEN", "from-keychain")
    assert (
        keychain.get_secret("TELEGRAM_BOT_TOKEN") == "from-keychain"
        and keychain.source_of("TELEGRAM_BOT_TOKEN") == "keychain"
    )
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "from-env")
    assert (
        keychain.get_secret("TELEGRAM_BOT_TOKEN") == "from-env"
        and keychain.source_of("TELEGRAM_BOT_TOKEN") == "environment"
    )
    assert keychain.delete_secret("TELEGRAM_BOT_TOKEN") and not keychain.delete_secret(
        "TELEGRAM_BOT_TOKEN"
    )


def test_keychain_is_never_consulted_when_disabled(monkeypatch):
    monkeypatch.setattr(keychain, "_runner", lambda a, s: pytest.fail("security called"))
    monkeypatch.setenv("RADAR_USE_KEYCHAIN", "0")
    keychain.clear_cache()
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert keychain.get_secret("TELEGRAM_BOT_TOKEN") == ""


def test_secrets_cli_never_prints_values(fake_security, monkeypatch):
    from typer.testing import CliRunner

    store, _ = fake_security
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setattr("getpass.getpass", lambda prompt: "1234567:super-secret-value")
    runner = CliRunner()
    r = runner.invoke(app, ["secrets", "set", "TELEGRAM_BOT_TOKEN"])
    assert (
        r.exit_code == 0
        and "super-secret" not in r.output
        and store["TELEGRAM_BOT_TOKEN"].startswith("1234567")
    )
    st = runner.invoke(app, ["secrets", "status"])
    assert "keychain" in st.output and "super-secret" not in st.output
    assert runner.invoke(app, ["secrets", "set", "NOT_A_SECRET"]).exit_code == 2
    assert "Deleted" in runner.invoke(app, ["secrets", "delete", "TELEGRAM_BOT_TOKEN"]).output


# --- catch-up and job tracking -----------------------------------------------------------------------------
def test_jobs_are_expected_once_installed_or_run_and_gaps_are_measured(env, tmp_path):
    agents = tmp_path / "agents"
    assert (
        job_gaps(env.conn, env.cfg, env.clock, agents) == []
    )  # nothing scheduled, nothing overdue
    launchd.install(env.cfg, agents_dir=agents, load=False)
    gaps = {g.job: g for g in job_gaps(env.conn, env.cfg, env.clock, agents)}
    assert (
        set(gaps) == {"sentinel", "discovery", "digest", "backup"}
        and gaps["sentinel"].overdue_hours is None
    )
    assert "never completed" in gaps["sentinel"].describe()
    now = env.clock.now_utc()
    for job, ago in (("sentinel", timedelta(hours=30)), ("backup", timedelta(hours=50)),
                     ("discovery", timedelta(days=3)), ("digest", timedelta(days=10))):  # fmt: skip
        env.conn.execute("INSERT INTO job_runs(id, job_type, trigger_type, started_at, status) VALUES (?,?, 'launchd', ?, 'success')",
                         (job, job, (now - ago).strftime("%Y-%m-%dT%H:%M:%SZ")))  # fmt: skip
    gaps = {g.job: g for g in job_gaps(env.conn, env.cfg, env.clock, agents)}
    assert (
        set(gaps) == {"backup", "digest"}
        and gaps["backup"].overdue_hours == 14
        and gaps["digest"].overdue_hours == 24
    )
    env.conn.execute("UPDATE job_runs SET status='failed' WHERE job_type='sentinel'")
    assert "sentinel" in {
        g.job for g in job_gaps(env.conn, env.cfg, env.clock, agents)
    }  # failures don't count


def test_gap_alert_is_sent_once_per_gap(env):
    from opportunity_radar.monitoring.cycle import queue_gap_alerts

    env.discover()
    env.conn.execute(
        "INSERT INTO job_runs(id, job_type, trigger_type, started_at, status) VALUES ('s','sentinel','launchd','2027-02-20T07:30:00Z','success')"
    )

    def gap_msgs():
        return [m for m, _ in env.sink.sent if m.notification_type == "monitoring_gap"]

    assert (
        queue_gap_alerts(env.conn, env.cfg, env.clock, job_gaps(env.conn, env.cfg, env.clock)) == 1
    )
    env.cycle()
    assert len(gap_msgs()) == 1 and "sentinel" in gap_msgs()[0].text
    assert "recalculated from the current time" in gap_msgs()[0].text
    assert (
        queue_gap_alerts(env.conn, env.cfg, env.clock, job_gaps(env.conn, env.cfg, env.clock)) == 0
    )  # same gap
    env.conn.execute(
        "INSERT INTO job_runs(id, job_type, trigger_type, started_at, status) VALUES ('s2','sentinel','launchd','2027-02-25T07:30:00Z','success')"
    )
    env.clock.advance(days=3)
    assert (
        queue_gap_alerts(env.conn, env.cfg, env.clock, job_gaps(env.conn, env.cfg, env.clock)) == 1
    )  # a new gap
    env.cfg.settings.telegram.enabled = False
    env.clock.advance(days=3)
    assert (
        queue_gap_alerts(env.conn, env.cfg, env.clock, job_gaps(env.conn, env.cfg, env.clock)) == 0
    )


# --- reports -----------------------------------------------------------------------------------------------
def test_weekly_markdown_has_all_sections_links_labels_and_honest_health(env):
    env.discover()
    env.cycle()
    md = weekly_report.render_markdown(weekly_report.gather(env.conn, env.cfg, env.clock))
    for h in ("## 1. Top actions", "## 2. New high-value opportunities", "## 3. Applications opening",
              "## 4. Deadlines within 30, 14, 7 and 2 days", "## 5. Material deadline or eligibility changes",
              "## 6. Future-cycle", "## 7. Conflicts, review queue, stale facts, failed sources", "## 8. Monitoring health"):  # fmt: skip
        assert h in md
    assert f"]({CHILD})" in md and "| 30 d |" in md and "15 March 2027 | confirmed |" in md
    assert "1 configured, 1 enabled" in md and "Overdue" not in md


def test_digest_and_weekly_report_share_one_data_source(env):
    env.discover()
    env.cycle()
    data = weekly_report.gather(env.conn, env.cfg, env.clock)
    text = weekly_report.render_text(data)
    from opportunity_radar.monitoring.deadlines import build_digest

    assert build_digest(env.conn, env.cfg, env.clock) == text


def test_changes_report_lists_moved_deadlines_and_new_editions(env):
    env.discover()
    env.cycle()
    env.clock.set(2027, 3, 1)
    env.programme = env.programme.replace(b"15 March 2027", b"8 March 2027")
    env.recheck(env.web())
    env.cycle()
    data = changes_report.build_changes(env.conn, env.clock, timedelta(days=14))
    assert [m["to"] for m in data["moved_deadlines"]] == ["2027-03-08"] and data["moved_deadlines"][
        0
    ]["from"] == "2027-03-15"
    assert len(data["new_editions"]) == 1 and data["alerts_sent"].get("deadline_changed") == 1
    md = changes_report.render_markdown(data)
    assert "2027-03-15 → **2027-03-08**" in md and CHILD in md


def test_sources_report_never_reports_the_target_as_a_count(env):
    env.discover()
    r = sources_report.build_sources_report(env.conn, env.clock)
    assert (
        r["target"] == 200
        and r["configured"] == 1
        and r["healthy_30d"] == 1
        and r["unassigned_portfolio"] == 1
    )
    assert sum(p["configured"] for p in r["portfolio"]) == 0 and {
        p["portfolio"] for p in r["portfolio"]
    } >= {"de_research", "discovery_only"}
    env.conn.execute("UPDATE sources SET portfolio='de_research'")
    r = sources_report.build_sources_report(env.conn, env.clock)
    assert next(p for p in r["portfolio"] if p["portfolio"] == "de_research") == {
        "portfolio": "de_research",
        "target": 45,
        "configured": 1,
        "enabled": 1,
        "healthy": 1,
    }
    md = sources_report.render_markdown(r)
    assert "**Actual:** 1 configured, 1 enabled, 1 healthy" in md and "~200" in md
    env.conn.execute("UPDATE sources SET failure_streak=2")
    assert sources_report.build_sources_report(env.conn, env.clock)["healthy_30d"] == 0


def test_source_skeleton_files_are_valid_and_empty():
    from opportunity_radar.sources.registry import load_source_files

    files = sorted((Path(__file__).parents[2] / "config" / "sources").glob("*.yaml"))
    assert len(files) == 8 and load_source_files(files) == []
    for f in files:
        assert (
            "EMPTY ON PURPOSE" in f.read_text()
            and "http" not in f.read_text().replace("https://", "").lower().split("version")[0]
        )


def test_portfolio_field_is_validated_and_stored(env, tmp_path):
    from opportunity_radar.errors import ConfigurationError
    from opportunity_radar.sources.registry import load_source_files

    base = (Path(__file__).parents[1] / "fixtures" / "sources_good.yaml").read_text()
    good = tmp_path / "g.yaml"
    good.write_text(
        base.replace(
            "source_type: official_programme_index",
            "source_type: official_programme_index\n    portfolio: de_research",
        )
    )
    assert load_source_files([good])[0].portfolio == "de_research"
    bad = tmp_path / "b.yaml"
    bad.write_text(
        base.replace(
            "source_type: official_programme_index",
            "source_type: official_programme_index\n    portfolio: moon_base",
        )
    )
    with pytest.raises(ConfigurationError, match="portfolio"):
        load_source_files([bad])
