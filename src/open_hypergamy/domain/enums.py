from enum import StrEnum


class TrustTier(StrEnum):
    T1_OFFICIAL_PROGRAM = "t1_official_program"
    T2_OFFICIAL_ORG = "t2_official_org"
    T3_TRUSTED_LISTING = "t3_trusted_listing"
    T4_AGGREGATOR = "t4_aggregator"
    T5_COMMUNITY = "t5_community"


class AdapterType(StrEnum):
    RSS_ATOM = "rss_atom"
    ICAL = "ical"
    SITEMAP = "sitemap"
    HTML = "html"
    PLAYWRIGHT = "playwright"
    MANUAL = "manual"


class FactStatus(StrEnum):
    CONFIRMED_OFFICIAL = "confirmed_official"
    ANNOUNCED_NOT_OPEN = "announced_not_open"
    ESTIMATED_RECURRING = "estimated_recurring"
    UNVERIFIED = "unverified"
    UNKNOWN = "unknown"
    CONFLICTING_SOURCES = "conflicting_sources"
    STALE = "stale"
    CANCELLED_OFFICIAL = "cancelled_official"


class EligibilityStatus(StrEnum):
    ELIGIBLE = "eligible"
    POSSIBLY_ELIGIBLE = "possibly_eligible"
    INELIGIBLE = "ineligible"
    NEEDS_REVIEW = "needs_review"
    FUTURE_CYCLE = "future_cycle"


class OpportunityAction(StrEnum):
    APPLY = "apply"
    PREPARE = "prepare"
    MONITOR = "monitor"
    FUTURE_CYCLE = "future_cycle"
    APPLIED = "applied"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    ARCHIVED = "archived"


class DeadlineType(StrEnum):
    APPLICATION_OPEN = "application_open"
    APPLICATION_CLOSE = "application_close"
    EARLY_APPLICATION_CLOSE = "early_application_close"
    ABSTRACT_SUBMISSION = "abstract_submission"
    PAPER_SUBMISSION = "paper_submission"
    REGISTRATION_CLOSE = "registration_close"
    RECOMMENDATION_LETTER = "recommendation_letter"
    TRAVEL_GRANT = "travel_grant"
    SCHOLARSHIP = "scholarship"
    TEAM_FORMATION = "team_formation"
    OTHER = "other"


class ReviewState(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class SourceRunStatus(StrEnum):
    SUCCESS = "success"
    NOT_MODIFIED = "not_modified"
    PARTIAL = "partial"
    BLOCKED_POLICY = "blocked_policy"
    FAILED = "failed"
    SKIPPED = "skipped"
