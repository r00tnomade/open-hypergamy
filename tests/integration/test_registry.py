from datetime import UTC, datetime
from pathlib import Path

import pytest

from opportunity_radar.clock import FixedClock
from opportunity_radar.errors import ConfigurationError
from opportunity_radar.persistence import db as dbm
from opportunity_radar.persistence import migrations as mig
from opportunity_radar.persistence.repositories.sources import SourceRepository
from opportunity_radar.sources.registry import load_source_files

CLOCK = FixedClock(datetime(2026, 10, 29, 12, 0, tzinfo=UTC))

GOOD = """
version: 1
sources:
  - source_key: example-student-programmes
    name: Example Institute Student Programmes
    organization: {name: Example Institute, canonical_domain: example.edu, country_code: DE}
    canonical_url: https://example.edu/students/opportunities?utm_source=x
    domain: example.edu
    source_type: official_programme_index
    adapter_type: html
    trust_tier: t2_official_org
    allow_paths: [/students]
    deny_paths: [/login]
    robots_policy_checked_at: 2026-10-01
    terms_review_note: "Reviewed 2026-10-01: public pages, no crawl restrictions beyond robots."
    discovery_policy: {follow_internal_links: true, max_depth: 1, max_pages_per_run: 20}
"""


def write(tmp_path: Path, text: str, name="s.yaml") -> Path:
    p = tmp_path / name
    p.write_text(text)
    return p


@pytest.fixture
def repo(tmp_path):
    conn = dbm.connect(tmp_path / "t.sqlite3", create=True)
    mig.migrate(conn, mig.discover(), CLOCK)
    yield SourceRepository(conn, CLOCK)
    conn.close()


def test_valid_file_loads_and_canonicalizes(tmp_path):
    [c] = load_source_files([write(tmp_path, GOOD)])
    assert c.canonical_url == "https://example.edu/students/opportunities"
    assert (
        c.allowed_domains == ["example.edu"] and c.policy_review_satisfied and not c.discovery_only
    )


def test_import_is_idempotent_and_preserves_health(repo):
    cfgs = load_source_files([Path(__file__).parent.parent / "fixtures" / "sources_good.yaml"])
    r1 = repo.import_configs(cfgs)
    assert r1.created == ["example-student-programmes"] and r1.review_required == []
    src = repo.get("example-student-programmes")
    assert src.enabled and src.state == "active"
    repo.conn.execute("UPDATE sources SET failure_streak=3, etag='e', last_content_hash='h', "
                      "last_success_at='2026-10-01T00:00:00Z' WHERE id=?", (src.id,))  # fmt: skip
    cfgs[0].name = "Renamed"
    r2 = repo.import_configs(cfgs)
    assert r2.created == [] and r2.updated == ["example-student-programmes"]
    again = repo.get("example-student-programmes")
    assert again.name == "Renamed" and again.failure_streak == 3
    assert again.etag == "e" and again.last_content_hash == "h" and again.last_success_at
    assert repo.coverage()["configured"] == 1


def test_missing_policy_review_means_disabled_review_required(repo, tmp_path):
    text = GOOD.replace("    robots_policy_checked_at: 2026-10-01\n", "").replace(
        'terms_review_note: "Reviewed 2026-10-01: public pages, no crawl restrictions beyond robots."',
        "",
    )
    rep = repo.import_configs(load_source_files([write(tmp_path, text)]))
    src = repo.get("example-student-programmes")
    assert rep.review_required == ["example-student-programmes"]
    assert not src.enabled and src.state == "review_required"
    assert repo.list_due("2099-01-01T00:00:00Z") == []  # never polled


def test_override_policy_review_is_audited(repo, tmp_path):
    text = GOOD.replace("    robots_policy_checked_at: 2026-10-01\n", "")
    rep = repo.import_configs(
        load_source_files([write(tmp_path, text)]), override_policy_review=True
    )
    assert rep.overridden == ["example-student-programmes"]
    row = repo.conn.execute("SELECT enabled, state, policy_override_at FROM sources").fetchone()
    assert (
        row["enabled"] == 1
        and row["state"] == "active"
        and row["policy_override_at"] == "2026-10-29T12:00:00Z"
    )


def test_reimport_after_review_activates_source(repo, tmp_path):
    bare = GOOD.replace("    robots_policy_checked_at: 2026-10-01\n", "")
    repo.import_configs(load_source_files([write(tmp_path, bare)]))
    assert repo.get("example-student-programmes").state == "review_required"
    repo.import_configs(load_source_files([write(tmp_path, GOOD)]))
    assert repo.get("example-student-programmes").state == "active"


def test_enable_requires_override_for_review_required(repo):
    key = repo.add_manual(
        "https://example.org/page", trust_tier="t4_aggregator", discovery_only=True, name=None
    )
    with pytest.raises(ConfigurationError, match="policy review"):
        repo.set_enabled(key, True)
    assert repo.set_enabled(key, True, override_policy_review=True).enabled
    assert repo.get(key).discovery_only


def test_dry_run_changes_nothing(repo, tmp_path):
    rep = repo.import_configs(load_source_files([write(tmp_path, GOOD)]), dry_run=True)
    assert rep.created and repo.coverage()["configured"] == 0


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (
            ("https://example.edu/students/opportunities?utm_source=x", "http://127.0.0.1/admin"),
            "non-public",
        ),
        (
            (
                "https://example.edu/students/opportunities?utm_source=x",
                "https://user:pw@example.edu/",
            ),
            "credentials",
        ),
        (
            ("https://example.edu/students/opportunities?utm_source=x", "ftp://example.edu/x"),
            "scheme",
        ),
        (("domain: example.edu", "domain: other.edu"), "does not match"),
        (("trust_tier: t2_official_org", "trust_tier: t9_made_up"), "trust_tier"),
        (("[/students]", "[students]"), "start with"),
        (("adapter_type: html", "adapter_type: playwright"), "playwright"),
        (
            (
                "source_type: official_programme_index",
                "source_type: official_programme_index\n    surprise: 1",
            ),
            "surprise",
        ),
        ("fetch_interval_hours", None),
    ],
)
def test_validation_rejects(tmp_path, edit, message):
    text = GOOD + ("    fetch_interval_hours: 0\n" if edit == "fetch_interval_hours" else "")
    if edit != "fetch_interval_hours":
        assert edit[0] in text
        text = text.replace(*edit)
    else:
        message = "greater than 0"
    with pytest.raises(ConfigurationError, match=message):
        load_source_files([write(tmp_path, text)])


def test_playwright_allowed_only_when_allowlisted(tmp_path):
    text = GOOD.replace("adapter_type: html", "adapter_type: playwright")
    assert load_source_files(
        [write(tmp_path, text)], playwright_allowed=["example-student-programmes"]
    )


def test_duplicates_across_files_detected(tmp_path):
    a, b = write(tmp_path, GOOD, "a.yaml"), write(tmp_path, GOOD, "b.yaml")
    with pytest.raises(ConfigurationError, match="duplicate source_key"):
        load_source_files([a, b])
    other_key = GOOD.replace("example-student-programmes", "another-key-here")
    with pytest.raises(ConfigurationError, match="duplicate canonical_url"):
        load_source_files([a, write(tmp_path, other_key, "c.yaml")])


def test_t4_t5_are_discovery_only_unless_authority_documented(tmp_path):
    t4 = GOOD.replace("t2_official_org", "t4_aggregator")
    [c] = load_source_files([write(tmp_path, t4)])
    assert c.discovery_only
    [c2] = load_source_files(
        [
            write(
                tmp_path,
                t4.replace(
                    "source_type:",
                    'authority_scope: "Deadlines for its own listings"\n    source_type:',
                ),
                "x.yaml",
            )
        ]
    )
    assert not c2.discovery_only


def test_auto_promotion_of_outbound_links_rejected(tmp_path):
    text = GOOD.replace(
        "max_pages_per_run: 20}",
        "max_pages_per_run: 20, promote_outbound_links_automatically: true}",
    )
    with pytest.raises(ConfigurationError, match="never be promoted|automatically"):
        load_source_files([write(tmp_path, text)])
