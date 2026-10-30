"""Resumable onboarding progress: `<home>/onboarding.json` (0600).

Holds which steps are done or skipped and unsaved drafts of non-secret form fields, so an
interrupted session resumes where it stopped. Never holds secrets: drafts are filtered
against an allowlist per step before they are written.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

STEPS = ("welcome", "profile", "opportunities", "matching", "notifications", "ai", "review")
OPTIONAL = frozenset({"notifications", "ai"})
StepStatus = Literal["done", "skipped"]

# Draftable fields per step. Token/key inputs are deliberately absent.
DRAFT_FIELDS: dict[str, frozenset[str]] = {
    "profile": frozenset(
        {
            "display_name",
            "degree_level",
            "current_year",
            "expected_graduation_year",
            "institution",
            "institution_type",
            "country",
            "subject_tags",
            "research_tags",
            "skills",
        }
    ),
    "opportunities": frozenset(
        {
            "everything",
            "categories",
            "regions",
            "formats",
            "international_when_funded",
            "needs_funding_or_low_cost",
            "budget_limit_eur",
        }
    ),
    "notifications": frozenset(
        {
            "enabled",
            "digest_enabled",
            "digest_weekday",
            "digest_time",
            "timezone",
            "deadline_offsets_days",
            "minimum_fit_score_for_immediate_alert",
        }
    ),
}
_MAX_DRAFT_BYTES = 32_000


@dataclass
class OnboardingState:
    version: int = 1
    steps: dict[str, StepStatus] = field(default_factory=dict)
    current_step: str = "welcome"
    drafts: dict[str, dict[str, Any]] = field(default_factory=dict)
    completed_at: str | None = None
    updated_at: str | None = None

    @property
    def completed(self) -> bool:
        return self.completed_at is not None


def path_for(home: Path) -> Path:
    return home / "onboarding.json"


def load(home: Path) -> OnboardingState:
    """A missing or corrupt file yields a fresh state; it is never fatal."""
    try:
        raw = json.loads(path_for(home).read_text())
    except (OSError, ValueError):
        return OnboardingState()
    if not isinstance(raw, dict) or raw.get("version") != 1:
        return OnboardingState()
    st = OnboardingState()
    steps = raw.get("steps")
    if isinstance(steps, dict):
        st.steps = {k: v for k, v in steps.items() if k in STEPS and v in ("done", "skipped")}
    if raw.get("current_step") in STEPS:
        st.current_step = raw["current_step"]
    drafts = raw.get("drafts")
    if isinstance(drafts, dict):
        st.drafts = {
            k: clean_draft(k, v)
            for k, v in drafts.items()
            if k in DRAFT_FIELDS and isinstance(v, dict)
        }
    st.completed_at = raw.get("completed_at") if isinstance(raw.get("completed_at"), str) else None
    st.updated_at = raw.get("updated_at") if isinstance(raw.get("updated_at"), str) else None
    return st


def save(home: Path, st: OnboardingState, now: str) -> None:
    st.updated_at = now
    home.mkdir(parents=True, exist_ok=True)
    p = path_for(home)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(asdict(st), indent=2, sort_keys=True) + "\n")
    tmp.chmod(0o600)
    os.replace(tmp, p)


def clean_draft(step: str, data: dict[str, Any]) -> dict[str, Any]:
    allowed = DRAFT_FIELDS.get(step, frozenset())
    out = {k: v for k, v in data.items() if k in allowed}
    if len(json.dumps(out)) > _MAX_DRAFT_BYTES:
        raise ValueError("draft is too large")
    return out
