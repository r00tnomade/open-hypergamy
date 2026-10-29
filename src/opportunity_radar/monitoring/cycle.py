"""Score everything, queue alerts, deliver the outbox. Shared by every `radar run …` job."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field

from opportunity_radar.clock import Clock
from opportunity_radar.config import LoadedConfig
from opportunity_radar.errors import ConfigurationError
from opportunity_radar.monitoring.deadlines import AlertReport, queue_alerts
from opportunity_radar.notifications.base import NotificationMessage, NotificationSink
from opportunity_radar.notifications.outbox import DeliveryReport, Outbox
from opportunity_radar.profile import load_profile_for
from opportunity_radar.scoring.service import ScoreOutcome, rescore_all

SinkFactory = Callable[[], NotificationSink]


class PreviewOutbox:
    """Records what would be queued; used by --dry-run (no database or network writes)."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, NotificationMessage]] = []

    def enqueue(
        self, msg: NotificationMessage, key: str, *, status: str = "pending", note: str = ""
    ) -> bool:
        if status == "pending":
            self.messages.append((key, msg))
        return True


@dataclass
class CycleReport:
    profile_found: bool = True
    outcomes: list[ScoreOutcome] = field(default_factory=list)
    alerts: AlertReport = field(default_factory=AlertReport)
    delivery: DeliveryReport | None = None
    delivery_note: str = ""
    preview: list[tuple[str, NotificationMessage]] = field(default_factory=list)


def score_and_alert(
    conn: sqlite3.Connection,
    cfg: LoadedConfig,
    clock: Clock,
    *,
    sink_factory: SinkFactory | None,
    dry_run: bool = False,
    deliver: bool = True,
) -> CycleReport:
    rep = CycleReport()
    profile = load_profile_for(cfg)
    if profile is None:
        rep.profile_found = False
    else:
        rep.outcomes = rescore_all(conn, cfg, clock, profile)
        if dry_run:
            pv = PreviewOutbox()
            rep.alerts = queue_alerts(conn, cfg, clock, rep.outcomes, pv)  # type: ignore[arg-type]
            rep.preview = pv.messages
            return rep
        outbox = Outbox(conn, clock, cfg.settings.telegram)
        rep.alerts = queue_alerts(conn, cfg, clock, rep.outcomes, outbox)
    if dry_run or not deliver or not cfg.settings.telegram.enabled:
        return rep
    outbox = Outbox(conn, clock, cfg.settings.telegram)
    if sink_factory is None:
        rep.delivery_note = "no notification sink"
        return rep
    try:
        sink = sink_factory()
    except ConfigurationError as e:
        rep.delivery_note = f"not delivered ({e}); messages stay queued"
        return rep
    rep.delivery = outbox.deliver(sink)
    return rep
