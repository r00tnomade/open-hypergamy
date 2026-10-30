"""Fetcher resilience (ADR-009): barriers, Retry-After, host cooldown, jitter, adaptive throttle."""

import threading
from datetime import UTC, datetime

import httpx
import pytest
from tests.helpers import FakeWeb, html, make_fetcher, public_dns

from open_hypergamy.clock import FixedClock
from open_hypergamy.config import AppSettings, CrawlingSettings
from open_hypergamy.errors import AccessBarrier, FetchHTTPError, HostCoolingDown
from open_hypergamy.sources.fetch import Fetcher, HostGate
from open_hypergamy.sources.policy import Scope

SCOPE = Scope(("example.edu", "other.edu"))
URL = "https://example.edu/page"
OTHER = "https://other.edu/page"
CHALLENGE = b"<html><head><title>Just a moment...</title></head><body>cf_chl_opt</body></html>"


class Timeline:
    """Fake monotonic clock + sleep; handlers can advance it to simulate server latency."""

    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def mono(self):
        return self.now

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s


def fetcher_on(web, tl, *, jitter=lambda: 0.5, **app):
    return Fetcher(
        AppSettings(**app), CrawlingSettings(), transport=web.transport, resolver=public_dns,
        monotonic=tl.mono, sleep=tl.sleep, jitter=jitter,
        clock=FixedClock(datetime(2026, 10, 29, 12, 0, tzinfo=UTC)),
    )  # fmt: skip


def test_unchanged_content_is_a_304_reusing_validators_and_changed_content_is_200():
    state = {"etag": '"v1"', "body": b"<html>one</html>"}

    def handler(req):
        if req.headers.get("if-none-match") == state["etag"]:
            return httpx.Response(304, headers={"etag": state["etag"]})
        return html(state["body"], etag=state["etag"])

    web = FakeWeb({URL: handler})
    f, _ = make_fetcher(web)
    first = f.fetch(URL, SCOPE)
    again = f.fetch(URL, SCOPE, etag=first.etag)
    assert again.not_modified and again.body == b"" and again.status == 304
    state.update(etag='"v2"', body=b"<html>two</html>")
    changed = f.fetch(URL, SCOPE, etag=first.etag)
    assert (
        not changed.not_modified and changed.body == b"<html>two</html>" and changed.etag == '"v2"'
    )


def test_200_challenge_page_raises_access_barrier_without_retry():
    web = FakeWeb({URL: html(CHALLENGE)})
    f, _ = make_fetcher(web)
    with pytest.raises(AccessBarrier) as e:
        f.fetch(URL, SCOPE)
    assert not e.value.retryable and e.value.http_status == 200 and web.urls.count(URL) == 1


def test_redirect_to_login_is_a_barrier():
    login = "https://example.edu/accounts/login"
    web = FakeWeb(
        {URL: httpx.Response(302, headers={"location": login}), login: html(b"<html>x</html>")}
    )
    f, _ = make_fetcher(web)
    with pytest.raises(AccessBarrier, match="login"):
        f.fetch(URL, SCOPE)


def test_429_with_http_date_retry_after_is_parsed_and_long_waits_handed_to_the_scheduler():
    web = FakeWeb(
        {URL: httpx.Response(429, headers={"retry-after": "Thu, 29 Oct 2026 14:00:00 GMT"})}
    )
    tl = Timeline()
    f = fetcher_on(web, tl)
    with pytest.raises(FetchHTTPError) as e:
        f.fetch(URL, SCOPE)
    assert e.value.http_status == 429 and e.value.retry_after == 7200.0
    assert web.urls.count(URL) == 1  # 2 h is beyond the in-run cap: no blind retry


def test_503_exhausting_retries_cools_the_whole_host_for_the_run():
    web = FakeWeb(
        {URL: httpx.Response(503), "https://example.edu/b": html(b"ok"), OTHER: html(b"ok")}
    )
    tl = Timeline()
    f = fetcher_on(web, tl, host_cooldown_seconds=300)
    with pytest.raises(FetchHTTPError):
        f.fetch(URL, SCOPE)
    assert web.urls.count(URL) == 3  # 1 + max_retries, then stop
    with pytest.raises(HostCoolingDown) as e:
        f.fetch("https://example.edu/b", SCOPE)
    assert "https://example.edu/b" not in web.urls and 0 < e.value.retry_after <= 300
    assert f.fetch(OTHER, SCOPE).body == b"ok"  # other hosts unaffected
    tl.now += 301
    assert f.fetch("https://example.edu/b", SCOPE).body == b"ok"  # recovers after the pause


def test_404_and_403_do_not_cool_the_host():
    web = FakeWeb({URL: httpx.Response(403), "https://example.edu/b": html(b"ok")})
    f, _ = make_fetcher(web)
    with pytest.raises(FetchHTTPError):
        f.fetch(URL, SCOPE)
    assert f.fetch("https://example.edu/b", SCOPE).body == b"ok"


@pytest.mark.parametrize(("r", "lo", "hi"), [(0.0, 1.0, 2.0), (0.999, 2.99, 6.0)])
def test_backoff_has_bounded_jitter(r, lo, hi):
    calls = []

    def flaky(req):
        calls.append(1)
        return httpx.Response(500) if len(calls) < 3 else html(b"ok")

    tl = Timeline()
    f = fetcher_on(FakeWeb({URL: flaky}), tl, jitter=lambda: r, per_host_min_interval_seconds=0)
    f.fetch(URL, SCOPE)
    backoffs = [s for s in tl.sleeps if s not in (0,)]
    assert len(backoffs) == 2 and lo <= backoffs[0] < hi
    assert backoffs[1] == pytest.approx(backoffs[0] * 2)


def test_adaptive_throttle_slows_slow_hosts_and_never_drops_below_floor():
    tl = Timeline()

    def slow(req):
        tl.now += 9.0  # 9 s server latency
        return html(b"ok")

    web = FakeWeb({URL: slow, OTHER: html(b"ok")})
    f = fetcher_on(web, tl)
    f.fetch(URL, SCOPE)
    st = f.gate.stats("example.edu")
    assert st.delay == pytest.approx(6.0) and st.latency_ewma == pytest.approx(9.0)
    f.fetch(URL, SCOPE)
    assert st.delay == pytest.approx(7.5)  # converging towards the observed latency
    f.fetch(OTHER, SCOPE)
    assert f.gate.stats("other.edu").delay == 3.0  # fast host stays at the configured floor


def test_overload_doubles_delay_and_errors_never_speed_up():
    tl = Timeline()
    web = FakeWeb({URL: httpx.Response(429, headers={"retry-after": "1"})})
    f = fetcher_on(web, tl, max_retries=0)
    with pytest.raises(FetchHTTPError):
        f.fetch(URL, SCOPE)
    assert f.gate.stats("example.edu").delay == 6.0
    assert f.gate.stats("example.edu").statuses == {429: 1}


def test_static_throttle_when_adaptive_disabled():
    tl = Timeline()

    def slow(req):
        tl.now += 9.0
        return html(b"ok")

    f = fetcher_on(FakeWeb({URL: slow}), tl, adaptive_throttle=False)
    f.fetch(URL, SCOPE)
    assert f.gate.stats("example.edu").delay == 3.0


def test_per_host_concurrency_is_limited():
    gate = HostGate(min_interval=0, max_delay=1, max_concurrency=1, adaptive=False,
                    monotonic=lambda: 0.0, sleep=lambda s: None)  # fmt: skip
    entered = threading.Event()
    release = threading.Event()
    order: list[str] = []

    def holder():
        with gate.slot("example.edu"):
            order.append("a-in")
            entered.set()
            release.wait(5)
            order.append("a-out")

    t = threading.Thread(target=holder)
    t.start()
    entered.wait(5)
    st = gate.stats("example.edu")
    assert not st.slots.acquire(blocking=False)  # the only slot is taken
    with gate.slot("other.edu"):
        order.append("other")  # a different host is not blocked
    release.set()
    t.join(5)
    with gate.slot("example.edu"):
        order.append("b-in")
    assert order == ["a-in", "other", "a-out", "b-in"]


def test_concurrent_callers_are_spaced_by_the_host_interval():
    tl = Timeline()
    lock = threading.Lock()

    def sleep(s):
        with lock:
            tl.sleeps.append(s)

    gate = HostGate(min_interval=3.0, max_delay=60, max_concurrency=4, adaptive=False,
                    monotonic=tl.mono, sleep=sleep)  # fmt: skip
    threads = [threading.Thread(target=lambda: gate.slot("h").__enter__()) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert sorted(tl.sleeps) == [3.0, 6.0, 9.0]  # reserved start times, never simultaneous


def test_user_agent_header_identifies_the_crawler():
    seen = {}

    def handler(req):
        seen["ua"] = req.headers["user-agent"]
        return html(b"ok")

    f, _ = make_fetcher(FakeWeb({URL: handler}), app=AppSettings(crawler_contact="ops@example.org"))
    f.fetch(URL, SCOPE)
    assert (
        seen["ua"]
        == "OpenHypergamy/0.1 (+https://github.com/r00tnomade/open-hypergamy; ops@example.org)"
    )
