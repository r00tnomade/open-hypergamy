import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from tests.helpers import FakeWeb, fixture, html, make_fetcher
from tests.helpers_llm import FakeGateway, empty_output, ev
from tests.helpers_tg import RecordingSink

from open_hypergamy.clock import FixedClock
from open_hypergamy.config import load_config
from open_hypergamy.discovery import orchestrator as orch
from open_hypergamy.errors import ConfigurationError
from open_hypergamy.extraction.llm_extractor import build_llm_service
from open_hypergamy.llm.ack import write_ack
from open_hypergamy.llm.client import OpenAICompatClient
from open_hypergamy.monitoring.cycle import score_and_alert
from open_hypergamy.monitoring.deadlines import build_digest, prepare, queue_digest
from open_hypergamy.monitoring.recheck import recheck_editions
from open_hypergamy.notifications.outbox import Outbox
from open_hypergamy.persistence import db as dbm
from open_hypergamy.persistence import migrations as mig
from open_hypergamy.persistence.repositories.sources import SourceRepository
from open_hypergamy.sources.registry import load_source_files

SEED = "https://example.edu/students/opportunities"
CHILD = SEED + "/summer-school"
FIXTURES = Path(__file__).parent.parent / "fixtures"


class Clk(FixedClock):
    def set(self, y, m, d, h=12):
        self._now = datetime(y, m, d, h, tzinfo=UTC)

    def advance(self, **kw):
        self._now += timedelta(**kw)


def rich(p):
    o = empty_output()
    o["format"] = {"value": "in_person", "evidence": ev(p, "is held in person")}
    o["location"] = {"value": "Berlin", "evidence": ev(p, "in Berlin")}
    o["funding"] = {
        "status": "partially_funded",
        "details": "travel grants",
        "evidence": ev(p, "Travel grants are available"),
    }
    o["eligibility_requirements"] = [{"requirement": "undergraduate students", "blocking": "true",
                                      "evidence": ev(p, "invites undergraduate students")}]  # fmt: skip
    return o


class Env:
    def __init__(self, tmp_path, profile=True):
        self.clock = Clk(datetime(2027, 2, 25, 12, tzinfo=UTC))
        self.cfg = load_config(
            home=tmp_path / "home",
            env={"OHG_FREELLMAPI_API_KEY": "k", "OHG_TELEGRAM_SEND_DELAY_SECONDS": "0"},
        )
        self.cfg.paths.ensure()
        if profile:
            shutil.copy(FIXTURES / "profile.yaml", self.cfg.paths.home / "profile.yaml")
        self.conn = dbm.connect(self.cfg.paths.db, create=True)
        mig.migrate(self.conn, mig.discover(), self.clock)
        SourceRepository(self.conn, self.clock).import_configs(
            load_source_files([FIXTURES / "sources_good.yaml"])
        )
        write_ack(self.cfg.paths.llm_ack, self.clock, "freellmapi", "auto:ohg-free")
        self.sink = RecordingSink()
        self.programme = fixture("programme.html")

    def web(self):
        return FakeWeb({SEED: html(fixture("index.html")), CHILD: html(self.programme)})

    def discover(self, web=None, gw=None):
        gw = gw or FakeGateway(rich)
        svc = build_llm_service(self.conn, self.cfg, self.clock, client=OpenAICompatClient(
            "http://127.0.0.1:3001/v1", "auto:ohg-free", "k", transport=gw.transport))  # fmt: skip
        fetcher, _ = make_fetcher(web or self.web())
        return orch.run_discovery(self.conn, self.cfg, fetcher, self.clock, llm=svc)

    def cycle(self, sink=None, **kw):
        return score_and_alert(
            self.conn, self.cfg, self.clock, sink_factory=lambda: sink or self.sink, **kw
        )

    def recheck(self, web):
        prep = prepare(self.conn, self.cfg, self.clock)
        fetcher, _ = make_fetcher(web)
        return prep, recheck_editions(
            self.conn, self.cfg, fetcher, self.clock, prep.editions_to_recheck
        )

    def q(self, sql, *a):
        return self.conn.execute(sql, a).fetchall()

    def texts(self):
        return [m.text for m, _ in self.sink.sent]

    def types(self):
        return [m.notification_type for m, _ in self.sink.sent]

    def alerts_sent(self):
        """Messages other than monitoring-gap notices (clock jumps in tests create genuine gaps)."""
        return [t for t in self.types() if t != "monitoring_gap"]


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    yield e
    e.conn.close()


def test_discovery_scores_plans_and_alerts_with_evidence(env):
    env.discover()
    rep = env.cycle()
    [ed] = env.q("SELECT * FROM editions")
    [snap] = env.q("SELECT * FROM score_snapshots")
    assert ed["fact_status"] == "confirmed_official" and ed["application_status"] == "open"
    assert snap["eligibility_status"] == "eligible" and snap["profile_version"] == "2026-10"
    assert snap["priority_band"] == "high" and ed["user_action"] == "apply"
    comps = json.loads(snap["component_scores_json"])
    assert round(sum(comps[k] * w for k, w in dict(career_alignment=.30, technical_research_value=.25,
                     eligibility_feasibility=.20, funding_accessibility=.15, time_cost=.10).items()), 1) == snap["fit_score"]  # fmt: skip
    assert {"HIGH_CAREER_ALIGNMENT", "APPLICATION_OPEN"} <= set(
        json.loads(snap["reason_codes_json"])
    )
    [a] = env.q("SELECT * FROM eligibility_assessments")
    assert (
        a["status"] == "eligible"
        and a["assessed_by"] == "llm_assisted"
        and a["profile_version"] == "2026-10"
    )
    assert json.loads(a["criteria_json"])[0]["assessment"] == "satisfied"
    acts = {r["action_type"]: r for r in env.q("SELECT * FROM action_items")}
    assert set(acts) == {"submit_application", "prepare_materials"}
    assert (
        acts["submit_application"]["due_date_local"] == "2027-03-15"
        and acts["submit_application"]["status"] == "open"
    )
    assert (
        acts["submit_application"]["idempotency_key"]
        == f"action:{ed['id']}:submit_application:{acts['submit_application']['deadline_id']}:actions-1"
    )
    assert (
        set(rep.alerts.queued) == {"new_opportunity", "application_opened", "deadline_reminder"}
        and rep.delivery.sent == 3
    )
    for text in env.texts():
        assert CHILD in text or "example.edu" in text  # official link in every alert
    new = next(t for t in env.texts() if t.startswith("🎯"))
    assert (
        "Evidence: confirmed" in new
        and "Application: 15 March 2027 (confirmed)" in new
        and "Next action: apply" in new
    )
    leaked = " ".join(env.texts()).lower()
    for private in (
        "applied_ml",
        "python",
        "visuotactile",
        "computer_engineering",
        "profile",
        "2026-10",
    ):
        assert private not in leaked, private


def test_rerun_creates_no_duplicate_alerts_or_actions(env):
    env.discover()
    env.cycle()
    sent, actions, snaps = (
        len(env.sink.sent),
        len(env.q("SELECT 1 FROM action_items")),
        len(env.q("SELECT 1 FROM score_snapshots")),
    )
    for _ in range(3):
        rep = env.cycle()
        assert rep.alerts.queued == {} and rep.delivery.sent == 0
    env.clock.advance(days=8)
    env.discover()
    assert len(env.sink.sent) == sent
    assert (
        len(env.q("SELECT 1 FROM action_items")) == actions
        and len(env.q("SELECT 1 FROM eligibility_assessments")) == 1
    )
    assert (
        len(env.q("SELECT 1 FROM score_snapshots")) >= snaps
    )  # may append only when values change
    assert len(env.q("SELECT idempotency_key FROM notification_log")) == len(
        {r[0] for r in env.q("SELECT idempotency_key FROM notification_log")}
    )


def test_reminder_thresholds_and_catch_up_sends_only_the_most_urgent(env):
    env.clock.set(2027, 3, 10)  # first ever run, 5 days before the deadline
    env.discover()
    env.cycle()
    reminders = [t for t in env.texts() if t.startswith("⏳")]
    assert len(reminders) == 1 and "in 5 days" in reminders[0]
    log = {
        r["idempotency_key"].split(":")[3]: r["status"]
        for r in env.q("SELECT * FROM notification_log WHERE notification_type='deadline_reminder'")
    }
    assert log == {
        "7": "sent",
        "14": "suppressed",
        "30": "suppressed",
    }  # earlier thresholds recorded, not sent
    env.clock.set(2027, 3, 13)
    env.recheck(env.web())
    env.cycle()
    assert [t for t in env.texts() if t.startswith("⏳")][-1].startswith("⏳ Deadline in 2 days")
    env.cycle()
    assert len([t for t in env.texts() if t.startswith("⏳")]) == 2  # nothing repeated
    env.clock.set(2027, 3, 16)  # deadline passed: no stale reminder
    before = len(env.alerts_sent())
    env.cycle()
    assert len(env.alerts_sent()) == before


def test_unchanged_page_recheck_renews_freshness_and_restores_confirmed(env):
    env.discover()
    env.cycle()
    env.clock.set(2027, 3, 10)
    prep, rep = env.recheck(env.web())
    assert prep.marked_stale == 2 and len(prep.editions_to_recheck) == 1 and rep.reverified == 1
    assert {r["fact_status"] for r in env.q("SELECT fact_status FROM deadlines")} == {
        "confirmed_official"
    }
    [ed] = env.q("SELECT * FROM editions")
    assert (
        ed["source_fresh_until"] > "2027-03-10T12:00:00Z"
        and ed["fact_status"] == "confirmed_official"
    )


def test_failed_recheck_leaves_the_fact_visibly_stale_and_alerts(env):
    env.discover()
    env.cycle()
    env.clock.set(2027, 3, 10)
    prep, rep = env.recheck(FakeWeb({CHILD: httpx.Response(500)}))
    assert rep.failed == 1 and rep.reverified == 0
    close = env.q("SELECT * FROM deadlines WHERE deadline_type='application_close'")[0]
    assert close["fact_status"] == "stale" and close["due_date_local"] == "2027-03-15"  # value kept
    out = env.cycle()
    assert "deadline_stale" in out.alerts.queued and not any(
        t.startswith("⏳") for t in env.texts()[3:]
    )
    stale = next(t for t in env.texts() if "needs rechecking" in t)
    assert "(stale)" in stale and CHILD in stale
    assert (
        env.q("SELECT user_action FROM editions")[0][0] == "apply"
    )  # a stale date doesn't demote the action
    assert any(
        a["action_type"] == "recheck_source"
        for a in env.q("SELECT * FROM action_items WHERE status='open'")
    )


def test_moved_deadline_is_detected_and_alerted_once(env):
    env.discover()
    env.cycle()
    env.clock.set(2027, 3, 1)
    env.programme = env.programme.replace(b"15 March 2027", b"8 March 2027")
    prep, rep = env.recheck(env.web())
    assert rep.changed == 1
    assert (
        env.q("SELECT due_date_local FROM deadlines WHERE deadline_type='application_close'")[0][0]
        == "2027-03-08"
    )
    out = env.cycle()
    assert out.alerts.queued.get("deadline_changed") == 1
    moved = next(t for t in env.texts() if t.startswith("🔄"))
    assert "2027-03-15 → 2027-03-08" in moved and "(confirmed)" in moved
    assert env.cycle().alerts.queued == {}


def test_manual_action_locks_the_planner_until_auto(env):
    env.discover()
    env.cycle()
    [ed] = env.q("SELECT id FROM editions")
    env.conn.execute(
        "UPDATE editions SET user_action='applied', action_locked=1 WHERE id=?", (ed[0],)
    )
    env.clock.set(2027, 3, 10)
    env.recheck(env.web())
    before = len(env.alerts_sent())
    out = env.cycle()
    assert (
        env.q("SELECT user_action FROM editions")[0][0] == "applied"
        and len(env.alerts_sent()) == before
    )
    assert not env.q(
        "SELECT 1 FROM action_items WHERE status='open'"
    )  # open items are dismissed, none created
    assert set(out.alerts.queued) <= {"monitoring_gap"}  # a real gap, nothing else


def test_completed_and_dismissed_actions_are_not_recreated(env):
    env.discover()
    env.cycle()
    env.conn.execute("UPDATE action_items SET status='done' WHERE action_type='submit_application'")
    env.conn.execute(
        "UPDATE action_items SET status='dismissed' WHERE action_type='prepare_materials'"
    )
    env.clock.advance(hours=3)
    env.cycle()
    assert {r["status"] for r in env.q("SELECT status FROM action_items")} == {"done", "dismissed"}
    assert len(env.q("SELECT 1 FROM action_items")) == 2


def test_profile_change_makes_it_ineligible_then_back(env):
    env.discover()
    env.cycle()
    path = env.cfg.paths.home / "profile.yaml"
    original = path.read_text()
    path.write_text(
        original.replace("degree_level: bachelor", "degree_level: master").replace(
            'profile_version: "2026-10"', 'profile_version: "2026-11"'
        )
    )
    before = len(env.sink.sent)
    env.clock.advance(days=1)
    env.cycle()
    [ed] = env.q("SELECT * FROM editions")
    snap = env.q("SELECT * FROM score_snapshots ORDER BY created_at DESC, rowid DESC")[0]
    assert (
        snap["eligibility_status"] == "ineligible"
        and snap["priority_band"] == "excluded"
        and ed["user_action"] == "archived"
    )
    assert (
        not env.q("SELECT 1 FROM action_items WHERE status='open'") and len(env.sink.sent) == before
    )
    assert (
        len(env.q("SELECT 1 FROM eligibility_assessments")) == 2
    )  # history kept, with the profile version
    path.write_text(original)
    env.clock.advance(days=1)
    env.cycle()
    assert (
        env.q("SELECT user_action FROM editions")[0][0] == "apply"
    )  # revived because the planner archived it


def test_first_year_requirement_becomes_future_cycle(env):
    gw = FakeGateway(
        lambda p: {
            **rich(p),
            "eligibility_requirements": [
                {
                    "requirement": "at least second year",
                    "blocking": "true",
                    "evidence": ev(p, "invites undergraduate students"),
                }
            ],
        }
    )
    env.discover(gw=gw)
    env.cycle()
    snap = env.q("SELECT * FROM score_snapshots")[0]
    assert (
        snap["eligibility_status"] == "future_cycle"
        and "FIRST_YEAR_INELIGIBLE" in snap["reason_codes_json"]
    )
    assert env.q("SELECT user_action FROM editions")[0][0] == "future_cycle"
    assert "new_opportunity" not in env.types()


def test_unclear_eligibility_creates_a_review_action_and_caps_priority(env):
    gw = FakeGateway(
        lambda p: {
            **rich(p),
            "eligibility_requirements": [
                {
                    "requirement": "EU citizens only",
                    "blocking": "true",
                    "evidence": ev(p, "invites undergraduate students"),
                }
            ],
        }
    )
    env.discover(gw=gw)
    env.cycle()
    snap = env.q("SELECT * FROM score_snapshots")[0]
    assert (
        snap["eligibility_status"] == "possibly_eligible"
        and "ELIGIBILITY_UNCLEAR" in snap["reason_codes_json"]
    )
    assert snap["priority_band"] == "medium"  # LLD §11.3 cap
    assert any(
        r["action_type"] == "review_eligibility" for r in env.q("SELECT * FROM action_items")
    )


def test_no_eligibility_statement_is_not_proof_of_eligibility(env):
    env.discover(gw=FakeGateway(lambda p: empty_output()))
    env.cycle()
    snap = env.q("SELECT * FROM score_snapshots")[0]
    assert snap["eligibility_status"] == "possibly_eligible"
    assert (
        "absence is not proof"
        in env.q("SELECT assessment_summary FROM eligibility_assessments")[0][0]
    )


def test_unverified_deadlines_never_drive_urgency_or_reminders(env):
    env.conn.execute("UPDATE sources SET trust_tier='t4_aggregator', discovery_only=1")
    env.discover()
    [cand] = env.q("SELECT id FROM candidates")
    from open_hypergamy.discovery.pipeline import promote_from_db

    promote_from_db(env.conn, env.cfg, env.clock, cand[0])
    env.cycle()
    assert (
        env.q("SELECT fact_status FROM deadlines WHERE deadline_type='application_close'")[0][0]
        == "unverified"
    )
    assert env.q("SELECT urgency_score FROM score_snapshots")[0][0] == 10
    assert env.sink.sent == []


def test_telegram_down_keeps_messages_queued_and_later_delivers_once(env):
    env.discover()

    def broken():
        raise ConfigurationError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")

    rep = score_and_alert(env.conn, env.cfg, env.clock, sink_factory=broken)
    assert rep.delivery is None and "stay queued" in rep.delivery_note
    assert {r["status"] for r in env.q("SELECT status FROM notification_log")} == {"pending"}
    out = env.cycle()
    assert out.delivery.sent == 3 and out.alerts.queued == {}
    assert env.cycle().delivery.sent == 0


def test_transient_telegram_failure_retries_later_without_duplicates(env):
    from open_hypergamy.notifications.base import SendResult

    env.discover()
    flaky = RecordingSink([SendResult(False, error="HTTP 502")])
    env.cycle(sink=flaky)
    assert len(env.q("SELECT 1 FROM notification_log WHERE status='sent'")) == 2
    env.clock.advance(hours=2)
    env.cycle(sink=flaky)
    assert len(env.q("SELECT 1 FROM notification_log WHERE status='sent'")) == 3
    assert len({k for _, k in flaky.sent}) == 3


def test_disabled_telegram_and_missing_profile_send_nothing(env, tmp_path):
    env.discover()
    env.cfg.settings.telegram.enabled = False
    rep = env.cycle()
    assert (
        env.sink.sent == []
        and env.q("SELECT 1 FROM notification_log") == []
        and rep.delivery is None
    )
    (env.cfg.paths.home / "profile.yaml").unlink()
    env.cfg.settings.telegram.enabled = True
    out = env.cycle()
    assert out.profile_found is False and env.sink.sent == []


def test_dry_run_previews_without_writing_or_sending(env):
    env.discover()
    rep = env.cycle(dry_run=True)
    assert (
        len(rep.preview) == 3
        and env.sink.sent == []
        and env.q("SELECT 1 FROM notification_log") == []
    )


def test_source_health_alert_for_failing_source_behind_a_deadline(env):
    env.discover()
    env.conn.execute("UPDATE sources SET failure_streak=3, last_success_at='2027-02-20T00:00:00Z'")
    env.cycle()
    health = next(t for t in env.texts() if t.startswith("⚠️ Monitoring issue"))
    assert "Failure streak: 3" in health and "ohg sources failures" in health
    env.conn.execute("UPDATE sources SET failure_streak=3")
    assert env.cycle().alerts.queued == {}  # same bucket: no repeat
    env.conn.execute("UPDATE sources SET failure_streak=4")
    assert env.cycle().alerts.queued == {"source_health": 1}


def test_weekly_digest_content_and_idempotency(env):
    env.discover()
    env.cycle()
    text = build_digest(env.conn, env.cfg, env.clock)
    for section in ("1. Top actions", "2. New this week", "3. Applications opening", "4. Deadlines within 30 days",
                    "7. Verification & monitoring", "8. Monitoring health"):  # fmt: skip
        assert section in text
    assert "Submit application" in text and CHILD in text and "(confirmed, 18 d)" in text
    ob = Outbox(env.conn, env.clock, env.cfg.settings.telegram)
    assert queue_digest(env.conn, env.cfg, env.clock, ob)[1] >= 1
    assert queue_digest(env.conn, env.cfg, env.clock, ob)[1] == 0  # same ISO week: no second digest
    env.clock.advance(days=7)
    assert queue_digest(env.conn, env.cfg, env.clock, ob)[1] >= 1


def test_overflow_new_opportunity_alerts_fold_into_digest(env):
    env.discover()
    env.cfg.settings.telegram.maximum_messages_per_run = 1
    env.cycle()
    statuses = {
        r["notification_type"]: r["status"] for r in env.q("SELECT * FROM notification_log")
    }
    assert statuses["deadline_reminder"] == "sent" and statuses["new_opportunity"] == "suppressed"
