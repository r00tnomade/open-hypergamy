import json
from datetime import UTC, datetime

import pytest
from tests.helpers import FakeWeb, fixture, html, make_fetcher

from open_hypergamy.clock import FixedClock
from open_hypergamy.config import load_config
from open_hypergamy.discovery import orchestrator as orch
from open_hypergamy.discovery import review as review_svc
from open_hypergamy.discovery.pipeline import promote_from_db
from open_hypergamy.errors import OhgError
from open_hypergamy.persistence import db as dbm
from open_hypergamy.persistence import migrations as mig
from open_hypergamy.persistence.repositories.sources import SourceRepository
from open_hypergamy.sources.registry import load_source_files

CLOCK = FixedClock(datetime(2026, 10, 29, 12, 0, tzinfo=UTC))
PAGE_A, PAGE_B = "https://example.edu/summer-school-2027", "https://summerschool-example.org/2027"

YAML = """
version: 1
sources:
  - source_key: example-a
    name: Example A
    organization: {name: Example Institute, canonical_domain: example.edu}
    canonical_url: %s
    domain: example.edu
    source_type: official_programme_page
    adapter_type: html
    trust_tier: t1_official_program
    robots_policy_checked_at: 2026-10-01
    terms_review_note: reviewed
  - source_key: example-b
    name: Example B
    organization: {name: Example Institute, canonical_domain: example.edu}
    canonical_url: %s
    domain: summerschool-example.org
    source_type: official_programme_page
    adapter_type: html
    trust_tier: t1_official_program
    robots_policy_checked_at: 2026-10-01
    terms_review_note: reviewed
""" % (PAGE_A, PAGE_B)


@pytest.fixture
def env(tmp_path):
    cfg = load_config(home=tmp_path / "home", env={})
    cfg.paths.ensure()
    conn = dbm.connect(cfg.paths.db, create=True)
    mig.migrate(conn, mig.discover(), CLOCK)
    y = tmp_path / "s.yaml"
    y.write_text(YAML)
    SourceRepository(conn, CLOCK).import_configs(load_source_files([y]))
    yield cfg, conn
    conn.close()


def run(env, web):
    cfg, conn = env
    fetcher, _ = make_fetcher(web)
    return orch.run_discovery(conn, cfg, fetcher, CLOCK)


def rows(conn, sql, *a):
    return conn.execute(sql, a).fetchall()


def two_publishers(env, close_b=b"20 March 2027"):
    page_b = fixture("programme.html").replace(b"15 March 2027", close_b)
    run(env, FakeWeb({PAGE_A: html(fixture("programme.html")), PAGE_B: html(page_b)}))


def test_conflicting_official_sources_preserve_both_claims_and_flag(env):
    two_publishers(env)
    conn = env[1]
    assert (
        len(rows(conn, "SELECT 1 FROM editions")) == 1
        and len(rows(conn, "SELECT 1 FROM programs")) == 1
    )
    [close] = rows(conn, "SELECT * FROM deadlines WHERE deadline_type='application_close'")
    assert close["fact_status"] == "conflicting_sources" and close["due_date_local"] == "2027-03-15"
    values = {
        json.loads(c["proposed_value_json"])["date"]
        for c in rows(conn, "SELECT * FROM claims WHERE deadline_id=?", close["id"])
    }
    assert values == {"2027-03-15", "2027-03-20"}  # neither silently chosen nor discarded
    [rev] = rows(conn, "SELECT * FROM review_queue WHERE reason_code='deadline_conflict'")
    assert rev["priority"] == "critical" and rev["state"] == "pending"
    [ed] = rows(conn, "SELECT * FROM editions")
    assert ed["fact_status"] == "conflicting_sources" and ed["application_status"] == "conflicting"


def test_same_dates_from_two_publishers_corroborate_without_conflict(env):
    two_publishers(env, close_b=b"15 March 2027")
    conn = env[1]
    [close] = rows(conn, "SELECT * FROM deadlines WHERE deadline_type='application_close'")
    assert close["fact_status"] == "confirmed_official"
    assert len(rows(conn, "SELECT 1 FROM claims WHERE deadline_id=?", close["id"])) == 2
    assert not rows(conn, "SELECT 1 FROM review_queue WHERE reason_code LIKE '%conflict'")


def test_accept_cannot_settle_a_conflict_and_resolve_requires_an_official_claim(env):
    two_publishers(env)
    cfg, conn = env
    [rev] = rows(conn, "SELECT * FROM review_queue WHERE reason_code='deadline_conflict'")
    with pytest.raises(OhgError, match="resolve"):
        review_svc.decide(conn, CLOCK, rev["id"], accept=True, note="looks fine")
    with pytest.raises(OhgError, match="official"):
        review_svc.resolve_conflict(conn, CLOCK, rev["id"], claim_id="nope", note="x")
    chosen = rows(
        conn,
        "SELECT c.id FROM claims c JOIN deadlines d ON d.id=c.deadline_id WHERE "
        "d.deadline_type='application_close' AND c.proposed_value_json LIKE '%2027-03-20%'",
    )[0][0]
    review_svc.resolve_conflict(conn, CLOCK, rev["id"], claim_id=chosen, note="B is the organiser")
    [close] = rows(conn, "SELECT * FROM deadlines WHERE deadline_type='application_close'")
    assert close["due_date_local"] == "2027-03-20" and close["fact_status"] == "confirmed_official"
    assert rows(conn, "SELECT state FROM review_queue WHERE id=?", rev["id"])[0][0] == "accepted"
    assert rows(conn, "SELECT fact_status FROM editions")[0][0] == "confirmed_official"


def test_accepting_a_review_never_changes_fact_status(env):
    cfg, conn = env
    page = fixture("programme.html").replace(b"close on 15 March 2027", b"close on 15 March")
    run(env, FakeWeb({PAGE_A: html(page), PAGE_B: html(page)}))
    [rev, *_] = rows(conn, "SELECT * FROM review_queue WHERE reason_code='missing_year'")
    before = rows(conn, "SELECT fact_status FROM claims WHERE id=?", rev["claim_id"])[0][0]
    review_svc.decide(conn, CLOCK, rev["id"], accept=True, note="I checked the site by hand")
    after = rows(conn, "SELECT fact_status, reviewed_at FROM claims WHERE id=?", rev["claim_id"])[0]
    assert before == after[0] == "unverified" and after[1] is not None
    with pytest.raises(OhgError, match="already"):
        review_svc.decide(conn, CLOCK, rev["id"], accept=True, note="again")


def test_event_date_conflict_between_publishers(env):
    page_b = fixture("programme.html").replace(b"10 to 14 June 2027", b"11 to 15 June 2027")
    run(env, FakeWeb({PAGE_A: html(fixture("programme.html")), PAGE_B: html(page_b)}))
    conn = env[1]
    [ed] = rows(conn, "SELECT * FROM editions")
    assert ed["event_start_date"] == "2027-06-10"  # first confirmed value kept, not overwritten
    assert rows(conn, "SELECT 1 FROM review_queue WHERE reason_code='event_date_conflict'")
    assert ed["fact_status"] == "conflicting_sources"


def test_similar_programme_name_is_held_not_merged(env):
    cfg, conn = env
    run(
        env,
        FakeWeb(
            {
                PAGE_A: html(fixture("programme.html")),
                PAGE_B: html(b"<html><title>x</title></html>"),
            }
        ),
    )
    other = (
        fixture("programme.html")
        .replace(b"Robotics Summer School 2027", b"Robotics Summers School 2028")
        .replace(b"2027", b"2028")
    )
    conn.execute("UPDATE sources SET enabled=0 WHERE source_key='example-b'")
    conn.execute("UPDATE sources SET next_due_at=NULL")
    conn.execute("UPDATE candidates SET status='promoted'")
    web = FakeWeb({PAGE_A: html(other)})
    s = run(env, web)
    assert s.pipeline.needs_review == 1 and len(rows(conn, "SELECT 1 FROM programs")) == 1
    [rev] = rows(conn, "SELECT * FROM review_queue WHERE reason_code='possible_duplicate_program'")
    assert rev["candidate_id"] and "Robotics Summer School" in rev["details"]
    cand = rows(conn, "SELECT * FROM candidates WHERE id=?", rev["candidate_id"])[0]
    assert cand["status"] == "needs_review"
    out = promote_from_db(conn, cfg, CLOCK, cand["id"], new_program=True)  # reviewer says: distinct
    assert out.status == "promoted" and len(rows(conn, "SELECT 1 FROM programs")) == 2


def test_unknown_edition_key_is_held_until_supplied(env):
    cfg, conn = env
    page = (
        b"<html><head><title>Robotics Summer School</title></head><body><p>"
        + (
            b"Join our summer school for robotics students. Applications are welcome from all "
            b"universities and we offer lectures, labs and projects for two weeks. "
        )
        * 2
        + b"</p></body></html>"
    )
    undated = {
        "https://example.edu/summer-school": "example-a",
        "https://summerschool-example.org/school": "example-b",
    }  # no year anywhere in the URL
    for url, key in undated.items():
        conn.execute("UPDATE sources SET canonical_url=? WHERE source_key=?", (url, key))
    s = run(env, FakeWeb({u: html(page) for u in undated}))
    assert s.pipeline.promoted == 0 and s.pipeline.needs_review >= 1
    assert not rows(conn, "SELECT 1 FROM editions")
    [rev, *_] = rows(conn, "SELECT * FROM review_queue WHERE reason_code='edition_key_unknown'")
    out = promote_from_db(conn, cfg, CLOCK, rev["candidate_id"], edition_key="2027")
    assert out.status == "promoted"
    assert rows(conn, "SELECT edition_key FROM editions")[0][0] == "2027"
