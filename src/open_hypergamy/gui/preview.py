"""Matching preview: run the real eligibility, fit, urgency and band rules on made-up examples.

The examples are fictional and labelled as such in the UI. Nothing here touches the database,
the network or the LLM; it only shows how the saved profile would be read by the scoring code.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from open_hypergamy.clock import local_today
from open_hypergamy.config import ScoringWeights
from open_hypergamy.domain.enums import EligibilityStatus
from open_hypergamy.gui import catalog
from open_hypergamy.notifications.templates import _REASON_PHRASES
from open_hypergamy.profile import Profile
from open_hypergamy.scoring.actions import priority_band, recommended_action
from open_hypergamy.scoring.fit import compute_fit, matched_interests
from open_hypergamy.scoring.urgency import compute_urgency
from open_hypergamy.verification.eligibility import assess

SAMPLES: list[dict[str, Any]] = [
    {
        "title": "Robot Learning Summer School",
        "category": "summer_school",
        "topic": "summer school on robot learning, manipulation and machine learning for robotics",
        "location": "Zurich, Switzerland",
        "format": "in_person",
        "funding": "partially_funded",
        "requirements": ["Open to master's and PhD students."],
        "close_in_days": 12,
    },
    {
        "title": "Undergraduate Research Fellowship in Trustworthy ML",
        "category": "research_programme",
        "topic": "research fellowship on deep learning, ai systems and security of machine learning",
        "location": "Online",
        "format": "online",
        "funding": "fully_funded",
        "requirements": ["Applicants must be bachelor students in their second year or above."],
        "close_in_days": 40,
    },
    {
        "title": "Open Hardware Hackathon",
        "category": "hackathon",
        "topic": "hackathon for embedded systems, open source hardware and drones",
        "location": "Boston, USA",
        "format": "in_person",
        "funding": "self_funded",
        "requirements": ["Open to all university students.", "Participants must be over 18."],
        "close_in_days": None,
    },
]

_EXTRA_PHRASES = {
    "OUTSIDE_PREFERRED_CATEGORIES": "not a kind of opportunity you selected",
    "HIGH_TRAVEL_COST": "far from your preferred regions and not funded",
    "ELIGIBILITY_UNCLEAR": "some requirements could not be checked automatically",
    "FIRST_YEAR_INELIGIBLE": "not open to first-year students",
}
_ELIG_LABEL = {
    "eligible": "Looks eligible",
    "possibly_eligible": "Possibly eligible",
    "needs_review": "Needs your review",
    "future_cycle": "Eligible in a future cycle",
    "ineligible": "Not eligible",
}


def _phrase(code: str) -> str:
    return _REASON_PHRASES.get(code) or _EXTRA_PHRASES.get(code) or code.lower().replace("_", " ")


def _certainty(elig: EligibilityStatus, has_deadline: bool, unresolved: int) -> tuple[str, str]:
    """A plain summary of how much the rules could settle, not a probability."""
    if elig is EligibilityStatus.ELIGIBLE and has_deadline:
        return "higher", "every stated requirement was checked and the deadline is known"
    if elig is EligibilityStatus.INELIGIBLE:
        return "higher", "a stated requirement rules this out"
    if elig is EligibilityStatus.FUTURE_CYCLE:
        return "higher", "a stated requirement rules this out for now, but not for good"
    gaps = []
    if unresolved:
        gaps.append(
            f"{unresolved} requirement{'s' if unresolved > 1 else ''} need{'' if unresolved > 1 else 's'} a human look"
        )
    if not has_deadline:
        gaps.append("no confirmed deadline")
    if gaps:
        return "lower", " and ".join(gaps)
    return "medium", "requirements look fine but are not all explicit"


def evaluate(profile: Profile, weights: ScoringWeights, now: datetime) -> list[dict[str, Any]]:
    today = local_today(now)
    labels = dict(catalog.INTERESTS)
    cats = {c[0]: c[1] for c in catalog.CATEGORIES}
    out = []
    for s in SAMPLES:
        elig = assess([(r, "unknown", None) for r in s["requirements"]], profile)
        fit = compute_fit(
            topic=s["topic"] + " " + s["title"],
            category=s["category"],
            eligibility=elig.status,
            funding_status=s["funding"],
            funding_confirmed=True,
            fee_max=None,
            fmt=s["format"],
            location=s["location"],
            profile=profile,
            weights=weights,
        )
        close = s["close_in_days"]
        deadlines = (
            [
                {
                    "id": "sample",
                    "deadline_type": "application_close",
                    "fact_status": "confirmed_official",
                    "due_date_local": (today + timedelta(days=close)).isoformat(),
                }
            ]
            if close is not None
            else []
        )
        edition = {
            "fact_status": "confirmed_official",
            "source_fresh_until": "9999-12-31T00:00:00Z",
        }
        urg = compute_urgency(edition, deadlines, today, now)  # type: ignore[arg-type]
        unresolved_critical = any(
            c.assessment == "unclear" and c.blocking_flag != "false" for c in elig.criteria
        )
        band = priority_band(fit.fit, urg.score, elig.status, "open", unresolved_critical)
        action = recommended_action(elig.status, band, "open", urg, today)
        level, why = _certainty(elig.status, close is not None, elig.unresolved_count)
        reasons = list(dict.fromkeys(fit.reasons + urg.reasons))
        if elig.unresolved_count:
            reasons.append("ELIGIBILITY_UNCLEAR")
        out.append(
            {
                "title": s["title"],
                "category": cats.get(s["category"], s["category"]),
                "location": s["location"],
                "fit": fit.fit,
                "components": fit.components,
                "urgency": urg.score,
                "days_left": urg.distance_days,
                "band": band,
                "action": action,
                "matched_interests": [
                    labels.get(t, t.replace("_", " "))
                    for t in matched_interests(s["topic"], profile)
                ],
                "reasons": [_phrase(r) for r in reasons],
                "eligibility": {
                    "status": elig.status.value,
                    "label": _ELIG_LABEL[elig.status.value],
                    "criteria": [
                        {"text": c.requirement_text, "assessment": c.assessment, "why": c.rationale}
                        for c in elig.criteria
                    ],
                },
                "certainty": {"level": level, "why": why},
            }
        )
    return out
