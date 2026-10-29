"""Injected time source so tests are deterministic (LLD §4.2)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class Clock(Protocol):
    def now_utc(self) -> datetime: ...


class SystemClock:
    def now_utc(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    def __init__(self, now: datetime) -> None:
        if now.tzinfo is None:
            raise ValueError("FixedClock requires a timezone-aware datetime")
        self._now = now.astimezone(UTC)

    def now_utc(self) -> datetime:
        return self._now


def iso_compact(dt: datetime) -> str:
    """Filename-safe UTC stamp, e.g. 20261029T120000Z."""
    return iso_z(dt).replace("-", "").replace(":", "")


def iso_z(dt: datetime) -> str:
    """Persisted timestamp format: UTC ISO-8601 with a `Z` suffix."""
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


_local_tz = ZoneInfo("Europe/Berlin")


def set_local_timezone(name: str) -> None:
    """Zone used for "today" in date-only arithmetic (config: app.timezone)."""
    global _local_tz
    try:
        _local_tz = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ValueError(f"unknown timezone {name!r}") from e


def local_today(dt: datetime) -> date:
    """The user's calendar date at `dt`. Date-only deadlines have no timezone of their own, so
    they are compared with the local date, not the UTC date (which lags local midnight by 1-2 h)."""
    return dt.astimezone(_local_tz).date()
