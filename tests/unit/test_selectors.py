import pytest

from open_hypergamy.errors import ConfigurationError, ParseError
from open_hypergamy.extraction.selectors import apply_selectors, parse_hints

URL = "https://example.edu/jobs/"
PAGE = """<html><body><main><h1>Open positions</h1>
<ul class="jobs"><li><a href="/job/a/">Role A</a></li><li><a href="/job/b/">Role B</a></li></ul>
<p class="x">Apply by 1 March 2027</p></main><footer><a href="/privacy">Privacy</a></footer></body></html>"""
MOVED = """<html><body><section><div class="listing"><li><a href="/job/a/">Role A</a></li>
<li><a href="/job/b/">Role B</a></li></div><h1>Open positions</h1></section></body></html>"""


def hints(**sel):
    return parse_hints({"selectors": sel})


def test_no_selectors_means_none():
    assert parse_hints({}) is None and parse_hints({"other": 1}) is None


@pytest.mark.parametrize(
    "bad",
    [
        {},  # nothing selected
        {"title": {}},  # neither css nor xpath
        {"title": {"css": "h1", "xpath": "//h1"}},  # both
        {"title": {"css": "h1"}, "bogus": 1},  # unknown key
    ],
)
def test_invalid_hints_are_rejected(bad):
    with pytest.raises(ConfigurationError):
        parse_hints({"selectors": bad})


def test_css_and_xpath_extraction():
    h = hints(title={"css": "h1"}, text={"css": "main"}, links={"xpath": "//ul[@class='jobs']//a"})
    r = apply_selectors(PAGE, url=URL, hints=h, source_key="s", storage_file=None)
    assert r.title == "Open positions" and "Apply by 1 March 2027" in (r.text or "")
    assert r.link_hrefs == ["/job/a/", "/job/b/"] and r.relocated == ()
    assert "Privacy" not in (r.text or "")  # footer excluded: that is the point of a selector


def test_container_selector_yields_its_anchors():
    r = apply_selectors(
        PAGE, url=URL, hints=hints(links={"css": "ul.jobs"}), source_key="s", storage_file=None
    )
    assert r.link_hrefs == ["/job/a/", "/job/b/"]


def test_a_selector_that_matches_nothing_is_a_parse_error_not_an_empty_scan():
    with pytest.raises(ParseError, match="matched nothing"):
        apply_selectors(
            PAGE, url=URL, hints=hints(text={"css": "div.gone"}), source_key="s", storage_file=None
        )


def test_adaptive_relocates_after_markup_change(tmp_path):
    db = tmp_path / "sel.sqlite3"
    h = hints(adaptive=True, links={"css": "ul.jobs a"})
    first = apply_selectors(PAGE, url=URL, hints=h, source_key="s", storage_file=db)
    assert first.relocated == () and db.exists()
    second = apply_selectors(MOVED, url=URL, hints=h, source_key="s", storage_file=db)
    assert second.relocated == ("links",) and second.link_hrefs  # best-effort, flagged
    assert "/job/a/" in second.link_hrefs


def test_without_storage_adaptive_is_off_and_a_miss_still_fails(tmp_path):
    h = hints(adaptive=True, links={"css": "ul.jobs a"})
    with pytest.raises(ParseError):
        apply_selectors(MOVED, url=URL, hints=h, source_key="s", storage_file=None)


def test_adaptive_without_a_saved_fingerprint_fails_instead_of_guessing(tmp_path):
    h = hints(adaptive=True, links={"css": "ul.jobs a"})
    with pytest.raises(ParseError):
        apply_selectors(
            MOVED, url=URL, hints=h, source_key="never-seen", storage_file=tmp_path / "new.sqlite3"
        )
