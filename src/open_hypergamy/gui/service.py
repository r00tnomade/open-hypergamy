"""Onboarding application service: the only layer the HTTP API calls (ADR-014).

It orchestrates existing modules (config, profile, settings_store, keychain, Telegram, LLM
client/ack, scoring, reporting) and adds no business rules of its own beyond input validation.
Return values are plain JSON-able dicts. Secrets are accepted on input, written to the
Keychain, and never returned: responses only say where a secret comes from.
"""

from __future__ import annotations

import re
import secrets
import threading
import zoneinfo
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from open_hypergamy import __version__, keychain, settings_store
from open_hypergamy.clock import Clock, SystemClock, iso_compact, iso_z
from open_hypergamy.config import LoadedConfig, load_config, resolve_home
from open_hypergamy.errors import ConfigurationError, OhgError
from open_hypergamy.extraction.llm_extractor import build_client, llm_enabled
from open_hypergamy.gui import catalog, preview, state
from open_hypergamy.llm.ack import CHECKLIST, ack_is_current, require_ack, write_ack
from open_hypergamy.llm.client import LLMClient
from open_hypergamy.notifications import telegram as tg
from open_hypergamy.notifications.base import NotificationMessage
from open_hypergamy.observability.logging import redact
from open_hypergamy.persistence import bootstrap
from open_hypergamy.persistence import db as dbm
from open_hypergamy.profile import Profile, load_profile, profile_path, save_profile
from open_hypergamy.reporting.sources import build_sources_report

TOKEN = "TELEGRAM_BOT_TOKEN"
CHAT = "TELEGRAM_CHAT_ID"
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_FREE_TEXT_MAX = 120


class ApiError(Exception):
    def __init__(self, status: int, message: str, fields: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.status, self.message, self.fields = status, redact(message), fields or {}


@dataclass
class Deps:
    clock: Clock = field(default_factory=SystemClock)
    telegram_transport: httpx.BaseTransport | None = None
    llm_client: Callable[[LoadedConfig], LLMClient] | None = None  # default: build_client


def _tags(value: Any, name: str, limit: int, errors: dict[str, str]) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        errors[name] = "Expected a list of words."
        return []
    out = list(dict.fromkeys(t for t in (catalog.normalise_tag(x) for x in value) if t))
    if len(out) > limit:
        errors[name] = f"Pick at most {limit}."
    return out[:limit]


def _opt_int(value: Any, name: str, lo: int, hi: int, errors: dict[str, str]) -> int | None:
    if value in (None, ""):
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        errors[name] = "Enter a whole number."
        return None
    if not lo <= n <= hi:
        errors[name] = f"Enter a number between {lo} and {hi}."
        return None
    return n


def _text(value: Any, name: str, errors: dict[str, str]) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        errors[name] = "Expected text."
        return None
    v = " ".join(value.split())
    if len(v) > _FREE_TEXT_MAX:
        errors[name] = f"Keep this under {_FREE_TEXT_MAX} characters."
    return v[:_FREE_TEXT_MAX] or None


def _bool(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


class OnboardingService:
    def __init__(
        self, home: Path | None = None, config: Path | None = None, deps: Deps | None = None
    ) -> None:
        self._home_opt, self._config_opt = home, config
        self.deps = deps or Deps()
        self._lock = threading.RLock()  # serialises file writes; network calls run outside it
        self._chat_refs: dict[str, str] = {}

    # -- plumbing ------------------------------------------------------------------------------

    @property
    def home(self) -> Path:
        return resolve_home(self._home_opt)

    def _now(self) -> str:
        return iso_z(self.deps.clock.now_utc())

    def cfg(self) -> LoadedConfig:
        try:
            return load_config(home=self._home_opt, config=self._config_opt)
        except ConfigurationError as e:
            raise ApiError(409, f"Your settings file could not be read: {e}") from None

    def _profile(self, cfg: LoadedConfig) -> tuple[Profile | None, str | None]:
        p = profile_path(cfg)
        if p is None:
            return None, None
        try:
            return load_profile(p), None
        except ConfigurationError:
            return (
                None,
                "Your existing profile file has a problem. Saving here replaces it (a backup is kept).",
            )

    def _state(self) -> state.OnboardingState:
        return state.load(self.home)

    def _save_state(self, st: state.OnboardingState) -> None:
        state.save(self.home, st, self._now())

    def _mark(self, step: str, status: state.StepStatus, advance_to: str | None = None) -> None:
        with self._lock:
            st = self._state()
            st.steps[step] = status
            st.drafts.pop(step, None)
            if advance_to:
                st.current_step = advance_to
            self._save_state(st)

    def _llm_client(self, cfg: LoadedConfig) -> LLMClient:
        return (self.deps.llm_client or build_client)(cfg)

    def start(self) -> bootstrap.InitResult | None:
        """Initialise the data directory and database if needed (same as `ohg init`)."""
        cfg = load_config(home=self._home_opt, config=self._config_opt)
        if bootstrap.needs_init(cfg):
            return bootstrap.initialize(cfg, self.deps.clock)
        return None

    # -- read model ----------------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Everything the UI needs to render, without any network access."""
        st = self._state()
        base: dict[str, Any] = {
            "version": __version__,
            "catalog": catalog.as_json(),
            "steps": list(state.STEPS),
            "optional_steps": sorted(state.OPTIONAL),
            "llm_checklist": CHECKLIST,
        }
        try:
            cfg = self.cfg()
        except ApiError as e:
            return {
                **base,
                "config_error": e.message,
                "recoverable": self._managed_settings_broken(),
                "onboarding": self._onboarding_json(st, existing=False),
            }
        profile, problem = self._profile(cfg)
        existing = profile is not None and not state.path_for(self.home).exists()
        if existing:  # an install that predates the GUI: its profile counts as done
            st.steps.update({"profile": "done", "opportunities": "done"})
            with self._lock:
                self._save_state(st)
        s = cfg.settings
        return {
            **base,
            "config_error": None,
            "initialized": cfg.paths.db.exists(),
            "onboarding": self._onboarding_json(st, existing=existing),
            "profile": self._profile_json(profile),
            "profile_problem": problem,
            "settings": {
                "editable": settings_store.editable(cfg),
                "timezone": s.app.timezone,
                "telegram": {
                    "enabled": s.telegram.enabled,
                    "digest_enabled": s.telegram.digest_enabled,
                    "digest_weekday": s.schedule.digest_weekday % 7,
                    "digest_time": s.schedule.digest_time,
                    "deadline_offsets_days": s.telegram.deadline_offsets_days,
                    "minimum_fit_score_for_immediate_alert": s.telegram.minimum_fit_score_for_immediate_alert,
                },
                "llm": {
                    "enabled": s.llm.enabled,
                    "effective": llm_enabled(cfg),
                    "provider": s.llm.provider,
                    "model": s.llm.active.model,
                    "base_url": s.llm.active.base_url,
                },
            },
            "secrets": self._secret_sources(cfg),
            "llm_ack": s.llm.provider == "local"
            or ack_is_current(cfg.paths.llm_ack, s.llm.provider),
        }

    def _onboarding_json(self, st: state.OnboardingState, *, existing: bool) -> dict[str, Any]:
        return {
            "steps": st.steps,
            "current_step": st.current_step,
            "drafts": st.drafts,
            "completed": st.completed,
            "completed_at": st.completed_at,
            "existing_install": existing,
        }

    def _secret_sources(self, cfg: LoadedConfig) -> dict[str, Any]:
        key_env = cfg.settings.llm.freellmapi.api_key_env
        return {
            "keychain_available": keychain.keychain_enabled(),
            "telegram_token": keychain.source_of(TOKEN),
            "telegram_chat": keychain.source_of(CHAT),
            "llm_api_key": keychain.source_of(key_env),
        }

    @staticmethod
    def _profile_json(p: Profile | None) -> dict[str, Any] | None:
        if p is None:
            return None
        a, pref = p.academic, p.preferences
        region_ids = {r[0] for r in catalog.REGIONS}
        return {
            "display_name": p.display_name,
            "degree_level": a.degree_level,
            "current_year": a.current_year,
            "expected_graduation_year": a.expected_graduation_year,
            "institution": a.institution,
            "institution_type": a.institution_type,
            "country": a.country.upper(),
            "subject_tags": a.subject_tags,
            "research_tags": p.research_tags,
            "skills": p.skills,
            "everything": not pref.categories,
            "categories": list(pref.categories),
            "regions": [r.upper() for r in pref.primary_regions if r.upper() in region_ids],
            "formats": pref.formats,
            "international_when_funded": pref.international_when_funded,
            "needs_funding_or_low_cost": pref.needs_funding_or_low_cost,
            "budget_limit_eur": pref.budget_limit_eur,
        }

    # -- drafts and steps ----------------------------------------------------------------------

    def save_draft(self, step: str, data: Any) -> dict[str, Any]:
        if step not in state.DRAFT_FIELDS or not isinstance(data, dict):
            raise ApiError(400, "This step has no draft to save.")
        try:
            clean = state.clean_draft(step, data)
        except ValueError as e:
            raise ApiError(413, str(e)) from None
        with self._lock:
            st = self._state()
            st.drafts[step] = clean
            st.current_step = step
            self._save_state(st)
        return {"saved_at": self._now()}

    def mark_step(self, step: str, status: str, current: str | None) -> dict[str, Any]:
        if step not in state.STEPS or status not in ("done", "skipped", "visited"):
            raise ApiError(400, "Unknown step.")
        if status == "skipped" and step not in state.OPTIONAL:
            raise ApiError(400, "This step can't be skipped.")
        if current is not None and current not in state.STEPS:
            raise ApiError(400, "Unknown step.")
        if status == "skipped" and step == "notifications":
            cfg = self.cfg()
            if settings_store.editable(cfg):  # skipping = no Telegram delivery from scheduled runs
                with self._lock:
                    settings_store.update(cfg, {"telegram.enabled": False})
        with self._lock:
            st = self._state()
            if status != "visited":
                st.steps[step] = status  # type: ignore[assignment]
            if current:
                st.current_step = current
            self._save_state(st)
        return {"onboarding": self._onboarding_json(st, existing=False)}

    # -- profile (step 1) and preferences (step 2) ---------------------------------------------

    def _base_profile(self, cfg: LoadedConfig) -> dict[str, Any]:
        existing, _ = self._profile(cfg)
        if existing is not None:
            return existing.model_dump(mode="json")
        return {"version": 1, "profile_id": "primary", "profile_version": "new"}

    def _write_profile(self, cfg: LoadedConfig, data: dict[str, Any]) -> Profile:
        before = self._base_profile(cfg)
        changed = {k: v for k, v in data.items() if k != "profile_version"} != {
            k: v for k, v in before.items() if k != "profile_version"
        }
        if changed or before.get("profile_version") == "new":
            stamp = "gui-" + iso_compact(self.deps.clock.now_utc())
            prev = str(before.get("profile_version"))
            if prev == stamp or prev.startswith(stamp + "."):  # another edit within the same second
                tail = prev[len(stamp) + 1 :]
                stamp = f"{stamp}.{int(tail) + 1 if tail.isdigit() else 2}"
            data["profile_version"] = stamp
        try:
            profile = Profile.model_validate(data)
        except ValidationError as e:
            fields = {
                ".".join(str(x) for x in err["loc"]): err["msg"]
                for err in e.errors(include_input=False, include_url=False)
            }
            raise ApiError(422, "Some answers need another look.", fields) from None
        with self._lock:
            save_profile(cfg, profile)
        return profile

    def save_profile(self, body: Any) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise ApiError(400, "Expected a JSON object.")
        cfg = self.cfg()
        errors: dict[str, str] = {}
        degree = body.get("degree_level")
        if degree not in {d[0] for d in catalog.DEGREES}:
            errors["degree_level"] = "Choose your current level of study."
        country = str(body.get("country") or "").strip().upper()
        if not _COUNTRY.match(country):
            errors["country"] = "Choose the country you study in."
        itype = body.get("institution_type") or "unknown"
        if itype not in {t[0] for t in catalog.INSTITUTION_TYPES}:
            errors["institution_type"] = "Choose one of the listed types."
        year = _opt_int(body.get("current_year"), "current_year", 1, 10, errors)
        grad = _opt_int(
            body.get("expected_graduation_year"), "expected_graduation_year", 1990, 2100, errors
        )
        name = _text(body.get("display_name"), "display_name", errors)
        inst = _text(body.get("institution"), "institution", errors)
        subjects = _tags(body.get("subject_tags"), "subject_tags", 10, errors)
        interests = _tags(body.get("research_tags"), "research_tags", 20, errors)
        skills = _tags(body.get("skills"), "skills", 30, errors)
        if errors:
            raise ApiError(422, "Some answers need another look.", errors)
        data = self._base_profile(cfg)
        data["display_name"] = name
        academic = dict(data.get("academic") or {})
        academic.update(
            country=country,
            institution_type=itype,
            institution=inst,
            degree_level=degree,
            subject_tags=subjects,
            current_year=year,
            expected_graduation_year=grad,
        )
        data.update(academic=academic, research_tags=interests, skills=skills)
        prefs = dict(data.get("preferences") or {})
        if not prefs.get("primary_regions"):
            prefs["primary_regions"] = [country]
        data["preferences"] = prefs
        profile = self._write_profile(cfg, data)
        self._mark("profile", "done", advance_to="opportunities")
        return {"profile": self._profile_json(profile)}

    def save_preferences(self, body: Any) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise ApiError(400, "Expected a JSON object.")
        cfg = self.cfg()
        existing, _ = self._profile(cfg)
        if existing is None:
            raise ApiError(409, "Save your profile first.")
        errors: dict[str, str] = {}
        everything = _bool(body.get("everything"), False)
        valid_cats = {c[0] for c in catalog.CATEGORIES}
        cats = body.get("categories") or []
        if not isinstance(cats, list) or any(c not in valid_cats for c in cats):
            errors["categories"] = "Choose from the listed kinds of opportunity."
            cats = []
        if not everything and not cats:
            errors["categories"] = "Pick at least one, or choose “Show me everything relevant”."
        regions = body.get("regions") or []
        if not isinstance(regions, list) or any(
            r not in {x[0] for x in catalog.REGIONS} for r in regions
        ):
            errors["regions"] = "Choose from the listed regions."
            regions = []
        formats = body.get("formats") or []
        if not isinstance(formats, list) or any(
            f not in {x[0] for x in catalog.FORMATS} for f in formats
        ):
            errors["formats"] = "Choose from the listed formats."
            formats = []
        elif not formats:
            errors["formats"] = "Pick at least one format."
        budget = body.get("budget_limit_eur")
        if budget in (None, ""):
            budget = None
        else:
            try:
                budget = float(budget)
                if not 0 <= budget <= 1_000_000:
                    raise ValueError
            except (TypeError, ValueError):
                errors["budget_limit_eur"] = "Enter an amount in euros, or leave it empty."
                budget = None
        if errors:
            raise ApiError(422, "Some answers need another look.", errors)
        data = existing.model_dump(mode="json")
        country = existing.academic.country.upper()
        data["preferences"] = {
            **data["preferences"],
            "categories": [] if everything else list(dict.fromkeys(cats)),
            "primary_regions": list(dict.fromkeys([country, *regions])),
            "formats": list(dict.fromkeys(formats)),
            "international_when_funded": _bool(body.get("international_when_funded"), True),
            "needs_funding_or_low_cost": _bool(body.get("needs_funding_or_low_cost"), True),
            "budget_limit_eur": budget,
        }
        profile = self._write_profile(cfg, data)
        self._mark("opportunities", "done", advance_to="matching")
        return {"profile": self._profile_json(profile)}

    # -- step 3: matching preview --------------------------------------------------------------

    def preview(self) -> dict[str, Any]:
        cfg = self.cfg()
        profile, _ = self._profile(cfg)
        if profile is None:
            raise ApiError(409, "Save your profile first.")
        return {
            "examples": preview.evaluate(
                profile, cfg.settings.scoring.weights, self.deps.clock.now_utc()
            ),
            "weights": cfg.settings.scoring.weights.model_dump(),
        }

    # -- step 4: Telegram ----------------------------------------------------------------------

    def _require_keychain(self) -> None:
        if not keychain.keychain_enabled():
            raise ApiError(
                409,
                "Secure storage (the macOS Keychain) isn't available on this system, so the GUI "
                "can't store this. Set it as an environment variable instead.",
            )

    def telegram_token(self, body: Any) -> dict[str, Any]:
        token = (body or {}).get("token") if isinstance(body, dict) else None
        if not isinstance(token, str) or not re.match(tg.TOKEN_SHAPE, token.strip()):
            raise ApiError(
                422,
                "That doesn't look like a bot token.",
                {"token": "It should look like 123456789:AA… (from @BotFather)."},
            )
        token = token.strip()
        self._require_keychain()
        check = tg.check_bot(token, transport=self.deps.telegram_transport)
        if check.rejected:
            raise ApiError(
                422,
                "Telegram rejected this token.",
                {"token": "Telegram says this token is invalid. Copy it again from @BotFather."},
            )
        with self._lock:
            keychain.set_secret(TOKEN, token)
        self._chat_refs.clear()
        return {
            "stored": True,
            "verified": check.ok,
            "bot_username": check.username,
            "warning": None
            if check.ok
            else f"Saved, but we couldn't verify it right now ({check.error}).",
            "secrets": self._secret_sources(self.cfg()),
        }

    def telegram_detect_chat(self) -> dict[str, Any]:
        token = keychain.get_secret(TOKEN)
        if not token:
            raise ApiError(409, "Add your bot token first.")
        try:
            chats = tg.recent_chats(token, transport=self.deps.telegram_transport)
        except ConfigurationError as e:
            raise ApiError(502, str(e)) from None
        if not chats:
            return {
                "stored": False,
                "chats": [],
                "hint": "No messages yet. Open your bot in Telegram, press Start or send it any message, then try again.",
            }
        private = [c for c in chats if c.kind == "private"]
        if len(chats) == 1 or len(private) == 1:
            pick = private[0] if private else chats[0]
            return self._store_chat(pick.chat_id, pick.label)
        self._chat_refs = {secrets.token_hex(8): c.chat_id for c in chats}
        labels = {c.chat_id: c for c in chats}
        return {
            "stored": False,
            "chats": [
                {"ref": ref, "label": labels[cid].label, "kind": labels[cid].kind}
                for ref, cid in self._chat_refs.items()
            ],
        }

    def telegram_pick_chat(self, body: Any) -> dict[str, Any]:
        ref = (body or {}).get("ref") if isinstance(body, dict) else None
        cid = self._chat_refs.get(ref) if isinstance(ref, str) else None
        if cid is None:
            raise ApiError(404, "That chat is no longer listed. Search again.")
        return self._store_chat(cid, str((body or {}).get("label") or "your chat"))

    def _store_chat(self, chat_id: str, label: str) -> dict[str, Any]:
        self._require_keychain()
        with self._lock:
            keychain.set_secret(CHAT, chat_id)
        self._chat_refs.clear()
        return {"stored": True, "label": label, "secrets": self._secret_sources(self.cfg())}

    def telegram_test(self) -> dict[str, Any]:
        token, chat = keychain.get_secret(TOKEN), keychain.get_secret(CHAT)
        if not token or not chat:
            raise ApiError(409, "Connect your bot and chat first.")
        sink = tg.TelegramSink(token, chat, transport=self.deps.telegram_transport)
        try:
            res = sink.send(
                NotificationMessage(
                    "✅ OpenHypergamy: Telegram is configured correctly.", "test", "system", "test"
                ),
                "test",
            )
        finally:
            sink.close()
        if not res.ok:
            raise ApiError(
                502, f"Telegram didn't accept the test message: {res.error or 'unknown error'}"
            )
        return {"sent": True}

    def telegram_settings(self, body: Any) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise ApiError(400, "Expected a JSON object.")
        cfg = self.cfg()
        if not settings_store.editable(cfg):
            raise ApiError(
                409, "Your settings come from a hand-written settings file; edit that file instead."
            )
        errors: dict[str, str] = {}
        tz = body.get("timezone")
        try:
            zoneinfo.ZoneInfo(str(tz))
        except (zoneinfo.ZoneInfoNotFoundError, ValueError):
            errors["timezone"] = "Choose a timezone from the list."
        t = body.get("digest_time")
        if not isinstance(t, str) or not _HHMM.match(t):
            errors["digest_time"] = "Use a 24-hour time like 08:30."
        wd = _opt_int(body.get("digest_weekday"), "digest_weekday", 0, 6, errors)
        offsets = body.get("deadline_offsets_days") or []
        if not isinstance(offsets, list) or any(o not in catalog.REMINDER_OFFSETS for o in offsets):
            errors["deadline_offsets_days"] = "Choose from the listed reminder times."
            offsets = []
        fit = _opt_int(
            body.get("minimum_fit_score_for_immediate_alert"),
            "minimum_fit_score_for_immediate_alert",
            0,
            100,
            errors,
        )
        if errors:
            raise ApiError(422, "Some answers need another look.", errors)
        enabled = _bool(body.get("enabled"), False)
        changes: dict[str, Any] = {
            "telegram.enabled": enabled,
            "telegram.digest_enabled": _bool(body.get("digest_enabled"), True),
            "telegram.deadline_offsets_days": sorted(set(offsets), reverse=True),
            "app.timezone": str(tz),
            "schedule.digest_time": t,
        }
        if wd is not None:
            changes["schedule.digest_weekday"] = wd
        if fit is not None:
            changes["telegram.minimum_fit_score_for_immediate_alert"] = fit
        with self._lock:
            try:
                settings_store.update(cfg, changes)
            except ConfigurationError as e:
                raise ApiError(422, str(e)) from None
        self._mark("notifications", "done" if enabled else "skipped", advance_to="ai")
        return self.snapshot()

    def telegram_forget(self) -> dict[str, Any]:
        self._require_keychain()
        with self._lock:
            keychain.delete_secret(TOKEN)
            keychain.delete_secret(CHAT)
        return {"secrets": self._secret_sources(self.cfg())}

    # -- step 5: AI enrichment -----------------------------------------------------------------

    def llm_status(self) -> dict[str, Any]:
        """Gateway reachability and model listing. Makes no inference request."""
        cfg = self.cfg()
        s = cfg.settings.llm
        out: dict[str, Any] = {
            "enabled": s.enabled,
            "effective": llm_enabled(cfg),
            "provider": s.provider,
            "model": s.active.model,
            "base_url": s.active.base_url,
            "acknowledged": s.provider == "local" or ack_is_current(cfg.paths.llm_ack, s.provider),
            "api_key": keychain.source_of(s.freellmapi.api_key_env)
            if s.provider == "freellmapi"
            else "not_needed",
            "reachable": False,
            "model_listed": None,
        }
        try:
            client = self._llm_client(cfg)
        except OhgError as e:
            out["error"] = redact(str(e))
            return out
        try:
            out["reachable"] = client.healthy()
            if out["reachable"]:
                try:
                    out["model_listed"] = s.active.model in client.list_models()
                except OhgError:
                    out["model_listed"] = None
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()
        return out

    def llm_ack(self, body: Any) -> dict[str, Any]:
        if not (isinstance(body, dict) and body.get("accept") is True):
            raise ApiError(400, "Acknowledgement must be explicit.")
        cfg = self.cfg()
        s = cfg.settings.llm
        if s.provider == "local":
            return {"acknowledged": True}
        with self._lock:
            cfg.paths.ensure()
            write_ack(cfg.paths.llm_ack, self.deps.clock, s.provider, s.freellmapi.model)
        return {"acknowledged": True}

    def llm_key(self, body: Any) -> dict[str, Any]:
        key = (body or {}).get("key") if isinstance(body, dict) else None
        if (
            not isinstance(key, str)
            or not (8 <= len(key.strip()) <= 512)
            or any(c.isspace() for c in key.strip())
        ):
            raise ApiError(
                422,
                "That key doesn't look right.",
                {"key": "Paste the unified key from FreeLLMAPI (no spaces)."},
            )
        cfg = self.cfg()
        name = cfg.settings.llm.freellmapi.api_key_env
        if name not in keychain.KNOWN:
            raise ApiError(409, "The configured key name can't be stored from the GUI.")
        self._require_keychain()
        with self._lock:
            keychain.set_secret(name, key.strip())
        return {"api_key": keychain.source_of(name)}

    def llm_test(self) -> dict[str, Any]:
        """One tiny inference request with a fixed, non-personal payload. Requires the ack."""
        cfg = self.cfg()
        s = cfg.settings.llm
        if not llm_enabled(cfg):
            raise ApiError(409, "AI enrichment is turned off.")
        try:
            require_ack(cfg.paths.llm_ack, s.provider)
        except OhgError:
            raise ApiError(409, "Acknowledge how AI enrichment handles data first.") from None
        client = self._llm_client(cfg)
        try:
            reply = client.complete_json(
                system_prompt='Reply with exactly this JSON object and nothing else: {"ok": true}',
                user_payload={"check": "openhypergamy-setup"},
                schema={"type": "object"},
                cache_key="onboarding-check",
            )
        except OhgError as e:
            raise ApiError(502, f"The AI gateway didn't complete the test: {e}") from None
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()
        return {"ok": reply.get("ok") is True, "model": client.last_model}

    def llm_settings(self, body: Any) -> dict[str, Any]:
        enabled = (body or {}).get("enabled") if isinstance(body, dict) else None
        if not isinstance(enabled, bool):
            raise ApiError(400, "Expected enabled: true or false.")
        cfg = self.cfg()
        if not settings_store.editable(cfg):
            raise ApiError(
                409, "Your settings come from a hand-written settings file; edit that file instead."
            )
        with self._lock:
            settings_store.update(cfg, {"llm.enabled": enabled})
        return self.snapshot()

    # -- step 6: finish, home ------------------------------------------------------------------

    def _sources(self, cfg: LoadedConfig) -> dict[str, Any] | None:
        if not cfg.paths.db.exists():
            return None
        conn = dbm.connect(cfg.paths.db, cfg.settings.database.busy_timeout_ms)
        try:
            r = build_sources_report(conn, self.deps.clock)
        finally:
            conn.close()
        return {
            k: r[k] for k in ("target", "configured", "enabled", "healthy_30d", "review_required")
        }

    def summary(self) -> dict[str, Any]:
        cfg = self.cfg()
        profile, problem = self._profile(cfg)
        sec = self._secret_sources(cfg)
        s = cfg.settings
        ack = s.llm.provider == "local" or ack_is_current(cfg.paths.llm_ack, s.llm.provider)
        tg_ready = sec["telegram_token"] != "unset" and sec["telegram_chat"] != "unset"
        cats = {c[0]: c[1] for c in catalog.CATEGORIES}
        todo: list[str] = []
        if s.telegram.enabled and not tg_ready:
            todo.append("Connect Telegram, or turn notifications off.")
        if not s.telegram.enabled:
            todo.append("Optional: connect Telegram for deadline reminders.")
        if llm_enabled(cfg) and not ack:
            todo.append("Optional: acknowledge the AI data policy to enable enrichment.")
        sources = self._sources(cfg)
        if sources is not None and sources["enabled"] == 0:
            todo.append(
                "No sources are enabled yet. Sources are added in reviewed batches; none are switched on automatically."
            )
        return {
            "profile": None
            if profile is None
            else {
                "name": profile.display_name,
                "degree_level": profile.academic.degree_level,
                "country": profile.academic.country,
                "interests": len(profile.research_tags),
                "subjects": len(profile.academic.subject_tags),
            },
            "profile_problem": problem,
            "categories": [cats.get(c, c) for c in profile.preferences.categories]
            if profile
            else [],
            "everything": bool(profile and not profile.preferences.categories),
            "telegram": {
                "enabled": s.telegram.enabled,
                "connected": tg_ready,
                "digest": s.telegram.digest_enabled,
            },
            "ai": {
                "enabled": s.llm.enabled,
                "effective": llm_enabled(cfg),
                "acknowledged": ack,
                "provider": s.llm.provider,
            },
            "sources": sources,
            "todo": todo,
        }

    def finish(self) -> dict[str, Any]:
        cfg = self.cfg()  # re-reading proves the saved settings validate
        profile, problem = self._profile(cfg)
        if profile is None:
            raise ApiError(409, problem or "Save your profile first.")
        st = self._state()
        missing = [s for s in ("profile", "opportunities") if st.steps.get(s) != "done"]
        if missing:
            raise ApiError(
                409, "A required step isn't finished yet.", {s: "Not finished" for s in missing}
            )
        with self._lock:
            st.completed_at = st.completed_at or self._now()
            st.current_step = "review"
            st.steps["review"] = "done"
            self._save_state(st)
        return {"completed_at": st.completed_at, "summary": self.summary()}

    def _managed_settings_broken(self) -> bool:
        """The managed file exists and nothing hand-written outranks it, so it caused the error."""
        return (self.home / settings_store.FILENAME).is_file() and not (
            settings_store.hand_written_active(self._config_opt)
        )

    def recover_settings(self) -> dict[str, Any]:
        """Move an unreadable app-managed settings file aside so defaults apply again."""
        if not self._managed_settings_broken():
            raise ApiError(
                409,
                "There is no app-managed settings file to reset. Fix the settings file you wrote by hand.",
            )
        with self._lock:
            moved = settings_store.quarantine(
                None, self.home, iso_compact(self.deps.clock.now_utc())
            )
        if moved is None:
            raise ApiError(
                409,
                "There is no app-managed settings file to reset. Fix the settings file you wrote by hand.",
            )
        return {"moved_to": moved.name}
