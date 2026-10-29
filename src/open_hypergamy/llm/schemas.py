"""Strict `opportunity_extract.v1` output schema (LLD §9.4). Extra fields are rejected."""

from __future__ import annotations

import json
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "opportunity_extract.v1"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Ev(_Strict):
    segment_id: str
    quote: str = Field(min_length=1, max_length=1000)


Evidence = Annotated[list[Ev], Field(default_factory=list, max_length=5)]


class TextField(_Strict):
    value: str | None = Field(default=None, max_length=500)
    evidence: Evidence


class DateField(_Strict):
    value: str | None = None  # YYYY-MM-DD
    raw_text: str | None = Field(default=None, max_length=200)
    timezone: str | None = Field(default=None, max_length=64)
    evidence: Evidence

    @field_validator("value")
    @classmethod
    def _iso(cls, v: str | None) -> str | None:
        if v is not None:
            date.fromisoformat(v)  # raises ValueError -> schema failure
        return v


class DeadlineField(DateField):
    time_precision: Literal["exact_time", "date_only", "month_only", "year_only", "unknown"] = (
        "unknown"
    )


class FormatField(_Strict):
    value: Literal["in_person", "online", "hybrid", "unknown"] = "unknown"
    evidence: Evidence


class Requirement(_Strict):
    requirement: str = Field(max_length=500)
    blocking: Literal["true", "false", "unknown"] = "unknown"
    evidence: Evidence


class Fee(_Strict):
    amount_min: float | None = Field(default=None, ge=0)
    amount_max: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=3)
    evidence: Evidence


class Funding(_Strict):
    status: Literal[
        "fully_funded",
        "partially_funded",
        "available_competitive",
        "self_funded",
        "unknown",
        "not_applicable",
    ] = "unknown"
    details: str | None = Field(default=None, max_length=500)
    evidence: Evidence


class OpportunityExtract(_Strict):
    schema_version: Literal["opportunity_extract.v1"]
    title: TextField
    organizer: TextField
    category: TextField
    edition_key: TextField
    event_start_date: DateField
    event_end_date: DateField
    application_open_date: DateField
    application_deadline: DeadlineField
    format: FormatField
    location: TextField
    eligibility_requirements: list[Requirement] = Field(default_factory=list, max_length=20)
    fee: Fee
    funding: Funding
    ambiguities: list[str] = Field(default_factory=list, max_length=20)


def compact_schema() -> str:
    return json.dumps(OpportunityExtract.model_json_schema(), separators=(",", ":"), sort_keys=True)
