import httpx
import pytest
from tests.helpers import FakeWeb, fixture, html, make_fetcher

from open_hypergamy.config import AppSettings
from open_hypergamy.errors import ParseError
from open_hypergamy.sources.base import FetchContext, SourceRecord
from open_hypergamy.sources.fetch import BodyCache
from open_hypergamy.sources.html import HtmlAdapter, parse_html
from open_hypergamy.sources.rss_atom import RssAtomAdapter
from open_hypergamy.sources.sitemap import SitemapAdapter, parse_sitemap


def source(url="https://example.edu/students/opportunities", adapter="html", **kw) -> SourceRecord:
    base = dict(
        id="sid", source_key="example", name="Example", canonical_url=url, domain="example.edu",
        source_type="official_programme_index", adapter_type=adapter,
        trust_tier="t2_official_org", authority_scope="", allowed_domains=("example.edu",),
        allow_paths=(), deny_paths=("/login",), fetch_interval_hours=168, priority=50,
        enabled=True, state="active", discovery_only=False, discovery_policy={},
        failure_streak=0, etag=None, last_modified=None, last_content_hash=None,
        next_due_at=None, last_success_at=None, last_attempt_at=None, last_content_change_at=None,
        robots_policy_checked_at=None, terms_review_note="",
    )  # fmt: skip
    return SourceRecord(**{**base, **kw})


def ctx_for(web, tmp_path=None, **app):
    f, _ = make_fetcher(web, app=AppSettings(**app) if app else None)
    return FetchContext(fetcher=f, settings=f.app, cache=BodyCache(tmp_path) if tmp_path else None)


def test_parse_html_extracts_title_text_links_meta():
    title, text, links, meta = parse_html(
        fixture("index.html").decode(), "https://example.edu/students/opportunities"
    )
    assert title == "Student Opportunities"
    assert "15 March 2027" in text
    assert (
        "https://example.edu/students/opportunities/summer-school" in links
    )  # tracking+fragment stripped
    assert "https://other.org/x" in links and not any(x.startswith("mailto") for x in links)
    assert meta["description"] == "Programmes for students"


def test_html_adapter_single_page_and_cache(tmp_path):
    src = source()
    web = FakeWeb({src.canonical_url: html(fixture("index.html"))})
    ctx = ctx_for(web, tmp_path)
    [obs] = HtmlAdapter().fetch(src, ctx)
    assert obs.title == "Student Opportunities" and obs.http_status == 200
    assert (tmp_path / obs.body_cache_relpath).read_bytes() == fixture("index.html")
    assert (tmp_path / obs.text_cache_relpath).read_text() == obs.text
    assert obs.content_sha256 in obs.body_cache_relpath


def test_html_crawl_respects_scope_depth_and_denies():
    src = source(
        allow_paths=("/students", "/research"),
        discovery_policy={"follow_internal_links": True, "max_depth": 1, "max_pages_per_run": 10},
    )
    child = html(b"<html><title>Child</title><body><a href='/students/opportunities/deeper'>d</a>"
                 b"<p>" + b"text " * 60 + b"</p></body></html>")  # fmt: skip
    web = FakeWeb({
        src.canonical_url: html(fixture("index.html")),
        "https://example.edu/students/opportunities/summer-school": child,
        "https://example.edu/research/internships": child,
        "https://example.edu/login": html(b"login"),
        "https://example.edu/about": html(b"about"),
        "https://other.org/x": html(b"external"),
    })  # fmt: skip
    obs = HtmlAdapter().fetch(src, ctx_for(web))
    fetched = {o.final_url for o in obs}
    assert fetched == {src.canonical_url, "https://example.edu/students/opportunities/summer-school",
                       "https://example.edu/research/internships"}  # fmt: skip
    for forbidden in ("/login", "/about", "other.org", "/deeper"):
        assert not any(forbidden in u for u in web.urls), forbidden  # denied links never fetched


def test_html_crawl_page_cap_and_child_failure_is_partial():
    src = source(
        discovery_policy={"follow_internal_links": True, "max_depth": 1, "max_pages_per_run": 2}
    )
    web = FakeWeb({src.canonical_url: html(fixture("index.html"))})  # children 404
    ctx = ctx_for(web)
    obs = HtmlAdapter().fetch(src, ctx)
    assert len(obs) == 1 and ctx.failures and ctx.failures[0].error_code == "http_error"


def test_html_304_returns_not_modified_without_crawling():
    src = source(etag='"v1"', last_content_hash="abc",
                 discovery_policy={"follow_internal_links": True})  # fmt: skip
    web = FakeWeb({src.canonical_url: httpx.Response(304)})
    [obs] = HtmlAdapter().fetch(src, ctx_for(web))
    assert obs.not_modified and obs.content_sha256 == "abc"
    assert not any("summer-school" in u for u in web.urls)


def test_rss_adapter_parses_entries_and_canonicalizes_links():
    src = source("https://example.edu/feed.xml", "rss_atom")
    web = FakeWeb({src.canonical_url: httpx.Response(200, content=fixture("feed.xml"),
                                                     headers={"content-type": "application/rss+xml"})})  # fmt: skip
    [obs] = RssAtomAdapter().fetch(src, ctx_for(web))
    assert obs.title == "Example Institute News" and len(obs.entries) == 2
    assert obs.entries[0].link == "https://example.edu/news/summer-school-2027"
    assert obs.entries[1].link == "https://example.edu/news/robotics-internship"
    assert "Applications open in January" in obs.text


def test_rss_adapter_rejects_non_feed():
    src = source("https://example.edu/feed.xml", "rss_atom")
    web = FakeWeb({src.canonical_url: httpx.Response(200, content=b"<html><body>no</body></html>",
                                                     headers={"content-type": "text/xml"})})  # fmt: skip
    with pytest.raises(ParseError):
        RssAtomAdapter().fetch(src, ctx_for(web))


def test_sitemap_filters_scope_and_sorts_by_lastmod():
    src = source("https://example.edu/sitemap.xml", "sitemap", allow_paths=("/students",))
    web = FakeWeb({src.canonical_url: httpx.Response(200, content=fixture("sitemap.xml"),
                                                     headers={"content-type": "application/xml"})})  # fmt: skip
    [obs] = SitemapAdapter().fetch(src, ctx_for(web))
    assert obs.links == ["https://example.edu/students/opportunities/b",
                         "https://example.edu/students/opportunities/a"]  # fmt: skip


def test_sitemap_index_followed_with_child_failure_recorded():
    idx = (b'<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
           b"<sitemap><loc>https://example.edu/s1.xml</loc></sitemap>"
           b"<sitemap><loc>https://example.edu/s2.xml</loc></sitemap></sitemapindex>")  # fmt: skip
    xml = {"content-type": "application/xml"}
    src = source("https://example.edu/sitemap.xml", "sitemap")
    web = FakeWeb({src.canonical_url: httpx.Response(200, content=idx, headers=xml),
                   "https://example.edu/s1.xml": httpx.Response(200, content=fixture("sitemap.xml"), headers=xml)})  # fmt: skip
    ctx = ctx_for(web)
    [obs] = SitemapAdapter().fetch(src, ctx)
    assert len(obs.links) == 2 and len(ctx.failures) == 1  # s2 -> 404 recorded, not fatal


def test_sitemap_blocks_entity_expansion():
    bomb = (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
            b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>&b;</loc></url></urlset>')  # fmt: skip
    with pytest.raises(Exception):  # noqa: B017 - defusedxml raises EntitiesForbidden
        parse_sitemap(bomb)


def test_html_adapter_applies_source_selectors_and_flags_them(tmp_path):
    page = (
        "<html><head><title>Careers</title></head><body><nav><a href='/about'>About</a></nav>"
        "<main><h1>Jobs</h1><ul class='j'><li><a href='/job/a/'>A</a></li></ul>"
        "<p>Deadline 1 March 2027 for the research internship.</p></main></body></html>"
    )
    src = source(
        extraction_hints={"selectors": {"links": {"css": "ul.j a"}, "text": {"css": "main"}}}
    )
    web = FakeWeb({src.canonical_url: html(page.encode())})
    ctx = ctx_for(web)
    ctx.selector_storage = tmp_path / "sel.sqlite3"
    [obs] = HtmlAdapter().fetch(src, ctx)
    assert obs.links == ["https://example.edu/job/a/"]  # nav link excluded, absolute, canonical
    assert "Deadline 1 March 2027" in obs.text and "About" not in obs.text
    assert obs.meta["selectors"] == "ok"


def test_html_adapter_selector_miss_is_a_parse_error():
    src = source(extraction_hints={"selectors": {"text": {"css": "div.missing"}}})
    web = FakeWeb({src.canonical_url: html(b"<html><body><p>hi</p></body></html>")})
    with pytest.raises(ParseError):
        HtmlAdapter().fetch(src, ctx_for(web))
