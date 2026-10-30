"""Child-page state transitions (ADR-011)."""

from datetime import UTC, datetime, timedelta

import pytest

from open_hypergamy.clock import iso_z
from open_hypergamy.sources.health import HealthPolicy
from open_hypergamy.sources.pages import PageUpdate, TrackedPage, plan_page

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
DAY = timedelta(hours=24)
POLICY = HealthPolicy(not_found_review_after=2, max_cooldown_hours=48)
URL = "https://example.edu/a"


def plan(prev, kind, now=NOW, **kw):
    return plan_page(prev, PageUpdate(URL, 1, kind, **kw), source_id="s", now=now,
                     interval=DAY, policy=POLICY)  # fmt: skip


def fetched(**kw):
    return plan(None, "fetched", http_status=200, etag='"1"', content_hash="h1", **kw)


def test_discovered_page_is_due_immediately_and_unvalidated():
    p = plan(None, "discovered")
    assert p.status == "active" and p.last_checked_at is None and p.is_due(NOW)
    assert (p.etag, p.content_hash, p.consecutive_failures) == (None, None, 0)


def test_fetch_sets_window_validators_and_change_time():
    p = fetched()
    assert p.next_check_at == iso_z(NOW + DAY) and not p.is_due(NOW) and p.is_due(NOW + DAY)
    assert p.etag == '"1"' and p.last_changed_at == iso_z(NOW)
    later = NOW + 2 * DAY
    same = plan(p, "fetched", later, http_status=200, etag='"1"', content_hash="h1")
    assert same.last_changed_at == p.last_changed_at  # identical content is not a change
    new = plan(p, "fetched", later, http_status=200, etag='"2"', content_hash="h2")
    assert new.last_changed_at == iso_z(later) and new.etag == '"2"'


def test_not_modified_keeps_validators_hash_and_change_time():
    p = fetched()
    q = plan(p, "not_modified", NOW + 2 * DAY, http_status=304)
    assert (q.etag, q.content_hash, q.last_changed_at) == ('"1"', "h1", p.last_changed_at)
    assert q.last_checked_at == iso_z(NOW + 2 * DAY) and q.last_http_status == 304
    r = plan(p, "not_modified", NOW + 2 * DAY, http_status=304, etag='"1b"')
    assert r.etag == '"1b"'


def test_transient_failures_back_off_keep_evidence_and_stay_active():
    p = fetched()
    t = NOW + 2 * DAY
    f1 = plan(p, "failed", t, http_status=503, error_code="http_error")
    assert f1.status == "active" and f1.consecutive_failures == 1
    assert f1.next_check_at == iso_z(t + timedelta(hours=1))
    assert (f1.etag, f1.content_hash, f1.last_checked_at) == (
        p.etag,
        p.content_hash,
        p.last_checked_at,
    )
    f2 = plan(f1, "failed", t, error_code="fetch_timeout")
    assert f2.next_check_at == iso_z(t + timedelta(hours=2))
    f9 = f2
    for _ in range(8):
        f9 = plan(f9, "failed", t, error_code="fetch_timeout")
    assert f9.next_check_at == iso_z(t + DAY)  # never longer than the page's own window
    long = plan(p, "failed", t, http_status=429, error_code="http_error", retry_after_seconds=10**7)
    assert long.next_check_at == iso_z(t + timedelta(hours=48))  # capped by max_cooldown_hours
    ok = plan(f2, "not_modified", t, http_status=304)
    assert ok.consecutive_failures == 0 and ok.last_error_code is None


def test_404_needs_two_in_a_row_but_410_is_immediate():
    p = fetched()
    one = plan(p, "failed", NOW, http_status=404, error_code="http_error")
    assert one.status == "active"
    two = plan(one, "failed", NOW, http_status=404, error_code="http_error", detail="HTTP 404")
    assert two.status == "missing" and "not_found" in (two.status_reason or "")
    assert plan(p, "failed", NOW, http_status=410, error_code="http_error").status == "missing"
    assert not two.is_due(NOW + 100 * DAY)  # missing pages are never polled
    assert (two.etag, two.content_hash) == (p.etag, p.content_hash)


@pytest.mark.parametrize(
    ("status", "code"), [(403, "http_error"), (401, "http_error"), (200, "access_barrier")]
)
def test_access_problems_hold_the_page(status, code):
    held = plan(fetched(), "failed", NOW, http_status=status, error_code=code)
    assert held.status == "held" and not held.is_due(NOW + 100 * DAY)


def test_listing_again_revives_only_missing_pages():
    missing = plan(plan(fetched(), "failed", NOW, http_status=410, error_code="http_error"),
                   "discovered", NOW + DAY)  # fmt: skip
    assert (
        missing.status == "active"
        and missing.is_due(NOW + DAY)
        and missing.consecutive_failures == 0
    )
    held = plan(fetched(), "failed", NOW, http_status=403, error_code="http_error")
    assert plan(held, "discovered", NOW + DAY).status == "held"  # needs an operator
    active = fetched()
    assert (
        plan(active, "discovered", NOW + DAY).next_check_at == active.next_check_at
    )  # still fresh


def test_invalid_and_depth():
    p = plan(fetched(), "invalid", NOW, error_code="out_of_scope", detail="scope tightened")
    assert p.status == "invalid" and not p.is_due(NOW + 100 * DAY)
    deeper = plan_page(fetched(), PageUpdate(URL, 3, "discovered"), source_id="s", now=NOW,
                       interval=DAY, policy=POLICY)  # fmt: skip
    assert deeper.depth == 1  # shallowest path wins
    assert isinstance(deeper, TrackedPage)
