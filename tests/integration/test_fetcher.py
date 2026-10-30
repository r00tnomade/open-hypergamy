import httpx
import pytest
from tests.helpers import FakeWeb, html, make_fetcher

from open_hypergamy.config import AppSettings
from open_hypergamy.errors import (
    ContentTooLarge,
    FetchHTTPError,
    FetchTimeout,
    SourcePolicyDenied,
    UnsupportedContentType,
)
from open_hypergamy.sources.policy import Scope

SCOPE = Scope(("example.edu",), deny_paths=("/login",))
URL = "https://example.edu/page"


def test_200_returns_body_and_validators():
    web = FakeWeb(
        {
            URL: html(
                b"<html>hi</html>",
                etag='"v1"',
                **{"last-modified": "Mon, 01 Jan 2026 00:00:00 GMT"},
            )
        }
    )
    f, _ = make_fetcher(web)
    r = f.fetch(URL, SCOPE)
    assert r.status == 200 and r.body == b"<html>hi</html>" and r.etag == '"v1"'
    assert r.mime_type == "text/html" and not r.not_modified


def test_conditional_headers_sent_and_304_handled():
    seen = {}

    def handler(req):
        seen.update(req.headers)
        return httpx.Response(304)

    f, _ = make_fetcher(FakeWeb({URL: handler}))
    r = f.fetch(URL, SCOPE, etag='"v1"', last_modified="Mon, 01 Jan 2026 00:00:00 GMT")
    assert r.not_modified and r.body == b""
    assert seen["if-none-match"] == '"v1"' and "if-modified-since" in seen


def test_404_is_error_not_empty_success():
    f, _ = make_fetcher(FakeWeb({}))
    with pytest.raises(FetchHTTPError) as e:
        f.fetch(URL, SCOPE)
    assert e.value.http_status == 404 and not e.value.retryable


def test_5xx_retries_then_succeeds():
    calls = []

    def flaky(req):
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else html(b"ok")

    f, sleeps = make_fetcher(FakeWeb({URL: flaky}))
    r = f.fetch(URL, SCOPE)
    assert r.body == b"ok" and r.retry_count == 2 and len(calls) == 3
    assert 2.0 in sleeps and 4.0 in sleeps  # exponential backoff between attempts


def test_retries_are_bounded():
    web = FakeWeb({URL: httpx.Response(500)})
    f, _ = make_fetcher(web)
    with pytest.raises(FetchHTTPError):
        f.fetch(URL, SCOPE)
    assert web.urls.count(URL) == 3  # 1 + max_retries(2)


def test_429_retry_after_honoured_and_long_waits_not_taken():
    n = []

    def handler(req):
        n.append(1)
        return httpx.Response(429, headers={"retry-after": "5"}) if len(n) == 1 else html(b"ok")

    f, sleeps = make_fetcher(FakeWeb({URL: handler}))
    assert f.fetch(URL, SCOPE).body == b"ok" and 5.0 in sleeps

    web = FakeWeb({URL: httpx.Response(429, headers={"retry-after": "3600"})})
    f2, _ = make_fetcher(web)
    with pytest.raises(FetchHTTPError) as e:
        f2.fetch(URL, SCOPE)
    assert e.value.http_status == 429 and web.urls.count(URL) == 1


def test_timeout_maps_to_fetch_timeout():
    def boom(req):
        raise httpx.ReadTimeout("slow", request=req)

    f, _ = make_fetcher(FakeWeb({URL: boom}))
    with pytest.raises(FetchTimeout):
        f.fetch(URL, SCOPE)


def test_ordinary_4xx_not_retried():
    web = FakeWeb({URL: httpx.Response(403)})
    f, _ = make_fetcher(web)
    with pytest.raises(FetchHTTPError):
        f.fetch(URL, SCOPE)
    assert web.urls.count(URL) == 1


def test_redirect_followed_within_scope():
    web = FakeWeb({URL: httpx.Response(302, headers={"location": "/final"}),
                   "https://example.edu/final": html(b"done")})  # fmt: skip
    f, _ = make_fetcher(web)
    r = f.fetch(URL, SCOPE)
    assert r.final_url == "https://example.edu/final" and r.body == b"done"


def test_redirect_to_other_domain_blocked_and_not_requested():
    web = FakeWeb({URL: httpx.Response(302, headers={"location": "https://evil.example/x"})})
    f, _ = make_fetcher(web)
    with pytest.raises(SourcePolicyDenied, match="outside"):
        f.fetch(URL, SCOPE)
    assert not any("evil.example" in u for u in web.urls)


def test_redirect_into_denied_path_blocked():
    web = FakeWeb({URL: httpx.Response(302, headers={"location": "/login?next=/"})})
    f, _ = make_fetcher(web)
    with pytest.raises(SourcePolicyDenied, match="denied"):
        f.fetch(URL, SCOPE)


def test_redirect_to_private_ip_blocked():
    web = FakeWeb({URL: httpx.Response(302, headers={"location": "http://169.254.169.254/"})})
    f, _ = make_fetcher(web, resolver=lambda h: ["93.184.216.34"])
    with pytest.raises(SourcePolicyDenied):
        f.fetch(URL, Scope(("example.edu", "169.254.169.254")))
    assert not any("169.254" in u for u in web.urls)


def test_redirect_to_host_resolving_private_blocked():
    web = FakeWeb({URL: httpx.Response(302, headers={"location": "https://cdn.example.edu/x"})})
    f, _ = make_fetcher(
        web, resolver=lambda h: ["10.0.0.9"] if h.startswith("cdn") else ["93.184.216.34"]
    )
    with pytest.raises(SourcePolicyDenied, match="non-public"):
        f.fetch(URL, SCOPE)


def test_redirect_loop_bounded():
    web = FakeWeb({URL: httpx.Response(302, headers={"location": URL})})
    f, _ = make_fetcher(web)
    with pytest.raises(FetchHTTPError, match="redirects"):
        f.fetch(URL, SCOPE)
    assert len(web.urls) <= AppSettings().max_redirects + 3  # + robots lookup


def test_oversize_declared_and_streamed():
    small = AppSettings(max_response_bytes=100)
    f, _ = make_fetcher(FakeWeb({URL: html(b"x" * 500)}), app=small)
    with pytest.raises(ContentTooLarge):
        f.fetch(URL, SCOPE)

    def chunked(req):  # no Content-Length: enforced while streaming
        return httpx.Response(
            200, content=iter([b"x" * 80, b"y" * 80]), headers={"content-type": "text/html"}
        )

    f2, _ = make_fetcher(FakeWeb({URL: chunked}), app=small)
    with pytest.raises(ContentTooLarge):
        f2.fetch(URL, SCOPE)


def test_unsupported_content_type():
    resp = httpx.Response(200, content=b"%PDF", headers={"content-type": "application/pdf"})
    f, _ = make_fetcher(FakeWeb({URL: resp}))
    with pytest.raises(UnsupportedContentType):
        f.fetch(URL, SCOPE)


def test_out_of_scope_and_denied_paths_never_requested():
    web = FakeWeb({})
    f, _ = make_fetcher(web)
    for bad in ("https://other.org/x", "https://example.edu/login"):
        with pytest.raises(SourcePolicyDenied):
            f.fetch(bad, SCOPE)
    assert web.requests == []


ROBOTS = "https://example.edu/robots.txt"


def test_robots_disallow_does_not_block_and_robots_is_not_requested():
    robots = httpx.Response(200, text="User-agent: *\nDisallow: /\n")
    web = FakeWeb({ROBOTS: robots, URL: html(b"ok")})
    f, _ = make_fetcher(web)
    assert f.fetch(URL, SCOPE).body == b"ok"
    assert ROBOTS not in web.urls  # ADR-008: robots.txt is not part of the fetch path


def test_agent_specific_disallow_does_not_block():
    robots = httpx.Response(200, text="User-agent: OpenHypergamy\nDisallow: /\n")
    f, _ = make_fetcher(FakeWeb({ROBOTS: robots, URL: html(b"ok")}))
    assert f.fetch(URL, SCOPE).body == b"ok"


def test_robots_unavailable_or_failing_does_not_block():
    for status in (403, 404, 503):
        f, _ = make_fetcher(FakeWeb({ROBOTS: httpx.Response(status), URL: html(b"ok")}))
        assert f.fetch(URL, SCOPE).body == b"ok"


def test_crawl_delay_is_not_enforced_but_configured_throttle_is():
    robots = httpx.Response(200, text="User-agent: *\nCrawl-delay: 60\n")
    web = FakeWeb({ROBOTS: robots, URL: html(b"a"), "https://example.edu/two": html(b"b")})
    f, sleeps = make_fetcher(web)
    f.fetch(URL, SCOPE)
    f.fetch("https://example.edu/two", SCOPE)
    assert sleeps and all(abs(s - 3.0) < 1e-6 for s in sleeps)  # per_host_min_interval only
    custom, sleeps2 = make_fetcher(web, app=AppSettings(per_host_min_interval_seconds=7.0))
    custom.fetch(URL, SCOPE)
    custom.fetch("https://example.edu/two", SCOPE)
    assert sleeps2 and all(abs(s - 7.0) < 1e-6 for s in sleeps2)  # configurable throttle kept


def test_robots_info_is_informational_and_cached():
    robots = httpx.Response(200, text="User-agent: *\nDisallow: /private/\nCrawl-delay: 10\n")
    web = FakeWeb({ROBOTS: robots})
    f, _ = make_fetcher(web)
    info = f.robots_info(URL)
    assert info is not None and info.crawl_delay("OpenHypergamy") == 10.0
    assert info.disallows("OpenHypergamy", "https://example.edu/private/x")
    assert not info.disallows("OpenHypergamy", URL)
    f.robots_info("https://example.edu/other")
    assert web.urls.count(ROBOTS) == 1
    missing, _ = make_fetcher(FakeWeb({ROBOTS: httpx.Response(500)}))
    assert missing.robots_info(URL) is None  # failures never raise


def test_403_is_not_retried_or_evaded_and_reports_http_status():
    web = FakeWeb({URL: httpx.Response(403, text="forbidden")})
    f, sleeps = make_fetcher(web)
    with pytest.raises(FetchHTTPError) as e:
        f.fetch(URL, SCOPE)
    assert e.value.http_status == 403 and not e.value.retryable
    assert web.urls.count(URL) == 1 and not sleeps  # one request, no retry, no alternate route


def test_ssrf_and_scope_checks_still_apply_when_robots_ignored():
    f, _ = make_fetcher(FakeWeb({}))
    with pytest.raises(SourcePolicyDenied):
        f.fetch("https://example.edu/login", SCOPE)  # source deny_paths remain enforced


def test_per_host_throttle_waits_between_requests():
    web = FakeWeb({URL: html(b"a"), "https://example.edu/two": html(b"b")})
    f, sleeps = make_fetcher(web)
    f.fetch(URL, SCOPE)
    f.fetch("https://example.edu/two", SCOPE)
    assert sleeps and all(abs(s - 3.0) < 1e-6 for s in sleeps)  # 3 s min interval
