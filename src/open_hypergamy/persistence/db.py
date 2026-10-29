"""SQLite connection factory and helpers (LLD §4.2)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

from open_hypergamy.errors import DatabaseInitializationError


def connect(path: Path, busy_timeout_ms: int = 5000, *, create: bool = False) -> sqlite3.Connection:
    if not create and not path.exists():
        raise DatabaseInitializationError(f"database not found: {path} (run `ohg init`)")
    try:
        # isolation_level=None: transactions are explicit (see `transaction`).
        conn = sqlite3.connect(path, isolation_level=None, timeout=busy_timeout_ms / 1000)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    except sqlite3.Error as e:
        raise DatabaseInitializationError(f"cannot open database {path}: {e}") from e
    return conn


def enable_journal_mode(conn: sqlite3.Connection, mode: str = "WAL") -> None:
    row = conn.execute(f"PRAGMA journal_mode = {mode}").fetchone()
    if str(row[0]).lower() != mode.lower():
        raise DatabaseInitializationError(f"could not enable journal_mode={mode}, got {row[0]}")


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Short write transaction. Never perform network or LLM I/O inside."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        with suppress(sqlite3.Error):
            conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def integrity_problems(conn: sqlite3.Connection) -> list[str]:
    problems = [r[0] for r in conn.execute("PRAGMA integrity_check") if r[0] != "ok"]
    for r in conn.execute("PRAGMA foreign_key_check"):
        problems.append(f"foreign key violation in {r[0]} rowid={r[1]} -> {r[2]}")
    return problems


def backup_to(conn: sqlite3.Connection, dest: Path) -> list[str]:
    """Consistent online backup via the SQLite backup API; returns integrity problems."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise DatabaseInitializationError(f"refusing to overwrite existing file: {dest}")
    target = sqlite3.connect(dest)
    try:
        conn.backup(target)
        # A backup is a standalone file: no -wal/-shm sidecars, safe to open read-only.
        target.execute("PRAGMA journal_mode = DELETE")
        target.row_factory = sqlite3.Row
        problems = integrity_problems(target)
    finally:
        target.close()
    dest.chmod(0o600)
    return problems
