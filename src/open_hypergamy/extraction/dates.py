"""Strict, deterministic date extraction (LLD §9.6).

Never guesses: a missing year, an invalid calendar date or an ambiguous numeric format is
reported as `ambiguous` with a reason and carries no start/end date. The raw wording is always
kept. Times of day are not interpreted (precision is `date_only`); timezones are never inferred.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from open_hypergamy.domain.enums import DeadlineType

MONTHS = {
    "january": 1,
    "jan": 1,
    "januar": 1,
    "february": 2,
    "feb": 2,
    "februar": 2,
    "march": 3,
    "mar": 3,
    "märz": 3,
    "maerz": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "mai": 5,
    "june": 6,
    "jun": 6,
    "juni": 6,
    "july": 7,
    "jul": 7,
    "juli": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "oktober": 10,
    "okt": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
    "dezember": 12,
    "dez": 12,
}
_MON = "|".join(sorted(MONTHS, key=len, reverse=True))
_M = rf"\b(?:{_MON})\b\.?"
_D = r"(?<![\d.])\d{1,2}(?!\d)"
_O = r"(?:st|nd|rd|th|\.)?"
_Y = r"(?<!\d)(?:19|20)\d{2}(?!\d)"
_SEP = r"\s*(?:[-–—]|\bto\b|\bbis\b|\buntil\b|\bthrough\b)\s*"
_OF = r"(?:\s+of)?"
_F = re.IGNORECASE


def _c(p: str) -> re.Pattern[str]:
    return re.compile(p, _F)


_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("iso", _c(rf"(?<![\d-])(?P<y>{_Y})-(?P<m>\d{{2}})-(?P<d>\d{{2}})(?!\d)")),
    ("dotted", _c(rf"(?<![\d.])(?P<d>\d{{1,2}})\.(?P<m>\d{{1,2}})\.(?P<y>{_Y})")),
    ("slash", _c(rf"(?<![\d/])(?P<a>\d{{1,2}})/(?P<b>\d{{1,2}})/(?P<y>{_Y})")),
    (
        "dmy_cross",
        _c(
            rf"(?P<d1>{_D}){_O}{_OF}\s+(?P<m1>{_M})\s*(?P<y1>{_Y})?{_SEP}"
            rf"(?P<d2>{_D}){_O}{_OF}\s+(?P<m2>{_M}),?\s*(?P<y2>{_Y})?"
        ),
    ),
    (
        "dmy_range",
        _c(rf"(?P<d1>{_D}){_O}{_SEP}(?P<d2>{_D}){_O}{_OF}\s+(?P<m>{_M}),?\s*(?P<y>{_Y})?"),
    ),
    ("dmy", _c(rf"(?P<d>{_D}){_O}{_OF}\s+(?P<m>{_M}),?\s*(?P<y>{_Y})?")),
    (
        "mdy_full_range",
        _c(
            rf"(?P<m1>{_M})\s+(?P<d1>{_D}){_O},?\s*(?P<y1>{_Y}){_SEP}"
            rf"(?P<m2>{_M})\s+(?P<d2>{_D}){_O},?\s*(?P<y2>{_Y})"
        ),
    ),
    (
        "mdy_cross",
        _c(
            rf"(?P<m1>{_M})\s+(?P<d1>{_D}){_O}{_SEP}(?P<m2>{_M})\s+(?P<d2>{_D}){_O},?\s*(?P<y>{_Y})?"
        ),
    ),
    ("mdy_range", _c(rf"(?P<m>{_M})\s+(?P<d1>{_D}){_O}{_SEP}(?P<d2>{_D}){_O},?\s*(?P<y>{_Y})?")),
    ("mdy", _c(rf"(?P<m>{_M})\s+(?P<d>{_D}){_O},?\s*(?P<y>{_Y})?")),
    ("month_year", _c(rf"(?P<m>{_M}),?\s+(?P<y>{_Y})")),
]


@dataclass(frozen=True)
class DateMention:
    raw: str
    start: date | None
    end: date | None
    precision: str  # date_only | month_only
    year_explicit: bool
    ambiguous: str | None  # reason code, or None when the mention is a usable calendar date
    span: tuple[int, int]

    @property
    def usable(self) -> bool:
        return self.ambiguous is None and self.start is not None


def _month(token: str) -> int:
    return MONTHS[token.strip(".").lower()]


def _mk(y: int | None, m: int, d: int) -> date | None:
    if y is None:
        return None
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _build(kind: str, g: dict[str, str | None], raw: str, span: tuple[int, int]) -> DateMention:
    def amb(reason: str, explicit: bool, precision: str = "date_only") -> DateMention:
        return DateMention(raw, None, None, precision, explicit, reason, span)

    def num(key: str) -> int | None:
        v = g.get(key)
        return int(v) if v else None

    if kind == "month_year":
        y, m = num("y"), _month(g["m"] or "")
        return DateMention(
            raw,
            date(y, m, 1) if y else None,
            None,
            "month_only",
            True,
            "month_only_precision",
            span,
        )
    if kind in ("iso", "dotted", "slash"):
        y = num("y")
        if kind == "slash":
            a, b = num("a") or 0, num("b") or 0
            if a > 12 >= b:
                d, m = a, b
            elif b > 12 >= a:
                d, m = b, a
            elif a == b:
                d, m = a, b
            else:
                return amb("ambiguous_numeric_format", True)
        else:
            d, m = num("d") or 0, num("m") or 0
        start = _mk(y, m, d)
        return DateMention(
            raw, start, None, "date_only", True, None if start else "invalid_date", span
        )

    # textual month formats
    if kind in ("dmy_cross", "mdy_cross", "mdy_full_range"):
        m1, m2 = _month(g["m1"] or ""), _month(g["m2"] or "")
        d1, d2 = num("d1") or 0, num("d2") or 0
        y2 = num("y2") or num("y")
        y1 = num("y1") or (y2 if (num("y1") is None) else None)
        if y2 is not None and num("y1") is None and m1 > m2:
            y1 = y2 - 1  # "28 Dec – 3 Jan 2027" spans the year boundary
        explicit = y2 is not None
    elif kind in ("dmy_range", "mdy_range"):
        m1 = m2 = _month(g["m"] or "")
        d1, d2 = num("d1") or 0, num("d2") or 0
        y1 = y2 = num("y")
        explicit = y1 is not None
    else:  # dmy / mdy
        m1 = m2 = _month(g["m"] or "")
        d1 = d2 = num("d") or 0
        y1 = y2 = num("y")
        explicit = y1 is not None
    # "may"/"mai" are ordinary words: without a year only the capitalised form counts.
    month_tokens = [g.get(k) for k in ("m", "m1", "m2") if g.get(k)]
    if not explicit and any(
        t and t.strip(".").lower() in ("may", "mai") and t[0].islower() for t in month_tokens
    ):
        return amb("not_a_date", False)
    if not explicit:
        return amb("missing_year", False)
    start, end = _mk(y1, m1, d1), _mk(y2, m2, d2)
    if start is None or end is None:
        return amb("invalid_date", True)
    if d1 == d2 and m1 == m2 and y1 == y2:
        return DateMention(raw, start, None, "date_only", True, None, span)
    if end < start:
        return amb("range_inverted", True)
    return DateMention(raw, start, end, "date_only", True, None, span)


def find_dates(text: str) -> list[DateMention]:
    taken: list[tuple[int, int]] = []
    found: list[DateMention] = []
    for kind, pat in _PATTERNS:
        for m in pat.finditer(text):
            span = m.span()
            if any(span[0] < e and s < span[1] for s, e in taken):
                continue
            mention = _build(kind, m.groupdict(), m.group(0).strip(), span)
            if mention.ambiguous == "not_a_date":
                continue
            taken.append(span)
            found.append(mention)
    return sorted(found, key=lambda x: x.span)


# --- context classification ---------------------------------------------------------------
EVENT = "event"
_SPECIFIC: list[tuple[str, list[str]]] = [  # order = tie-break priority
    (DeadlineType.ABSTRACT_SUBMISSION, [r"\babstracts?\b"]),
    (
        DeadlineType.PAPER_SUBMISSION,
        [r"full\s+papers?", r"paper\s+submissions?", r"manuscripts?", r"camera[- ]ready"],
    ),
    (
        DeadlineType.REGISTRATION_CLOSE,
        [
            r"registration\s+(?:deadline|closes?|closing|ends?)",
            r"register\s+(?:by|before|until)",
            r"anmeldeschluss",
            r"anmeldefrist",
        ],
    ),
    (
        DeadlineType.RECOMMENDATION_LETTER,
        [r"recommendations?", r"reference\s+letters?", r"referees?", r"empfehlungsschreiben"],
    ),
    (
        DeadlineType.TRAVEL_GRANT,
        [r"travel\s+(?:grants?|support|stipends?|funding)", r"reisekosten"],
    ),
    (DeadlineType.SCHOLARSHIP, [r"scholarships?\s+(?:deadline|applications?)"]),
    (DeadlineType.TEAM_FORMATION, [r"team\s+formation", r"form(?:ing)?\s+(?:a\s+)?teams?"]),
    (
        DeadlineType.APPLICATION_OPEN,
        [
            r"applications?\s+(?:will\s+)?(?:open|start|begin)s?",
            r"(?:call|submissions?)\s+opens?",
            r"\bopens?\s+(?:on|at|from)\b",
            r"open\s+from",
            r"bewerbungsstart",
            r"bewerbungen?\s+(?:ab|starten|beginnen)",
            r"application\s+period\s+(?:starts|begins)",
        ],
    ),
    (
        DeadlineType.APPLICATION_CLOSE,
        [
            r"application\s+deadline",
            r"deadline\s+for\s+(?:applications?|applying)",
            r"applications?\s+(?:must\s+be\s+\w+\s+)?(?:by|before|until|due)\b",
            r"\bclos(?:e|es|ed|ing)\b",
            r"apply\s+(?:by|before|until)",
            r"closing\s+date",
            r"last\s+date\s+to\s+apply",
            r"bewerbungsfrist",
            r"bewerbungsschluss",
            r"bewerbung(?:en)?\s+bis",
            r"submit\s+your\s+application\s+(?:by|before)",
        ],
    ),
    (
        EVENT,
        [
            r"takes?\s+place",
            r"will\s+be\s+held",
            r"\bheld\s+(?:on|from|in|at)\b",
            r"taking\s+place",
            r"event\s+dates?",
            r"(?:conference|workshop|school|programme|program|"
            r"hackathon)\s+dates?",
            r"\bdates?\s*:",
            r"runs?\s+(?:from|until|through)",
            r"findet\s+statt",
            r"stattfinden",
            r"\bvom\b",
            r"duration",
        ],
    ),
]
_GENERIC_DEADLINE = re.compile(r"\bdeadlines?\b|\bfrist\b|\bdue\b", _F)
_SPECIFIC_C = [(t, [_c(p) for p in ps]) for t, ps in _SPECIFIC]
_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ])|\n")


def _segment_before(text: str, start: int) -> str:
    """Text before `start` back to the previous sentence/line boundary (extended one segment if
    that boundary leaves nothing, e.g. a heading on the line above the value)."""
    window = text[max(0, start - 240) : start]
    parts = _BOUNDARY.split(window)
    seg = parts[-1]
    if len(seg.strip(" :-–—\t")) < 3 and len(parts) > 1:
        seg = parts[-2] + " " + seg
    return seg


def _segment_after(text: str, end: int) -> str:
    return _BOUNDARY.split(text[end : end + 90])[0]


def _best_hit(segment: str) -> str | None:
    best: tuple[int, int, str] | None = None  # (end_pos, -priority, type) -> max
    for prio, (typ, pats) in enumerate(_SPECIFIC_C):
        for p in pats:
            for m in p.finditer(segment):
                cand = (m.end(), -prio, typ)
                if best is None or cand[:2] > best[:2]:
                    best = cand
    if best is not None:
        return best[2]
    return DeadlineType.APPLICATION_CLOSE.value if _GENERIC_DEADLINE.search(segment) else None


def classify_context(text: str, mention: DateMention) -> str | None:
    """DeadlineType value, `event`, or None when the surrounding wording is unclear."""
    before = _best_hit(_segment_before(text, mention.span[0]))
    return before or _best_hit(_segment_after(text, mention.span[1]))


def sentence_around(text: str, span: tuple[int, int], limit: int = 400) -> str:
    """The sentence/line containing a mention, verbatim from `text`, for evidence excerpts."""
    start = max((m.end() for m in _BOUNDARY.finditer(text, 0, span[0])), default=0)
    nxt = _BOUNDARY.search(text, span[1])
    end = nxt.start() if nxt else len(text)
    seg = text[start:end].strip()
    if len(seg) > limit:
        rel = span[0] - start
        seg = text[max(start, span[0] - limit // 2) : min(end, span[1] + limit // 2)].strip()
        _ = rel
    return seg
