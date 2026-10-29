import httpx
import pytest
from tests.helpers import FakeWeb, html, make_fetcher

from opportunity_radar.config import AppSettings
from opportunity_radar.errors import (
    ContentTooLarge,
    FetchHTTPError,
    FetchTimeout,
    SourcePolicyDenied,
    UnsupportedContentType,
)
from opportunity_radar.sources.policy import Scope

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


def test_robots_disallow_blocks_without_fetching_page():
    robots = httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")
    web = FakeWeb({"https://example.edu/robots.txt": robots, "https://example.edu/private/x": html(b"secret"),
                   URL: html(b"ok")})  # fmt: skip
    f, _ = make_fetcher(web)
    with pytest.raises(SourcePolicyDenied, match="robots"):
        f.fetch("https://example.edu/private/x", SCOPE)
    assert "https://example.edu/private/x" not in web.urls
    assert f.fetch(URL, SCOPE).body == b"ok"
    assert web.urls.count("https://example.edu/robots.txt") == 1  # cached per origin


def test_robots_agent_specific_rule():
    robots = httpx.Response(200, text="User-agent: OpportunityRadar\nDisallow: /\n")
    f, _ = make_fetcher(FakeWeb({"https://example.edu/robots.txt": robots, URL: html(b"ok")}))
    with pytest.raises(SourcePolicyDenied):
        f.fetch(URL, SCOPE)


def test_robots_5xx_means_do_not_crawl_but_4xx_means_allowed():
    f, _ = make_fetcher(
        FakeWeb({"https://example.edu/robots.txt": httpx.Response(503), URL: html(b"ok")})
    )
    with pytest.raises(SourcePolicyDenied, match="robots"):
        f.fetch(URL, SCOPE)
    f2, _ = make_fetcher(
        FakeWeb({"https://example.edu/robots.txt": httpx.Response(403), URL: html(b"ok")})
    )
    assert f2.fetch(URL, SCOPE).body == b"ok"


def test_per_host_throttle_waits_between_requests():
    web = FakeWeb({URL: html(b"a"), "https://example.edu/two": html(b"b")})
    f, sleeps = make_fetcher(web)
    f.fetch(URL, SCOPE)
    f.fetch("https://example.edu/two", SCOPE)
    assert sleeps and all(abs(s - 3.0) < 1e-6 for s in sleeps)  # 3 s min interval
