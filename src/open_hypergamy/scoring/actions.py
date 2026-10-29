"""Priority band, recommended action and action-item plan (LLD §10.3, §11.3, §12)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from open_hypergamy.domain.enums import EligibilityStatus
from open_hypergamy.scoring.urgency import UrgencyResult

ACTION_POLICY_VERSION = "actions-1"
MANAGED_ACTIONS = ("apply", "prepare", "monitor", "future_cycle")  # the planner may move these


def priority_band(
    fit: float, urgency: float, elig: EligibilityStatus, app_status: str, unresolved_critical: bool
) -> str:
    if elig is EligibilityStatus.INELIGIBLE:
        return "excluded"
    if fit >= 70 and urgency >= 75 and app_status == "open":
        band = "critical"
    elif (fit >= 70 and (urgency >= 50 or app_status == "open")) or (fit >= 55 and urgency >= 75):
        band = "high"
    elif fit >= 50:
        band = "medium"
    else:
        band = "low"
    if unresolved_critical and band in ("critical", "high"):
        band = "medium"  # LLD §11.3: unresolved critical eligibility caps priority
    return band


def recommended_action(
    elig: EligibilityStatus, band: str, app_status: str, urg: UrgencyResult, today: date
) -> str:
    if elig is EligibilityStatus.INELIGIBLE:
        return "archived"
    if elig is EligibilityStatus.FUTURE_CYCLE:
        return "future_cycle"
    worthwhile = band in ("critical", "high", "medium")
    if app_status == "open" and worthwhile:
        return (
            "apply"
            if elig in (EligibilityStatus.ELIGIBLE, EligibilityStatus.POSSIBLY_ELIGIBLE)
            else "prepare"
        )
    if (
        app_status == "not_open"
        and worthwhile
        and urg.open_date
        and 0 <= (urg.open_date - today).days <= 90
    ):
        return "prepare"
    return "monitor"


@dataclass(frozen=True)
class ActionSpec:
    action_type: str
    title: str
    description: str
    priority: str
    due_date_local: str | None = None
    deadline_id: str | None = None

    def key(self, edition_id: str) -> str:
        return f"action:{edition_id}:{self.action_type}:{self.deadline_id or 'none'}:{ACTION_POLICY_VERSION}"


def _prio_by_days(days: int | None) -> str:
    if days is None:
        return "medium"
    return "critical" if days <= 7 else "high" if days <= 14 else "medium"


def plan_actions(
    *,
    name: str,
    action: str,
    elig: EligibilityStatus,
    unresolved: bool,
    urg: UrgencyResult,
    reasons: list[str],
    today: date,
    recommendation_deadline: tuple[str, str] | None,
    close_status: str | None,
) -> list[ActionSpec]:
    specs: list[ActionSpec] = []
    days = urg.distance_days
    if elig in (EligibilityStatus.NEEDS_REVIEW,) or (
        elig is EligibilityStatus.POSSIBLY_ELIGIBLE and unresolved
    ):
        specs.append(
            ActionSpec(
                "review_eligibility",
                f"Review official eligibility: {name}",
                "Eligibility is unclear for this profile; read the official requirements.",
                "high" if days is not None and days <= 30 else "medium",
            )
        )
    if (
        action in ("apply", "prepare")
        and urg.close_date
        and urg.problem is None
        and days is not None
        and days >= 0
    ):
        close = urg.close_date.isoformat()
        if action == "apply":
            specs.append(
                ActionSpec(
                    "submit_application",
                    f"Submit application: {name}",
                    "Submit before the verified deadline.",
                    _prio_by_days(days),
                    close,
                    urg.close_deadline_id,
                )
            )
        prep_due = max(today, urg.close_date - timedelta(days=21))
        specs.append(
            ActionSpec(
                "prepare_materials",
                f"Prepare CV/transcript/motivation: {name}",
                "Collect application documents ahead of the deadline.",
                "high" if days <= 21 else "medium",
                prep_due.isoformat(),
                urg.close_deadline_id,
            )
        )
    elif action == "prepare" and urg.open_date and urg.open_date >= today:
        specs.append(
            ActionSpec(
                "prepare_for_opening",
                f"Prepare before applications open: {name}",
                f"Applications open on {urg.open_date.isoformat()} (verified).",
                "medium",
                (urg.open_date - timedelta(days=7)).isoformat(),
            )
        )
    if (
        urg.problem
        or close_status in ("unverified", "stale", "conflicting_sources")
        and action in ("apply", "prepare")
    ):
        specs.append(
            ActionSpec(
                "recheck_source",
                f"Recheck official source: {name}",
                "A critical date is stale, conflicting or unverified.",
                "high",
                None,
                urg.close_deadline_id,
            )
        )
    if "HIGH_TRAVEL_COST" in reasons and action in ("apply", "prepare"):
        specs.append(
            ActionSpec(
                "confirm_travel_costs",
                f"Confirm travel costs and support: {name}",
                "In-person event outside your primary regions.",
                "medium",
            )
        )
    if recommendation_deadline and action in ("apply", "prepare"):
        did, due = recommendation_deadline
        ask_by = max(today, date.fromisoformat(due) - timedelta(days=14))
        specs.append(
            ActionSpec(
                "request_recommendation",
                f"Request recommendation letter: {name}",
                f"Letters are due {due}; ask referees early.",
                "high",
                ask_by.isoformat(),
                did,
            )
        )
    return specs
