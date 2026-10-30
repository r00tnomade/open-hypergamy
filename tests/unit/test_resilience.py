"""Alternatives, permission requests, newsletter import and recall measurement (ADR-013)."""

import json
import sqlite3
from datetime import UTC, datetime

import pytest
from tests.integration.test_adapters import source
from typer.testing import CliRunner

from open_hypergamy.cli import app
from open_hypergamy.config import load_config
from open_hypergamy.errors import ConfigurationError
from open_hypergamy.resilience import alternatives, newsletter, permission, recall

runner = CliRunner()

PAGE = """<html><head>
<link rel="alternate" type="application/rss+xml" href="/students/feed.xml">
<link rel="alternate" type="text/calendar" href="https://example.edu/cal/events.ics">
<link rel="alternate" type="application/rss+xml" href="https://elsewhere.example.org/feed">
<link rel="stylesheet" href="/s.css"></head>
<body><a href="/students/calendar">Calendar</a><a href="/about">About</a>
<a href="https://other.example.org/feed.rss">Other site feed</a></body></html>"""


def test_alternatives_only_from_the_publishers_own_site():
    found = alternatives.from_cached_page(
        source(), PAGE, "https://example.edu/students/opportunities"
    )
    got = {(a.kind, a.adapter_type, a.url) for a in found}
    assert ("declared_feed", "rss_atom", "https://example.edu/students/feed.xml") in got
    assert ("declared_feed", "ical", "https://example.edu/cal/events.ics") in got
    assert ("linked_channel", "ical", "https://example.edu/students/calendar") in got
    assert not any("elsewhere" in a.url or "other.example" in a.url for a in found)
    assert all("unverified" in a.note for a in found)


def test_permission_request_states_pacing_identity_and_allowlist_addresses(tmp_path):
    cfg = load_config(home=tmp_path / "h", env={"OHG_CRAWLER_CONTACT": "ops@example.org"})
    text = permission.render_request(cfg, source(), {"edge1": ["198.51.100.10"]})
    for needle in ("every 168 hours", "one request per 3 s", "OpenHypergamy/0.1",
                   "198.51.100.10", "no login, CAPTCHA or paywall bypass", "ops@example.org"):  # fmt: skip
        assert needle in text
    assert "rotating identities" in text and "allowlist" in text


def test_egress_ips_must_be_public_addresses():
    from tests.helpers_egress import profile

    assert profile("p1", egress_ips=["93.184.216.34"]).egress_ips == ["93.184.216.34"]
    for bad in ("10.0.0.1", "not-an-ip", "169.254.169.254"):
        with pytest.raises(ValueError, match="public IP"):
            profile("p1", egress_ips=[bad])


EML = (
    b"From: news@example.edu\nSubject: Opportunities\nMIME-Version: 1.0\n"
    b'Content-Type: text/html; charset="utf-8"\n\n'
    b'<p><a href="https://example.edu/students/summer-school-2027?utm_source=nl">'
    b"Robotics Summer School 2027</a> <a href='https://example.edu/unsubscribe?u=1'>unsubscribe</a>"
    b' <a href="https://example.edu/about">About us</a>'
    b' <a href="https://example.edu/fellowship-call-2027">Fellowship call</a></p>'
)


def test_newsletter_leads_are_opportunity_links_without_tracking_or_unsubscribe():
    leads = newsletter.extract_leads(EML)
    assert [x.url for x in leads] == [
        "https://example.edu/students/summer-school-2027",
        "https://example.edu/fellowship-call-2027",
    ]
    assert leads[0].text == "Robotics Summer School 2027"


def test_plain_text_newsletter_and_lead_cap():
    text = "Hi\nApply to the Summer School 2027: https://example.edu/summer-school-2027.\nBye"
    assert [x.url for x in newsletter.extract_leads(text.encode())] == [
        "https://example.edu/summer-school-2027"
    ]
    many = "\n".join(f"Summer school https://example.edu/summer-school-{i}" for i in range(80))
    assert len(newsletter.extract_leads(many.encode())) == newsletter.MAX_LEADS


# -- recall ---------------------------------------------------------------------------------------


def make_db(urls_fps):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE sources(id TEXT, adapter_type TEXT);"
        "CREATE TABLE candidates(canonical_url TEXT, normalized_fingerprint TEXT, "
        "discovered_by_source_id TEXT, first_seen_at TEXT, id TEXT);"
        "INSERT INTO sources VALUES ('s1','rss_atom'),('s2','html');"
    )
    for i, (url, fp, sid) in enumerate(urls_fps):
        conn.execute(
            "INSERT INTO candidates VALUES (?,?,?,?,?)", (url, fp, sid, f"t{i:04d}", f"c{i}")
        )
    return conn


def truth(n, **kw):
    items = [
        {"title": f"Summer School {i} 2027", "url": f"https://example.edu/ss-{i}"} for i in range(n)
    ]
    return recall.TruthSet(id="t", opportunities=items, **kw)


def test_recall_counts_any_channel_and_matches_by_url_or_identity():
    from open_hypergamy.discovery.normalize import fingerprint

    fp = fingerprint("Summer School 1 2027", "example.edu", "2027")
    conn = make_db(
        [("https://example.edu/ss-0", "x", "s1"), ("https://example.edu/other", fp, None)]
    )
    rep = recall.measure(conn, truth(3))
    assert (rep.captured, rep.n) == (2, 3) and rep.missed == ["Summer School 2 2027"]
    assert rep.by_channel == {"rss_atom": 1, "manual": 1}


def test_wilson_interval_values():
    low, high = recall.wilson_interval(100, 100)
    assert low == pytest.approx(0.9630, abs=1e-3) and high == 1.0
    low, _ = recall.wilson_interval(194, 200)
    assert low == pytest.approx(0.9361, abs=1e-3)


def attested(n):
    return truth(n, independent=True, compiled_by="auditor", method="manual review of 12 portals")


def captured_db(n, k):
    return make_db([(f"https://example.edu/ss-{i}", f"f{i}", "s1") for i in range(k)])


def test_verdicts_never_claim_the_target_without_attested_evidence_and_sample():
    assert recall.measure(captured_db(10, 10), truth(10)).verdict.startswith("UNVERIFIED")
    assert recall.measure(captured_db(50, 50), attested(50)).verdict.startswith("INSUFFICIENT")
    # perfect recall on exactly 100 items still cannot demonstrate 97 %: lower bound is 96.3 %
    assert recall.measure(captured_db(100, 100), attested(100)).verdict.startswith(
        "NOT DEMONSTRATED"
    )
    assert recall.measure(captured_db(300, 300), attested(300)).verdict.startswith("CONSISTENT")
    assert recall.measure(captured_db(300, 280), attested(300)).verdict.startswith(
        "NOT DEMONSTRATED"
    )


def test_truth_loading_errors_do_not_dump_input(tmp_path):
    bad = tmp_path / "t.yaml"
    bad.write_text("truth_set:\n  id: x\n  opportunities: []\n")
    with pytest.raises(ConfigurationError, match="no opportunities"):
        recall.load_truth(bad)
    with pytest.raises(ConfigurationError):
        recall.load_truth(tmp_path / "missing.yaml")


# -- CLI ----------------------------------------------------------------------------------------------


def test_cli_recall_and_newsletter_dry_run(tmp_path):
    runner.invoke(app, ["init"])
    t = tmp_path / "truth.yaml"
    t.write_text(
        "truth_set:\n  id: audit-1\n  opportunities:\n    - {title: Summer School 2027, url: https://example.edu/ss}\n"
    )
    r = runner.invoke(app, ["measure", "recall", "--truth", str(t), "--json"])
    assert r.exit_code == 0, r.output
    data = json.loads(r.stdout)
    assert data["captured"] == 0 and data["verdict"].startswith("UNVERIFIED")
    assert data["missed"] == ["Summer School 2027"]
    nl = tmp_path / "n.eml"
    nl.write_bytes(EML)
    r2 = runner.invoke(app, ["import", "newsletter", str(nl), "--dry-run"])
    assert r2.exit_code == 0 and "2 opportunity link(s)" in r2.output
    r3 = runner.invoke(app, ["sources", "permission-request", "nope"])
    assert r3.exit_code == 2


_ = datetime, UTC
