"""Data-directory and database initialization shared by `ohg init` and the onboarding GUI."""

from __future__ import annotations

from dataclasses import dataclass

from open_hypergamy.clock import Clock
from open_hypergamy.config import LoadedConfig
from open_hypergamy.errors import DatabaseInitializationError
from open_hypergamy.persistence import db as dbm
from open_hypergamy.persistence import migrations as mig


@dataclass(frozen=True)
class InitResult:
    created: bool  # the database file did not exist before
    schema_version: int
    applied: int


def needs_init(cfg: LoadedConfig) -> bool:
    """True when the database is missing or has unapplied migrations. Never writes."""
    if not cfg.paths.db.exists():
        return True
    conn = dbm.connect(cfg.paths.db, cfg.settings.database.busy_timeout_ms)
    try:
        return bool(mig.pending(conn, mig.discover()))
    finally:
        conn.close()


def initialize(cfg: LoadedConfig, clock: Clock) -> InitResult:
    """Create the data directory and database and apply migrations (idempotent)."""
    cfg.paths.ensure()
    existed = cfg.paths.db.exists()
    conn = dbm.connect(cfg.paths.db, cfg.settings.database.busy_timeout_ms, create=True)
    try:
        dbm.enable_journal_mode(conn, cfg.settings.database.journal_mode)
        applied = mig.migrate(conn, mig.discover(), clock, backup_dir=cfg.paths.backups)
        problems = dbm.integrity_problems(conn)
        if problems:
            raise DatabaseInitializationError("integrity check failed: " + "; ".join(problems))
        version = mig.schema_version(conn)
    finally:
        conn.close()
    cfg.paths.db.chmod(0o600)
    return InitResult(not existed, version, len(applied))
