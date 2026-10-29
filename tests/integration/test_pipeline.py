import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from tests.helpers import FakeWeb, fixture, html, make_fetcher

from open_hypergamy.clock import FixedClock
from open_hypergamy.config import load_config
from open_hypergamy.discovery import orchestrator as orch
from open_hypergamy.discovery.pipeline import promote_from_db
from open_hypergamy.persistence import db as dbm
from open_hypergamy.persistence import migrations as mig
from open_hypergamy.persistence.repositories.opportunities import OpportunityRepository
from open_hypergamy.persistence.repositories.sources import SourceRepository
from open_hypergamy.sources.registry import load_source_files

SEED = "https://example.edu/students/opportunities"
CHILD = "https://example.edu/students/opportunities/summer-school"
GOOD = Path(__file__).parent.parent / "fixtures" / "sources_good.yaml"


class MovableClock(FixedClock):
    def advance(self, **kw):
        self._now += timedelta(**kw)


@pytest.fixture
def env(tmp_path):
    clock = MovableClock(datetime(2026, 10, 29, 12, 0, tzinfo=UTC))
    cfg = load_config(home=tmp_path / "home", env={})
    cfg.paths.ensure()
    conn = dbm.connect(cfg.paths.db, create=True)
    mig.migrate(conn, mig.discover(), clock)
    SourceRepository(conn, clock).import_configs(load_source_files([GOOD]))
    yield cfg, conn, clock
    conn.close()


def run(env, web, **kw):
    cfg, conn, clock = env
    fetcher, _ = make_fetcher(web)
    return orch.run_discovery(conn, cfg, fetcher, clock, **kw)


def web_with(programme=None):
    return FakeWeb(
        {SEED: html(fixture("index.html")), CHILD: html(programme or fixture("programme.html"))}
    )


def rows(conn, sql, *a):
    return conn.execute(sql, a).fetchall()


def test_official_page_becomes_edition_with_confirmed_deadline_and_evidence(env):
    cfg, conn, clock = env
    s = run(env, web_with())
    assert s.pipeline.created == 1 and s.pipeline.promoted == 1
    [ed] = rows(conn, "SELECT * FROM editions")
    assert ed["edition_key"] == "2027" and ed["display_name"] == "Robotics Summer School 2027"
    assert ed["event_start_date"] == "2027-06-10" and ed["event_end_date"] == "2027-06-14"
    assert (ed["fact_status"], ed["application_status"], ed["lifecycle_status"]) == (
        "confirmed_official",
        "not_open",
        "announced",
    )  # opens 1 Jan 2027; today is Oct 2026
    d = {r["deadline_type"]: r for r in rows(conn, "SELECT * FROM deadlines")}
    assert d["application_close"]["due_date_local"] == "2027-03-15"
    assert d["application_close"]["fact_status"] == "confirmed_official"
    assert d["application_close"]["raw_date_text"] == "15 March 2027"
    assert (
        d["application_close"]["time_precision"] == "date_only"
        and d["application_close"]["due_at_utc"] is None
    )
    assert d["application_open"]["due_date_local"] == "2027-01-01"
    assert d["abstract_submission"]["due_date_local"] == "2027-05-01"
    # every critical confirmed fact has a grounded excerpt on the official URL, tied to an observation
    for c in rows(conn, "SELECT * FROM claims WHERE fact_status='confirmed_official'"):
        assert c["excerpt"] and c["source_url"] == CHILD and c["source_observation_id"]
        assert c["extraction_method"] == "rule" and c["source_trust_tier"] == "t2_official_org"
    close_claim = rows(
        conn,
        "SELECT c.* FROM claims c JOIN deadlines d ON d.id=c.deadline_id "
        "WHERE d.deadline_type='application_close'",
    )[0]
    assert "close on 15 March 2027" in close_claim["excerpt"]
    # candidate traces to the observation that introduced it
    [cand] = rows(conn, "SELECT * FROM candidates")
    assert cand["status"] == "promoted" and cand["promoted_edition_id"] == ed["id"]
    assert rows(
        conn, "SELECT 1 FROM source_observations WHERE id=?", cand["discovered_from_observation_id"]
    )


def test_rerun_with_same_content_creates_nothing_new(env):
    cfg, conn, clock = env
    run(env, web_with())
    counts = {
        t: len(rows(conn, f"SELECT 1 FROM {t}"))
        for t in ("candidates", "editions", "programs", "deadlines", "claims")
    }
    clock.advance(days=8)
    run(env, web_with())
    assert counts == {t: len(rows(conn, f"SELECT 1 FROM {t}")) for t in counts}


def test_year_missing_deadline_is_review_not_confirmed(env):
    page = fixture("programme.html").replace(b"close on 15 March 2027", b"close on 15 March")
    run(env, web_with(page))
    d = {r["deadline_type"]: r for r in rows(env[1], "SELECT * FROM deadlines")}
    assert "application_close" not in d  # no row invented from an ambiguous mention
    claim = rows(env[1], "SELECT * FROM claims WHERE field_name='deadline:application_close'")[0]
    assert (
        claim["fact_status"] == "unverified"
        and json.loads(claim["proposed_value_json"])["date"] is None
    )
    [rev] = rows(env[1], "SELECT * FROM review_queue WHERE reason_code='missing_year'")
    assert (
        rev["state"] == "pending" and rev["priority"] == "high" and rev["claim_id"] == claim["id"]
    )
    [ed] = rows(env[1], "SELECT * FROM editions")
    assert ed["fact_status"] != "confirmed_official"


def test_ambiguous_numeric_date_cannot_confirm(env):
    page = fixture("programme.html").replace(b"close on 15 March 2027", b"close on 05/06/2027")
    run(env, web_with(page))
    assert not rows(env[1], "SELECT 1 FROM deadlines WHERE deadline_type='application_close'")
    assert rows(env[1], "SELECT 1 FROM review_queue WHERE reason_code='ambiguous_numeric_format'")


def test_two_different_close_dates_on_one_page_confirm_neither(env):
    page = fixture("programme.html").replace(
        b"Please prepare", b"Application deadline: 1 April 2027. Please prepare"
    )
    run(env, web_with(page))
    closes = rows(env[1], "SELECT * FROM deadlines WHERE deadline_type='application_close'")
    assert all(r["fact_status"] != "confirmed_official" for r in closes)
    assert rows(env[1], "SELECT 1 FROM review_queue WHERE reason_code='multiple_dates_for_field'")


def test_chronology_violation_demotes_and_flags(env):
    page = fixture("programme.html").replace(b"close on 15 March 2027", b"close on 15 July 2027")
    run(env, web_with(page))  # closes after the event (10-14 June 2027)
    d = {r["deadline_type"]: r for r in rows(env[1], "SELECT * FROM deadlines")}
    assert d["application_close"]["fact_status"] == "unverified"
    assert rows(env[1], "SELECT 1 FROM review_queue WHERE reason_code='chronology_invalid'")
    [ed] = rows(env[1], "SELECT * FROM editions")
    assert ed["fact_status"] != "confirmed_official"


def test_official_deadline_change_updates_value_keeps_history(env):
    cfg, conn, clock = env
    run(env, web_with())
    clock.advance(days=8)
    changed = fixture("programme.html").replace(b"15 March 2027", b"1 March 2027")
    run(env, web_with(changed))
    [close] = rows(conn, "SELECT * FROM deadlines WHERE deadline_type='application_close'")
    assert close["due_date_local"] == "2027-03-01" and close["fact_status"] == "confirmed_official"
    claims = rows(conn, "SELECT proposed_value_json FROM claims WHERE deadline_id=?", close["id"])
    assert {json.loads(c[0])["date"] for c in claims} == {"2027-03-15", "2027-03-01"}  # both kept
    assert rows(conn, "SELECT last_material_change_at FROM editions")[0][0] is not None


def test_feed_entry_is_lead_until_official_page_is_followed(env):
    cfg, conn, clock = env
    feed = (
        b'<?xml version="1.0"?><rss version="2.0"><channel><title>News</title><item>'
        b"<title>Robotics Summer School 2027 announced</title><link>" + CHILD.encode() + b"</link>"
        b"<description>Applications close 15 March 2027.</description></item></channel></rss>"
    )
    conn.execute(
        "UPDATE sources SET adapter_type='rss_atom', canonical_url=?",
        ("https://example.edu/feed.xml",),
    )
    web = FakeWeb({"https://example.edu/feed.xml": httpx.Response(200, content=feed, headers={"content-type": "application/rss+xml"}),
                   CHILD: html(fixture("programme.html"))})  # fmt: skip
    s = run(env, web)
    assert s.pipeline.followed == 1 and s.pipeline.promoted == 1
    close = rows(conn, "SELECT * FROM deadlines WHERE deadline_type='application_close'")[0]
    assert close["fact_status"] == "confirmed_official"
    # confirmation came from the fetched official page, not from the feed's own summary
    confirmed = rows(
        conn,
        "SELECT source_url, extraction_method FROM claims WHERE fact_status='confirmed_official'",
    )
    assert confirmed and all(
        c["source_url"] == CHILD and c["extraction_method"] == "rule" for c in confirmed
    )


def test_feed_only_never_confirms_when_page_not_followable(env):
    cfg, conn, clock = env
    feed = (
        b'<?xml version="1.0"?><rss version="2.0"><channel><title>News</title><item>'
        b"<title>Robotics Summer School 2027 announced</title><link>https://example.edu/news/ss</link>"
        b"<description>Applications close 15 March 2027.</description></item></channel></rss>"
    )
    conn.execute(
        "UPDATE sources SET adapter_type='rss_atom', canonical_url=?, deny_paths_json='[\"/news\"]'",
        ("https://example.edu/feed.xml",),
    )
    web = FakeWeb(
        {
            "https://example.edu/feed.xml": httpx.Response(
                200, content=feed, headers={"content-type": "application/rss+xml"}
            )
        }
    )
    s = run(env, web)
    assert s.pipeline.created == 1 and s.pipeline.promoted == 0 and s.pipeline.leads == 1
    assert not rows(conn, "SELECT 1 FROM editions")
    [cand] = rows(conn, "SELECT * FROM candidates")
    assert cand["status"] == "new"
    # a manual promotion of the lead records feed hints but can never confirm them
    out = promote_from_db(conn, cfg, clock, cand["id"])
    assert out.status == "promoted"
    assert not rows(conn, "SELECT 1 FROM claims WHERE fact_status='confirmed_official'")
    d = rows(conn, "SELECT * FROM deadlines WHERE deadline_type='application_close'")[0]
    assert d["fact_status"] == "unverified"


def test_t4_aggregator_page_is_never_confirmed(env):
    cfg, conn, clock = env
    conn.execute("UPDATE sources SET trust_tier='t4_aggregator', discovery_only=1")
    run(env, web_with())
    assert not rows(conn, "SELECT 1 FROM claims WHERE fact_status='confirmed_official'")
    [cand] = rows(conn, "SELECT * FROM candidates")
    assert cand["status"] == "new"  # a lead, not auto-promoted


def test_duplicate_url_across_sources_does_not_duplicate_edition(env):
    cfg, conn, clock = env
    run(env, web_with())
    # a second source discovers the same page: no new candidate, programme or edition
    OpportunityRepository(conn, clock).upsert_candidate(
        source_id=None, observation_id=None, url=CHILD, title="Robotics Summer School 2027",
        normalized_title="x", organizer_domain="example.edu", category=None, edition_key="2027",
        fingerprint="other", metadata={})  # fmt: skip
    assert len(rows(conn, "SELECT 1 FROM candidates")) == 1
    assert len(rows(conn, "SELECT 1 FROM editions")) == 1


def test_different_years_are_separate_editions_of_one_programme(env):
    cfg, conn, clock = env
    run(env, web_with())
    clock.advance(days=8)
    y2028 = fixture("programme.html").replace(b"2027", b"2028")
    web = FakeWeb({SEED: html(fixture("index.html")), CHILD: html(y2028)})
    conn.execute("UPDATE candidates SET status='promoted'")
    # same URL: the page now describes 2028 -> treated as a new edition of the same programme
    run(env, web)
    assert len(rows(conn, "SELECT 1 FROM programs")) == 1
    keys = {r["edition_key"] for r in rows(conn, "SELECT edition_key FROM editions")}
    assert keys == {"2027", "2028"}
    d27 = rows(
        conn,
        "SELECT due_date_local FROM deadlines d JOIN editions e ON e.id=d.edition_id "
        "WHERE e.edition_key='2027' AND d.deadline_type='application_close'",
    )
    assert d27[0][0] == "2027-03-15"  # the 2027 edition's facts were not overwritten


def test_event_dates_ignored_as_deadlines(env):
    run(env, web_with())
    types = {r["deadline_type"] for r in rows(env[1], "SELECT deadline_type FROM deadlines")}
    assert types == {"application_open", "application_close", "abstract_submission"}
