"""Idempotent notification outbox over `notification_log` (LLD §13.4, §13.5).

A row is written *before* sending (`pending`), moved to `sending`, then `sent`, back to
`pending` with a retry time, or `failed`. Delivery is at-least-once: a crash between Telegram
accepting a message and the local `sent` update can duplicate it once.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from opportunity_radar.clock import Clock, iso_z
from opportunity_radar.config import TelegramSettings
from opportunity_radar.notifications.base import (
    CRITICAL_TYPES,
    DIGESTABLE_TYPES,
    NotificationMessage,
    NotificationSink,
)
from opportunity_radar.observability.logging import redact
from opportunity_radar.persistence.db import transaction

STUCK_SENDING_MINUTES = 10


@dataclass
class DeliveryReport:
    sent: int = 0
    failed: int = 0
    retry_scheduled: int = 0
    suppressed: int = 0
    deferred: int = 0


class Outbox:
    def __init__(self, conn: sqlite3.Connection, clock: Clock, settings: TelegramSettings) -> None:
        self.conn, self.clock, self.s = conn, clock, settings

    @property
    def now(self) -> str:
        return iso_z(self.clock.now_utc())

    def enqueue(
        self, msg: NotificationMessage, key: str, *, status: str = "pending", note: str = ""
    ) -> bool:
        """True if newly queued; False if this idempotency key was already used."""
        with transaction(self.conn):
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO notification_log(id, channel, notification_type, entity_type, "
                "entity_id, idempotency_key, payload_hash, message_preview, message_text, status, "
                "created_at, last_error_redacted) VALUES (?, 'telegram', ?,?,?,?,?,?,?,?,?,?)",
                (
                    str(uuid.uuid4()),
                    msg.notification_type,
                    msg.entity_type,
                    msg.entity_id,
                    key,
                    hashlib.sha256(msg.text.encode()).hexdigest(),
                    msg.text[:160],
                    msg.text,
                    status,
                    self.now,
                    note or None,
                ),
            )
            return cur.rowcount == 1

    def has_key(self, key: str) -> bool:
        return (
            self.conn.execute(
                "SELECT 1 FROM notification_log WHERE idempotency_key=?", (key,)
            ).fetchone()
            is not None
        )

    def counts(self) -> dict[str, int]:
        return {
            r[0]: r[1]
            for r in self.conn.execute(
                "SELECT status, COUNT(*) FROM notification_log GROUP BY status"
            )
        }

    def requeue_failed(self) -> int:
        with transaction(self.conn):
            return self.conn.execute(
                "UPDATE notification_log SET status='pending', attempts=0, next_retry_at=NULL "
                "WHERE status='failed' AND message_text != ''"
            ).rowcount

    def deliver(
        self,
        sink: NotificationSink,
        *,
        sleep: Callable[[float], None] = time.sleep,
        max_messages: int | None = None,
    ) -> DeliveryReport:
        cap = max_messages if max_messages is not None else self.s.maximum_messages_per_run
        report = DeliveryReport()
        now_dt = self.clock.now_utc()
        stuck = iso_z(now_dt - timedelta(minutes=STUCK_SENDING_MINUTES))
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE notification_log SET status='pending' WHERE status='sending' "
                "AND last_attempt_at < ?",
                (stuck,),
            )
        rows = self.conn.execute(
            "SELECT * FROM notification_log WHERE status='pending' AND message_text != '' AND "
            "(next_retry_at IS NULL OR next_retry_at <= ?) ORDER BY created_at, rowid",
            (self.now,),
        ).fetchall()
        rows.sort(
            key=lambda r: r["notification_type"] not in CRITICAL_TYPES
        )  # stable: critical first
        sent_this_run = 0
        for r in rows:
            if sent_this_run >= cap:
                if r["notification_type"] in DIGESTABLE_TYPES:
                    with transaction(self.conn):
                        self.conn.execute(
                            "UPDATE notification_log SET status='suppressed', "
                            "last_error_redacted='grouped into weekly digest' WHERE id=?",
                            (r["id"],),
                        )
                    report.suppressed += 1
                else:
                    report.deferred += 1
                continue
            if sent_this_run:
                sleep(self.s.send_delay_seconds)
            with transaction(self.conn):
                self.conn.execute(
                    "UPDATE notification_log SET status='sending', attempts=attempts+1, "
                    "last_attempt_at=? WHERE id=?",
                    (self.now, r["id"]),
                )
            res = sink.send(
                NotificationMessage(
                    r["message_text"], r["notification_type"], r["entity_type"], r["entity_id"]
                ),
                r["idempotency_key"],
            )
            sent_this_run += 1
            attempts = r["attempts"] + 1
            with transaction(self.conn):
                if res.ok:
                    self.conn.execute(
                        "UPDATE notification_log SET status='sent', sent_at=?, "
                        "telegram_message_id=?, last_error_redacted=NULL WHERE id=?",
                        (self.now, res.message_id, r["id"]),
                    )
                    report.sent += 1
                elif res.permanent or attempts >= self.s.retry_limit:
                    self.conn.execute(
                        "UPDATE notification_log SET status='failed', last_error_redacted=? WHERE id=?",
                        (redact(res.error or "failed")[:300], r["id"]),
                    )
                    report.failed += 1
                else:
                    wait = (
                        res.retry_after
                        if res.retry_after is not None
                        else min(2**attempts * 60, 3600)
                    )
                    self.conn.execute(
                        "UPDATE notification_log SET status='pending', next_retry_at=?, "
                        "last_error_redacted=? WHERE id=?",
                        (
                            iso_z(now_dt + timedelta(seconds=wait)),
                            redact(res.error or "")[:300],
                            r["id"],
                        ),
                    )
                    report.retry_scheduled += 1
        return report
