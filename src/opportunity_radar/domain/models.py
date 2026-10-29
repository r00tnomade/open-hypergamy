"""Boundary value objects for the candidate/evidence pipeline (LLD §5.1)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ExtractionMethod = Literal["structured_page", "rule", "llm", "manual", "feed_metadata"]


class EvidenceQuote(BaseModel):
    source_url: str  # canonical string; HttpUrl would re-normalize (ADR-003)
    observation_id: str | None = None
    excerpt: str = Field(min_length=1, max_length=2000)
    field_name: str


class CandidateFact(BaseModel):
    field_name: str
    proposed_value: Any
    raw_text: str | None = None
    evidence: list[EvidenceQuote] = Field(default_factory=list)
    extraction_method: ExtractionMethod
    needs_review: bool = False
    review_reason: str | None = None
    model_name: str | None = None
    prompt_version: str | None = None
    # Set only by verification.evidence.ground_facts: was every excerpt found verbatim in the text?
    grounded: bool | None = None

    @property
    def date_value(self) -> str | None:
        v = self.proposed_value
        return v.get("date") if isinstance(v, dict) else None


class CandidateEdition(BaseModel):
    candidate_id: str | None = None
    title: str
    organizer: str | None = None
    category: str | None = None
    official_url: str
    application_url: str | None = None
    edition_key: str | None = None
    facts: list[CandidateFact] = Field(default_factory=list)
    discovery_source_id: str | None = None
    discovery_observation_id: str | None = None
