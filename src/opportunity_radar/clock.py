"""Injected time source so tests are deterministic (LLD §4.2)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol


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
