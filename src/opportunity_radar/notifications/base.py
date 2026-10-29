"""Notification contracts (LLD §5.2). Telegram is the only sink; it is outbound-only."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

# Alert types that must never be dropped for volume reasons.
CRITICAL_TYPES = frozenset(
    {
        "deadline_reminder",
        "deadline_conflict",
        "deadline_stale",
        "deadline_changed",
        "source_health",
    }
)
# Types that may be folded into the weekly digest when a run exceeds its message cap.
DIGESTABLE_TYPES = frozenset({"new_opportunity", "application_opened"})


@dataclass(frozen=True)
class NotificationMessage:
    text: str
    notification_type: str
    entity_type: str
    entity_id: str


@dataclass(frozen=True)
class SendResult:
    ok: bool
    message_id: str | None = None
    error: str | None = None
    retry_after: float | None = None
    permanent: bool = False  # bad token/chat id etc.: do not retry without intervention


class NotificationSink(Protocol):
    def send(self, message: NotificationMessage, idempotency_key: str) -> SendResult: ...
