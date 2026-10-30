"""Child-page revalidation behind a 304 index (ADR-011)."""

import json

import httpx
import pytest
from tests.helpers import FakeWeb, fixture, html
from tests.integration.test_discovery import SEED, env, q, run  # noqa: F401, F811

from open_hypergamy.errors import OhgError

KEY = "example-student-programmes"
A, B, C = SEED + "/a", SEED + "/b", SEED + "/c"


def index(*urls: str, extra: str = "") -> bytes:
    links = "".join(f'<a href="{u}">{u.rsplit("/", 1)[1]}</a>' for u in urls)
    return f"<html><head><title>Opportunities</title></head><body>{links}{extra}</body></html>".encode()


def page(name: str, version: int = 1) -> bytes:
    return f"<html><head><title>{name}</title></head><body>{name} v{version}</body></html>".encode()


class Resource:
    """A conditional-GET resource: 304 when If-None-Match matches, else 200 with its ETag."""

    def __init__(self, body: bytes, etag: str, **headers: str):
        self.body, self.etag, self.headers = body, etag, headers
        self.seen: list[httpx.Headers] = []

    def update(self, body: bytes, etag: str) -> None:
        self.body, self.etag = body, etag

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.seen.append(req.headers)
        if req.headers.get("if-none-match") == self.etag:
            return httpx.Response(304)  # deliberately without an ETag header
        return html(self.body, etag=self.etag, **self.headers)


def follow(conn, **policy) -> None:
    base = {"follow_internal_links": True, "max_depth": 1, "max_pages_per_run": 20,
            "child_recheck_hours": 24}  # fmt: skip
    conn.execute(
        "UPDATE sources SET fetch_interval_hours=6, discovery_policy_json=?",
        (json.dumps({**base, **policy}),),
    )


def pages(conn):
    return {r["canonical_url"]: r for r in q(conn, "SELECT * FROM source_pages")}


def obs_count(conn) -> int:
    return q(conn, "SELECT COUNT(*) FROM source_observations")[0][0]


@pytest.fixture
def site(env):
    """Index + two children, crawled once; returns (web resources, env)."""
    cfg, conn, repo, clock = env
    follow(conn)
    res = {
        SEED: Resource(index(A, B), '"i1"'),
        A: Resource(page("A"), '"a1"', **{"last-modified": "Mon, 01 Jan 2026 00:00:00 GMT"}),
        B: Resource(page("B"), '"b1"'),
    }
    run(env, FakeWeb(dict(res)))
    assert obs_count(conn) == 3 and set(pages(conn)) == {A, B}
    for r in res.values():
        r.seen.clear()
    return res, env


def test_304_index_still_revalidates_due_children(site):
    res, env = site
    cfg, conn, repo, clock = env
    before = pages(conn)
    clock.advance(hours=25)
    res[B].update(page("B", 2), '"b2"')
    web = FakeWeb(dict(res))
    s = run(env, web)
    assert web.urls == [SEED, A, B]  # index 304, then both due children, oldest first
    assert s.results[0]["status"] == "not_modified"  # only B changed; nothing failed
    assert obs_count(conn) == 4  # B's new content is a new observation; A's 304 is not
    p = pages(conn)
    assert p[B]["content_hash"] != before[B]["content_hash"]
    assert p[A]["content_hash"] == before[A]["content_hash"]
    assert p[B]["etag"] == '"b2"' and p[A]["etag"] == '"a1"'  # 304 kept A's validators
    assert p[B]["last_changed_at"] > p[A]["last_changed_at"]
    src = repo.get(KEY)
    assert src.etag == '"i1"' and src.failure_streak == 0  # 304 did not erase index validators
    assert src.last_content_change_at == "2026-10-30T13:00:00Z"  # a changed child counts


def test_conditional_headers_are_sent_for_children(site):
    res, env = site
    env[3].advance(hours=25)
    run(env, FakeWeb(dict(res)))
    assert res[A].seen[-1]["if-none-match"] == '"a1"'
    assert res[A].seen[-1]["if-modified-since"] == "Mon, 01 Jan 2026 00:00:00 GMT"
    assert res[B].seen[-1]["if-none-match"] == '"b1"' and "if-modified-since" not in res[B].seen[-1]


def test_fresh_children_are_not_fetched(site):
    res, env = site
    cfg, conn, repo, clock = env
    clock.advance(hours=7)  # source is due again (6 h) but children are fresh (24 h)
    web = FakeWeb(dict(res))
    run(env, web)
    assert web.urls == [SEED]
    clock.advance(hours=18)  # 25 h since the children were checked
    web = FakeWeb(dict(res))
    run(env, web)
    assert web.urls == [SEED, A, B]


def test_only_stale_children_are_fetched(site):
    res, env = site
    cfg, conn, repo, clock = env
    clock.advance(hours=7)
    conn.execute(
        "UPDATE source_pages SET next_check_at='2026-10-01T00:00:00Z' WHERE canonical_url=?", (A,)
    )
    web = FakeWeb(dict(res))
    run(env, web)
    assert web.urls == [SEED, A]


def test_child_304_renews_freshness_without_new_observation(site):
    res, env = site
    cfg, conn, repo, clock = env
    before = pages(conn)[A]
    clock.advance(hours=25)
    run(env, FakeWeb(dict(res)))
    after = pages(conn)[A]
    assert obs_count(conn) == 3
    assert after["last_checked_at"] == "2026-10-30T13:00:00Z" > before["last_checked_at"]
    assert after["next_check_at"] == "2026-10-31T13:00:00Z"  # own 24 h window, not the source's 6 h
    assert (after["content_hash"], after["last_changed_at"]) == (
        before["content_hash"], before["last_changed_at"],
    )  # fmt: skip
    assert after["consecutive_failures"] == 0 and after["last_http_status"] == 304


def test_changed_index_skips_fresh_known_children_and_fetches_new_ones(site):
    res, env = site
    cfg, conn, repo, clock = env
    clock.advance(hours=7)
    res[SEED].update(index(A, B, C), '"i2"')
    res[C] = Resource(page("C"), '"c1"')
    web = FakeWeb(dict(res))
    run(env, web)
    assert web.urls == [SEED, C]  # A and B are fresh; only the new link is fetched
    assert set(pages(conn)) == {A, B, C} and obs_count(conn) == 5  # index v2 + C


def test_page_limit_counts_every_request_and_never_starves_unchecked_pages(env):
    cfg, conn, repo, clock = env
    follow(conn, max_pages_per_run=3)  # seed + two children per run
    res = {SEED: Resource(index(A, B, C), '"i1"'), A: Resource(page("A"), '"a1"'),
           B: Resource(page("B"), '"b1"'), C: Resource(page("C"), '"c1"')}  # fmt: skip
    web = FakeWeb(dict(res))
    run(env, web)
    assert web.urls == [SEED, A, B]  # C is remembered but over the limit
    p = pages(conn)
    assert p[C]["last_checked_at"] is None and p[C]["status"] == "active"
    clock.advance(hours=25)
    web = FakeWeb(dict(res))
    run(env, web)
    assert web.urls == [SEED, C, A]  # 304s count; never-checked C goes first, B waits its turn
    clock.advance(hours=6)
    web = FakeWeb(dict(res))
    run(env, web)
    assert web.urls == [SEED, B]  # A and C are fresh; the one left over is picked up


def test_tracked_page_cap_is_enforced(env):
    cfg, conn, repo, clock = env
    follow(conn, max_pages_per_run=1)
    cfg.settings.app.max_tracked_pages_per_source = 2
    web = FakeWeb({SEED: Resource(index(A, B, C), '"i1"')})
    run(env, web)
    assert len(pages(conn)) == 2


# -- cooldowns, circuit breaker, throttling ----------------------------------------------------
def test_source_cooldown_blocks_child_revalidation_until_it_expires(site):
    res, env = site
    cfg, conn, repo, clock = env
    clock.advance(hours=25)
    before = pages(conn)[A]["last_checked_at"]
    web = FakeWeb(
        {SEED: httpx.Response(429, headers={"retry-after": "7200"}), A: res[A], B: res[B]}
    )
    s = run(env, web)
    assert s.results[0]["status"] == "failed" and web.urls == [SEED]  # children never touched
    assert pages(conn)[A]["last_checked_at"] == before
    clock.advance(hours=1)
    web = FakeWeb(dict(res))
    assert run(env, web).considered == 0 and web.urls == []  # scheduler skips it
    with pytest.raises(OhgError, match="cooling down"):
        run(env, web, source_ref=KEY)
    assert web.urls == []
    clock.advance(hours=1, minutes=1)
    web = FakeWeb(dict(res))
    run(env, web)  # half-open: the probe succeeds and the overdue children are revalidated
    assert web.urls == [SEED, A, B]
    assert repo.get(KEY).cooldown_until is None


def test_blocked_source_never_revalidates_children(site):
    res, env = site
    cfg, conn, repo, clock = env
    clock.advance(hours=25)
    run(env, FakeWeb({SEED: httpx.Response(403), A: res[A], B: res[B]}))
    clock.advance(days=30)
    web = FakeWeb(dict(res))
    assert run(env, web).considered == 0 and web.urls == []


def test_host_cooldown_mid_run_stops_remaining_children(site):
    res, env = site
    cfg, conn, repo, clock = env
    clock.advance(hours=25)
    web = FakeWeb({SEED: res[SEED], A: httpx.Response(503), B: res[B]})
    s = run(env, web)
    assert (
        web.urls.count(A) == 3 and B not in web.urls
    )  # bounded retries, then the host is left alone
    assert s.results[0]["status"] == "partial"
    p = pages(conn)
    assert p[A]["consecutive_failures"] == 1 and p[A]["status"] == "active"
    assert p[A]["next_check_at"] == "2026-10-30T14:00:00Z"  # 1 h backoff
    assert p[B]["next_check_at"] <= "2026-10-30T13:00:00Z"  # B is still due next time
    assert p[A]["last_checked_at"] == "2026-10-29T12:00:00Z"  # the last good check is kept
    assert repo.get(KEY).failure_streak == 0  # child trouble does not trip the source breaker


def test_child_requests_respect_per_host_throttle(site):
    res, env = site
    cfg, conn, repo, clock = env
    clock.advance(hours=25)
    from tests.helpers import make_fetcher

    from open_hypergamy.discovery import orchestrator as orch

    fetcher, sleeps = make_fetcher(FakeWeb(dict(res)))
    orch.run_discovery(conn, cfg, fetcher, clock)
    assert sleeps.count(3.0) == 2  # 3 requests to one host, each spaced by the 3 s floor


# -- removed / invalid children never delete opportunities -------------------------------------
def promoted_site(env):
    cfg, conn, repo, clock = env
    follow(conn)
    child = SEED + "/summer-school"
    res = {SEED: Resource(fixture("index.html"), '"i1"'),
           child: Resource(fixture("programme.html"), '"p1"')}  # fmt: skip
    run(env, FakeWeb(dict(res)))
    return res, child


def facts(conn):
    return {
        t: q(conn, f"SELECT COUNT(*) FROM {t}")[0][0]
        for t in (
            "source_observations",
            "candidates",
            "programs",
            "editions",
            "deadlines",
            "claims",
        )
    }


def test_404_child_becomes_missing_but_opportunities_are_kept(env):
    cfg, conn, repo, clock = env
    res, child = promoted_site(env)
    before = facts(conn)
    assert before["editions"] == 1 and before["deadlines"] >= 1
    clock.advance(hours=25)
    run(env, FakeWeb({SEED: res[SEED], child: httpx.Response(404)}))
    p = pages(conn)[child]
    assert p["status"] == "active" and p["consecutive_failures"] == 1  # one 404 is not enough
    clock.advance(hours=25)
    run(env, FakeWeb({SEED: res[SEED], child: httpx.Response(404)}))
    p = pages(conn)[child]
    assert p["status"] == "missing" and p["status_reason"].startswith("not_found")
    assert facts(conn) == before  # nothing deleted, nothing replaced
    clock.advance(hours=25)
    web = FakeWeb({SEED: res[SEED], child: httpx.Response(404)})
    run(env, web)
    assert web.urls == [SEED]  # a missing page is no longer polled
    assert facts(conn) == before


def test_410_is_missing_immediately_and_index_listing_it_again_retries_once(env):
    cfg, conn, repo, clock = env
    res, child = promoted_site(env)
    clock.advance(hours=25)
    run(env, FakeWeb({SEED: res[SEED], child: httpx.Response(410)}))
    assert pages(conn)[child]["status"] == "missing"
    clock.advance(hours=25)
    res[SEED].update(fixture("index.html").replace(b"</body>", b"<p>Updated</p></body>"), '"i2"')
    res[child] = Resource(fixture("programme.html"), '"p1"')
    web = FakeWeb(dict(res))
    run(env, web)
    assert web.urls == [SEED, child]
    p = pages(conn)[child]
    assert p["status"] == "active" and p["consecutive_failures"] == 0


def test_403_child_is_held_not_retried_and_unblock_releases_it(env):
    cfg, conn, repo, clock = env
    res, child = promoted_site(env)
    before = facts(conn)
    clock.advance(hours=25)
    web = FakeWeb({SEED: res[SEED], child: httpx.Response(403)})
    run(env, web)
    assert web.urls.count(child) == 1 and pages(conn)[child]["status"] == "held"
    clock.advance(hours=25)
    web = FakeWeb(dict(res))
    run(env, web)
    assert web.urls == [SEED]  # never retried automatically
    repo.clear_hold(KEY)
    web = FakeWeb(dict(res))
    run(env, web)
    assert child in web.urls and pages(conn)[child]["status"] == "active"
    assert facts(conn) == before


def test_challenge_page_on_a_child_is_held_and_not_ingested(site):
    res, env = site
    cfg, conn, repo, clock = env
    clock.advance(hours=25)
    challenge = b"<html><head><title>Just a moment...</title></head><body>cf_chl_opt</body></html>"
    run(env, FakeWeb({SEED: res[SEED], A: html(challenge), B: res[B]}))
    assert pages(conn)[A]["status"] == "held" and obs_count(conn) == 3


def test_tightened_scope_marks_child_invalid_without_requesting_it(site):
    res, env = site
    cfg, conn, repo, clock = env
    conn.execute(
        "UPDATE sources SET deny_paths_json=?",
        (json.dumps(["/login", "/students/opportunities/a"]),),
    )
    clock.advance(hours=25)
    web = FakeWeb(dict(res))
    run(env, web)
    assert web.urls == [SEED, B]
    assert pages(conn)[A]["status"] == "invalid" and obs_count(conn) == 3


def test_following_disabled_makes_no_child_requests(site):
    res, env = site
    cfg, conn, repo, clock = env
    follow(conn, follow_internal_links=False)
    clock.advance(hours=25)
    web = FakeWeb(dict(res))
    run(env, web)
    assert web.urls == [SEED]


def test_missing_and_held_pages_are_visible_in_the_report(env):
    from open_hypergamy.reporting.sources import build_sources_report

    cfg, conn, repo, clock = env
    res, child = promoted_site(env)
    clock.advance(hours=25)
    run(env, FakeWeb({SEED: res[SEED], child: httpx.Response(410)}))
    [s] = build_sources_report(conn, clock)["sources"]
    assert (s["pages_tracked"], s["pages_missing"], s["pages_held"], s["pages_due"]) == (1, 1, 0, 0)
