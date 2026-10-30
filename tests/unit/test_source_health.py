"""Source health model (ADR-009): categories, circuit-breaker transitions, derived state."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from tests.helpers import FIXTURES

from open_hypergamy.clock import iso_z
from open_hypergamy.config import AppSettings
from open_hypergamy.domain.enums import ErrorCategory as C
from open_hypergamy.domain.enums import SourceHealthState as H
from open_hypergamy.sources.barriers import detect_barrier
from open_hypergamy.sources.fetch import _retry_after
from open_hypergamy.sources.health import (
    HealthPolicy,
    categorize,
    health_state,
    plan_check,
)
from open_hypergamy.sources.registry import load_source_files, record_from_config

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
POLICY = HealthPolicy(cooldown_after_failures=3, not_found_review_after=2, max_cooldown_hours=168)


@pytest.fixture
def src():
    [c] = load_source_files([FIXTURES / "sources_good.yaml"])
    r = record_from_config(c)
    return replace(r, enabled=True, state="active", last_success_at=iso_z(NOW - timedelta(hours=1)))


def apply(src, status, category, now=NOW, retry_after=None, detail=None):
    """Plan a check and fold the result back into the record, as record_check does."""
    p = plan_check(
        src, status, category, now, policy=POLICY, retry_after_seconds=retry_after, detail=detail
    )
    ok = status in ("success", "not_modified", "partial")
    return p, replace(
        src,
        failure_streak=p.failure_streak,
        next_due_at=iso_z(p.next_due_at),
        cooldown_until=iso_z(p.cooldown_until) if p.cooldown_until else None,
        blocked_reason=p.blocked_reason,
        last_error_category=p.error_category.value if p.error_category else None,
        last_success_at=iso_z(now) if ok else src.last_success_at,
    )


@pytest.mark.parametrize(
    ("status", "code", "http", "expected"),
    [
        ("success", None, 200, None),
        ("not_modified", None, 304, None),
        ("skipped", "adapter_unavailable", None, None),
        ("partial", "child_pages_failed", 200, C.PARTIAL),
        ("blocked_policy", "source_policy_denied", None, C.POLICY),
        ("failed", "access_barrier", 200, C.ACCESS_BARRIER),
        ("failed", "host_cooldown", None, C.RATE_LIMITED),
        ("failed", "http_error", 403, C.ACCESS_DENIED),
        ("failed", "http_error", 401, C.ACCESS_DENIED),
        ("failed", "http_error", 429, C.RATE_LIMITED),
        ("failed", "http_error", 503, C.SERVER_ERROR),
        ("failed", "http_error", 404, C.NOT_FOUND),
        ("failed", "http_error", 410, C.GONE),
        ("failed", "http_error", 418, C.HTTP_ERROR),
        ("failed", "fetch_timeout", None, C.NETWORK),
        ("failed", "network_error", None, C.NETWORK),
        ("failed", "parse_error", None, C.CONTENT),
        ("failed", "unexpected_error", None, C.INTERNAL),
    ],
)
def test_categorize(status, code, http, expected):
    assert categorize(status, code, http) == expected


def test_breaker_closed_degraded_open_halfopen_closed(src):
    assert health_state(src, NOW) is H.HEALTHY
    # two transient network failures: degraded, backing off, still closed
    p, s = apply(src, "failed", C.NETWORK)
    assert (p.failure_streak, p.cooldown_until) == (1, None) and health_state(s, NOW) is H.DEGRADED
    assert p.next_due_at == NOW + timedelta(hours=1)
    p, s = apply(s, "failed", C.NETWORK)
    assert p.cooldown_until is None and p.next_due_at == NOW + timedelta(hours=2)
    # third in a row opens the breaker
    p, s = apply(s, "failed", C.NETWORK)
    assert p.cooldown_until == NOW + timedelta(hours=4) == p.next_due_at
    assert health_state(s, NOW) is H.COOLDOWN
    assert health_state(s, NOW + timedelta(hours=4, seconds=1)) is H.DEGRADED  # half-open
    # half-open failure re-opens it for longer
    later = NOW + timedelta(hours=5)
    p2, s2 = apply(s, "failed", C.NETWORK, now=later)
    assert p2.cooldown_until == later + timedelta(hours=8)
    # half-open success closes it and clears everything
    p3, s3 = apply(s, "success", None, now=later)
    assert (p3.failure_streak, p3.cooldown_until, p3.blocked_reason) == (0, None, None)
    assert health_state(s3, later) is H.HEALTHY


def test_429_cools_down_immediately_and_honours_long_retry_after(src):
    p, s = apply(src, "failed", C.RATE_LIMITED, retry_after=6 * 3600)
    assert p.cooldown_until == NOW + timedelta(hours=6) and health_state(s, NOW) is H.COOLDOWN
    huge, _ = apply(src, "failed", C.RATE_LIMITED, retry_after=10**9)
    assert huge.cooldown_until == NOW + timedelta(hours=168)  # never beyond the cap


def test_5xx_cools_down_on_first_failure(src):
    p, _ = apply(src, "failed", C.SERVER_ERROR)
    assert p.failure_streak == 1 and p.cooldown_until == NOW + timedelta(hours=1)


@pytest.mark.parametrize("cat", [C.ACCESS_DENIED, C.ACCESS_BARRIER, C.GONE])
def test_access_problems_hold_for_review_immediately(src, cat):
    p, s = apply(src, "failed", cat, detail="HTTP 403 from x")
    assert p.blocked_reason == f"{cat}: HTTP 403 from x" and p.cooldown_until is None
    assert health_state(s, NOW + timedelta(days=365)) is H.BLOCKED_REVIEW  # never times out


def test_404_holds_only_when_repeated(src):
    p, s = apply(src, "failed", C.NOT_FOUND)
    assert p.blocked_reason is None and health_state(s, NOW) is H.DEGRADED
    p, s = apply(s, "failed", C.NOT_FOUND)
    assert p.blocked_reason and health_state(s, NOW) is H.BLOCKED_REVIEW


def test_partial_is_degraded_without_a_streak(src):
    p, s = apply(src, "partial", C.PARTIAL)
    assert p.failure_streak == 0 and health_state(s, NOW) is H.DEGRADED
    _, s = apply(s, "success", None)
    assert health_state(s, NOW) is H.HEALTHY


def test_policy_block_and_skip_do_not_count_as_failures(src):
    _, s = apply(src, "failed", C.SERVER_ERROR)
    p, _ = apply(s, "blocked_policy", C.POLICY)
    assert p.failure_streak == 1 and p.cooldown_until is not None  # running cooldown kept
    p, _ = apply(s, "skipped", None)
    assert p.failure_streak == 1 and p.error_category is C.SERVER_ERROR


def test_stale_and_disabled_states(src):
    assert health_state(replace(src, last_success_at=None), NOW) is H.STALE
    old = iso_z(NOW - timedelta(hours=2 * src.fetch_interval_hours + 1))
    assert health_state(replace(src, last_success_at=old), NOW) is H.STALE
    assert health_state(replace(src, enabled=False), NOW) is H.DISABLED
    assert health_state(replace(src, state="review_required"), NOW) is H.DISABLED


# -- access-barrier detection ----------------------------------------------------------------------
U = "https://example.edu/programme"


@pytest.mark.parametrize(
    "body",
    [
        b"<html><head><title>Just a moment...</title></head><body>cf_chl_opt</body></html>",
        b"<!DOCTYPE html><html><head><title>Attention Required! | Cloudflare</title></head></html>",
        b"<html><head><title>Access Denied</title></head><body>Reference #18.abc</body></html>",
        b"<html><head><title>Sign in to continue</title></head><body><form><input type='password' name=p></form></body></html>",
        b"<html><body><script src='https://geo.captcha-delivery.com/captcha/'></script></body></html>",
        b"<html><head><title>Are you a robot?</title></head><body>verify</body></html>",
    ],
)
def test_barrier_pages_detected(body):
    assert detect_barrier(U, U, "text/html", body)


@pytest.mark.parametrize(
    "body",
    [
        # official pages that merely mention logins/CAPTCHAs, or carry vendor beacons
        b"<html><head><title>Summer School 2027</title></head><body>Apply via the portal login. "
        b"<div class='g-recaptcha'></div><script src='/cdn-cgi/challenge-platform/scripts/jsd/main.js'></script>"
        b"<script src='/_Incapsula_Resource?x'></script></body></html>",
        b"<html><head><title>Login help for applicants</title></head><body>No form here.</body></html>",
        b"<html><head><title>Access to research data: a guide</title></head></html>",
    ],
)
def test_ordinary_pages_not_flagged(body):
    assert detect_barrier(U, U, "text/html", body) is None


def test_login_redirect_and_non_html():
    assert "login" in detect_barrier(U, "https://example.edu/sso/login?next=x", "text/html", b"")
    assert (
        detect_barrier(
            "https://example.edu/login", "https://example.edu/login", "text/html", b"<html></html>"
        )
        is None
    )
    assert (
        detect_barrier(U, U, "application/rss+xml", b"<rss><title>Just a moment</title></rss>")
        is None
    )


# -- Retry-After and crawler identity -------------------------------------------------------------
def test_retry_after_seconds_and_http_date():
    assert _retry_after("120", NOW) == 120.0
    assert _retry_after("Thu, 29 Oct 2026 14:00:00 GMT", NOW) == 7200.0
    assert _retry_after("Wed, 28 Oct 2026 14:00:00 GMT", NOW) == 0.0  # past -> retry now
    assert _retry_after("soon", NOW) is None and _retry_after(None, NOW) is None


def test_user_agent_is_transparent_and_browser_impersonation_rejected():
    ua = AppSettings().effective_user_agent()
    assert ua == "OpenHypergamy/0.1 (+https://github.com/r00tnomade/open-hypergamy)"
    with_contact = AppSettings(crawler_contact="mailto:ops@example.org").effective_user_agent()
    assert with_contact.endswith("; mailto:ops@example.org)")
    assert AppSettings(user_agent="OpenHypergamy/0.1 (+custom)").effective_user_agent() == (
        "OpenHypergamy/0.1 (+custom)"
    )
    for fake in ("Mozilla/5.0 (Macintosh)", "OpenHypergamy/0.1 Chrome/120.0", "  "):
        with pytest.raises(ValueError, match="user_agent"):
            AppSettings(user_agent=fake)
