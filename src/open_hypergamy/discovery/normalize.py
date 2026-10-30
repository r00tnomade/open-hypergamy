"""Title/organizer normalization and edition-key guesses (LLD §3.2, §8.3)."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import urlsplit

_YEAR_RANGE = re.compile(r"\b(20\d{2})\s*[/–-]\s*(20\d{2}|\d{2})\b")
_YEAR = re.compile(r"\b(20\d{2})\b")
_ORDINAL = re.compile(r"\b\d+(?:st|nd|rd|th)\b")
_STOP = {
    "annual",
    "the",
    "a",
    "an",
    "of",
    "and",
    "for",
    "in",
    "at",
    "to",
    "der",
    "die",
    "das",
    "und",
    "fur",
    "für",
}
_CATEGORIES: list[tuple[str, str]] = [
    ("call_for_papers", r"call for papers|\bcfp\b"),
    ("summer_school", r"summer school|winter school|sommerschule|spring school"),
    ("internship", r"internship|praktikum|traineeship|werkstudent"),
    ("fellowship", r"fellowship"),
    ("scholarship", r"scholarship|stipend|stipendium"),
    ("hackathon", r"hackathon"),
    ("challenge", r"challenge|competition|wettbewerb"),
    ("conference", r"conference|symposium|konferenz"),
    ("workshop", r"workshop"),
    ("grant", r"\bgrants?\b|funding programme"),
    # Last, so it only claims titles that previously fell through to "other" (ADR-014).
    ("research_programme", r"research programm?e?\b|undergraduate research|summer research"),
]
OPPORTUNITY_RE = re.compile(
    "|".join(p for _, p in _CATEGORIES)
    + r"|research programme|research program|undergraduate research|ausschreibung",
    re.IGNORECASE,
)
APPLICATION_PHRASE_RE = re.compile(
    r"\bapply\b|application|\bapplicants?\b|call for|bewerb|\bsubmission\b|registration",
    re.IGNORECASE,
)
# Strong, low-noise URL keywords for link-only candidates (sitemaps).
URL_KEYWORD_RE = re.compile(
    r"summer-?school|winter-?school|internship|fellowship|scholarship|hackathon|call-?for-?papers|"
    r"\bcfp\b|praktikum|stipendium|sommerschule|traineeship",
    re.IGNORECASE,
)


def normalize_title(title: str) -> str:
    """Lowercased, accent-folded, punctuation- and year-free title for identity comparison."""
    t = unicodedata.normalize("NFKD", title).casefold()
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = _ORDINAL.sub(" ", _YEAR_RANGE.sub(" ", t))
    t = _YEAR.sub(" ", t)
    t = re.sub(r"[^\w\s]", " ", t)
    return " ".join(w for w in t.split() if w not in _STOP)


def organizer_domain(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def guess_edition_key(title: str, url: str, event_years: set[int] | None = None) -> str | None:
    """Year/cycle from the title, then URL path, then a single unambiguous event-date year."""
    for source in (title, urlsplit(url).path):
        m = _YEAR_RANGE.search(source)
        if m:
            end = m[2] if len(m[2]) == 4 else m[1][:2] + m[2]
            return f"{m[1]}-{end}"
        years: set[str] = set(_YEAR.findall(source))
        if len(years) == 1:
            return years.pop()
    if event_years and len(event_years) == 1:
        return str(next(iter(event_years)))
    return None


def edition_year(edition_key: str | None) -> int | None:
    m = _YEAR.search(edition_key or "")
    return int(m[1]) if m else None


def fingerprint(title: str, domain: str, edition_key: str | None) -> str:
    raw = f"{normalize_title(title)}|{domain}|{edition_key or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()


def guess_category(text: str) -> str:
    for name, pat in _CATEGORIES:
        if re.search(pat, text, re.IGNORECASE):
            return name
    return "other"


def title_from_url(url: str) -> str:
    slug = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    return re.sub(r"[-_]+", " ", re.sub(r"\.\w{2,5}$", "", slug)).strip().title()


_TITLE_SEP = re.compile(r"\s+[|–—]\s+|\s+-\s+")


def clean_title(title: str) -> str:
    """Drop site-name suffixes ('Summer School 2027 | Example Institute')."""
    parts = [p.strip() for p in _TITLE_SEP.split(title) if p.strip()]
    if not parts:
        return title.strip()
    for p in parts:
        if OPPORTUNITY_RE.search(p):
            return p
    return parts[0]


def registrable_domain(host: str) -> str:
    """Approximate registrable domain without a public-suffix list (sub-domains dropped)."""
    labels = organizer_domain(f"https://{host}/").split(".")
    if len(labels) <= 2:
        return ".".join(labels)
    if len(labels[-1]) == 2 and labels[-2] in {"co", "ac", "org", "gov", "edu", "com", "net"}:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])
