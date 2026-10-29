import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from tests.helpers import FakeWeb, fixture, html, make_fetcher
from tests.helpers_llm import FakeGateway, empty_output, ev

from opportunity_radar.clock import FixedClock
from opportunity_radar.config import load_config
from opportunity_radar.discovery import orchestrator as orch
from opportunity_radar.discovery.pipeline import promote_from_db, run_llm_queue
from opportunity_radar.extraction.llm_extractor import build_llm_service
from opportunity_radar.llm.ack import write_ack
from opportunity_radar.llm.client import OpenAICompatClient
from opportunity_radar.persistence import db as dbm
from opportunity_radar.persistence import migrations as mig
from opportunity_radar.persistence.repositories.sources import SourceRepository
from opportunity_radar.sources.registry import load_source_files

CLOCK = FixedClock(datetime(2026, 10, 29, 12, 0, tzinfo=UTC))
SEED = "https://example.edu/students/opportunities"
CHILD = SEED + "/summer-school"
GOOD = Path(__file__).parent.parent / "fixtures" / "sources_good.yaml"


@pytest.fixture
def env(tmp_path):
    cfg = load_config(home=tmp_path / "home", env={"RADAR_FREELLMAPI_API_KEY": "k"})
    cfg.paths.ensure()
    conn = dbm.connect(cfg.paths.db, create=True)
    mig.migrate(conn, mig.discover(), CLOCK)
    SourceRepository(conn, CLOCK).import_configs(load_source_files([GOOD]))
    yield cfg, conn
    conn.close()


def web(programme=None):
    return FakeWeb(
        {SEED: html(fixture("index.html")), CHILD: html(programme or fixture("programme.html"))}
    )


def run(env, gw, w=None, ack=True):
    cfg, conn = env
    if ack:
        write_ack(cfg.paths.llm_ack, CLOCK, "freellmapi", "auto:radar-free")
    svc = build_llm_service(
        conn,
        cfg,
        CLOCK,
        client=OpenAICompatClient(
            "http://127.0.0.1:3001/v1", "auto:radar-free", "k", transport=gw.transport
        ),
    )
    fetcher, _ = make_fetcher(w or web())
    return orch.run_discovery(conn, cfg, fetcher, CLOCK, llm=svc), svc


def rows(conn, sql, *a):
    return conn.execute(sql, a).fetchall()


def rich(p):
    o = empty_output()
    q = "close on 15 March 2027"
    o["application_deadline"] = {"value": "2027-03-15", "raw_text": None, "timezone": None,
                                 "time_precision": "date_only", "evidence": ev(p, q)}  # fmt: skip
    o["event_start_date"] = {"value": "2027-06-10", "raw_text": None, "timezone": None,
                             "evidence": ev(p, "takes place from 10 to 14 June 2027")}  # fmt: skip
    o["format"] = {"value": "in_person", "evidence": ev(p, "is held in person")}
    o["location"] = {"value": "Berlin", "evidence": ev(p, "in Berlin")}
    o["funding"] = {"status": "partially_funded", "details": "travel grants",
                    "evidence": ev(p, "Travel grants are available")}  # fmt: skip
    o["eligibility_requirements"] = [{"requirement": "undergraduate students", "blocking": "unknown",
                                      "evidence": ev(p, "invites undergraduate students")}]  # fmt: skip
    return o


def test_llm_facts_are_recorded_but_can_never_confirm(env):
    cfg, conn = env
    gw = FakeGateway(rich)
    s, svc = run(env, gw)
    assert s.pipeline.llm_done == 1 and s.pipeline.promoted == 1
    llm_claims = rows(conn, "SELECT * FROM claims WHERE extraction_method='llm'")
    fields = {c["field_name"] for c in llm_claims}
    assert {
        "deadline:application_close",
        "event_start_date",
        "format",
        "location",
        "funding",
        "eligibility",
    } <= fields
    assert all(c["fact_status"] == "unverified" for c in llm_claims)  # invariant 1
    assert all(
        c["model_name"] == "routed-free-model" and c["prompt_version"] == "extract-v1"
        for c in llm_claims
    )
    # the deterministic, rule-grounded value is still what is confirmed
    [close] = rows(conn, "SELECT * FROM deadlines WHERE deadline_type='application_close'")
    assert close["fact_status"] == "confirmed_official"
    assert {
        c["extraction_method"]
        for c in rows(conn, "SELECT * FROM claims WHERE fact_status='confirmed_official'")
    } == {"rule"}
    meta = json.loads(rows(conn, "SELECT metadata_json FROM candidates")[0][0])
    assert meta["llm_state"] == "done"


def test_llm_alone_cannot_create_a_confirmed_fact(env):
    cfg, conn = env
    page = fixture("programme.html").replace(b"Applications open on 1 January 2027 and close on 15 March 2027.",
                                             b"Please send your documents until 15 March 2027.")  # fmt: skip

    def responder(p):
        o = empty_output()
        o["application_deadline"] = {"value": "2027-03-15", "raw_text": None, "timezone": None,
                                     "time_precision": "date_only",
                                     "evidence": ev(p, "send your documents until 15 March 2027")}  # fmt: skip
        return o

    run(env, FakeGateway(responder), web(page))
    [close] = rows(conn, "SELECT * FROM deadlines WHERE deadline_type='application_close'")
    assert close["due_date_local"] == "2027-03-15" and close["fact_status"] == "unverified"
    assert not rows(conn, "SELECT 1 FROM claims WHERE fact_status='confirmed_official' "
                          "AND extraction_method='llm'")  # fmt: skip
    ed = rows(conn, "SELECT fact_status FROM editions")[0][0]
    assert ed != "confirmed_official"


def test_hallucinated_claims_are_dropped_and_recorded(env):
    cfg, conn = env

    def responder(p):
        o = empty_output()
        o["application_deadline"] = {"value": "2027-04-01", "raw_text": None, "timezone": None,
                                     "time_precision": "date_only",
                                     "evidence": [{"segment_id": "s1", "quote": "Applications close on 1 April 2027."}]}  # fmt: skip
        return o

    run(env, FakeGateway(responder))
    assert not rows(conn, "SELECT 1 FROM claims WHERE extraction_method='llm'")
    meta = json.loads(rows(conn, "SELECT metadata_json FROM candidates")[0][0])
    assert meta["llm_rejected"] == ["deadline:application_close: quote_not_in_segment"]
    assert (
        rows(conn, "SELECT due_date_local FROM deadlines WHERE deadline_type='application_close'")[
            0
        ][0]
        == "2027-03-15"
    )


def test_llm_disagreement_flags_review_without_touching_confirmed_value(env):
    cfg, conn = env
    page = fixture("programme.html").replace(
        b"Please prepare", b"Selected candidates are notified on 20 April 2027. Please prepare"
    )

    def responder(p):
        o = empty_output()
        o["application_deadline"] = {"value": "2027-04-20", "raw_text": None, "timezone": None,
                                     "time_precision": "date_only",
                                     "evidence": ev(p, "notified on 20 April 2027")}  # fmt: skip
        return o

    run(env, FakeGateway(responder), web(page))
    [close] = rows(conn, "SELECT * FROM deadlines WHERE deadline_type='application_close'")
    assert close["due_date_local"] == "2027-03-15" and close["fact_status"] == "confirmed_official"
    assert rows(conn, "SELECT 1 FROM review_queue WHERE reason_code='unverified_source_disagrees'")


def test_gateway_down_queues_work_and_deterministic_pipeline_continues(env):
    cfg, conn = env
    gw = FakeGateway(lambda p: httpx.ConnectError("refused"))
    s, svc = run(env, gw)
    assert s.pipeline.promoted == 1 and s.pipeline.llm_queued == 1 and s.status == "success"
    assert (
        rows(conn, "SELECT fact_status FROM deadlines WHERE deadline_type='application_close'")[0][
            0
        ]
        == "confirmed_official"
    )
    meta = json.loads(rows(conn, "SELECT metadata_json FROM candidates")[0][0])
    assert meta["llm_state"] == "pending"
    # later: gateway healthy again -> `run llm` drains the queue and adds advisory claims
    gw2 = FakeGateway(rich)
    svc2 = build_llm_service(
        conn,
        cfg,
        CLOCK,
        client=OpenAICompatClient(
            "http://127.0.0.1:3001/v1", "auto:radar-free", "k", transport=gw2.transport
        ),
    )
    stats = run_llm_queue(conn, cfg, CLOCK, svc2, limit=10)
    assert stats.llm_done == 1 and stats.llm_queued == 0
    assert rows(conn, "SELECT 1 FROM claims WHERE extraction_method='llm'")
    assert (
        json.loads(rows(conn, "SELECT metadata_json FROM candidates")[0][0])["llm_state"] == "done"
    )
    assert run_llm_queue(conn, cfg, CLOCK, svc2, limit=10).llm_done == 0  # nothing left


def test_queue_run_stops_at_first_unavailable_and_keeps_the_rest_queued(env):
    cfg, conn = env
    run(env, FakeGateway(lambda p: httpx.Response(429)))
    gw = FakeGateway(lambda p: httpx.Response(429))
    svc = build_llm_service(
        conn,
        cfg,
        CLOCK,
        client=OpenAICompatClient("http://127.0.0.1:3001/v1", "m", "k", transport=gw.transport),
    )
    stats = run_llm_queue(conn, cfg, CLOCK, svc, limit=10)
    assert stats.llm_queued == 1 and stats.llm_done == 0
    assert (
        json.loads(rows(conn, "SELECT metadata_json FROM candidates")[0][0])["llm_state"]
        == "pending"
    )


def test_missing_acknowledgement_queues_without_sending_anything(env):
    gw = FakeGateway(rich)
    s, svc = run(env, gw, ack=False)
    assert gw.requests == [] and s.pipeline.llm_queued == 1 and s.pipeline.promoted == 1


def test_disabled_llm_makes_no_requests_and_queues_nothing(tmp_path):
    cfg = load_config(home=tmp_path / "home", env={"RADAR_LLM_ENABLED": "false"})
    cfg.paths.ensure()
    conn = dbm.connect(cfg.paths.db, create=True)
    mig.migrate(conn, mig.discover(), CLOCK)
    SourceRepository(conn, CLOCK).import_configs(load_source_files([GOOD]))
    fetcher, _ = make_fetcher(web())
    svc = build_llm_service(conn, cfg, CLOCK)
    assert svc is None
    s = orch.run_discovery(conn, cfg, fetcher, CLOCK, llm=svc)
    assert s.pipeline.promoted == 1 and s.pipeline.llm_queued == 0
    assert "llm_state" not in json.loads(
        conn.execute("SELECT metadata_json FROM candidates").fetchone()[0]
    )
    conn.close()


def test_invalid_output_creates_review_item_not_a_failed_run(env):
    cfg, conn = env
    s, svc = run(env, FakeGateway(lambda p: {"nonsense": True}))
    assert s.status == "success" and s.pipeline.llm_invalid == 1 and s.pipeline.promoted == 1
    assert rows(conn, "SELECT 1 FROM review_queue WHERE reason_code='llm_invalid_output'")


def test_manual_promote_path_never_calls_the_llm(env):
    cfg, conn = env
    conn.execute("UPDATE sources SET trust_tier='t4_aggregator', discovery_only=1")
    run(env, FakeGateway(rich))  # lead only: not official, so no LLM call either
    [cand] = rows(conn, "SELECT * FROM candidates")
    assert cand["status"] == "new"
    gw = FakeGateway(rich)
    promote_from_db(conn, cfg, CLOCK, cand["id"])
    assert gw.requests == []
    assert not rows(conn, "SELECT 1 FROM claims WHERE extraction_method='llm'")
