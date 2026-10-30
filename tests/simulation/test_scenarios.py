"""End-to-end scenarios on the local simulated network (ADR-013).

Each scenario checks four things: DETECTION (what the system saw), CLASSIFICATION (which error
category / health state), RECOVERY (what an authorized path back looks like) and FALLBACK (which
alternative channel keeps capture going), plus that nothing already discovered disappears.
"""

import httpx

from open_hypergamy.discovery import orchestrator as orch
from open_hypergamy.persistence.repositories.sources import SourceRepository
from open_hypergamy.resilience.alternatives import alternatives_for
from open_hypergamy.sources.health import health_state
from open_hypergamy.sources.registry import SourceConfig
from tests.helpers import fixture
from tests.integration.test_pipeline import CHILD, SEED, MovableClock, env, rows  # noqa: F401, F811
from tests.simulation.sim import HEALTH_URL, P1, P2, Network, network

KEY = "example-student-programmes"
FEED = "https://example.edu/students/feed.xml"
INDEX = fixture("index.html").replace(
    b"</head>",
    b'<link rel="alternate" type="application/rss+xml" href="/students/feed.xml"></head>',
)
FEED_XML = (
    b'<?xml version="1.0"?><rss version="2.0"><channel><title>Example news</title><item>'
    b"<title>Robotics Summer School 2027 announced</title><link>" + CHILD.encode() + b"</link>"
    b"<description>Applications open on 1 January 2027 and close on 15 March 2027.</description>"
    b"</item></channel></rss>"
)
PAGES = {SEED: INDEX, CHILD: fixture("programme.html"), FEED: FEED_XML}


def mk(assign, **kw):
    return network(PAGES, assign, content_type={FEED: "application/rss+xml"}, **kw)


def go(env, net: Network):
    cfg, conn, clock = env
    return orch.run_discovery(conn, cfg, net.fetcher, clock)


def snapshot(conn):
    return {
        "editions": [tuple(r) for r in rows(conn, "SELECT id, display_name, fact_status FROM editions ORDER BY id")],
        "deadlines": [tuple(r) for r in rows(conn, "SELECT id, deadline_type, due_date_local, fact_status FROM deadlines ORDER BY id")],
        "claims": rows(conn, "SELECT COUNT(*) FROM claims")[0][0],
        "candidates": rows(conn, "SELECT COUNT(*) FROM candidates")[0][0],
    }  # fmt: skip


def source(env):
    cfg, conn, clock = env
    return SourceRepository(conn, clock).get(KEY)


def egress_rows(conn):
    return rows(conn, "SELECT * FROM source_check_egress ORDER BY rowid")


def baseline(env, assign=None, **kw):
    """A healthy first run that discovers the programme through p1."""
    net = mk(assign or {KEY: ["p1", "p2"]}, **kw)
    s = go(env, net)
    assert s.pipeline.promoted == 1, s.results
    return net


# -- IP blocking and publisher-approved routing --------------------------------------------------


def test_ip_block_is_held_for_review_and_never_triggers_another_identity(env):
    cfg, conn, clock = env
    net = baseline(env)
    before = snapshot(conn)
    net.publisher.blocked_ips = {P1.ip}  # the publisher blocks the identity we use
    clock.advance(days=8)
    s = go(env, net)
    assert s.results[0]["status"] == "failed"
    src = source(env)
    assert src.blocked_reason.startswith("access_denied") and src.last_http_status == 403
    assert health_state(src, clock.now_utc()).value == "blocked_review"
    # detection: exactly one refused request, from the one identity; p2 was never tried
    assert net.publisher.identities_seen() == {P1.ip} and net.proxies["p2"].requests == 0
    assert net.direct.requests == 0
    egress = egress_rows(conn)[-1]
    assert (egress["failover_count"], egress["rotation_count"], egress["destination_status"]) == (
        0,
        0,
        403,
    )
    # nothing discovered earlier disappeared
    assert snapshot(conn) == before


def test_recovery_after_a_block_is_an_operator_decision_not_an_automatic_switch(env):
    cfg, conn, clock = env
    net = baseline(env)
    net.publisher.blocked_ips = {P1.ip}
    clock.advance(days=8)
    go(env, net)
    clock.advance(days=30)
    assert go(env, net).considered == 0  # held sources are not retried by anything automatic
    assert net.publisher.identities_seen() == {P1.ip}
    # the operator obtained approval for a different egress path, reassigns, and releases the hold
    net.publisher.blocked_ips = set()
    net.publisher.allowlist_ips = {P2.ip}
    net.pool.settings.assignments[KEY] = ["p2"]
    net.pool.release_restrictions()  # what a fresh process after the operator's change does
    SourceRepository(conn, clock).clear_hold(KEY)
    s = go(env, net)
    assert s.count("success", "not_modified", "partial") == 1
    assert source(env).blocked_reason is None
    assert net.publisher.identities_seen() == {P1.ip, P2.ip}


def test_publisher_approved_egress_routing_works_only_on_the_approved_identity(env):
    cfg, conn, clock = env
    net = mk({KEY: ["p2"]}, allowlist_ips={P2.ip})  # publisher allowlisted p2 only
    assert go(env, net).pipeline.promoted == 1
    assert net.publisher.identities_seen() == {P2.ip}
    assert egress_rows(conn)[-1]["profile"] == "p2"


def test_assignment_to_a_non_approved_identity_is_a_hold_not_a_search_for_a_working_one(env):
    cfg, conn, clock = env
    net = mk({KEY: ["p1", "p2"]}, allowlist_ips={P2.ip})  # p1 first, not approved
    s = go(env, net)
    assert s.results[0]["status"] == "failed"
    assert source(env).blocked_reason.startswith("access_denied")
    assert net.proxies["p2"].requests == 0  # the approved identity is not discovered by trial


# -- rate limiting -----------------------------------------------------------------------------------


def test_http_rate_limiting_cools_the_host_on_the_same_identity(env):
    cfg, conn, clock = env
    net = mk({KEY: ["p1", "p2"]}, rate_limit=(1, 5.0), retry_after=120)
    s = go(env, net)  # seed passes, the child hits 429
    statuses = [st for _, _, st in net.publisher.log if _ != HEALTH_URL]
    assert 429 in statuses and net.publisher.identities_seen() == {P1.ip}
    assert net.proxies["p2"].requests == 0
    egress = egress_rows(conn)[-1]
    assert (egress["failover_count"], egress["rotation_count"]) == (0, 0)
    assert net.fetcher.gate.cooldown_remaining("example.edu") > 0  # host paused for this run
    assert s.results[0]["status"] in ("partial", "failed")
    # time passes, the window clears: normal service resumes on the same identity
    net.advance(700)
    clock.advance(days=8)
    s2 = go(env, net)
    assert s2.results[0]["status"] in ("success", "partial", "not_modified")
    assert (CHILD, P1.ip, 200) in net.publisher.log and net.publisher.identities_seen() == {P1.ip}
    assert rows(conn, "SELECT COUNT(*) FROM editions")[0][0] == 1


# -- CAPTCHA / challenge --------------------------------------------------------------------------


def test_captcha_page_is_detected_held_and_not_routed_around(env):
    cfg, conn, clock = env
    net = baseline(env)
    before = snapshot(conn)
    net.publisher.captcha_urls = {SEED}
    clock.advance(days=8)
    s = go(env, net)
    assert s.results[0]["error_code"] == "access_barrier"
    src = source(env)
    assert src.blocked_reason.startswith("access_barrier")
    assert net.publisher.identities_seen() == {P1.ip}
    assert snapshot(conn) == before


# -- geo restriction --------------------------------------------------------------------------------


def test_geo_restriction_451_is_held_and_no_region_shopping_happens(env):
    cfg, conn, clock = env
    net = mk({KEY: ["p1", "p2"]}, geo_allowed={"US"})  # p1 is DE, p2 is US
    s = go(env, net)
    assert s.results[0]["status"] == "failed" and source(env).last_http_status == 451
    assert source(env).blocked_reason.startswith("access_denied")
    assert net.proxies["p2"].requests == 0 and net.publisher.identities_seen() == {P1.ip}


# -- JavaScript-rendered pages and alternative channels -------------------------------------------


def test_js_shell_is_classified_and_an_official_feed_keeps_capture_going(env):
    cfg, conn, clock = env
    net = baseline(env)
    before = snapshot(conn)
    net.publisher.shell_urls = {SEED}  # the publisher migrates to a JS-only front end
    clock.advance(days=8)
    s = go(env, net)
    assert s.results[0]["error_code"] == "rendering_required"
    src = source(env)
    assert src.blocked_reason.startswith("rendering_required")
    assert health_state(src, clock.now_utc()).value == "blocked_review"
    assert snapshot(conn) == before  # a shell is a failure, never "the opportunities are gone"

    # alternatives come from the page we already hold: the publisher advertises a feed
    found = alternatives_for(conn, src, cfg.paths.cache)
    feeds = [a for a in found if a.kind == "declared_feed"]
    assert [(a.adapter_type, a.url) for a in feeds] == [("rss_atom", FEED)]

    # the operator registers the advertised feed (after a terms review); capture continues
    repo = SourceRepository(conn, clock)
    repo.import_configs(
        [
            SourceConfig(
                source_key="example-feed", name="Example feed", canonical_url=FEED,
                domain="example.edu", source_type="official_programme_index",
                adapter_type="rss_atom", trust_tier="t2_official_org",
                allow_paths=["/students"], robots_policy_checked_at="2026-10-01",
                terms_review_note="Reviewed: publisher-advertised feed.",
            )
        ]
    )  # fmt: skip
    net.pool.settings.assignments["example-feed"] = ["p1"]
    s2 = go(env, net)
    feed_result = [r for r in s2.results if r["source"] == "example-feed"]
    assert feed_result and feed_result[0]["status"] in ("success", "partial")
    # cross-source dedupe: the feed found the same programme page, so nothing duplicated
    assert rows(conn, "SELECT COUNT(*) FROM editions")[0][0] == 1
    assert rows(conn, "SELECT COUNT(*) FROM candidates")[0][0] == 1
    assert rows(conn, "SELECT COUNT(*) FROM programs")[0][0] == 1


# -- proxy failures -------------------------------------------------------------------------------------


def test_one_dead_proxy_fails_over_and_capture_continues(env):
    cfg, conn, clock = env
    net = mk({KEY: ["p1", "p2"]})
    net.proxies["p1"].broken = httpx.ConnectError("refused")
    assert go(env, net).pipeline.promoted == 1
    egress = egress_rows(conn)[-1]
    assert (egress["profile"], egress["failover_count"]) == ("p2", 1)
    assert net.publisher.identities_seen() == {P2.ip} and net.direct.requests == 0


def test_total_proxy_outage_never_goes_direct_and_loses_nothing_then_recovers(env):
    cfg, conn, clock = env
    net = baseline(env)
    before = snapshot(conn)
    for p in net.proxies.values():
        p.broken = httpx.ConnectTimeout("down")
    clock.advance(days=8)
    s = go(env, net)
    assert s.results[0]["error_code"] == "egress_unavailable"
    assert net.direct.requests == 0 and source(env).blocked_reason is None  # transient, not a hold
    assert snapshot(conn) == before
    # repair the proxies; after the cooldown a probe must pass before they are used again
    for p in net.proxies.values():
        p.broken = None
    net.advance(61)
    clock.advance(days=3)
    s2 = go(env, net)
    assert s2.count("success", "not_modified", "partial") == 1 and net.direct.requests == 0


def test_source_downtime_503_keeps_every_earlier_discovery(env):
    cfg, conn, clock = env
    net = baseline(env)
    before = snapshot(conn)
    net.publisher.offline = True
    for _ in range(3):
        clock.advance(days=8)
        net.advance(3600)
        go(env, net)
    assert snapshot(conn) == before
    assert source(env).last_success_at is not None


# -- HostGate stays global across identities --------------------------------------------------------


def test_destination_pacing_is_global_across_identities(env):
    cfg, conn, clock = env
    net = mk({KEY: ["p1", "p2"]})
    net.pool.settings.affinity = "none"  # rotate per fetch: the publisher sees two identities
    go(env, net)
    seen = [(t, ip) for (u, ip, _), t in zip(net.publisher.log, net.publisher.times, strict=True)
            if u != HEALTH_URL]  # fmt: skip
    assert {ip for _, ip in seen} == {P1.ip, P2.ip}
    gaps = [b[0] - a[0] for a, b in zip(seen, seen[1:], strict=False)]
    assert gaps and all(g >= 3.0 for g in gaps)  # the 3 s floor holds across egress identities
    assert set(net.fetcher.gate.snapshot()) == {"example.edu"}  # keyed by destination only
