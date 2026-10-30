"""Source health: error categories, circuit-breaker planning and derived state (ADR-009).

Pure functions only; `SourceRepository.record_check` persists what `plan_check` returns.

Circuit breaker, per source:
  closed     HEALTHY / DEGRADED: polled on its interval; failures back off 1 h, 2 h, 4 h ...
  open       COOLDOWN: after a 429/5xx, or `cooldown_after_failures` transient failures in a row.
             Not polled (scheduled or manual) until `cooldown_until`; Retry-After extends it.
  half-open  the first check after the cooldown: success closes it, failure re-opens it longer.
  held       BLOCKED_REVIEW: 401/403, a 200 challenge/login page, 410, or repeated 404. Never
             retried automatically; `ohg sources unblock` after a human has looked.
A failure only ever changes health columns: facts, observations and last-known content stay.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from open_hypergamy.clock import iso_z
from open_hypergamy.domain.enums import ErrorCategory, SourceHealthState
from open_hypergamy.sources.base import SourceRecord

_NETWORK_CODES = {"fetch_timeout", "network_error", "egress_unavailable"}
_CONTENT_CODES = {"parse_error", "unsupported_content_type", "content_too_large"}
_HOLD = {
    ErrorCategory.ACCESS_DENIED,
    ErrorCategory.ACCESS_BARRIER,
    ErrorCategory.RENDERING_REQUIRED,
    ErrorCategory.GONE,
}
_COOL_NOW = {ErrorCategory.RATE_LIMITED, ErrorCategory.SERVER_ERROR}
_OK = {"success", "not_modified", "partial"}


def categorize(
    status: str, error_code: str | None, http_status: int | None
) -> ErrorCategory | None:
    if status in ("success", "not_modified", "skipped"):
        return None
    if status == "partial":
        return ErrorCategory.PARTIAL
    if status == "blocked_policy":
        return ErrorCategory.POLICY
    if error_code == "access_barrier":
        return ErrorCategory.ACCESS_BARRIER
    if error_code == "rendering_required":
        return ErrorCategory.RENDERING_REQUIRED
    if error_code == "host_cooldown":
        return ErrorCategory.RATE_LIMITED
    if error_code in _NETWORK_CODES or http_status == 408:
        return ErrorCategory.NETWORK
    if error_code in _CONTENT_CODES:
        return ErrorCategory.CONTENT
    if http_status is not None:
        if http_status in (401, 403, 451):
            return ErrorCategory.ACCESS_DENIED
        if http_status == 429:
            return ErrorCategory.RATE_LIMITED
        if http_status == 404:
            return ErrorCategory.NOT_FOUND
        if http_status == 410:
            return ErrorCategory.GONE
        if http_status >= 500:
            return ErrorCategory.SERVER_ERROR
        return ErrorCategory.HTTP_ERROR
    return ErrorCategory.INTERNAL


@dataclass(frozen=True)
class HealthPolicy:
    cooldown_after_failures: int = 3
    not_found_review_after: int = 2
    max_cooldown_hours: int = 168
    max_tracked_pages: int = 200


@dataclass(frozen=True)
class HealthUpdate:
    failure_streak: int
    next_due_at: datetime
    cooldown_until: datetime | None
    blocked_reason: str | None
    error_category: ErrorCategory | None


def plan_check(
    source: SourceRecord,
    status: str,
    category: ErrorCategory | None,
    now: datetime,
    *,
    policy: HealthPolicy,
    retry_after_seconds: float | None = None,
    detail: str | None = None,
) -> HealthUpdate:
    interval = timedelta(hours=source.fetch_interval_hours)
    if status in _OK:
        return HealthUpdate(0, now + interval, None, None, category)
    if status in ("blocked_policy", "skipped"):  # not a source failure; retry next interval
        prior = _parse(source.cooldown_until)
        return HealthUpdate(
            source.failure_streak,
            now + interval,
            prior if prior and prior > now else None,
            source.blocked_reason,
            category if status == "blocked_policy" else _category(source.last_error_category),
        )
    streak = source.failure_streak + 1
    backoff = timedelta(hours=min(2 ** (streak - 1), source.fetch_interval_hours))
    blocked: str | None = None
    if category in _HOLD or (
        category is ErrorCategory.NOT_FOUND and streak >= policy.not_found_review_after
    ):
        blocked = f"{category}: {detail}" if detail else str(category)
    cooldown: datetime | None = None
    if blocked is None and (category in _COOL_NOW or streak >= policy.cooldown_after_failures):
        duration = backoff
        if retry_after_seconds is not None:
            duration = max(duration, timedelta(seconds=retry_after_seconds))
        duration = min(duration, timedelta(hours=policy.max_cooldown_hours))
        cooldown = now + duration
    return HealthUpdate(streak, cooldown or now + backoff, cooldown, blocked, category)


def health_state(source: SourceRecord, now: datetime) -> SourceHealthState:
    if not source.enabled or source.state != "active":
        return SourceHealthState.DISABLED
    if source.blocked_reason:
        return SourceHealthState.BLOCKED_REVIEW
    cooldown = _parse(source.cooldown_until)
    if cooldown and cooldown > now:
        return SourceHealthState.COOLDOWN
    last_ok = _parse(source.last_success_at)
    if last_ok is None or last_ok < now - 2 * timedelta(hours=source.fetch_interval_hours):
        return SourceHealthState.STALE
    if source.failure_streak > 0 or source.last_error_category:
        return SourceHealthState.DEGRADED
    return SourceHealthState.HEALTHY


def in_cooldown(source: SourceRecord, now: datetime) -> bool:
    cooldown = _parse(source.cooldown_until)
    return cooldown is not None and cooldown > now


def iso_or_none(value: datetime | None) -> str | None:
    return iso_z(value) if value else None


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _category(value: str | None) -> ErrorCategory | None:
    return ErrorCategory(value) if value else None
