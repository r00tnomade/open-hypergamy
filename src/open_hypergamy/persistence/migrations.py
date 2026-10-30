"""Checksum-verified, immutable, ordered SQL migrations (LLD §4.2)."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from open_hypergamy.clock import Clock, iso_compact, iso_z
from open_hypergamy.errors import DatabaseInitializationError, MigrationIntegrityError
from open_hypergamy.persistence.db import backup_to

# Repo-level `migrations/` (LLD §1.3) in an editable install; a built wheel carries the same
# files as `open_hypergamy/_migrations` (pyproject force-include, ADR-014).
_SOURCE_TREE_MIGRATIONS = Path(__file__).resolve().parents[3] / "migrations"
DEFAULT_MIGRATIONS_DIR = (
    _SOURCE_TREE_MIGRATIONS
    if _SOURCE_TREE_MIGRATIONS.is_dir()
    else Path(__file__).resolve().parents[1] / "_migrations"
)
_FILENAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path
    checksum: str


def discover(directory: Path = DEFAULT_MIGRATIONS_DIR) -> list[Migration]:
    if not directory.is_dir():
        raise DatabaseInitializationError(f"migrations directory not found: {directory}")
    found: list[Migration] = []
    for p in sorted(directory.glob("*.sql")):
        parsed = _FILENAME.match(p.name)
        if not parsed:
            raise MigrationIntegrityError(f"bad migration filename: {p.name}")
        checksum = hashlib.sha256(p.read_bytes()).hexdigest()
        found.append(Migration(int(parsed[1]), parsed[2], p, checksum))
    if [m.version for m in found] != list(range(1, len(found) + 1)):
        raise MigrationIntegrityError("migration versions must be contiguous starting at 0001")
    manifest = directory / "migration_manifest.json"
    if manifest.is_file():
        expected = {
            e["version"]: e["sha256"] for e in json.loads(manifest.read_text())["migrations"]
        }
        for m in found:
            if m.version in expected and expected[m.version] != m.checksum:
                raise MigrationIntegrityError(
                    f"migration {m.path.name} does not match migration_manifest.json"
                )
    return found


def applied_versions(conn: sqlite3.Connection) -> dict[int, str]:
    has_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if not has_table:
        return {}
    return {
        r["version"]: r["checksum"]
        for r in conn.execute("SELECT version, checksum FROM schema_migrations")
    }


def schema_version(conn: sqlite3.Connection) -> int:
    return max(applied_versions(conn), default=0)


def verify_applied(conn: sqlite3.Connection, migrations: list[Migration]) -> None:
    by_version = {m.version: m for m in migrations}
    for version, checksum in applied_versions(conn).items():
        m = by_version.get(version)
        if m is None:
            raise MigrationIntegrityError(f"database has unknown migration version {version}")
        if m.checksum != checksum:
            raise MigrationIntegrityError(
                f"checksum mismatch for applied migration {m.path.name}; "
                "applied migrations are immutable"
            )


def pending(conn: sqlite3.Connection, migrations: list[Migration]) -> list[Migration]:
    verify_applied(conn, migrations)
    done = applied_versions(conn)
    return [m for m in migrations if m.version not in done]


def migrate(
    conn: sqlite3.Connection,
    migrations: list[Migration],
    clock: Clock,
    *,
    backup_dir: Path | None = None,
    dry_run: bool = False,
) -> list[Migration]:
    todo = pending(conn, migrations)
    if dry_run or not todo:
        return todo
    if backup_dir is not None and applied_versions(conn):
        backup_to(conn, backup_dir / f"pre-migration-{iso_compact(clock.now_utc())}.sqlite3")
    for m in todo:
        # Each migration + its bookkeeping row commit atomically. Name/checksum are
        # validated filename/hex so literal interpolation is safe.
        script = (
            "BEGIN IMMEDIATE;\n"
            f"{m.path.read_text()}\n"
            "INSERT INTO schema_migrations(version, name, checksum, applied_at) "
            f"VALUES ({m.version}, '{m.name}', '{m.checksum}', '{iso_z(clock.now_utc())}');\n"
            "COMMIT;"
        )
        try:
            conn.executescript(script)
        except sqlite3.Error as e:
            with suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
            raise DatabaseInitializationError(f"migration {m.path.name} failed: {e}") from e
    return todo
