"""Source health through discovery + persistence (ADR-009): holds, cooldowns, recovery, metrics."""

import httpx
import pytest
from tests.helpers import FakeWeb, fixture, html
from tests.integration.test_discovery import SEED, env, q, run  # noqa: F401, F811

from open_hypergamy.discovery import orchestrator as orch
from open_hypergamy.errors import OhgError
from open_hypergamy.reporting.sources import build_sources_report
from open_hypergamy.sources.health import health_state

KEY = "example-student-programmes"
CHALLENGE = b"<html><head><title>Just a moment...</title></head><body>cf_chl_opt</body></html>"


def due(repo, clock):
    return [s.source_key for s in repo.list_due(clock.now_utc().isoformat().replace("+00:00", "Z"))]


def state(repo, clock):
    return health_state(repo.get(KEY), clock.now_utc()).value


def test_403_holds_the_source_until_an_operator_unblocks_it(env):
    cfg, conn, repo, clock = env
    run(env, FakeWeb({SEED: html(fixture("index.html"))}))
    good = repo.get(KEY)
    clock.advance(days=8)
    web = FakeWeb({SEED: httpx.Response(403)})
    run(env, web)
    held = repo.get(KEY)
    assert held.blocked_reason.startswith("access_denied") and held.blocked_at
    assert held.last_error_category == "access_denied" and held.last_http_status == 403
    assert state(repo, clock) == "blocked_review"
    assert (held.etag, held.last_content_hash, held.last_success_at) == (
        good.etag, good.last_content_hash, good.last_success_at,
    )  # fmt: skip
    clock.advance(days=30)
    assert due(repo, clock) == []  # never retried automatically
    assert run(env, web).considered == 0 and web.urls.count(SEED) == 1
    with pytest.raises(OhgError, match="held for review"):
        run(env, web, source_ref=KEY)
    repo.clear_hold(KEY)
    assert due(repo, clock) == [KEY] and state(repo, clock) != "blocked_review"
    run(env, FakeWeb({SEED: html(fixture("index.html"))}))
    assert state(repo, clock) == "healthy" and repo.get(KEY).last_error_category is None


def test_429_retry_after_cools_down_then_recovers(env):
    cfg, conn, repo, clock = env
    web = FakeWeb({SEED: httpx.Response(429, headers={"retry-after": "7200"})})
    s = run(env, web)
    src = repo.get(KEY)
    assert s.results[0]["status"] == "failed" and web.urls.count(SEED) == 1
    assert src.cooldown_until == "2026-10-29T14:00:00Z" == src.next_due_at
    assert state(repo, clock) == "cooldown" and src.last_error_category == "rate_limited"
    with pytest.raises(OhgError, match="cooling down"):
        run(env, web, source_ref=KEY)
    clock.advance(hours=1)
    assert due(repo, clock) == []
    clock.advance(hours=1, seconds=1)
    assert due(repo, clock) == [KEY]  # half-open
    run(env, FakeWeb({SEED: html(fixture("index.html"))}))
    src = repo.get(KEY)
    assert (src.failure_streak, src.cooldown_until, src.last_error_category) == (0, None, None)


def test_challenge_page_stores_nothing_and_is_held(env):
    cfg, conn, repo, clock = env
    s = run(env, FakeWeb({SEED: html(CHALLENGE)}))
    assert s.results[0]["error_code"] == "access_barrier"
    assert q(conn, "SELECT 1 FROM source_observations") == []  # never ingested as content
    assert q(conn, "SELECT 1 FROM candidates") == []
    assert state(repo, clock) == "blocked_review"


def test_repeated_network_failures_open_the_breaker(env):
    cfg, conn, repo, clock = env

    def down(req):
        raise httpx.ConnectError("refused")

    for expected in ("stale", "stale", "cooldown"):  # never succeeded, so stale until it does
        run(env, FakeWeb({SEED: down}))
        assert state(repo, clock) == expected
        clock.advance(hours=2 ** repo.get(KEY).failure_streak)
    src = repo.get(KEY)
    assert src.failure_streak == 3 and src.last_error_category == "network"


def test_failures_preserve_ingested_records_and_report_metrics(env):
    cfg, conn, repo, clock = env
    conn.execute(
        'UPDATE sources SET discovery_policy_json=\'{"follow_internal_links":true,"max_depth":1,"max_pages_per_run":5}\''
    )
    child = SEED + "/summer-school"
    run(env, FakeWeb({SEED: html(fixture("index.html")), child: html(fixture("programme.html"))}))
    tables = ("source_observations", "candidates", "programs", "editions", "deadlines", "claims")

    def counts():
        return {t: q(conn, f"SELECT COUNT(*) FROM {t}")[0][0] for t in tables}

    before = counts()
    assert before["editions"] == 1 and before["deadlines"] >= 1 and before["claims"] >= 1
    for resp in (httpx.Response(503), httpx.Response(404), httpx.Response(403)):
        clock.advance(days=8)
        repo.clear_hold(KEY)  # operator lets it run again after each failure
        run(env, FakeWeb({SEED: resp}))
    assert counts() == before  # a failing source never deletes or empties anything

    report = build_sources_report(conn, clock)
    [s] = report["sources"]
    assert s["health"] == "blocked_review" and s["checks_30d"] == 4
    assert s["retrieval_success_rate"] == 0.25 and s["http_status_counts"] == {
        "200": 1, "403": 1, "404": 1, "503": 1,
    }  # fmt: skip
    assert s["extraction_success_rate"] == 1.0 and s["last_successful_ingestion_at"]
    assert s["content_changes_30d"] == 1 and s["avg_latency_ms"] is not None
    assert report["health_states"]["blocked_review"] == 1 and report["healthy_30d"] == 0
    assert s["stale_opportunities"] == 0
    conn.execute("UPDATE editions SET source_fresh_until='2026-01-01T00:00:00Z'")
    stale = build_sources_report(conn, clock)
    assert stale["sources"][0]["stale_opportunities"] == 1 == stale["stale_opportunities"]
    runs = q(
        conn,
        "SELECT elapsed_ms, bytes_received FROM source_check_runs WHERE status='partial' OR status='success'",
    )
    assert runs and runs[0]["bytes_received"] > 0  # transport metrics now recorded


def test_manual_run_of_unknown_or_held_source_does_not_fetch(env):
    cfg, conn, repo, clock = env
    conn.execute("UPDATE sources SET blocked_reason='access_denied: test'")
    web = FakeWeb({SEED: html(b"x")})
    with pytest.raises(OhgError):
        orch.run_discovery(conn, cfg, None, clock, source_ref=KEY)  # type: ignore[arg-type]
    assert web.urls == []
