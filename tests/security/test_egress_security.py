"""Egress proxy security invariants (ADR-012).

Failover is for proxy-infrastructure faults only. A destination's answer (403, 429, 401, 451,
a challenge page) never changes egress identity; there is no silent direct fallback; HostGate
stays keyed by destination host; secrets and addresses never leak.
"""

import inspect
import shutil
import ssl
import subprocess
import threading
from socket import socket

import httpx
import pytest
from tests.helpers import PUBLIC_IP, html
from tests.helpers_egress import HEALTH_URL, cert_error, profile, rig, settings

from open_hypergamy.config import AppSettings, CrawlingSettings
from open_hypergamy.egress.classify import ProxyFailure, classify_proxy_error
from open_hypergamy.egress.pool import EgressReport, egress_scope
from open_hypergamy.egress.security import scrub
from open_hypergamy.egress.transport import EgressClients
from open_hypergamy.errors import (
    AccessBarrier,
    ContentTooLarge,
    EgressUnavailable,
    FetchHTTPError,
    FetchNetworkError,
    SourcePolicyDenied,
    UnsupportedContentType,
)
from open_hypergamy.sources.fetch import Fetcher
from open_hypergamy.sources.policy import Scope

URL = "https://example.edu/opportunities"
SCOPE = Scope(("example.edu",))
PAGE = html(b"<html><title>Programme</title><body>Apply by 1 March 2027.</body></html>")
CHALLENGE = html(
    b"<html><head><title>Just a moment...</title></head><body>cf_chl_opt</body></html>"
)


def fetch(r, url=URL, source="src-a", **kw):
    rep = EgressReport()
    with egress_scope(source, rep, **kw):
        try:
            return r.fetcher.fetch(url, SCOPE), rep
        except Exception as e:  # noqa: BLE001
            e.report = rep  # type: ignore[attr-defined]
            raise


# -- direct is the default; proxies are strictly opt-in ---------------------------------------


def test_without_proxy_config_everything_is_direct_and_ambient_proxies_are_ignored(monkeypatch):
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(var, "http://203.0.113.9:3128")
    f = Fetcher(AppSettings(), CrawlingSettings())
    assert not f._client._mounts  # no env-derived proxy mounts: trust_env is off
    assert type(f._client._transport._pool).__name__ == "ConnectionPool"  # type: ignore[attr-defined]
    assert f.egress is None
    f.close()


def test_sources_without_an_assignment_stay_direct_even_when_proxies_are_on():
    r = rig(
        {URL: PAGE}, proxy_settings=settings(default_profiles=[], assignments={"src-a": ["p1"]})
    )
    with egress_scope("unassigned"):
        r.fetcher.fetch(URL, SCOPE)
    assert r.direct.urls == [URL] and not any(p.requests for p in r.proxies.values())


def test_assigned_sources_use_their_own_profile_only():
    s = settings(default_profiles=[], assignments={"a": ["p1"], "b": ["p2"]})
    r = rig({URL: PAGE}, proxy_settings=s)
    fetch(r, source="a")
    fetch(r, source="b")
    assert [len(r.proxies["p1"].requests), len(r.proxies["p2"].requests)] == [1, 1]
    assert r.direct.requests == []  # no direct traffic for assigned sources


# -- failover only for proxy infrastructure ---------------------------------------------------


@pytest.mark.parametrize(
    ("failure", "kind"),
    [
        (httpx.ConnectError("refused"), "unavailable"),
        (httpx.ConnectTimeout("timeout"), "timeout"),
        (httpx.ProxyError("502 Bad Gateway"), "unavailable"),
        (httpx.ProxyError("407 Proxy Authentication Required"), "auth"),
        (httpx.Response(407), "auth"),  # forward-proxy auth demand arrives as a response
    ],
)
def test_proxy_infrastructure_failure_fails_over_to_the_next_trusted_profile(failure, kind):
    r = rig({URL: PAGE})
    r.proxies["p1"].mode = failure
    resp, rep = fetch(r)
    assert resp.status == 200 and rep.failover_count == 1 and rep.profile == "p2"
    assert rep.proxy_failures == {kind: 1} and rep.profiles_used == ["p1", "p2"]
    assert r.direct.requests == []


def test_failover_is_bounded_and_never_falls_back_to_direct():
    s = settings(("p1", "p2", "p3"), max_failovers=1)
    r = rig({URL: PAGE}, proxy_settings=s)
    for p in r.proxies.values():
        p.mode = httpx.ConnectError("refused")
    with pytest.raises(EgressUnavailable) as e:
        fetch(r)
    assert e.value.report.failover_count == 1  # type: ignore[attr-defined]
    assert sum(len(p.requests) for p in r.proxies.values()) == 2  # initial + one failover
    assert r.direct.requests == []
    assert "proxy.example.net" not in str(e.value)  # address scrubbed from the message


def test_when_every_profile_is_down_the_source_fails_instead_of_going_direct():
    r = rig({URL: PAGE})
    for p in r.proxies.values():
        p.mode = httpx.ConnectTimeout("t")
    with pytest.raises(EgressUnavailable):
        fetch(r)
    with pytest.raises(EgressUnavailable):  # profiles are now cooling down: still no direct
        fetch(r)
    assert r.direct.requests == []


def test_assigned_only_to_disabled_profiles_fails_closed():
    s = settings(profiles=[profile("p1", enabled=False)], default_profiles=["p1"],
                 trusted_endpoint_hosts=[])  # fmt: skip
    r = rig({URL: PAGE}, proxy_settings=s)
    with pytest.raises(EgressUnavailable):
        fetch(r)
    assert r.direct.requests == []


def test_proxy_denial_is_a_policy_decision_not_a_reason_to_rotate():
    r = rig({URL: PAGE})
    r.proxies["p1"].mode = httpx.ProxyError("403 Forbidden")
    with pytest.raises(SourcePolicyDenied):
        fetch(r)
    assert len(r.proxies["p2"].requests) == 0 and r.direct.requests == []


def test_ambiguous_tls_verification_failure_fails_closed_without_failover():
    r = rig({URL: PAGE})
    r.proxies["p1"].mode = cert_error()
    with pytest.raises(FetchNetworkError):
        fetch(r)
    assert len(r.proxies["p2"].requests) == 0 and r.direct.requests == []


# -- destination restrictions never change identity -------------------------------------------


@pytest.mark.parametrize("status", [401, 403, 451])
def test_access_restrictions_do_not_rotate_or_fail_over(status):
    r = rig({URL: httpx.Response(status)}, proxy_settings=settings(affinity="none"))
    with pytest.raises(FetchHTTPError) as e:
        fetch(r)
    rep = e.value.report  # type: ignore[attr-defined]
    assert e.value.http_status == status and rep.destination_status == status
    assert rep.failover_count == 0 and rep.rotation_count == 0 and rep.profiles_used == ["p1"]
    assert len(r.proxies["p2"].requests) == 0 and r.direct.requests == []
    assert len(r.proxies["p1"].requests) == 1  # no retry, no second identity


def test_429_retries_stay_on_the_same_identity_and_respect_retry_after():
    r = rig({URL: httpx.Response(429, headers={"retry-after": "9"})})
    with pytest.raises(FetchHTTPError) as e:
        fetch(r)
    rep = e.value.report  # type: ignore[attr-defined]
    assert e.value.http_status == 429 and rep.failover_count == 0 and rep.rotation_count == 0
    assert len(r.proxies["p1"].requests) == 3 and len(r.proxies["p2"].requests) == 0
    assert 9.0 in r.sleeps  # Retry-After honoured
    assert r.fetcher.gate.cooldown_remaining("example.edu") > 0  # host cooled for the run


def test_challenge_pages_do_not_trigger_another_identity():
    r = rig({URL: CHALLENGE})
    with pytest.raises(AccessBarrier) as e:
        fetch(r)
    assert e.value.report.failover_count == 0  # type: ignore[attr-defined]
    assert len(r.proxies["p2"].requests) == 0 and len(r.proxies["p1"].requests) == 1


def test_a_host_that_restricted_access_is_pinned_and_never_fails_over_afterwards():
    r = rig({URL: httpx.Response(403)}, proxy_settings=settings(affinity="none"))
    with pytest.raises(FetchHTTPError):
        fetch(r)
    assert r.pool.restricted_hosts() == {"example.edu": "p1"}
    r.web.routes[URL] = PAGE
    resp, rep = fetch(r)  # round-robin would pick p2: the pin keeps p1
    assert rep.profile == "p1" and rep.rotation_count == 0
    r.proxies["p1"].mode = httpx.ConnectError("down")
    with pytest.raises(EgressUnavailable):  # no switching identity for a restricted host
        fetch(r)
    assert len(r.proxies["p2"].requests) == 0


# -- HostGate and circuit breaker semantics ----------------------------------------------------


def test_host_gate_is_global_per_destination_across_profiles():
    r = rig({URL: PAGE}, proxy_settings=settings(affinity="none"))
    fetch(r, source="a")
    fetch(r, source="b")  # different source -> different proxy, same destination host
    assert [len(r.proxies["p1"].requests), len(r.proxies["p2"].requests)] == [1, 1]
    assert r.fetcher.gate.stats("example.edu").requests == 2
    assert any(s >= 3.0 for s in r.sleeps)  # the 3 s floor applied across egress identities
    assert set(r.fetcher.gate.snapshot()) >= {"example.edu"}
    assert not any("proxy" in h for h in r.fetcher.gate.snapshot())  # keyed by destination only


def test_failover_attempts_still_consume_destination_slots():
    r = rig({URL: PAGE})
    r.proxies["p1"].mode = httpx.ConnectTimeout("t")
    fetch(r)
    assert any(s >= 3.0 for s in r.sleeps)  # the replacement attempt waited for the host gate


def test_a_dead_proxy_does_not_speed_up_or_poison_the_destinations_pacing():
    r = rig({URL: PAGE})
    r.proxies["p1"].mode = httpx.ConnectError("x")
    fetch(r)
    st = r.fetcher.gate.stats("example.edu")
    assert st.requests == 1 and st.statuses == {200: 1}  # only the real destination answer counted


# -- SSRF, rebinding, redirects ------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    ["https://169.254.169.254/latest/meta-data", "https://10.0.0.7/", "https://127.0.0.1/",
     "https://localhost/", "https://metadata.google.internal/"],
)  # fmt: skip
def test_internal_and_metadata_destinations_never_reach_the_proxy(url):
    r = rig({})
    with pytest.raises(SourcePolicyDenied):
        r.fetcher.fetch(
            url,
            Scope(
                (
                    "169.254.169.254",
                    "10.0.0.7",
                    "127.0.0.1",
                    "localhost",
                    "metadata.google.internal",
                )
            ),
        )
    assert not any(p.requests for p in r.proxies.values()) and r.direct.requests == []


def test_destination_dns_rebinding_to_a_private_address_is_refused():
    r = rig({URL: PAGE}, resolver=lambda h: ["10.0.0.9"])
    with pytest.raises(SourcePolicyDenied):
        fetch(r)
    assert not any(p.requests for p in r.proxies.values())


def test_redirects_through_a_proxy_are_revalidated_per_hop():
    seen = []

    def hostile_redirect(req):
        seen.append(str(req.url))
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})

    r = rig({URL: hostile_redirect})
    with pytest.raises(SourcePolicyDenied):
        fetch(r)
    assert seen == [URL] and len(r.proxies["p1"].requests) == 1


def test_redirect_to_another_domain_is_blocked_by_source_scope_through_a_proxy():
    r = rig({URL: httpx.Response(302, headers={"location": "https://evil.example.org/x"})})
    with pytest.raises(SourcePolicyDenied):
        fetch(r)


def test_proxy_endpoint_rebinding_takes_the_profile_out_of_rotation():
    answers = {"p1.proxy.example.net": [PUBLIC_IP]}
    r = rig({URL: PAGE}, pool_resolver=lambda h: answers.get(h, [PUBLIC_IP]))
    fetch(r)
    answers["p1.proxy.example.net"] = ["169.254.169.254"]
    _, rep = fetch(r)
    assert rep.profile == "p2" and len(r.proxies["p1"].requests) == 1
    assert r.pool.state("p1").last_failure is ProxyFailure.ENDPOINT_REJECTED


# -- hostile proxies -----------------------------------------------------------------------------


def test_a_proxy_cannot_exceed_size_or_type_limits():
    big = httpx.Response(200, content=b"x" * 3000, headers={"content-type": "text/html"})
    r = rig({URL: big}, app=AppSettings(max_response_bytes=1000))
    with pytest.raises(ContentTooLarge):
        fetch(r)
    r = rig(
        {
            URL: httpx.Response(
                200, content=b"MZ\x90", headers={"content-type": "application/x-msdownload"}
            )
        }
    )
    with pytest.raises(UnsupportedContentType):
        fetch(r)


def test_malformed_proxy_replies_fail_over_and_garbage_bodies_do_not_corrupt_state():
    r = rig({URL: PAGE})
    r.proxies["p1"].mode = httpx.ProxyError("\x00\x01 not http at all")
    _, rep = fetch(r)
    assert rep.profile == "p2" and rep.proxy_failures == {"unavailable": 1}
    r2 = rig({URL: PAGE})
    r2.proxies["p1"].mode = httpx.RemoteProtocolError("garbled")
    with pytest.raises(FetchNetworkError):  # not evidence about the proxy: no identity change
        fetch(r2)
    assert len(r2.proxies["p2"].requests) == 0 and r2.direct.requests == []


def test_a_hostile_proxy_that_returns_other_content_cannot_make_it_through_scope():
    # A proxy may forge a body but cannot widen scope: a redirect off-domain is refused.
    r = rig({URL: httpx.Response(307, headers={"location": "https://127.0.0.1/admin"})})
    with pytest.raises(SourcePolicyDenied):
        fetch(r)


# -- recovery -------------------------------------------------------------------------------------


def test_unavailable_proxy_is_reintroduced_only_after_cooldown_and_a_passing_probe():
    s = settings(("p1",), failure_threshold=1, cooldown_seconds=60, max_cooldown_seconds=60)
    r = rig({URL: PAGE}, proxy_settings=s)
    r.proxies["p1"].mode = httpx.ConnectError("down")
    with pytest.raises(EgressUnavailable):
        fetch(r)
    r.proxies["p1"].mode = None  # proxy repaired
    with pytest.raises(EgressUnavailable):  # still cooling down
        fetch(r)
    probes_before = len([u for u in r.web.urls if u == HEALTH_URL])
    r.advance(61)
    resp, _ = fetch(r)  # cooldown over -> probe via health_check_url -> reintroduced
    assert resp.status == 200
    assert len([u for u in r.web.urls if u == HEALTH_URL]) == probes_before + 1
    assert r.pool.health_of("p1").value in ("degraded", "healthy")


def test_recovery_probe_failure_keeps_the_proxy_out():
    s = settings(("p1",), failure_threshold=1, cooldown_seconds=60, max_cooldown_seconds=600)
    r = rig({URL: PAGE}, proxy_settings=s)
    r.proxies["p1"].mode = httpx.ConnectError("down")
    with pytest.raises(EgressUnavailable):
        fetch(r)
    r.advance(61)
    with pytest.raises(EgressUnavailable):  # probe fails (still down)
        fetch(r)
    r.proxies["p1"].mode = None
    r.advance(30)  # doubled cooldown (120 s) not over yet
    with pytest.raises(EgressUnavailable):
        fetch(r)


# -- secrets, redaction, isolation ----------------------------------------------------------------


def test_scrub_removes_addresses_userinfo_and_secret_values():
    p = profile("p1")
    text = (
        "connect to p1.proxy.example.net:8443 failed for https://bob:s3cr3tpw@p1.proxy.example.net:8443 "
        "token=s3cr3tpw"
    )
    out = scrub(text, p, "s3cr3tpw", "bob")
    assert "s3cr3tpw" not in out and "p1.proxy.example.net" not in out and "bob:" not in out
    assert "<proxy:p1>" in out


def test_credentials_come_from_secret_stores_and_never_reach_the_url(monkeypatch):
    monkeypatch.setenv("OHG_PROXY_P1_USER", "alice")
    monkeypatch.setenv("OHG_PROXY_P1_PASS", "pa55-w0rd-SECRET")
    p = profile("p1", username_secret="OHG_PROXY_P1_USER", password_secret="OHG_PROXY_P1_PASS")
    s = settings(("p1",), profiles=[p])
    clients = EgressClients(s, user_agent="t", timeout=httpx.Timeout(5.0))
    c = clients.client("p1")
    assert "pa55" not in repr(c) and "pa55" not in str(p.model_dump())
    assert "pa55" not in p.url
    [mount] = c._mounts.values()  # type: ignore[attr-defined]
    pool = mount._pool
    assert type(pool).__name__ == "HTTPProxy" and pool._proxy_url.host == b"p1.proxy.example.net"
    clients.close()


def test_missing_credential_secrets_fail_closed_with_a_name_free_message(monkeypatch):
    p = profile("p1", username_secret="OHG_PROXY_P1_USER", password_secret="OHG_PROXY_P1_PASS")
    clients = EgressClients(
        settings(("p1",), profiles=[p]), user_agent="t", timeout=httpx.Timeout(5.0)
    )
    from open_hypergamy.errors import ConfigurationError

    with pytest.raises(ConfigurationError, match="not set"):
        clients.client("p1")


def test_each_profile_has_its_own_client_and_cookie_jar_and_never_the_direct_one():
    r = rig({URL: PAGE})
    c1 = r.fetcher._egress_clients.client("p1")  # type: ignore[union-attr]
    c2 = r.fetcher._egress_clients.client("p2")  # type: ignore[union-attr]
    assert len({id(c1), id(c2), id(r.fetcher._client)}) == 3
    c1.cookies.set("sid", "abc", domain="example.edu")
    assert "sid" not in c2.cookies and "sid" not in r.fetcher._client.cookies


def test_proxy_clients_never_trust_ambient_proxy_environment(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://203.0.113.9:3128")
    monkeypatch.setenv("ALL_PROXY", "socks5://203.0.113.9:1080")
    s = settings(("p1",))
    clients = EgressClients(s, user_agent="t", timeout=httpx.Timeout(5.0))
    c = clients.client("p1")
    [mount] = c._mounts.values()  # only the configured profile; no env-derived proxy mounts
    assert mount._pool._proxy_url.host == b"p1.proxy.example.net"
    clients.close()


def test_sensitive_clients_are_direct_only_and_ignore_ambient_proxies(monkeypatch):
    from open_hypergamy.llm.client import LLMClient  # noqa: F401
    from open_hypergamy.notifications.telegram import TelegramSink

    monkeypatch.setenv("HTTPS_PROXY", "http://203.0.113.9:3128")
    monkeypatch.setenv("HTTP_PROXY", "http://203.0.113.9:3128")
    sink = TelegramSink("123456:ABCDEF-token-value-0000000000000", "42")
    assert not sink._http._mounts  # type: ignore[attr-defined]
    assert type(sink._http._transport._pool).__name__ == "ConnectionPool"  # type: ignore[attr-defined]
    for cls in (TelegramSink, LLMClient):
        assert "proxy" not in inspect.signature(cls.__init__).parameters  # cannot be injected
    assert "egress" not in inspect.signature(TelegramSink.__init__).parameters


def test_unscoped_traffic_is_never_routed_through_a_proxy():
    r = rig({URL: PAGE})
    r.fetcher.fetch(URL, SCOPE)  # no egress_scope: e.g. a notification or manual lead
    assert r.direct.urls == [URL] and not any(p.requests for p in r.proxies.values())


def test_manual_profile_selection_pins_that_profile_without_failover():
    r = rig({URL: PAGE})
    resp, rep = fetch(r, forced_profile="p2")
    assert rep.profile == "p2" and len(r.proxies["p1"].requests) == 0
    r.proxies["p2"].mode = httpx.ConnectError("down")
    with pytest.raises(EgressUnavailable):
        fetch(r, forced_profile="p2")
    assert len(r.proxies["p1"].requests) == 0


def test_robots_lookups_follow_the_sources_egress_not_a_direct_connection():
    r = rig({"https://example.edu/robots.txt": httpx.Response(200, text="User-agent: *\nDisallow: /x\n",
                                                                 headers={"content-type": "text/plain"})})  # fmt: skip
    with egress_scope("src-a"):
        info = r.fetcher.robots_info(URL)
    assert info is not None and r.direct.requests == []
    assert any(u.endswith("/robots.txt") for u in r.proxies["p1"].urls)


# -- TLS: real handshake against a local server --------------------------------------------------


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl CLI not available")
def test_untrusted_proxy_certificate_is_rejected_and_a_configured_ca_is_honoured(tmp_path):
    key, crt = tmp_path / "k.pem", tmp_path / "c.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
         "-out", str(crt), "-days", "2", "-subj", "/CN=127.0.0.1",
         "-addext", "subjectAltName=IP:127.0.0.1"],
        check=True, capture_output=True,
    )  # fmt: skip
    srv_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    srv_ctx.load_cert_chain(crt, key)
    listener = socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)
    port = listener.getsockname()[1]
    stop = threading.Event()

    def serve():
        listener.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = listener.accept()
            except OSError:
                continue
            try:
                with srv_ctx.wrap_socket(conn, server_side=True) as tls:
                    tls.recv(4096)  # swallow the request, answer nothing useful
            except (ssl.SSLError, OSError):
                pass

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    try:
        base = {"name": "loc", "url": f"https://127.0.0.1:{port}", "trusted": True,
                "allow_private_endpoint": True}  # fmt: skip
        timeout = httpx.Timeout(3.0)
        bad = settings(("loc",), trusted_endpoint_hosts=["127.0.0.1"],
                       profiles=[profile("loc", url=base["url"], allow_private_endpoint=True)])  # fmt: skip
        clients = EgressClients(bad, user_agent="t", timeout=timeout)
        with pytest.raises(httpx.TransportError) as e:
            clients.client("loc").get("http://example.org/")
        assert classify_proxy_error(e.value) is ProxyFailure.TLS_VERIFY  # default store rejects it
        clients.close()

        good = settings(("loc",), trusted_endpoint_hosts=["127.0.0.1"],
                        profiles=[profile("loc", url=base["url"], allow_private_endpoint=True,
                                          ca_bundle=str(crt))])  # fmt: skip
        clients = EgressClients(good, user_agent="t", timeout=timeout)
        with pytest.raises(httpx.TransportError) as e2:
            clients.client("loc").get("http://example.org/")
        # the handshake now succeeds; failure moves on to the (silent) fake proxy protocol
        assert classify_proxy_error(e2.value) is not ProxyFailure.TLS_VERIFY
        clients.close()
    finally:
        stop.set()
        listener.close()
        t.join(2)
