"""Egress diagnostics persisted per source check, and the circuit breaker staying in charge."""

import json

import httpx
from tests.helpers import FakeWeb, fixture, html, public_dns
from tests.helpers_egress import HEALTH_URL, FakeProxy, settings
from tests.integration.test_discovery import SEED, env, q  # noqa: F401, F811

from open_hypergamy.config import AppSettings, CrawlingSettings
from open_hypergamy.discovery import orchestrator as orch
from open_hypergamy.egress.pool import EgressPool
from open_hypergamy.sources.fetch import Fetcher
from open_hypergamy.sources.health import health_state

KEY = "example-student-programmes"


def build(web, **kw):
    s = settings(assignments={KEY: ["p1", "p2"]}, **kw)
    routes = FakeWeb({HEALTH_URL: html(b"ok"), **web.routes})
    proxies = {p.name: FakeProxy(p.name, routes) for p in s.profiles}
    direct = FakeWeb(dict(web.routes))
    pool = EgressPool(s, resolver=public_dns)
    f = Fetcher(
        AppSettings(),
        CrawlingSettings(),
        transport=direct.transport, resolver=public_dns, monotonic=lambda: 0.0,
        sleep=lambda s: None, jitter=lambda: 0.5, egress=pool,
        proxy_transport_factory=lambda p: proxies[p.name],
    )  # fmt: skip
    return f, proxies, direct


def test_failover_is_recorded_without_addresses_or_credentials(env):  # noqa: F811
    cfg, conn, repo, clock = env
    f, proxies, direct = build(FakeWeb({SEED: html(fixture("index.html"))}))
    proxies["p1"].mode = httpx.ConnectError("connection refused to p1.proxy.example.net:8443")
    s = orch.run_discovery(conn, cfg, f, clock)
    assert s.count("success") == 1 and direct.requests == []
    [row] = q(conn, "SELECT * FROM source_check_egress")
    assert (row["profile"], row["failover_count"], row["destination_status"]) == ("p2", 1, 200)
    detail = json.loads(row["detail_json"])
    assert detail["proxy_failures"] == {"unavailable": 1} and detail["profiles_used"] == [
        "p1",
        "p2",
    ]
    assert detail["proxy_health"]["p1"] == "degraded"
    assert "proxy.example.net" not in row["detail_json"] and "8443" not in row["detail_json"]


def test_destination_403_is_recorded_and_the_source_is_held_exactly_as_before(env):  # noqa: F811
    cfg, conn, repo, clock = env
    f, proxies, direct = build(FakeWeb({SEED: httpx.Response(403)}))
    s = orch.run_discovery(conn, cfg, f, clock)
    assert s.results[0]["status"] == "failed"
    src = repo.get(KEY)
    assert src.blocked_reason.startswith("access_denied") and src.last_http_status == 403
    assert health_state(src, clock.now_utc()).value == "blocked_review"
    [row] = q(conn, "SELECT * FROM source_check_egress")
    assert (row["failover_count"], row["rotation_count"], row["destination_status"]) == (0, 0, 403)
    assert len(proxies["p2"].requests) == 0 and direct.requests == []
    # held sources are not polled again, through any proxy
    s2 = orch.run_discovery(conn, cfg, f, clock)
    assert s2.considered == 0 and len(proxies["p1"].requests) == 1


def test_total_proxy_outage_counts_as_a_transient_source_failure_not_a_hold(env):  # noqa: F811
    cfg, conn, repo, clock = env
    f, proxies, direct = build(FakeWeb({SEED: html(fixture("index.html"))}))
    for p in proxies.values():
        p.mode = httpx.ConnectTimeout("t")
    s = orch.run_discovery(conn, cfg, f, clock)
    assert s.results[0]["error_code"] == "egress_unavailable" and direct.requests == []
    src = repo.get(KEY)
    assert src.blocked_reason is None and src.failure_streak == 1
    assert src.last_error_category == "network"


def test_direct_sources_record_no_egress_row(env):  # noqa: F811
    cfg, conn, repo, clock = env
    f, _, direct = build(FakeWeb({SEED: html(fixture("index.html"))}))
    f._egress.settings.assignments.clear()  # type: ignore[union-attr]
    f._egress.settings.default_profiles.clear()  # type: ignore[union-attr]
    orch.run_discovery(conn, cfg, f, clock)
    assert q(conn, "SELECT * FROM source_check_egress") == [] and direct.urls.count(SEED) == 1
