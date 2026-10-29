import shutil
import sqlite3
from datetime import UTC, datetime

import pytest

from opportunity_radar.clock import FixedClock
from opportunity_radar.errors import MigrationIntegrityError
from opportunity_radar.persistence import db as dbm
from opportunity_radar.persistence import migrations as mig

CLOCK = FixedClock(datetime(2026, 10, 29, 12, 0, tzinfo=UTC))


@pytest.fixture
def conn(tmp_path):
    c = dbm.connect(tmp_path / "t.sqlite3", create=True)
    yield c
    c.close()


def test_apply_is_repeatable(conn):
    ms = mig.discover()
    assert len(mig.migrate(conn, ms, CLOCK)) == 1
    assert mig.migrate(conn, ms, CLOCK) == []
    assert mig.schema_version(conn) == 1
    row = conn.execute("SELECT checksum, applied_at FROM schema_migrations").fetchone()
    assert row["checksum"] == ms[0].checksum and row["applied_at"] == "2026-10-29T12:00:00Z"


def test_expected_tables_and_fk_enforced(conn):
    mig.migrate(conn, mig.discover(), CLOCK)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "sources",
        "programs",
        "editions",
        "deadlines",
        "claims",
        "review_queue",
        "notification_log",
        "llm_cache",
        "schema_migrations",
    } <= tables
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO source_check_runs(id, source_id, started_at, status) "
            "VALUES ('a','missing','t','success')"
        )


def test_claims_requires_exactly_one_target(conn):
    mig.migrate(conn, mig.discover(), CLOCK)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO claims(id, field_name, proposed_value_json, source_url, "
            "source_trust_tier, extraction_method, created_at) "
            "VALUES ('c','f','{}','u','t1','rule','t')"
        )


def test_applied_migration_checksum_mismatch_is_fatal(conn, tmp_path):
    d = tmp_path / "m"
    shutil.copytree(mig.DEFAULT_MIGRATIONS_DIR, d)
    mig.migrate(conn, mig.discover(d), CLOCK)
    (d / "0001_initial.sql").write_text((d / "0001_initial.sql").read_text() + "\n-- tampered\n")
    (d / "migration_manifest.json").unlink()  # isolate the DB-checksum check
    with pytest.raises(MigrationIntegrityError, match="checksum mismatch"):
        mig.pending(conn, mig.discover(d))


def test_manifest_mismatch_is_fatal(tmp_path):
    d = tmp_path / "m"
    shutil.copytree(mig.DEFAULT_MIGRATIONS_DIR, d)
    (d / "0001_initial.sql").write_text("-- changed\n")
    with pytest.raises(MigrationIntegrityError, match="manifest"):
        mig.discover(d)


def test_failed_migration_rolls_back(conn, tmp_path):
    d = tmp_path / "m"
    d.mkdir()
    (d / "0001_bad.sql").write_text(
        "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, "
        "name TEXT, checksum TEXT, applied_at TEXT);\nCREATE TABLE x(;"
    )
    with pytest.raises(Exception, match="failed"):
        mig.migrate(conn, mig.discover(d), CLOCK)
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='schema_migrations'"
        ).fetchone()[0]
        == 0
    )


def test_backup_is_consistent_and_never_overwrites(conn, tmp_path):
    mig.migrate(conn, mig.discover(), CLOCK)
    dest = tmp_path / "b" / "backup.sqlite3"
    assert dbm.backup_to(conn, dest) == []
    assert (dest.stat().st_mode & 0o777) == 0o600
    with pytest.raises(Exception, match="overwrite"):
        dbm.backup_to(conn, dest)


def test_transaction_rolls_back_on_error(conn):
    mig.migrate(conn, mig.discover(), CLOCK)
    with pytest.raises(RuntimeError), dbm.transaction(conn):
        conn.execute(
            "INSERT INTO organizations(id,name,created_at,updated_at) VALUES ('o','n','t','t')"
        )
        raise RuntimeError
    assert conn.execute("SELECT COUNT(*) FROM organizations").fetchone()[0] == 0
