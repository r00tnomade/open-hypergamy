from datetime import UTC, datetime, timedelta

import httpx
import pytest
from tests.helpers_tg import FakeBotApi, RecordingSink

from opportunity_radar.clock import FixedClock
from opportunity_radar.config import TelegramSettings
from opportunity_radar.errors import ConfigurationError
from opportunity_radar.notifications import templates as T
from opportunity_radar.notifications.base import NotificationMessage, SendResult
from opportunity_radar.notifications.outbox import Outbox
from opportunity_radar.notifications.telegram import TelegramSink, split_message
from opportunity_radar.persistence import db as dbm
from opportunity_radar.persistence import migrations as mig

TOKEN = "1234567:AAH-secret-token-abcdefghijklmnop"


class Clk(FixedClock):
    def advance(self, **kw):
        self._now += timedelta(**kw)


@pytest.fixture
def box(tmp_path):
    clock = Clk(datetime(2027, 3, 1, 12, tzinfo=UTC))
    conn = dbm.connect(tmp_path / "n.sqlite3", create=True)
    mig.migrate(conn, mig.discover(), clock)
    yield Outbox(conn, clock, TelegramSettings(send_delay_seconds=1.0)), conn, clock
    conn.close()


def msg(text="hello", kind="deadline_reminder", entity="e1"):
    return NotificationMessage(text, kind, "edition", entity)


def rows(conn, status=None):
    sql = "SELECT * FROM notification_log" + (" WHERE status=?" if status else "")
    return conn.execute(sql, (status,) if status else ()).fetchall()


# --- Telegram sink ---------------------------------------------------------------------------------
def test_sink_posts_plain_text_to_the_bot_api_without_link_preview():
    api = FakeBotApi()
    res = TelegramSink(TOKEN, "42", transport=api.transport).send(
        msg("Hi https://example.edu/x"), "k"
    )
    assert res.ok and res.message_id == "7"
    [req] = api.requests
    assert str(req.url) == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    body = req.content.decode()
    assert '"chat_id":"42"' in body.replace(" ", "") and "parse_mode" not in body
    assert '"disable_web_page_preview":true' in body.replace(" ", "")


def test_sink_requires_configuration(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(ConfigurationError):
        TelegramSink.from_env()


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_invalid_token_or_chat_is_permanent_and_token_is_redacted(status):
    api = FakeBotApi(
        lambda b: httpx.Response(status, json={"ok": False, "description": f"Unauthorized {TOKEN}"})
    )
    res = TelegramSink(TOKEN, "42", transport=api.transport).send(msg(), "k")
    assert not res.ok and res.permanent and TOKEN not in (res.error or "")


def test_rate_limit_and_server_errors_are_transient():
    api = FakeBotApi(
        lambda b: httpx.Response(
            429, json={"ok": False, "description": "slow", "parameters": {"retry_after": 17}}
        )
    )
    r = TelegramSink(TOKEN, "42", transport=api.transport).send(msg(), "k")
    assert not r.ok and not r.permanent and r.retry_after == 17
    r5 = TelegramSink(
        TOKEN, "42", transport=FakeBotApi(lambda b: httpx.Response(502)).transport
    ).send(msg(), "k")
    assert not r5.ok and not r5.permanent


def test_network_errors_never_leak_the_token():
    api = FakeBotApi(
        lambda b: httpx.ConnectError(
            f"cannot reach https://api.telegram.org/bot{TOKEN}/sendMessage"
        )
    )
    r = TelegramSink(TOKEN, "42", transport=api.transport).send(msg(), "k")
    assert not r.ok and TOKEN not in (r.error or "")
    t = TelegramSink(
        TOKEN, "42", transport=FakeBotApi(lambda b: httpx.ReadTimeout("x")).transport
    ).send(msg(), "k")
    assert t.error == "timeout"


def test_long_messages_split_on_line_boundaries():
    text = "\n".join(f"line {i} " + "x" * 60 for i in range(200))
    parts = split_message(text, limit=1000)
    assert (
        len(parts) > 5
        and all(len(p) <= 1000 for p in parts)
        and "\n".join(parts).count("line ") == 200
    )
    assert split_message("short") == ["short"]


# --- templates -----------------------------------------------------------------------------------------
def test_templates_carry_link_certainty_and_never_show_estimates_as_confirmed():
    url = "https://example.edu/ss-2027"
    r = T.deadline_reminder(
        days=5,
        name="Summer School",
        raw="15 March 2027",
        status="confirmed_official",
        eligibility="eligible",
        still_needed="Submit application",
        url=url,
    )
    assert url in r and "(confirmed)" in r and "in 5 days" in r
    est = T.deadline_reminder(
        days=5,
        name="X",
        raw="mid March",
        status="estimated_recurring",
        eligibility="eligible",
        still_needed="-",
        url=url,
    )
    assert "estimated (NOT confirmed)" in est and "(confirmed)" not in est
    n = T.new_opportunity(
        name="N",
        fit=81.2,
        eligibility="eligible",
        event="2027-06-10..2027-06-14",
        application="x",
        funding="y",
        reasons=["HIGH_CAREER_ALIGNMENT", "SECRET_INTERNAL_CODE"],
        evidence="confirmed",
        next_action="apply",
        url=url,
    )
    assert url in n and "Evidence: confirmed" in n and "SECRET_INTERNAL_CODE" not in n
    assert "strong match with your focus areas" in n
    assert T.deadline_reminder(
        days=1, name="X", raw="r", status="stale", eligibility="e", still_needed="s", url=url
    ).startswith("⏳ Deadline in 1 day:")
    assert T.evidence_label("confirmed_official", "confirmed_official") == "confirmed"
    assert T.evidence_label("unverified", "conflicting_sources") == "conflict"
    assert (
        T.evidence_label("announced_not_open", None) == "partial"
        and T.evidence_label("unverified", None) == "unverified"
    )


# --- outbox -----------------------------------------------------------------------------------------------
def test_enqueue_is_idempotent_and_written_before_sending(box):
    ob, conn, _ = box
    assert ob.enqueue(msg(), "deadline:E:D:7:2027-03-15") and not ob.enqueue(
        msg("other text"), "deadline:E:D:7:2027-03-15"
    )
    [r] = rows(conn)
    assert (
        r["status"] == "pending"
        and r["message_text"] == "hello"
        and r["attempts"] == 0
        and r["channel"] == "telegram"
    )


def test_delivery_marks_sent_and_never_resends(box):
    ob, conn, _ = box
    ob.enqueue(msg("a", entity="1"), "k1")
    ob.enqueue(msg("b", entity="2"), "k2")
    sink = RecordingSink()
    rep = ob.deliver(sink, sleep=lambda s: None)
    assert rep.sent == 2 and [m.text for m, _ in sink.sent] == ["a", "b"]
    assert {r["status"] for r in rows(conn)} == {"sent"} and rows(conn)[0]["telegram_message_id"]
    assert ob.deliver(sink, sleep=lambda s: None).sent == 0 and len(sink.sent) == 2


def test_transient_failure_retries_with_backoff_then_fails_after_the_limit(box):
    ob, conn, clock = box
    ob.enqueue(msg(), "k")
    sink = RecordingSink([SendResult(False, error="HTTP 502")] * 5)
    r1 = ob.deliver(sink, sleep=lambda s: None)
    assert r1.retry_scheduled == 1
    [row] = rows(conn)
    assert (
        row["status"] == "pending"
        and row["attempts"] == 1
        and row["next_retry_at"] > "2027-03-01T12:00:00Z"
    )
    assert ob.deliver(sink, sleep=lambda s: None).sent == 0 and len(sink.sent) == 1  # not due yet
    clock.advance(hours=2)
    ob.deliver(sink, sleep=lambda s: None)
    clock.advance(hours=2)
    last = ob.deliver(sink, sleep=lambda s: None)
    assert (
        last.failed == 1 and rows(conn)[0]["status"] == "failed" and rows(conn)[0]["attempts"] == 3
    )
    assert "HTTP 502" in rows(conn)[0]["last_error_redacted"]
    clock.advance(days=1)
    assert ob.deliver(sink, sleep=lambda s: None).sent == 0  # failed stays failed until requeued


def test_rate_limit_retry_after_is_honoured(box):
    ob, conn, clock = box
    ob.enqueue(msg(), "k")
    ob.deliver(
        RecordingSink([SendResult(False, error="rate limited", retry_after=90)]),
        sleep=lambda s: None,
    )
    assert rows(conn)[0]["next_retry_at"] == "2027-03-01T12:01:30Z"


def test_permanent_failure_is_not_retried_and_can_be_requeued(box):
    ob, conn, _ = box
    ob.enqueue(msg(), "k")
    sink = RecordingSink([SendResult(False, error="HTTP 401: Unauthorized", permanent=True)])
    assert ob.deliver(sink, sleep=lambda s: None).failed == 1
    assert ob.deliver(sink, sleep=lambda s: None).sent == 0 and len(sink.sent) == 1
    assert ob.requeue_failed() == 1
    assert ob.deliver(sink, sleep=lambda s: None).sent == 1


def test_per_run_cap_critical_first_digestable_folded_into_digest(box):
    ob, conn, _ = box
    ob.s.maximum_messages_per_run = 2
    for i in range(3):
        ob.enqueue(msg(f"new{i}", "new_opportunity", f"n{i}"), f"new:{i}")
    for i in range(2):
        ob.enqueue(msg(f"rem{i}", "deadline_reminder", f"r{i}"), f"rem:{i}")
    sink = RecordingSink()
    rep = ob.deliver(sink, sleep=lambda s: None)
    assert [m.text for m, _ in sink.sent] == ["rem0", "rem1"]  # critical alerts go first
    assert rep.sent == 2 and rep.suppressed == 3
    assert {r["last_error_redacted"] for r in rows(conn, "suppressed")} == {
        "grouped into weekly digest"
    }


def test_critical_overflow_is_deferred_not_dropped(box):
    ob, conn, _ = box
    ob.s.maximum_messages_per_run = 1
    ob.enqueue(msg("a", entity="1"), "a")
    ob.enqueue(msg("b", entity="2"), "b")
    rep = ob.deliver(RecordingSink(), sleep=lambda s: None)
    assert rep.sent == 1 and rep.deferred == 1 and len(rows(conn, "pending")) == 1


def test_sends_are_paced(box):
    ob, _, _ = box
    for i in range(3):
        ob.enqueue(msg(f"m{i}", entity=str(i)), f"k{i}")
    pauses = []
    ob.deliver(RecordingSink(), sleep=pauses.append)
    assert pauses == [1.0, 1.0]


def test_stuck_sending_rows_are_recovered(box):
    ob, conn, clock = box
    ob.enqueue(msg(), "k")
    conn.execute(
        "UPDATE notification_log SET status='sending', last_attempt_at=?", ("2027-03-01T11:00:00Z",)
    )
    assert ob.deliver(RecordingSink(), sleep=lambda s: None).sent == 1


def test_suppressed_placeholder_rows_reserve_the_key_without_sending(box):
    ob, conn, _ = box
    assert ob.enqueue(msg("", "deadline_reminder"), "k", status="suppressed", note="superseded")
    assert not ob.enqueue(msg("real"), "k")
    assert ob.deliver(RecordingSink(), sleep=lambda s: None).sent == 0
