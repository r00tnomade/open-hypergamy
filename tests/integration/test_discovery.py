from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from tests.helpers import FakeWeb, fixture, html, make_fetcher

from open_hypergamy.clock import FixedClock
from open_hypergamy.config import load_config
from open_hypergamy.discovery import orchestrator as orch
from open_hypergamy.persistence import db as dbm
from open_hypergamy.persistence import migrations as mig
from open_hypergamy.persistence.repositories.sources import SourceRepository
from open_hypergamy.sources.registry import load_source_files

SEED = "https://example.edu/students/opportunities"
GOOD = Path(__file__).parent.parent / "fixtures" / "sources_good.yaml"


class MovableClock(FixedClock):
    def advance(self, **kw):
        self._now += timedelta(**kw)


@pytest.fixture
def env(tmp_path):
    clock = MovableClock(datetime(2026, 10, 29, 12, 0, tzinfo=UTC))
    cfg = load_config(home=tmp_path / "home", env={})
    cfg.paths.ensure()
    conn = dbm.connect(cfg.paths.db, create=True)
    mig.migrate(conn, mig.discover(), clock)
    repo = SourceRepository(conn, clock)
    configs = load_source_files([GOOD])
    configs[0].discovery_policy.follow_internal_links = False  # single page unless a test opts in
    repo.import_configs(configs)
    yield cfg, conn, repo, clock
    conn.close()


def run(env, web, **kw):
    cfg, conn, _, clock = env
    fetcher, _ = make_fetcher(web)
    return orch.run_discovery(conn, cfg, fetcher, clock, **kw)


def q(conn, sql):
    return conn.execute(sql).fetchall()


def test_success_persists_observation_health_and_job(env):
    cfg, conn, repo, clock = env
    s = run(env, FakeWeb({SEED: html(fixture("index.html"), etag='"v1"')}))
    assert s.status == "success" and s.count("success") == 1
    [obs] = q(conn, "SELECT * FROM source_observations")
    assert obs["canonical_url"] == SEED and obs["title"] == "Student Opportunities"
    assert (cfg.paths.cache / obs["body_cache_relpath"]).exists()
    src = repo.get("example-student-programmes")
    assert (
        src.etag == '"v1"'
        and src.failure_streak == 0
        and src.last_success_at == "2026-10-29T12:00:00Z"
    )
    assert src.next_due_at == "2026-11-05T12:00:00Z"  # 168 h interval
    [job] = q(conn, "SELECT * FROM job_runs")
    assert job["status"] == "success" and job["sources_succeeded"] == 1 and job["finished_at"]
    [chk] = q(conn, "SELECT * FROM source_check_runs")
    assert chk["status"] == "success" and chk["job_run_id"] == job["id"]


def test_not_due_source_is_skipped_until_interval_passes(env):
    run(env, FakeWeb({SEED: html(fixture("index.html"))}))
    assert run(env, FakeWeb({})).considered == 0
    env[3].advance(days=8)
    assert run(env, FakeWeb({SEED: html(fixture("index.html"))})).considered == 1


def test_304_is_not_a_change(env):
    cfg, conn, repo, clock = env
    run(env, FakeWeb({SEED: html(fixture("index.html"), etag='"v1"')}))
    changed_at = repo.get("example-student-programmes").last_content_change_at
    clock.advance(days=8)
    seen = {}

    def handler(req):
        seen.update(req.headers)
        return httpx.Response(304)

    s = run(env, FakeWeb({SEED: handler}))
    assert s.count("not_modified") == 1 and seen["if-none-match"] == '"v1"'
    assert len(q(conn, "SELECT 1 FROM source_observations")) == 1
    src = repo.get("example-student-programmes")
    assert src.last_content_change_at == changed_at and src.etag == '"v1"' and src.last_content_hash
    assert src.last_success_at == "2026-11-06T12:00:00Z"  # but freshness advanced


def test_changed_content_creates_new_observation_identical_does_not(env):
    cfg, conn, repo, clock = env
    run(env, FakeWeb({SEED: html(fixture("index.html"))}))
    clock.advance(days=8)
    run(env, FakeWeb({SEED: html(fixture("index.html"), etag='"new-etag-same-body"')}))
    assert len(q(conn, "SELECT 1 FROM source_observations")) == 1  # same bytes: no duplicate
    clock.advance(days=8)
    run(env, FakeWeb({SEED: html(fixture("index.html") + b"<!-- changed -->")}))
    assert len(q(conn, "SELECT 1 FROM source_observations")) == 2
    assert repo.get("example-student-programmes").last_content_change_at == "2026-11-14T12:00:00Z"


def test_failure_preserves_last_known_state_and_backs_off(env):
    cfg, conn, repo, clock = env
    run(env, FakeWeb({SEED: html(fixture("index.html"), etag='"v1"')}))
    good = repo.get("example-student-programmes")
    clock.advance(days=8)
    s = run(env, FakeWeb({SEED: httpx.Response(500)}))
    assert s.status == "failed"
    bad = repo.get("example-student-programmes")
    assert bad.failure_streak == 1 and bad.next_due_at == "2026-11-06T13:00:00Z"  # +1 h
    assert (bad.etag, bad.last_content_hash, bad.last_success_at) == (
        good.etag,
        good.last_content_hash,
        good.last_success_at,
    )
    assert len(q(conn, "SELECT 1 FROM source_observations")) == 1  # nothing replaced or emptied
    clock.advance(hours=2)
    run(env, FakeWeb({SEED: httpx.Response(404)}))
    again = repo.get("example-student-programmes")
    assert again.failure_streak == 2 and again.next_due_at == "2026-11-06T16:00:00Z"  # +2 h backoff
    codes = [
        r["error_code"]
        for r in q(conn, "SELECT error_code FROM source_check_runs WHERE status='failed'")
    ]
    assert codes == ["http_error", "http_error"]
    assert repo.coverage()["failing_2plus"] == 1


def test_robots_disallow_does_not_block_discovery(env):
    web = FakeWeb({"https://example.edu/robots.txt": httpx.Response(200, text="User-agent: *\nDisallow: /\n"),
                   SEED: html(b"x")})  # fmt: skip
    s = run(env, web)
    assert s.results[0]["status"] != "blocked_policy" and SEED in web.urls


def test_http_403_is_a_failure_with_backoff_not_evasion(env):
    web = FakeWeb({SEED: httpx.Response(403)})
    s = run(env, web)
    assert s.results[0]["status"] == "failed" and web.urls.count(SEED) == 1
    src = env[2].get("example-student-programmes")
    assert src.failure_streak == 1 and src.next_due_at != "2026-11-05T12:00:00Z"


def test_crawl_child_failure_gives_partial(env):
    cfg, conn, repo, clock = env
    conn.execute(
        'UPDATE sources SET discovery_policy_json=\'{"follow_internal_links":true,"max_depth":1,"max_pages_per_run":5}\''
    )
    s = run(env, FakeWeb({SEED: html(fixture("index.html"))}))
    assert s.status == "partial" and s.results[0]["status"] == "partial"
    assert len(q(conn, "SELECT 1 FROM source_observations")) == 1
    assert repo.get("example-student-programmes").failure_streak == 0  # seed fetched fine


def test_unexpected_adapter_bug_does_not_abort_run(env, monkeypatch):
    cfg, conn, repo, clock = env

    class Boom:
        adapter_type = "html"

        def fetch(self, source, ctx):
            raise RuntimeError("parser exploded")

    monkeypatch.setitem(orch.ADAPTERS, "html", Boom())
    s = run(env, FakeWeb({}))
    assert s.results[0]["error_code"] == "unexpected_error" and s.status == "failed"
    assert repo.get("example-student-programmes").failure_streak == 1


def test_unimplemented_adapter_is_skipped_not_failed(env):
    cfg, conn, repo, clock = env
    conn.execute("UPDATE sources SET adapter_type='playwright'")
    s = run(env, FakeWeb({}))
    assert s.results[0]["status"] == "skipped" and s.status == "success"
    assert repo.get("example-student-programmes").failure_streak == 0


def test_dry_run_touches_nothing(env):
    web = FakeWeb({})
    s = run(env, web, dry_run=True)
    assert s.considered == 1 and web.requests == []
    assert (
        q(env[1], "SELECT 1 FROM job_runs") == []
        and q(env[1], "SELECT 1 FROM source_check_runs") == []
    )


def test_disabled_and_review_required_sources_not_polled(env):
    cfg, conn, repo, clock = env
    repo.set_enabled("example-student-programmes", False)
    assert run(env, FakeWeb({})).considered == 0
    with pytest.raises(Exception, match="not enabled"):
        run(env, FakeWeb({}), source_ref="example-student-programmes")


def test_limit_and_priority_order(env):
    cfg, conn, repo, clock = env
    for i, prio in enumerate((10, 90)):
        conn.execute(
            "INSERT INTO sources(id, source_key, name, canonical_url, domain, source_type, adapter_type, "
            "trust_tier, allowed_domains_json, priority, created_at, updated_at) VALUES "
            "(?,?,?,?,?,'x','html','t2_official_org','[\"example.edu\"]',?,'t','t')",
            (f"id{i}", f"extra-{i}", f"E{i}", f"https://example.edu/e{i}", "example.edu", prio),
        )
    s = run(env, FakeWeb({}), limit=2, dry_run=True)
    assert [r["source"] for r in s.results][0] in ("extra-1", "example-student-programmes")
    assert len(s.results) == 2 and "extra-0" not in [r["source"] for r in s.results]
