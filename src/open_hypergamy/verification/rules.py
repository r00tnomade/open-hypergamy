"""Deterministic fact verification (LLD §9.6, §10). Only this module can yield CONFIRMED_OFFICIAL.

An LLM, a feed hint, a non-authoritative source, an ungrounded excerpt, or any ambiguity can
never confirm a fact. Confirmation requires every rule below to pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from open_hypergamy.domain.enums import FactStatus, TrustTier
from open_hypergamy.domain.models import CandidateFact

AUTHORITATIVE_TIERS = frozenset(
    {TrustTier.T1_OFFICIAL_PROGRAM.value, TrustTier.T2_OFFICIAL_ORG.value}
)
YEARS_BACK, YEARS_AHEAD = 1, 3


@dataclass(frozen=True)
class VerificationResult:
    status: FactStatus
    reasons: list[str] = field(default_factory=list)
    needs_review: bool = False

    @property
    def confirmed(self) -> bool:
        return self.status is FactStatus.CONFIRMED_OFFICIAL


def _unverified(reason: str, *, review: bool = False) -> VerificationResult:
    return VerificationResult(FactStatus.UNVERIFIED, [reason], review)


def verify_fact(
    fact: CandidateFact,
    *,
    source_trust_tier: str,
    discovery_only: bool,
    url_in_scope: bool,
    today: date,
    edition_year: int | None,
    distinct_values_for_field: int,
) -> VerificationResult:
    if fact.extraction_method == "llm":
        return _unverified("llm_cannot_confirm")  # invariant: LLM output is a proposal only
    if fact.extraction_method == "feed_metadata":
        return _unverified("feed_is_discovery_hint")
    if fact.extraction_method == "manual":
        return _unverified("manual_entry_is_not_official_evidence")
    if fact.needs_review or fact.date_value is None:
        return _unverified(fact.review_reason or "no_normalized_value", review=True)
    if fact.grounded is not True:
        return _unverified("ungrounded_excerpt", review=True)
    if source_trust_tier not in AUTHORITATIVE_TIERS or discovery_only or not url_in_scope:
        return _unverified("source_not_authoritative_for_claim")
    if distinct_values_for_field > 1:
        return _unverified("multiple_dates_for_field", review=True)
    d = date.fromisoformat(fact.date_value)
    if not (today.year - YEARS_BACK <= d.year <= today.year + YEARS_AHEAD):
        return _unverified("implausible_year", review=True)
    if edition_year is not None and abs(d.year - edition_year) > 1:
        return _unverified("year_mismatch_with_edition", review=True)
    return VerificationResult(FactStatus.CONFIRMED_OFFICIAL, ["official_source_grounded_rule"])
