"""Official machine-readable channels: iCal, JSON Feed, and JS-shell classification."""

import json

import httpx
import pytest
from tests.helpers import FakeWeb, html, make_fetcher
from tests.integration.test_adapters import ctx_for, source

from open_hypergamy.discovery.candidates import drafts_from_observation
from open_hypergamy.errors import ParseError, RenderingRequired
from open_hypergamy.sources.barriers import detect_js_shell
from open_hypergamy.sources.ical import IcalAdapter, parse_events
from open_hypergamy.sources.json_feed import JsonFeedAdapter
from open_hypergamy.sources.policy import Scope

ICS_URL = "https://example.edu/students/events.ics"
ICS = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Example//EN\r\n"
    "BEGIN:VEVENT\r\nUID:ss-2027@example.edu\r\nDTSTART;VALUE=DATE:20270610\r\n"
    "SUMMARY:Robotics Summer School 2027\r\n"
    "DESCRIPTION:Applications open on 1 January 2027 and close on 15 March 2027.\\n\r\n"
    " Travel grants are available.\r\n"
    "URL:https://example.edu/students/opportunities/summer-school\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nUID:no-url\r\nSUMMARY:Open day\r\nEND:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)
JSON_URL = "https://example.edu/students/feed.json"
JSON_FEED = {
    "version": "https://jsonfeed.org/version/1.1",
    "title": "Example",
    "items": [
        {
            "id": "1",
            "url": "https://example.edu/students/opportunities/summer-school",
            "title": "Robotics Summer School 2027",
            "content_html": "<p>Applications close on <b>15 March 2027</b>.</p>",
            "date_published": "2026-10-20T10:00:00Z",
        },
        {"id": "2", "title": "No link"},
        "garbage",
    ],
}


def resp(body, ctype):
    return httpx.Response(200, content=body, headers={"content-type": ctype})


def test_ical_events_become_feed_entries_and_event_dates_stay_hints():
    web = FakeWeb({ICS_URL: resp(ICS.encode(), "text/calendar")})
    src = source(ICS_URL, adapter="ical")
    [obs] = IcalAdapter().fetch(src, ctx_for(web))
    assert [e.title for e in obs.entries] == ["Robotics Summer School 2027", "Open day"]
    first = obs.entries[0]
    assert first.published == "20270610" and first.entry_id == "ss-2027@example.edu"
    assert "close on 15 March 2027.\nTravel grants" in first.summary.replace("\n\n", "\n")
    assert obs.entries[1].link is None and obs.links == [first.link]
    drafts = drafts_from_observation(src, obs, None)
    assert [d.kind for d in drafts] == ["feed_entry"] and drafts[0].method == "feed_metadata"


def test_ical_rejects_non_calendars_and_unfolds_lines():
    with pytest.raises(ParseError):
        parse_events("<html>hello</html>")
    assert (
        parse_events(
            "BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:Long\n  title\nEND:VEVENT\nEND:VCALENDAR"
        )[0]["SUMMARY"]
        == "Long title"
    )


def test_json_feed_items_become_entries():
    web = FakeWeb({JSON_URL: resp(json.dumps(JSON_FEED).encode(), "application/feed+json")})
    src = source(JSON_URL, adapter="json_feed")
    [obs] = JsonFeedAdapter().fetch(src, ctx_for(web))
    assert [e.title for e in obs.entries] == ["Robotics Summer School 2027", "No link"]
    assert "15 March 2027" in obs.entries[0].summary and obs.entries[1].link is None
    assert drafts_from_observation(src, obs, None)[0].method == "feed_metadata"


@pytest.mark.parametrize("body", [b"not json", b'{"version": "other"}', b"[1,2]"])
def test_json_feed_rejects_other_documents(body):
    web = FakeWeb({JSON_URL: resp(body, "application/json")})
    with pytest.raises(ParseError):
        JsonFeedAdapter().fetch(source(JSON_URL, adapter="json_feed"), ctx_for(web))


SHELL = (
    b'<html><head><title>App</title><script src="/a.js"></script></head>'
    b'<body><div id="root"></div><noscript>You need to enable JavaScript.</noscript></body></html>'
)


def test_js_shell_detection_is_conservative():
    assert "JavaScript application shell" in detect_js_shell("text/html", SHELL)
    assert detect_js_shell("application/rss+xml", SHELL) is None
    real = (
        b"<html><head><script src=a.js></script></head><body><div id=root></div><p>"
        + b"word " * 80
        + b"</p></body></html>"
    )
    assert detect_js_shell("text/html", real) is None  # real content next to a script
    no_script = b"<html><body><div id='root'></div></body></html>"
    assert detect_js_shell("text/html", no_script) is None
    plain_short = b"<html><body><script>1</script><p>Closed.</p></body></html>"
    assert detect_js_shell("text/html", plain_short) is None  # short but no shell signal


def test_fetcher_raises_rendering_required_without_retrying_or_executing_anything():
    url = "https://example.edu/students/opportunities"
    web = FakeWeb({url: html(SHELL)})
    f, sleeps = make_fetcher(web)
    with pytest.raises(RenderingRequired) as e:
        f.fetch(url, Scope(("example.edu",)))
    assert e.value.code == "rendering_required" and not e.value.retryable
    assert web.urls.count(url) == 1 and sleeps == []
