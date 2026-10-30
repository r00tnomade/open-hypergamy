"""Selection, affinity, health transitions and recovery (ADR-012). Deterministic: no network."""

import httpx
import pytest
from tests.helpers import public_dns
from tests.helpers_egress import cert_error, profile, settings

from open_hypergamy.egress.classify import ProxyFailure, classify_proxy_error, classify_proxy_reply
from open_hypergamy.egress.pool import EgressPool, EgressReport, EgressScope, ProxyHealth
from open_hypergamy.errors import EgressUnavailable


def make(s=None, *, prober=None, resolver=public_dns):
    now = [0.0]
    pool = EgressPool(s or settings(("p1", "p2", "p3")), resolver=resolver, prober=prober,
                      monotonic=lambda: now[0])  # fmt: skip
    return pool, now


def scope(key="src", report=None, **kw):
    return EgressScope(key, report or EgressReport(), **kw)


def test_round_robin_rotates_across_sources_and_counts_rotations():
    pool, _ = make(settings(("p1", "p2", "p3"), affinity="none"))
    rep = EgressReport()
    picks = [pool.acquire(scope("a", rep), "h.example.org").profile for _ in range(4)]
    assert picks == ["p1", "p2", "p3", "p1"] and rep.rotation_count == 3


def test_source_affinity_keeps_a_source_on_one_profile():
    pool, _ = make(settings(("p1", "p2", "p3"), affinity="source"))
    a = [pool.acquire(scope("a"), "h.example.org").profile for _ in range(3)]
    assert a == ["p1", "p1", "p1"]
    assert pool.acquire(scope("b"), "h.example.org").profile == "p2"  # next source rotates on


def test_least_failure_prefers_the_cleanest_profile():
    pool, _ = make(settings(("p1", "p2", "p3"), selection="least_failure", affinity="none",
                            failure_threshold=5))  # fmt: skip
    r = pool.acquire(scope("a"), "h.example.org")
    pool.report_failure(r, ProxyFailure.TIMEOUT)
    assert r.profile == "p1"
    assert pool.acquire(scope("a"), "h.example.org").profile == "p2"  # p1 now has a failure
    assert pool.state("p1").health is ProxyHealth.DEGRADED


def test_health_transitions_cooldown_and_recovery_requires_a_passing_probe():
    probes: list[str] = []
    verdict = [False]

    def prober(p):
        probes.append(p.name)
        return verdict[0]

    pool, now = make(settings(("p1", "p2"), failure_threshold=2, cooldown_seconds=100,
                              max_cooldown_seconds=400), prober=prober)  # fmt: skip
    route = pool.acquire(scope("a"), "h.example.org")
    assert route.profile == "p1" and pool.health_of("p1") is ProxyHealth.HEALTHY
    pool.report_failure(route, ProxyFailure.CONNECT_REFUSED)
    assert pool.health_of("p1") is ProxyHealth.DEGRADED
    pool.report_failure(route, ProxyFailure.CONNECT_REFUSED)
    assert pool.health_of("p1") is ProxyHealth.UNHEALTHY  # threshold reached: out of rotation

    # during cooldown it is simply skipped, with no probe
    assert pool.acquire(scope("b"), "h.example.org").profile == "p2" and probes == []
    # cooldown over, probe fails: stays out, cooldown doubles
    now[0] = 101
    assert pool.acquire(scope("c"), "h.example.org").profile == "p2" and probes == ["p1"]
    now[0] = 101 + 150
    pool.acquire(scope("d"), "h.example.org")
    assert probes == ["p1"]  # still cooling (200 s step)
    # probe passes: reintroduced as degraded, healthy again after a real success
    verdict[0] = True
    now[0] = 101 + 201
    assert pool.acquire(scope("e"), "h.example.org").profile in ("p1", "p2")
    assert pool.health_of("p1") is ProxyHealth.DEGRADED
    r1 = pool.acquire(scope("f"), "h.example.org")
    pool.report_success(r1, 0.05)
    assert pool.state(r1.profile).latency_ewma_ms == pytest.approx(50)


def test_without_a_prober_an_unhealthy_profile_never_comes_back_on_its_own():
    pool, now = make(settings(("p1",), failure_threshold=1, cooldown_seconds=10))
    r = pool.acquire(scope("a"), "h.example.org")
    pool.report_failure(r, ProxyFailure.TIMEOUT)
    now[0] = 10_000
    with pytest.raises(EgressUnavailable):
        pool.acquire(scope("a"), "h.example.org")


def test_all_profiles_unusable_never_returns_direct():
    pool, _ = make(settings(("p1", "p2"), failure_threshold=1))
    for _ in range(2):
        r = pool.acquire(scope("a"), "h.example.org")
        pool.report_failure(r, ProxyFailure.UNAVAILABLE)
    with pytest.raises(EgressUnavailable):
        pool.acquire(scope("a"), "h.example.org")


def test_failover_is_bounded_and_skips_profiles_already_tried():
    pool, _ = make(settings(("p1", "p2", "p3"), max_failovers=1, affinity="none"))
    r = pool.acquire(scope("a"), "h.example.org")
    assert pool.failover(r, "h.example.org", ProxyFailure.TIMEOUT) and r.profile == "p2"
    assert not pool.failover(r, "h.example.org", ProxyFailure.TIMEOUT)  # bound reached
    assert r.report.failover_count == 1 and r.tried == {"p1", "p2"}


def test_denials_and_ambiguous_tls_errors_never_fail_over():
    pool, _ = make()
    r = pool.acquire(scope("a"), "h.example.org")
    assert not pool.failover(r, "h.example.org", ProxyFailure.DENIED)
    assert not pool.failover(r, "h.example.org", ProxyFailure.TLS_VERIFY)
    assert r.report.failover_count == 0 and r.profile == "p1"


def test_a_restricted_host_stays_on_its_identity_and_never_fails_over():
    pool, _ = make(settings(("p1", "p2"), affinity="none"))
    r = pool.acquire(scope("a"), "blocked.example.org")
    pool.note_restriction("blocked.example.org", r)
    again = pool.acquire(scope("a"), "blocked.example.org")
    assert again.profile == r.profile  # round-robin would have moved on
    assert not pool.failover(again, "blocked.example.org", ProxyFailure.TIMEOUT)
    assert pool.restricted_hosts() == {"blocked.example.org": r.profile}


def test_manual_selection_is_exact_and_has_no_failover():
    pool, _ = make()
    r = pool.acquire(scope("a", forced_profile="p3"), "h.example.org")
    assert r.profile == "p3" and r.forced
    assert not pool.failover(r, "h.example.org", ProxyFailure.TIMEOUT)
    with pytest.raises(EgressUnavailable):
        pool.acquire(scope("a", forced_profile="nope"), "h.example.org")


def test_disabled_profiles_are_never_selected():
    s = settings(profiles=[profile("p1", enabled=False), profile("p2")])
    pool, _ = make(s)
    assert {pool.acquire(scope(f"s{i}"), "h.example.org").profile for i in range(3)} == {"p2"}


def test_a_proxy_name_that_rebinds_to_a_private_address_leaves_rotation():
    answers = {"p1.proxy.example.net": ["93.184.216.34"]}
    pool, _ = make(settings(("p1", "p2")), resolver=lambda h: answers.get(h, ["93.184.216.35"]))
    assert pool.acquire(scope("a"), "h.example.org").profile == "p1"
    answers["p1.proxy.example.net"] = ["169.254.169.254"]  # DNS rebinding to metadata
    assert pool.acquire(scope("a"), "h.example.org").profile == "p2"  # sticky p1 re-validated
    assert pool.health_of("p1") is ProxyHealth.UNHEALTHY
    assert pool.state("p1").last_failure is ProxyFailure.ENDPOINT_REJECTED


# -- classification: proxy infrastructure vs everything else ---------------------------------


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (httpx.ConnectTimeout("t"), ProxyFailure.TIMEOUT),
        (httpx.ConnectError("refused"), ProxyFailure.UNAVAILABLE),
        (httpx.ProxyError("407 Proxy Authentication Required"), ProxyFailure.AUTH),
        (httpx.ProxyError("Invalid username/password"), ProxyFailure.AUTH),
        (httpx.ProxyError("502 Bad Gateway"), ProxyFailure.UNAVAILABLE),
        (httpx.ProxyError("503 Service Unavailable"), ProxyFailure.UNAVAILABLE),
        (httpx.ProxyError("403 Forbidden"), ProxyFailure.DENIED),
        (httpx.ProxyError("429 Too Many Requests"), ProxyFailure.DENIED),
        (
            httpx.ProxyError("Proxy Server could not connect: Connection not allowed by ruleset."),
            ProxyFailure.DENIED,
        ),
        (httpx.ProxyError("garbage"), ProxyFailure.UNAVAILABLE),
        (cert_error(), ProxyFailure.TLS_VERIFY),
        (httpx.ReadTimeout("slow destination"), None),
        (httpx.RemoteProtocolError("bad body"), None),
        (httpx.ReadError("reset mid-body"), None),
    ],
)
def test_classification(exc, kind):
    assert classify_proxy_error(exc) is kind


def test_connect_errors_with_root_causes():
    refused = httpx.ConnectError("x")
    refused.__cause__ = ConnectionRefusedError()
    assert classify_proxy_error(refused) is ProxyFailure.CONNECT_REFUSED
    import socket

    dns = httpx.ConnectError("x")
    dns.__cause__ = socket.gaierror(8, "nodename nor servname provided")
    assert classify_proxy_error(dns) is ProxyFailure.DNS
    assert classify_proxy_reply("504 Gateway Timeout") is ProxyFailure.UNAVAILABLE
