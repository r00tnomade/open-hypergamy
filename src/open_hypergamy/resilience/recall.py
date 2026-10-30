"""Opportunity-capture recall against an independent ground-truth set (ADR-013).

Recall is measured over the whole acquisition network: an opportunity counts as captured if ANY
channel (official page, feed, calendar, newsletter import, ...) produced a candidate for it.
Per-source or per-proxy HTTP success rates say nothing about this and are not used.

This module computes a number from evidence the operator supplies. It does not, and cannot,
establish that the ground truth is independent or complete, so the verdict is deliberately
conservative: it never reports "target met" without an attested truth set, a minimum sample and
a Wilson 95 % lower bound at or above the target.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from open_hypergamy.discovery.normalize import (
    fingerprint,
    guess_edition_key,
    organizer_domain,
    registrable_domain,
)
from open_hypergamy.errors import ConfigurationError
from open_hypergamy.sources.urls import canonicalize_url

MIN_SAMPLE = 100
Z95 = 1.959963984540054


class TruthItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    url: str | None = None
    organizer_domain: str | None = None
    edition_key: str | None = None


class TruthSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    compiled_by: str = ""  # who compiled it, outside OHG
    compiled_at: str = ""
    method: str = ""  # how it was compiled independently of OHG's own sources
    independent: bool = False  # operator attestation; OHG cannot verify it
    opportunities: list[TruthItem]

    @field_validator("opportunities")
    @classmethod
    def _non_empty(cls, v: list[TruthItem]) -> list[TruthItem]:
        if not v:
            raise ValueError("the truth set has no opportunities")
        return v

    @property
    def attested(self) -> bool:
        return self.independent and bool(self.compiled_by.strip()) and bool(self.method.strip())


def load_truth(path: Path) -> TruthSet:
    try:
        data: Any = yaml.safe_load(path.read_text())
        return TruthSet.model_validate(
            data.get("truth_set", data) if isinstance(data, dict) else data
        )
    except (OSError, yaml.YAMLError) as e:
        raise ConfigurationError(f"cannot read truth set: {e}") from None
    except ValidationError as e:
        problems = "; ".join(
            f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}"
            for err in e.errors(include_input=False, include_url=False, include_context=False)
        )
        raise ConfigurationError(f"invalid truth set: {problems}") from None


def wilson_interval(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


@dataclass
class RecallReport:
    truth_id: str
    n: int
    captured: int
    recall: float
    low: float
    high: float
    target: float
    attested: bool
    verdict: str
    by_channel: dict[str, int] = field(default_factory=dict)
    missed: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, object]:
        return {
            "truth_set": self.truth_id,
            "n": self.n,
            "captured": self.captured,
            "recall": round(self.recall, 4),
            "wilson95": [round(self.low, 4), round(self.high, 4)],
            "target": self.target,
            "truth_set_attested_independent": self.attested,
            "verdict": self.verdict,
            "captured_by_channel": dict(sorted(self.by_channel.items())),
            "missed": self.missed,
            "caveats": self.caveats,
        }


def _identity(item: TruthItem) -> tuple[str | None, str]:
    url = None
    if item.url:
        try:
            url = canonicalize_url(item.url)
        except Exception:  # noqa: BLE001
            url = None
    host = item.organizer_domain or (organizer_domain(url) if url else "")
    key = item.edition_key or guess_edition_key(item.title, url or "")
    return url, fingerprint(item.title, registrable_domain(host) if host else "", key)


def measure(conn: sqlite3.Connection, truth: TruthSet, *, target: float = 0.97) -> RecallReport:
    """Match each truth item to a candidate by canonical URL, else by identity fingerprint."""
    rows = conn.execute(
        "SELECT c.canonical_url, c.normalized_fingerprint, "
        "COALESCE(s.adapter_type, 'manual') AS ch "
        "FROM candidates c LEFT JOIN sources s ON s.id = c.discovered_by_source_id "
        "ORDER BY c.first_seen_at, c.id"
    ).fetchall()
    by_url: dict[str, str] = {}
    by_fp: dict[str, str] = {}
    for r in rows:
        by_url.setdefault(r["canonical_url"], r["ch"])
        by_fp.setdefault(r["normalized_fingerprint"], r["ch"])
    captured = 0
    channels: dict[str, int] = {}
    missed: list[str] = []
    for item in truth.opportunities:
        url, fp = _identity(item)
        channel = (by_url.get(url) if url else None) or by_fp.get(fp)
        if channel is None:
            missed.append(item.title)
        else:
            captured += 1
            channels[channel] = channels.get(channel, 0) + 1
    n = len(truth.opportunities)
    low, high = wilson_interval(captured, n)
    caveats = [
        "Recall is only as trustworthy as the truth set; OHG cannot verify its independence "
        "or completeness.",
        "A match means a candidate exists, not that its dates were verified.",
    ]
    if not truth.attested:
        verdict = "UNVERIFIED: truth set lacks an independence attestation, compiler and method"
    elif n < MIN_SAMPLE:
        verdict = f"INSUFFICIENT SAMPLE: n={n} < {MIN_SAMPLE}; the interval is too wide to conclude"
    elif low >= target:
        verdict = (
            f"CONSISTENT WITH TARGET: 95 % lower bound {low:.1%} >= {target:.0%} (attested set)"
        )
    else:
        verdict = f"NOT DEMONSTRATED: 95 % lower bound {low:.1%} < {target:.0%}"
    return RecallReport(
        truth.id, n, captured, captured / n, low, high, target, truth.attested, verdict,
        channels, missed, caveats,
    )  # fmt: skip
