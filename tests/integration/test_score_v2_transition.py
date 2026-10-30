"""score-v1 → score-v2 (ADR-014): one new snapshot per edition, history kept, no duplicate
alerts or actions, stable across restarts, and category preferences behave as specified."""

import yaml
from tests.integration.test_m5_flow import env  # noqa: F401

from open_hypergamy.profile import load_profile
from open_hypergamy.scoring import fit, service


def _counts(env):
    return {
        "snapshots": len(env.q("SELECT 1 FROM score_snapshots")),
        "actions": len(env.q("SELECT 1 FROM action_items")),
        "notifications": len(env.q("SELECT 1 FROM notification_log")),
        "eligibility": len(env.q("SELECT 1 FROM eligibility_assessments")),
    }


def test_upgrade_writes_one_snapshot_keeps_history_and_sends_nothing(env, monkeypatch):
    monkeypatch.setattr(service, "SCORING_VERSION", "score-v1")
    env.discover()
    env.cycle()
    before, sent = _counts(env), len(env.sink.sent)
    [v1] = env.q("SELECT * FROM score_snapshots")
    assert v1["scoring_version"] == "score-v1"

    monkeypatch.setattr(service, "SCORING_VERSION", fit.SCORING_VERSION)  # the upgrade
    rep = env.cycle()
    after = _counts(env)
    assert after["snapshots"] == before["snapshots"] + 1
    assert {k: v for k, v in after.items() if k != "snapshots"} == {
        k: v for k, v in before.items() if k != "snapshots"
    }
    assert rep.alerts.queued == {} and len(env.sink.sent) == sent
    rows = env.q("SELECT scoring_version, fit_score FROM score_snapshots ORDER BY rowid")
    assert [r["scoring_version"] for r in rows] == ["score-v1", "score-v2"]
    assert rows[0]["fit_score"] == v1["fit_score"]  # history is append-only and untouched
    assert rows[1]["fit_score"] == v1["fit_score"]  # no categories: same rules, same number

    for _ in range(3):  # "restarts": every later run is a no-op
        env.clock.advance(hours=1)
        env.cycle()
    assert _counts(env) == after and len(env.sink.sent) == sent


def test_preference_change_rescores_once_without_duplicate_alerts(env):
    env.discover()
    env.cycle()
    base, sent = _counts(env), len(env.sink.sent)
    [prog] = env.q("SELECT category FROM programs")

    path = env.cfg.paths.home / "profile.yaml"
    p = load_profile(path)
    other = "hackathon" if prog["category"] != "hackathon" else "conference"
    data = p.model_dump(mode="json")
    data["preferences"]["categories"] = [other]
    data["profile_version"] = "gui-test-1"
    path.write_text(yaml.safe_dump(data))
    env.cycle()
    after = _counts(env)
    assert after["snapshots"] == base["snapshots"] + 1
    assert after["eligibility"] == base["eligibility"] + 1  # new profile version, same verdict
    assert after["notifications"] == base["notifications"] and len(env.sink.sent) == sent
    [latest] = env.q("SELECT * FROM score_snapshots ORDER BY rowid DESC LIMIT 1")
    assert "OUTSIDE_PREFERRED_CATEGORIES" in latest["reason_codes_json"]

    env.clock.advance(hours=2)  # a later run after a restart
    env.cycle()
    assert _counts(env) == after
