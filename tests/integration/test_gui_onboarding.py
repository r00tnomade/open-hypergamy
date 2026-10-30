"""Onboarding GUI service behaviour through the HTTP layer (ADR-014). No network, no Keychain."""

import json
import stat
from pathlib import Path

import yaml
from tests.helpers_gui import BAD_TOKEN, GOOD_TOKEN, PROFILE, FakeLLM, fake_keychain, gui, make_gui  # noqa: F401

from open_hypergamy import settings_store
from open_hypergamy.config import ScoringWeights, load_config, resolve_home
from open_hypergamy.domain.enums import EligibilityStatus
from open_hypergamy.profile import load_profile, load_profile_for
from open_hypergamy.scoring.fit import compute_fit


def _home():
    return resolve_home()


def _onboard(c, prefs=None):
    c.post("/api/profile", PROFILE)
    c.post("/api/preferences", prefs or {"everything": True, "formats": ["online"]})


# --- first run, existing install, resume -------------------------------------------------------


def test_first_run_initializes_and_saves_profile_through_profile_service(gui):
    home = _home()
    assert (home / "open_hypergamy.sqlite3").exists()  # start() ran the same init as `ohg init`
    c = gui.client()
    snap = c.get("/api/state")
    assert snap["profile"] is None and snap["onboarding"]["existing_install"] is False
    assert snap["onboarding"]["current_step"] == "welcome"

    out = c.post("/api/profile", PROFILE)["profile"]
    assert out["country"] == "DE" and out["research_tags"] == ["robotics", "reinforcement_learning"]
    path = home / "profile.yaml"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    p = load_profile(path)  # the CLI's own loader accepts what the GUI wrote
    assert p.academic.degree_level == "bachelor" and p.preferences.primary_regions == ["DE"]
    assert p.profile_version.startswith("gui-")
    assert c.get("/api/state")["onboarding"]["steps"]["profile"] == "done"


def test_existing_installation_is_adopted_and_prefilled(fake_keychain):
    home = _home()
    home.mkdir(parents=True)
    (home / "profile.yaml").write_text(
        (Path(__file__).parents[1] / "fixtures" / "profile.yaml").read_text()
    )
    g = make_gui()
    snap = g.client().get("/api/state")
    assert snap["onboarding"]["existing_install"] is True
    assert snap["onboarding"]["steps"] == {"profile": "done", "opportunities": "done"}
    assert snap["profile"]["degree_level"] == "bachelor"
    assert snap["profile"]["regions"] == ["EU", "EUROPE"]  # DE is implicit (it's the country)
    assert snap["profile"]["everything"] is True


def test_autosave_drafts_survive_restart_and_never_hold_secrets(gui):
    c = gui.client()
    c.call(
        "PUT",
        "/api/draft",
        {
            "step": "profile",
            "data": {"degree_level": "master", "token": GOOD_TOKEN, "country": "NL"},
        },
    )
    c.call(
        "PUT",
        "/api/draft",
        {"step": "notifications", "data": {"enabled": True, "bot_token": GOOD_TOKEN}},
    )
    raw = (_home() / "onboarding.json").read_text()
    assert GOOD_TOKEN not in raw
    assert stat.S_IMODE((_home() / "onboarding.json").stat().st_mode) == 0o600

    snap = gui.restart().client().get("/api/state")  # new process, new session
    assert snap["onboarding"]["drafts"]["profile"] == {"degree_level": "master", "country": "NL"}
    assert snap["onboarding"]["current_step"] == "notifications"
    assert c.call("PUT", "/api/draft", {"step": "welcome", "data": {}}, expect=400)


def test_completed_onboarding_survives_restart(gui):
    c = gui.client()
    _onboard(c)
    done = c.post("/api/finish")
    assert done["summary"]["everything"] is True
    snap = gui.restart().client().get("/api/state")
    assert snap["onboarding"]["completed"] is True
    assert snap["onboarding"]["completed_at"] == done["completed_at"]


def test_finish_requires_the_required_steps(gui):
    c = gui.client()
    assert c.post("/api/finish", expect=409)["error"] == "Save your profile first."
    c.post("/api/profile", PROFILE)
    assert "opportunities" in c.post("/api/finish", expect=409)["fields"]


# --- validation --------------------------------------------------------------------------------


def test_profile_validation_is_field_level_and_plain(gui):
    c = gui.client()
    r = c.post(
        "/api/profile",
        {"country": "Germany", "current_year": 42, "research_tags": "ml"},
        expect=422,
    )
    assert set(r["fields"]) == {"degree_level", "country", "current_year", "research_tags"}
    assert r["fields"]["current_year"] == "Enter a number between 1 and 10."
    assert not (_home() / "profile.yaml").exists()
    r = c.post(
        "/api/profile", {**PROFILE, "research_tags": [f"t{i}" for i in range(25)]}, expect=422
    )
    assert r["fields"]["research_tags"] == "Pick at most 20."


def test_preferences_need_a_profile_and_valid_choices(gui):
    c = gui.client()
    c.post("/api/preferences", {"everything": True, "formats": ["online"]}, expect=409)
    c.post("/api/profile", PROFILE)
    r = c.post(
        "/api/preferences", {"everything": False, "categories": [], "formats": []}, expect=422
    )
    assert set(r["fields"]) == {"categories", "formats"}
    r = c.post(
        "/api/preferences",
        {
            "everything": False,
            "categories": ["parties"],
            "formats": ["online"],
            "budget_limit_eur": "lots",
        },
        expect=422,
    )
    assert set(r["fields"]) == {"categories", "budget_limit_eur"}


# --- preferences persist and affect matching ---------------------------------------------------


def test_preferences_persist_and_change_scores(gui):
    c = gui.client()
    _onboard(
        c,
        {
            "everything": False,
            "categories": ["summer_school"],
            "regions": ["WORLDWIDE"],
            "formats": ["online", "in_person"],
            "budget_limit_eur": 200,
        },
    )
    cfg = load_config()
    p = load_profile_for(cfg)
    assert p.preferences.categories == ["summer_school"]
    assert (
        p.preferences.primary_regions == ["DE", "WORLDWIDE"]
        and p.preferences.budget_limit_eur == 200
    )

    def fit(profile, category):
        return compute_fit(topic="robotics summer school", category=category, eligibility=EligibilityStatus.ELIGIBLE,
                           funding_status="unknown", funding_confirmed=False, fee_max=None, fmt="in_person",
                           location="Boston, USA", profile=profile, weights=ScoringWeights())  # fmt: skip

    everything = p.model_copy(
        update={"preferences": p.preferences.model_copy(update={"categories": []})}
    )
    assert fit(p, "summer_school").fit > fit(everything, "summer_school").fit
    assert fit(p, "hackathon").fit < fit(everything, "hackathon").fit
    assert "OUTSIDE_PREFERRED_CATEGORIES" in fit(p, "hackathon").reasons
    assert "HIGH_TRAVEL_COST" not in fit(p, "summer_school").reasons  # WORLDWIDE: far is fine

    ex = c.post("/api/preview")["examples"]
    assert [e["title"] for e in ex][0] == "Robot Learning Summer School"
    assert "a kind of opportunity you asked for" in ex[0]["reasons"]
    assert ex[0]["action"] == "future_cycle"  # master's/PhD only: the preview never says "apply"


# --- skipping optional steps -------------------------------------------------------------------


def test_skipping_notifications_turns_telegram_off_and_required_steps_cannot_be_skipped(gui):
    c = gui.client()
    assert load_config().settings.telegram.enabled is True  # default
    c.post("/api/step", {"step": "notifications", "status": "skipped", "current": "ai"})
    assert load_config().settings.telegram.enabled is False
    assert c.post("/api/step", {"step": "profile", "status": "skipped"}, expect=400)
    c.post("/api/step", {"step": "ai", "status": "skipped", "current": "review"})
    assert c.get("/api/state")["onboarding"]["steps"] == {
        "notifications": "skipped",
        "ai": "skipped",
    }
    assert gui.telegram.calls == []  # skipping never talks to Telegram


# --- Telegram ----------------------------------------------------------------------------------


def test_token_is_verified_stored_in_keychain_and_never_returned(gui, fake_keychain):
    c = gui.client()
    r = c.post("/api/telegram/token", {"token": GOOD_TOKEN})
    assert r == {**r, "stored": True, "verified": True, "bot_username": "test_bot"}
    assert fake_keychain["TELEGRAM_BOT_TOKEN"] == GOOD_TOKEN
    assert r["secrets"]["telegram_token"] == "keychain"
    for path in ("/api/state", "/api/summary"):
        assert GOOD_TOKEN not in json.dumps(c.get(path))
    for f in _home().rglob("*"):
        if f.is_file():
            assert GOOD_TOKEN.encode() not in f.read_bytes(), f.name  # not in YAML, JSON or SQLite
    assert gui.telegram.sent == []  # verifying uses getMe, never sendMessage


def test_rejected_or_malformed_tokens_are_not_stored(gui, fake_keychain):
    c = gui.client()
    r = c.post("/api/telegram/token", {"token": BAD_TOKEN}, expect=422)
    assert "invalid" in r["fields"]["token"] and BAD_TOKEN not in json.dumps(r)
    assert c.post("/api/telegram/token", {"token": "hunter2"}, expect=422)["fields"]["token"]
    assert "TELEGRAM_BOT_TOKEN" not in fake_keychain


def test_token_is_kept_when_telegram_is_unreachable(gui, fake_keychain):
    gui.telegram.down = True
    r = gui.client().post("/api/telegram/token", {"token": GOOD_TOKEN})
    assert r["stored"] is True and r["verified"] is False and "couldn't verify" in r["warning"]
    assert GOOD_TOKEN not in r["warning"]
    assert fake_keychain["TELEGRAM_BOT_TOKEN"] == GOOD_TOKEN


def test_keychain_unavailable_is_reported_not_worked_around(fake_keychain, monkeypatch):
    from open_hypergamy import keychain

    g = make_gui()
    monkeypatch.setattr(keychain, "keychain_enabled", lambda: False)
    r = g.client().post("/api/telegram/token", {"token": GOOD_TOKEN}, expect=409)
    assert "environment variable" in r["error"]
    assert fake_keychain == {}
    assert not any(GOOD_TOKEN.encode() in f.read_bytes() for f in _home().rglob("*") if f.is_file())


def test_chat_detection_single_and_multiple(gui, fake_keychain):
    c = gui.client()
    c.post("/api/telegram/chat/detect", expect=409)  # no token yet
    c.post("/api/telegram/token", {"token": GOOD_TOKEN})
    r = c.post("/api/telegram/chat/detect")
    assert (
        r["stored"] is True and r["label"] == "Ada" and fake_keychain["TELEGRAM_CHAT_ID"] == "4242"
    )

    gui.telegram.chats = [
        {"id": -100, "type": "group", "title": "Lab"},
        {"id": -200, "type": "channel", "title": "News"},
    ]
    r = c.post("/api/telegram/chat/detect")
    assert r["stored"] is False and {x["label"] for x in r["chats"]} == {"Lab", "News"}
    assert "-100" not in json.dumps(r)  # chat ids stay server-side; the page gets opaque refs
    ref = next(x["ref"] for x in r["chats"] if x["label"] == "Lab")
    c.post("/api/telegram/chat", {"ref": ref, "label": "Lab"})
    assert fake_keychain["TELEGRAM_CHAT_ID"] == "-100"
    c.post("/api/telegram/chat", {"ref": ref}, expect=404)  # refs are single-use


def test_test_message_only_on_explicit_request(gui):
    c = gui.client()
    c.post("/api/telegram/test", expect=409)
    c.post("/api/telegram/token", {"token": GOOD_TOKEN})
    c.post("/api/telegram/chat/detect")
    _onboard(c)
    c.post("/api/telegram/settings", {"enabled": True, "digest_enabled": True, "digest_weekday": 2, "digest_time": "09:15",
                                      "timezone": "Europe/Amsterdam", "deadline_offsets_days": [7, 30], "minimum_fit_score_for_immediate_alert": 80})  # fmt: skip
    c.post("/api/finish")
    assert gui.telegram.sent == []
    assert c.post("/api/telegram/test") == {"sent": True}
    assert len(gui.telegram.sent) == 1 and gui.telegram.sent[0]["chat_id"] == "4242"


def test_delivery_settings_are_validated_and_written_to_managed_settings(gui):
    c = gui.client()
    bad = c.post("/api/telegram/settings", {"enabled": True, "timezone": "Mars/Olympus", "digest_time": "25:00",
                                            "digest_weekday": 9, "deadline_offsets_days": [3]}, expect=422)  # fmt: skip
    assert set(bad["fields"]) == {
        "timezone",
        "digest_time",
        "digest_weekday",
        "deadline_offsets_days",
    }
    assert not (_home() / "settings.yaml").exists()
    c.post("/api/telegram/settings", {"enabled": False, "digest_enabled": False, "digest_weekday": 0, "digest_time": "07:00",
                                      "timezone": "Asia/Tokyo", "deadline_offsets_days": [14], "minimum_fit_score_for_immediate_alert": 90})  # fmt: skip
    s = load_config().settings
    assert (s.telegram.enabled, s.telegram.digest_enabled, s.app.timezone) == (
        False,
        False,
        "Asia/Tokyo",
    )
    assert (
        s.schedule.digest_weekday,
        s.schedule.digest_time,
        s.telegram.deadline_offsets_days,
    ) == (0, "07:00", [14])
    written = yaml.safe_load((_home() / "settings.yaml").read_text())
    assert "token" not in json.dumps(written).lower()
    assert stat.S_IMODE((_home() / "settings.yaml").stat().st_mode) == 0o600


def test_hand_written_settings_file_is_never_rewritten(gui, tmp_path, monkeypatch):
    cfg_file = tmp_path / "mine.yaml"
    cfg_file.write_text("# my comments\ntelegram:\n  enabled: true\n")
    monkeypatch.setenv("OHG_CONFIG", str(cfg_file))
    c = gui.restart().client()
    assert c.get("/api/state")["settings"]["editable"] is False
    r = c.post("/api/llm/settings", {"enabled": False}, expect=409)
    assert "hand-written" in r["error"]
    assert cfg_file.read_text() == "# my comments\ntelegram:\n  enabled: true\n"


def test_forget_removes_credentials(gui, fake_keychain):
    c = gui.client()
    c.post("/api/telegram/token", {"token": GOOD_TOKEN})
    c.post("/api/telegram/chat/detect")
    assert c.post("/api/telegram/forget")["secrets"]["telegram_token"] == "unset"
    assert fake_keychain == {}


# --- LLM ---------------------------------------------------------------------------------------


def test_llm_status_reports_truthfully(gui):
    c = gui.client()
    st = c.post("/api/llm/status")
    assert st["reachable"] is True and st["model_listed"] is True and st["acknowledged"] is False
    assert st["api_key"] == "unset" and gui.llm.requests == []  # status never runs inference
    gui.llm.models = ["auto:something-else"]
    assert c.post("/api/llm/status")["model_listed"] is False
    gui.llm.reachable = False
    st = c.post("/api/llm/status")
    assert st["reachable"] is False and st["model_listed"] is None


def test_llm_test_requires_ack_and_sends_nothing_personal(gui, fake_keychain):
    c = gui.client()
    _onboard(c)
    assert "Acknowledge" in c.post("/api/llm/test", expect=409)["error"]
    assert gui.llm.requests == []
    c.post("/api/llm/ack", {"accept": "yes"}, expect=400)  # must be literally true
    c.post("/api/llm/ack", {"accept": True})
    assert c.post("/api/llm/test") == {"ok": True, "model": "free/test"}
    payload = json.dumps(gui.llm.requests[0])
    for private in ("robotics", "reinforcement", "bachelor", str(_home())):
        assert private not in payload
    c.post("/api/llm/key", {"key": "short"}, expect=422)
    c.post("/api/llm/key", {"key": "sk-unified-key-0001"})
    assert fake_keychain["OHG_FREELLMAPI_API_KEY"] == "sk-unified-key-0001"
    assert "sk-unified-key-0001" not in json.dumps(c.post("/api/llm/status"))


def test_llm_disabled_blocks_the_test_and_is_persisted(gui):
    c = gui.client()
    c.post("/api/llm/ack", {"accept": True})
    snap = c.post("/api/llm/settings", {"enabled": False})
    assert (
        snap["settings"]["llm"]["enabled"] is False and load_config().settings.llm.enabled is False
    )
    assert "turned off" in c.post("/api/llm/test", expect=409)["error"]
    assert gui.llm.requests == []


# --- recovery ----------------------------------------------------------------------------------


def test_broken_managed_settings_can_be_recovered(gui):
    (_home() / "settings.yaml").write_text("telegram: [not, a, mapping\n")
    c = gui.client()
    snap = c.get("/api/state")
    assert snap["config_error"] and snap["recoverable"] is True
    c.post("/api/profile", PROFILE, expect=409)  # nothing half-saves while config is broken
    moved = c.post("/api/recover/settings")["moved_to"]
    assert moved.startswith("settings.yaml.broken-") and (_home() / moved).exists()
    assert c.get("/api/state")["config_error"] is None
    c.post("/api/recover/settings", expect=409)


def test_broken_profile_is_backed_up_and_replaced(gui):
    (_home() / "profile.yaml").write_text("version: 1\nacademic: {degree_level: wizard}\n")
    c = gui.client()
    assert "problem" in c.get("/api/state")["profile_problem"]
    c.post("/api/profile", PROFILE)
    assert "wizard" in (_home() / "profile.yaml.bak").read_text()
    assert load_profile(_home() / "profile.yaml").academic.degree_level == "bachelor"


def test_failed_integration_never_loses_saved_answers(gui):
    c = gui.client()
    _onboard(c)
    gui.telegram.down = True
    c.post("/api/telegram/token", {"token": GOOD_TOKEN})
    c.post("/api/telegram/chat/detect", expect=502)
    gui.llm.reachable = False
    c.post("/api/llm/status")
    assert c.get("/api/state")["profile"]["research_tags"] == ["robotics", "reinforcement_learning"]


# --- settings precedence -----------------------------------------------------------------------


def test_managed_settings_rank_below_hand_written_files(tmp_path, monkeypatch):
    home = _home()
    home.mkdir(parents=True)
    (home / "settings.yaml").write_text("app: {timezone: Asia/Tokyo}\n")
    assert load_config().settings.app.timezone == "Asia/Tokyo"
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.yaml").write_text("app: {timezone: Europe/Paris}\n")
    cfg = load_config()
    assert cfg.settings.app.timezone == "Europe/Paris" and not settings_store.editable(cfg)


def test_resaving_unchanged_answers_keeps_the_profile_version(gui):
    c = gui.client()
    _onboard(c)
    v1 = load_profile(_home() / "profile.yaml").profile_version
    c.post("/api/profile", PROFILE)
    c.post("/api/preferences", {"everything": True, "formats": ["online"]})
    assert load_profile(_home() / "profile.yaml").profile_version == v1  # no spurious rescoring
    c.post("/api/preferences", {"everything": True, "formats": ["online", "hybrid"]})
    assert load_profile(_home() / "profile.yaml").profile_version != v1


def test_reset_is_refused_when_a_hand_written_file_is_the_broken_one(gui, tmp_path, monkeypatch):
    settings_store.update(load_config(), {"app.timezone": "Asia/Tokyo"})  # a valid managed file
    managed = (_home() / "settings.yaml").read_text()
    bad = tmp_path / "mine.yaml"
    bad.write_text("app: [broken\n")
    c = gui.client()  # the server is running when the hand-written file breaks
    monkeypatch.setenv("OHG_CONFIG", str(bad))
    snap = c.get("/api/state")
    assert snap["config_error"] and snap["recoverable"] is False
    c.post("/api/recover/settings", expect=409)
    assert (_home() / "settings.yaml").read_text() == managed  # the good file is not moved aside
