"""Explainable fit score (LLD §11.3). Components are 0-100; rules are versioned in code.

Fit says how good an opportunity is for the profile. It never looks at deadlines: urgency
lives in `urgency.py` and must not inflate a weak fit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from open_hypergamy.config import ScoringWeights
from open_hypergamy.domain.enums import EligibilityStatus
from open_hypergamy.profile import Profile
from open_hypergamy.verification.eligibility import EU, EUROPE

SCORING_VERSION = "score-v2"  # v2: preferences.categories, WORLDWIDE region (ADR-014)

_TAG_KEYWORDS: dict[str, tuple[str, ...]] = {
    "ai_systems": (
        "ai systems",
        "ml systems",
        "mlsys",
        "inference",
        "llm",
        "large language",
        "distributed training",
        "gpu",
        "machine learning systems",
    ),
    "applied_ml": (
        "machine learning",
        "deep learning",
        "neural",
        "applied ai",
        "artificial intelligence",
    ),
    "robotics": ("robot", "manipulation", "mechatronic", "drone"),
    "autonomous_systems": ("autonomous", "self-driving", "uav", "unmanned"),
    "visuotactile_sensing": ("tactile", "haptic", "visuotactile"),
    "computer_vision": ("computer vision", "image recognition", "visual perception", "vision"),
    "systems_security": ("security", "cybersecurity", "cryptograph", "exploit", "ctf"),
    "natural_language_processing": ("natural language", "nlp", "language model", "speech"),
    "quantum_computing": ("quantum",),
    "high_performance_computing": ("high performance computing", "hpc", "supercomput"),
    "embedded_systems": ("embedded", "microcontroller", "fpga", "firmware"),
    "human_computer_interaction": (
        "human-computer",
        "hci",
        "interaction design",
        "user experience",
    ),
    "computational_biology": ("bioinformatic", "computational biology", "genomic"),
    "data_science": ("data science", "statistics", "data analysis"),
    "open_source": ("open source", "open-source"),
}
_CATEGORY_VALUE = {
    "research_programme": 85,
    "internship": 80,
    "fellowship": 80,
    "call_for_papers": 75,
    "summer_school": 70,
    "challenge": 60,
    "conference": 60,
    "hackathon": 55,
    "workshop": 55,
    "scholarship": 40,
    "other": 40,
}
_RESEARCH_WORDS = re.compile(r"\b(research|laborator|lab\b|publication|paper|thesis|phd)", re.I)
_FUNDING = {
    "fully_funded": 100,
    "partially_funded": 70,
    "available_competitive": 50,
    "unknown": 35,
    "self_funded": 15,
    "not_applicable": 50,
}
_DE_PLACES = (
    "germany",
    "deutschland",
    "berlin",
    "munich",
    "münchen",
    "hamburg",
    "aachen",
    "stuttgart",
    "karlsruhe",
    "darmstadt",
    "dresden",
    "leipzig",
    "cologne",
    "köln",
    "frankfurt",
    "heidelberg",
    "tübingen",
    "bonn",
    "garching",
    "jülich",
)
_EU_PLACES = {
    "france": "FR",
    "paris": "FR",
    "austria": "AT",
    "vienna": "AT",
    "netherlands": "NL",
    "amsterdam": "NL",
    "delft": "NL",
    "italy": "IT",
    "spain": "ES",
    "sweden": "SE",
    "finland": "FI",
    "denmark": "DK",
    "poland": "PL",
    "belgium": "BE",
    "leuven": "BE",
    "zurich": "CH",
    "switzerland": "CH",
    "lausanne": "CH",
    "london": "GB",
    "cambridge": "GB",
    "oxford": "GB",
}
_FAR = (
    "united states",
    "usa",
    "california",
    "boston",
    "new york",
    "pittsburgh",
    "japan",
    "tokyo",
    "china",
    "singapore",
    "canada",
    "toronto",
    "australia",
    "korea",
)


@dataclass
class FitResult:
    components: dict[str, float]
    fit: float
    reasons: list[str] = field(default_factory=list)


def detect_region(location: str | None) -> str | None:
    t = (location or "").lower()
    if any(p in t for p in _DE_PLACES):
        return "DE"
    for place, code in _EU_PLACES.items():
        if place in t:
            return code
    if "europe" in t:
        return "EU"
    return "FAR" if any(p in t for p in _FAR) else None


def region_ok(code: str | None, primary: list[str]) -> bool | None:
    if code is None:
        return None
    if any(x.upper() == "WORLDWIDE" for x in primary):
        return True
    if code == "FAR":
        return False
    p = {x.upper() for x in primary}
    return (
        code in p
        or ("EU" in p and (code in EU or code == "EU"))
        or ("EUROPE" in p and (code in EUROPE or code == "EU"))
    )


def matched_interests(topic: str, profile: Profile) -> list[str]:
    t = topic.lower()
    return [
        tag
        for tag in profile.research_tags
        if any(k in t for k in _TAG_KEYWORDS.get(tag, (tag.replace("_", " "),)))
    ]


def career_alignment(topic: str, profile: Profile) -> tuple[float, list[str]]:
    matched = set(matched_interests(topic, profile))
    if not matched:
        return 20.0, []
    score = min(100.0, 45.0 + 25.0 * (len(matched) - 1) + 30.0 * (len(matched) >= 1))
    return min(score, 100.0), (["HIGH_CAREER_ALIGNMENT"] if score >= 70 else [])


def technical_value(
    category: str | None, topic: str, preferred: list[str] | None = None
) -> tuple[float, list[str]]:
    base = _CATEGORY_VALUE.get(category or "other", 40)
    research = bool(_RESEARCH_WORDS.search(topic))
    score = min(100.0, base + (10 if research else 0))
    likely = category in ("call_for_papers", "research_programme") or bool(
        re.search(r"\b(publication|paper)", topic, re.I)
    )
    reasons = ["RESEARCH_OUTPUT_LIKELY"] if likely else []
    if preferred:  # empty = "show me everything relevant": no adjustment
        if (category or "other") in preferred:
            score = min(100.0, score + 15)
            reasons.append("PREFERRED_CATEGORY")
        else:
            score = max(0.0, score - 30)
            reasons.append("OUTSIDE_PREFERRED_CATEGORIES")
    return float(score), reasons


def funding_score(
    status: str | None, status_confirmed: bool, fee_max: float | None, profile: Profile
) -> tuple[float, list[str]]:
    base = float(_FUNDING.get(status or "unknown", 35))
    if fee_max and fee_max > 0:
        limit = profile.preferences.budget_limit_eur
        if limit is not None and fee_max > limit:
            base = min(base, 10.0)
        elif profile.preferences.needs_funding_or_low_cost and status in (
            None,
            "unknown",
            "self_funded",
        ):
            base = min(base, 20.0)
    reasons = (
        ["FUNDING_CONFIRMED"]
        if status in ("fully_funded", "partially_funded") and status_confirmed
        else []
    )
    return base, reasons


def time_cost(
    fmt: str | None, location: str | None, funding: str | None, profile: Profile
) -> tuple[float, list[str]]:
    score = 70.0
    reasons: list[str] = []
    if fmt == "online":
        score += 20
    elif fmt in ("in_person", "hybrid", None):
        ok = region_ok(detect_region(location), profile.preferences.primary_regions)
        if ok is False:
            funded = funding in ("fully_funded", "partially_funded")
            if not (profile.preferences.international_when_funded and funded):
                score -= 35
                reasons.append("HIGH_TRAVEL_COST")
            else:
                score -= 10
    return max(0.0, min(100.0, score)), reasons


_ELIG_SCORE = {
    EligibilityStatus.ELIGIBLE: 100.0,
    EligibilityStatus.POSSIBLY_ELIGIBLE: 60.0,
    EligibilityStatus.NEEDS_REVIEW: 40.0,
    EligibilityStatus.FUTURE_CYCLE: 20.0,
    EligibilityStatus.INELIGIBLE: 0.0,
}


def compute_fit(
    *,
    topic: str,
    category: str | None,
    eligibility: EligibilityStatus,
    funding_status: str | None,
    funding_confirmed: bool,
    fee_max: float | None,
    fmt: str | None,
    location: str | None,
    profile: Profile,
    weights: ScoringWeights,
) -> FitResult:
    ca, r1 = career_alignment(topic, profile)
    tv, r2 = technical_value(category, topic, list(profile.preferences.categories))
    fa, r3 = funding_score(funding_status, funding_confirmed, fee_max, profile)
    tc, r4 = time_cost(fmt, location, funding_status, profile)
    comps = {
        "career_alignment": ca,
        "technical_research_value": tv,
        "eligibility_feasibility": _ELIG_SCORE[eligibility],
        "funding_accessibility": fa,
        "time_cost": tc,
    }
    total = sum(comps[k] * getattr(weights, k) for k in comps) / 100.0
    return FitResult(comps, round(total, 1), r1 + r2 + r3 + r4)
