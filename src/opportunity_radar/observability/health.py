"""Doctor checks and status collection (LLD §16). No inference requests are made."""

from __future__ import annotations

import socket
import sqlite3
import sys
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

from opportunity_radar.clock import Clock, SystemClock
from opportunity_radar.config import LoadedConfig
from opportunity_radar.errors import RadarError
from opportunity_radar.keychain import get_secret, source_of
from opportunity_radar.llm.ack import ack_is_current
from opportunity_radar.llm.client import LLMClient
from opportunity_radar.monitoring.catchup import job_gaps
from opportunity_radar.persistence import db as dbm
from opportunity_radar.persistence import migrations as mig
from opportunity_radar.persistence.backups import last_restore_check

Level = Literal["ok", "warn", "fail"]


@dataclass(frozen=True)
class Check:
    name: str
    level: Level
    detail: str
    dependency: bool = False  # an unavailable local dependency (exit 5 under --strict)


def _tcp_reachable(base_url: str, timeout: float = 1.5) -> bool:
    u = urlparse(base_url)
    port = u.port or (443 if u.scheme == "https" else 80)
    try:
        with socket.create_connection((u.hostname or "127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def run_doctor(cfg: LoadedConfig, llm_client: LLMClient | None = None) -> list[Check]:
    s = cfg.settings
    checks: list[Check] = []
    v = sys.version_info
    checks.append(
        Check("python", "ok" if v >= (3, 12) else "fail", f"{v.major}.{v.minor}.{v.micro}")
    )
    checks.append(
        Check("data_dir", "ok" if cfg.paths.home.is_dir() else "fail", str(cfg.paths.home))
    )

    if not cfg.paths.db.exists():
        checks.append(Check("database", "fail", f"missing: {cfg.paths.db} (run `radar init`)"))
    else:
        try:
            conn = dbm.connect(cfg.paths.db, s.database.busy_timeout_ms)
            try:
                migrations = mig.discover()
                mig.verify_applied(conn, migrations)
                problems = dbm.integrity_problems(conn)
                n_pending = len(mig.pending(conn, migrations))
                level: Level = "fail" if problems else ("warn" if n_pending else "ok")
                detail = f"schema v{mig.schema_version(conn)}, {n_pending} pending migration(s)"
                checks.append(Check("database", level, "; ".join(problems) or detail))
            finally:
                conn.close()
        except Exception as e:  # doctor reports instead of crashing
            checks.append(Check("database", "fail", str(e)))

    llm = s.llm
    if not llm.enabled or not llm.allow_remote_public_content and llm.provider == "freellmapi":
        checks.append(Check("llm", "ok", "disabled; deterministic processing only"))
    else:
        block = llm.active
        reachable = _tcp_reachable(block.base_url)
        checks.append(
            Check(
                "llm_gateway",
                "ok" if reachable else "warn",
                f"{llm.provider} {block.base_url} {'reachable' if reachable else 'NOT reachable'}",
                dependency=True,
            )
        )
        if llm.provider == "freellmapi":
            key_env = llm.freellmapi.api_key_env
            checks.append(
                Check(
                    "llm_api_key",
                    "ok" if get_secret(key_env) else "warn",
                    f"${key_env} {'set (' + source_of(key_env) + ')' if get_secret(key_env) else 'not set'}",
                )
            )
            checks.append(
                Check(
                    "llm_profile",
                    "ok" if block.model == "auto:radar-free" else "warn",
                    f"model alias {block.model!r}; free-only chain is operator-attested "
                    "(cannot be verified by this tool)",
                )
            )
            if reachable:  # models listing is not an inference request
                from opportunity_radar.extraction.llm_extractor import build_client

                client = llm_client or build_client(cfg)
                try:
                    listed = block.model in client.list_models()
                    detail = (
                        f"alias {block.model!r} is listed by the gateway"
                        if listed
                        else f"alias {block.model!r} is NOT listed; create the `radar-free` chain"
                    )
                    checks.append(Check("llm_alias", "ok" if listed else "warn", detail))
                except RadarError as e:
                    checks.append(Check("llm_alias", "warn", f"could not list models: {e}"))
            acked = ack_is_current(cfg.paths.llm_ack, llm.provider)
            checks.append(
                Check(
                    "llm_acknowledgement",
                    "ok" if acked else "warn",
                    "recorded" if acked else "not recorded; required before first LLM request",
                )
            )
            checks.append(
                Check(
                    "llm_privacy",
                    "warn",
                    "prompts (public excerpts only) may be forwarded to upstream providers",
                )
            )
    if s.telegram.enabled:
        have = bool(get_secret("TELEGRAM_BOT_TOKEN")) and bool(get_secret("TELEGRAM_CHAT_ID"))
        checks.append(
            Check(
                "telegram",
                "ok" if have else "warn",
                "token and chat id configured" if have else "enabled but token/chat id not set",
            )
        )
    else:
        checks.append(Check("telegram", "ok", "disabled"))
    return checks


def collect_status(
    conn: sqlite3.Connection, cfg: LoadedConfig, clock: Clock | None = None
) -> dict[str, Any]:
    def one(sql: str) -> Any:
        return conn.execute(sql).fetchone()[0]

    last_jobs = {
        r["job_type"]: {"started_at": r["started_at"], "status": r["status"]}
        for r in conn.execute(
            "SELECT job_type, started_at, status FROM job_runs jr WHERE started_at = "
            "(SELECT MAX(started_at) FROM job_runs WHERE job_type = jr.job_type)"
        )
    }
    backups = sorted(cfg.paths.backups.glob("*.sqlite3")) if cfg.paths.backups.is_dir() else []
    return {
        "schema_version": mig.schema_version(conn),
        "database": str(cfg.paths.db),
        "sources_configured": one("SELECT COUNT(*) FROM sources"),
        "sources_enabled": one(
            "SELECT COUNT(*) FROM sources WHERE enabled = 1 AND state = 'active'"
        ),
        "sources_failing_2plus": one("SELECT COUNT(*) FROM sources WHERE failure_streak >= 2"),
        "review_pending": one("SELECT COUNT(*) FROM review_queue WHERE state = 'pending'"),
        "notifications_pending": one(
            "SELECT COUNT(*) FROM notification_log WHERE status IN ('pending','sending')"
        ),
        "last_notification_error": (
            conn.execute(
                "SELECT last_error_redacted FROM notification_log WHERE last_error_redacted IS NOT NULL "
                "ORDER BY last_attempt_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
            or [None]
        )[0],
        "notifications_failed": one(
            "SELECT COUNT(*) FROM notification_log WHERE status = 'failed'"
        ),
        "last_jobs": last_jobs,
        "latest_backup": backups[-1].name if backups else None,
        "backups_kept": len(backups),
        "latest_restore_check": last_restore_check(cfg.paths.backups),
        "overdue_jobs": [g.describe() for g in job_gaps(conn, cfg, clock or SystemClock())],
    }
