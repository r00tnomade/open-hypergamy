"""Backup retention and restore checks (LLD §11.3 of the HLD, §14.4)."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from open_hypergamy.clock import iso_z
from open_hypergamy.errors import DatabaseInitializationError
from open_hypergamy.persistence import db as dbm
from open_hypergamy.persistence import migrations as mig

_NAME = re.compile(r"^ohg-(\d{8}T\d{6}Z)\.sqlite3$")
CHECK_FILE = ".last_restore_check.json"


@dataclass(frozen=True)
class BackupFile:
    path: Path
    taken: datetime


def list_backups(directory: Path) -> list[BackupFile]:
    out = []
    for p in directory.glob("ohg-*.sqlite3") if directory.is_dir() else []:
        m = _NAME.match(p.name)
        if m:
            out.append(BackupFile(p, datetime.strptime(m[1], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)))
    return sorted(out, key=lambda b: b.taken)


def plan_prune(
    files: list[BackupFile], now: datetime, keep_daily: int, keep_weekly: int
) -> tuple[list[BackupFile], list[BackupFile]]:
    """Newest backup per day for `keep_daily` days, newest per ISO week back `keep_weekly` weeks,
    nothing older; the single newest backup is always kept. Returns (keep, remove)."""
    today = now.date()
    daily_cut = today - timedelta(days=keep_daily)
    weekly_cut = today - timedelta(weeks=keep_weekly)
    keep: dict[str, BackupFile] = {}
    for b in sorted(files, key=lambda f: f.taken):  # later files overwrite earlier ones per bucket
        d: date = b.taken.date()
        if d >= daily_cut:
            keep[f"d{d}"] = b
        elif d >= weekly_cut:
            iso = d.isocalendar()
            keep[f"w{iso.year}-{iso.week}"] = b
    if files:
        newest = max(files, key=lambda f: f.taken)
        keep[f"newest-{newest.path.name}"] = newest
    kept = {b.path for b in keep.values()}
    return sorted(kept_files := [b for b in files if b.path in kept], key=lambda f: f.taken), [
        b for b in files if b not in kept_files
    ]


def prune(
    directory: Path, now: datetime, keep_daily: int, keep_weekly: int, *, dry_run: bool = False
) -> tuple[int, list[Path]]:
    keep, remove = plan_prune(list_backups(directory), now, keep_daily, keep_weekly)
    if not dry_run:
        for b in remove:
            for suffix in ("", "-wal", "-shm"):
                Path(str(b.path) + suffix).unlink(missing_ok=True)
    return len(keep), [b.path for b in remove]


def check_backup(path: Path) -> int:
    """Open read-only, verify integrity and migration checksums; returns the schema version."""
    if not path.is_file():
        raise DatabaseInitializationError(f"backup not found: {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        problems = dbm.integrity_problems(conn)
        mig.verify_applied(conn, mig.discover())
        version = mig.schema_version(conn)
    except sqlite3.Error as e:
        raise DatabaseInitializationError(f"not a valid SQLite backup: {e}") from e
    finally:
        conn.close()
    if problems:
        raise DatabaseInitializationError("backup is corrupt: " + "; ".join(problems))
    return version


def record_restore_check(backups_dir: Path, path: Path, version: int, now: datetime) -> None:
    backups_dir.mkdir(parents=True, exist_ok=True)
    (backups_dir / CHECK_FILE).write_text(
        json.dumps({"checked_at": iso_z(now), "backup": path.name, "schema_version": version})
    )


def last_restore_check(backups_dir: Path) -> dict[str, object] | None:
    try:
        data: dict[str, object] = json.loads((backups_dir / CHECK_FILE).read_text())
        return data
    except (OSError, ValueError):
        return None


def restore_to(backup: Path, dest: Path) -> int:
    """Copy a verified backup to a NEW path using the backup API. Never overwrites anything."""
    version = check_backup(backup)
    if dest.exists():
        raise DatabaseInitializationError(f"refusing to overwrite existing file: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{backup}?mode=ro", uri=True)
    target = sqlite3.connect(dest)
    try:
        src.backup(target)
    finally:
        target.close()
        src.close()
    dest.chmod(0o600)
    return version
