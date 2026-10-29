"""Rule-based eligibility interpretation against the local profile (LLD §10.1, §11.2).

Requirement *text* comes from grounded claims (typically LLM-extracted); the *decision* is made
here by explicit rules. Anything the rules cannot resolve is `unclear`, never guessed, and
the absence of an eligibility statement is not proof of eligibility.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from open_hypergamy.domain.enums import EligibilityStatus
from open_hypergamy.profile import Profile

EU = {
    "AT",
    "BE",
    "BG",
    "HR",
    "CY",
    "CZ",
    "DK",
    "EE",
    "FI",
    "FR",
    "DE",
    "GR",
    "HU",
    "IE",
    "IT",
    "LV",
    "LT",
    "LU",
    "MT",
    "NL",
    "PL",
    "PT",
    "RO",
    "SK",
    "SI",
    "ES",
    "SE",
}
EEA = EU | {"IS", "LI", "NO"}
EUROPE = EEA | {"CH", "GB", "UK"}
_REGION = {
    "german": {"DE"},
    "austrian": {"AT"},
    "swiss": {"CH"},
    "french": {"FR"},
    "dutch": {"NL"},
    "eu": EU,
    "eea": EEA,
    "european": EUROPE,
    "uk": {"GB", "UK"},
    "us": {"US"},
}
_NUM = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "1": 1,
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
}
_LEVELS = {
    "bachelor": re.compile(r"\b(?:bachelor|undergraduate|b\.?sc\.?)\w*", re.I),
    "master": re.compile(r"\b(?:master|m\.?sc\.?|postgraduate|graduate\s+students?)\w*", re.I),
    "phd": re.compile(r"\b(?:ph\.?d|doctoral|doctorate|doktorand)\w*", re.I),
}
_RANK = {"bachelor": 1, "master": 2, "phd": 3}
_YEAR = re.compile(
    r"\b(?P<n>first|second|third|fourth|fifth|[1-5])(?:st|nd|rd|th)?[-\s]year\b", re.I
)
_MIN_CUE = re.compile(
    r"or\s+(?:above|higher|later|beyond|more)|at\s+least|minimum|from\s+the", re.I
)
_INSTITUTION = re.compile(
    r"(?:enrolled|registered|studying)\s+(?:at|in)\s+an?\s+(?P<c>german|austrian|swiss|french|dutch|"
    r"european|eu|eea|uk|us)\s+(?:university|institution|higher)",
    re.I,
)
_CITIZEN = re.compile(r"\b(?:citizens?|nationals?|nationality|passport|work\s+permit|visa)\b", re.I)
_AGE = re.compile(
    r"\b(?:under|below|over|aged?|younger\s+than|older\s+than)\s*\d{2}\b|\b\d{2}\s+years\s+old\b",
    re.I,
)
_SUBJECT = re.compile(
    r"(?:studying|enrolled\s+in|majoring\s+in|background\s+in|degree\s+in|studies\s+in)\s+(?P<s>[^.,;]+)",
    re.I,
)
_MATERIAL = re.compile(
    r"\b(?:cv|resume|curriculum|letters?|transcripts?|portfolio|motivation|statement|references?|recommendation|upload|form)\b",
    re.I,
)
_ENROLLED = re.compile(r"\benrolled\b|\bstudents?\b|\bstudying\b", re.I)


@dataclass
class RequirementResult:
    requirement_text: str
    assessment: str  # satisfied | blocking | unclear | not_applicable
    kind: str
    profile_field: str
    rationale: str
    assessment_method: str = "llm_assisted"  # text from the LLM, decision by rules
    blocking_flag: str = "unknown"
    future: bool = False
    evidence_claim_id: str | None = None

    def as_dict(self) -> dict[str, object]:
        return dict(vars(self))


@dataclass
class Eligibility:
    status: EligibilityStatus
    blocking_count: int = 0
    unresolved_count: int = 0
    summary: str = ""
    criteria: list[RequirementResult] = field(default_factory=list)
    year_blocked: bool = False


def interpret(text: str, profile: Profile, flag: str = "unknown") -> RequirementResult:
    a = profile.academic

    def res(
        assessment: str, kind: str, pfield: str, why: str, future: bool = False
    ) -> RequirementResult:
        if assessment == "blocking" and flag == "false":  # the source calls it optional/preferred
            assessment, why = "unclear", f"marked non-blocking by the source; {why}"
        return RequirementResult(
            text, assessment, kind, pfield, why, blocking_flag=flag, future=future
        )

    levels = {k for k, p in _LEVELS.items() if p.search(text)}
    if levels:
        if a.degree_level in levels:
            return res(
                "satisfied", "degree", "academic.degree_level", f"profile is {a.degree_level}"
            )
        later = any(_RANK[k] > _RANK[a.degree_level] for k in levels)
        return res(
            "blocking",
            "degree",
            "academic.degree_level",
            f"requires {'/'.join(sorted(levels))}; profile is {a.degree_level}",
            future=later,
        )

    ym = _YEAR.search(text)
    if ym:
        n = _NUM[ym["n"].lower()]
        cur = a.current_year
        if cur is None:
            return res("unclear", "year", "academic.current_year", "profile has no current_year")
        window = text[max(0, ym.start() - 25) : ym.end() + 30]
        if _MIN_CUE.search(window):
            if cur >= n:
                return res(
                    "satisfied", "year", "academic.current_year", f"year {cur} >= required {n}"
                )
            return res(
                "blocking",
                "year",
                "academic.current_year",
                f"requires year >= {n}; profile is year {cur}",
                future=True,
            )
        if cur == n:
            return res("satisfied", "year", "academic.current_year", f"year {cur} matches")
        return res(
            "blocking",
            "year",
            "academic.current_year",
            f"requires year {n}; profile is year {cur}",
            future=cur < n,
        )

    im = _INSTITUTION.search(text)
    if im:
        allowed = _REGION[im["c"].lower()]
        if a.country.upper() in allowed:
            return res(
                "satisfied", "institution", "academic.country", f"institution country {a.country}"
            )
        return res(
            "blocking",
            "institution",
            "academic.country",
            f"requires institution in {im['c']}; profile country is {a.country}",
        )

    if _CITIZEN.search(text):
        return res(
            "unclear",
            "citizenship",
            "(not stored)",
            "the profile stores no citizenship or visa data",
        )
    if _AGE.search(text):
        return res("unclear", "age", "(not stored)", "the profile stores no age data")

    sm = _SUBJECT.search(text)
    if sm:
        wanted = sm["s"].lower()
        tags = {t.replace("_", " ").lower() for t in a.subject_tags}
        if any(t in wanted or wanted.strip() in t for t in tags):
            return res(
                "satisfied", "subject", "academic.subject_tags", "subject matches a profile tag"
            )
        return res(
            "unclear",
            "subject",
            "academic.subject_tags",
            "subject wording does not match a profile tag",
        )

    if _MATERIAL.search(text):
        return res(
            "not_applicable", "materials", "-", "application material, not an eligibility criterion"
        )
    if _ENROLLED.search(text):
        return res("satisfied", "enrolment", "academic", "profile is an enrolled student")
    return res("unclear", "other", "-", "no deterministic rule covers this wording")


def assess(requirements: list[tuple[str, str, str | None]], profile: Profile) -> Eligibility:
    """`requirements` = (text, blocking_flag, claim_id)."""
    results = []
    for text, flag, claim_id in requirements:
        r = interpret(text, profile, flag)
        r.evidence_claim_id = claim_id
        results.append(r)
    blockers = [r for r in results if r.assessment == "blocking"]
    unclear = [r for r in results if r.assessment == "unclear" and r.blocking_flag != "false"]
    counted = [r for r in results if r.assessment != "not_applicable"]
    year_blocked = any(r.kind == "year" for r in blockers)
    if blockers:
        status = (
            EligibilityStatus.FUTURE_CYCLE
            if all(r.future for r in blockers)
            else EligibilityStatus.INELIGIBLE
        )
        return Eligibility(
            status,
            len(blockers),
            len(unclear),
            "; ".join(r.rationale for r in blockers),
            results,
            year_blocked,
        )
    if not counted:
        return Eligibility(
            EligibilityStatus.POSSIBLY_ELIGIBLE,
            0,
            1,
            "No eligibility statement found; absence is not proof of eligibility.",
            results,
        )
    if unclear:
        recognised = any(r.kind in ("degree", "year", "institution") for r in unclear)
        status = (
            EligibilityStatus.NEEDS_REVIEW
            if recognised or len(unclear) >= 3
            else EligibilityStatus.POSSIBLY_ELIGIBLE
        )
        return Eligibility(
            status, 0, len(unclear), "; ".join(r.rationale for r in unclear), results
        )
    return Eligibility(
        EligibilityStatus.ELIGIBLE, 0, 0, "all known requirements satisfied", results
    )
