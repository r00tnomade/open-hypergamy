from datetime import UTC, date, datetime

import pytest

from open_hypergamy.config import ScoringWeights
from open_hypergamy.domain.enums import EligibilityStatus as E
from open_hypergamy.profile import Profile
from open_hypergamy.scoring.actions import (
    plan_actions,
    priority_band,
    recommended_action,
)
from open_hypergamy.scoring.fit import compute_fit, detect_region, region_ok
from open_hypergamy.scoring.urgency import UrgencyResult, compute_urgency
from open_hypergamy.verification.eligibility import assess, interpret


def profile(**academic):
    base = {"country": "DE", "degree_level": "bachelor", "current_year": 1,
            "subject_tags": ["computer_science"]}  # fmt: skip
    return Profile.model_validate({
        "version": 1, "profile_version": "t1", "academic": {**base, **academic},
        "research_tags": ["robotics", "applied_ml"],
        "preferences": {"primary_regions": ["DE", "EU"], "needs_funding_or_low_cost": True},
    })  # fmt: skip


# --- eligibility rules --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "assessment", "kind"),
    [
        ("Open to bachelor and master students", "satisfied", "degree"),
        ("PhD students only", "blocking", "degree"),
        ("Undergraduate students enrolled at a European university", "satisfied", "degree"),
        ("Enrolled at a German university", "satisfied", "institution"),
        ("Enrolled at a US university", "blocking", "institution"),
        ("Students in their first year", "satisfied", "year"),
        ("Second year or above", "blocking", "year"),
        ("EU citizens only", "unclear", "citizenship"),
        ("Applicants must be under 30", "unclear", "age"),
        ("Studying computer science", "satisfied", "subject"),
        ("Studying marine biology", "unclear", "subject"),
        ("Please upload a CV and motivation letter", "not_applicable", "materials"),
        ("Must be enrolled", "satisfied", "enrolment"),
        ("Strong interest in the field is a plus", "unclear", "other"),
    ],
)
def test_requirement_rules(text, assessment, kind):
    r = interpret(text, profile())
    assert (r.assessment, r.kind) == (assessment, kind), r.rationale


def test_year_rules_use_profile_year_and_are_future_aware():
    assert interpret("at least second year", profile(current_year=2)).assessment == "satisfied"
    blocked = interpret("at least second year", profile(current_year=1))
    assert blocked.assessment == "blocking" and blocked.future
    gone = interpret("first-year students only", profile(current_year=3))
    assert gone.assessment == "blocking" and not gone.future
    assert interpret("second year or above", profile(current_year=None)).assessment == "unclear"


def test_optional_requirements_never_block():
    r = interpret("PhD students", profile(), flag="false")
    assert r.assessment == "unclear" and "non-blocking" in r.rationale


def test_decision_policy():
    p = profile()
    mk = lambda *texts, flag="true": assess([(t, flag, None) for t in texts], p)  # noqa: E731
    assert mk("Bachelor students", "Enrolled at a German university").status is E.ELIGIBLE
    assert mk("PhD students").status is E.FUTURE_CYCLE  # a later degree stage is a future cycle
    assert (
        assess([("Bachelor students only", "true", None)], profile(degree_level="master")).status
        is E.INELIGIBLE
    )
    assert (
        mk("Second year or above").status is E.FUTURE_CYCLE
        and mk("Second year or above").year_blocked
    )
    mixed = assess(
        [("Enrolled at a US university", "true", None), ("Second year or above", "true", None)], p
    )
    assert mixed.status is E.INELIGIBLE  # a blocker that will not clear wins over a future one
    none = assess([], p)
    assert none.status is E.POSSIBLY_ELIGIBLE and "absence is not proof" in none.summary
    assert mk("Bachelor students", "EU citizens").status is E.POSSIBLY_ELIGIBLE
    assert (
        assess([("Second year or above", "true", None)], profile(current_year=None)).status
        is E.NEEDS_REVIEW
    )
    assert (
        mk("Upload a CV").status is E.POSSIBLY_ELIGIBLE
    )  # only materials: nothing was actually assessed


# --- fit ----------------------------------------------------------------------------------------------
W = ScoringWeights()


def fit(**kw):
    base = dict(topic="robotics summer school", category="summer_school", eligibility=E.ELIGIBLE,
                funding_status="partially_funded", funding_confirmed=False, fee_max=None, fmt="in_person",
                location="Berlin", profile=profile(), weights=W)  # fmt: skip
    return compute_fit(**{**base, **kw})


def test_weights_and_formula_are_exact():
    r = fit()
    expected = round(sum(r.components[k] * getattr(W, k) for k in r.components) / 100, 1)
    assert r.fit == expected and sum(vars(W).values()) == 100
    assert set(r.components) == {"career_alignment", "technical_research_value", "eligibility_feasibility",
                                 "funding_accessibility", "time_cost"}  # fmt: skip


def test_alignment_requires_matching_topics():
    assert (
        fit(topic="robotics and machine learning").components["career_alignment"]
        > fit().components["career_alignment"]
    )
    off = fit(topic="medieval poetry workshop", category="workshop")
    assert off.components["career_alignment"] == 20 and "HIGH_CAREER_ALIGNMENT" not in off.reasons
    assert "HIGH_CAREER_ALIGNMENT" in fit().reasons


def test_eligibility_drives_feasibility_component():
    scores = {s: fit(eligibility=s).components["eligibility_feasibility"] for s in E}
    assert (
        scores[E.ELIGIBLE]
        > scores[E.POSSIBLY_ELIGIBLE]
        > scores[E.NEEDS_REVIEW]
        > scores[E.FUTURE_CYCLE]
        > scores[E.INELIGIBLE]
        == 0
    )


def test_funding_confirmed_reason_only_when_confirmed():
    assert (
        "FUNDING_CONFIRMED"
        not in fit(funding_status="fully_funded", funding_confirmed=False).reasons
    )
    assert "FUNDING_CONFIRMED" in fit(funding_status="fully_funded", funding_confirmed=True).reasons


def test_fees_hurt_without_funding_and_budget_limit_applies():
    free = fit(funding_status=None, fee_max=None).components["funding_accessibility"]
    paid = fit(funding_status=None, fee_max=500).components["funding_accessibility"]
    assert paid < free
    p = profile()
    p.preferences.budget_limit_eur = 100
    assert (
        fit(profile=p, funding_status="partially_funded", fee_max=500).components[
            "funding_accessibility"
        ]
        == 10
    )


def test_travel_cost_reason_for_far_unfunded_events_only():
    far = fit(location="Pittsburgh, USA", funding_status="unknown")
    assert (
        "HIGH_TRAVEL_COST" in far.reasons
        and far.components["time_cost"] < fit().components["time_cost"]
    )
    assert (
        "HIGH_TRAVEL_COST"
        not in fit(location="Pittsburgh, USA", funding_status="fully_funded").reasons
    )
    assert "HIGH_TRAVEL_COST" not in fit(location="Pittsburgh, USA", fmt="online").reasons
    assert detect_region("Munich, Germany") == "DE" and detect_region("somewhere") is None
    assert (
        region_ok("FR", ["EU"]) is True
        and region_ok("FAR", ["EU"]) is False
        and region_ok(None, ["EU"]) is None
    )


# --- urgency ----------------------------------------------------------------------------------------------
def ed(**kw):
    return {"fact_status": "confirmed_official", "source_fresh_until": None, **kw}


def dl(typ, due, status="confirmed_official", id_="d1"):
    return {"id": id_, "deadline_type": typ, "due_date_local": due, "fact_status": status}


NOW = datetime(2027, 3, 1, 12, tzinfo=UTC)
TODAY = date(2027, 3, 1)


@pytest.mark.parametrize(("close", "score"), [("2027-03-02", 100), ("2027-03-08", 90), ("2027-03-15", 75),
                                              ("2027-03-30", 55), ("2027-05-20", 30), ("2028-01-01", 15),
                                              ("2027-02-20", 0)])  # fmt: skip
def test_urgency_by_distance(close, score):
    u = compute_urgency(ed(), [dl("application_close", close)], TODAY, NOW)
    assert u.score == score


def test_urgency_ignores_unverified_conflicting_and_flags_stale():
    unv = compute_urgency(ed(), [dl("application_close", "2027-03-02", "unverified")], TODAY, NOW)
    assert unv.score == 10 and unv.distance_days is None
    assert (
        compute_urgency(
            ed(fact_status="conflicting_sources"),
            [dl("application_close", "2027-03-02")],
            TODAY,
            NOW,
        ).problem
        == "conflict"
    )
    stale = compute_urgency(ed(), [dl("application_close", "2027-03-02", "stale")], TODAY, NOW)
    assert stale.problem == "stale" and "CRITICAL_FACT_STALE" in stale.reasons
    lapsed = compute_urgency(
        ed(source_fresh_until="2027-02-28T00:00:00Z"),
        [dl("application_close", "2027-03-02")],
        TODAY,
        NOW,
    )
    assert lapsed.problem == "stale"


def test_urgency_before_opening_is_low_and_reason_codes():
    u = compute_urgency(
        ed(),
        [dl("application_open", "2027-03-10", id_="o"), dl("application_close", "2027-04-20")],
        TODAY,
        NOW,
    )
    assert u.score == 50 and "APPLICATION_OPEN" not in u.reasons
    soon = compute_urgency(ed(), [dl("application_close", "2027-03-10")], TODAY, NOW)
    assert {"APPLICATION_OPEN", "DEADLINE_WITHIN_14_DAYS"} <= set(soon.reasons)


# --- bands / actions ---------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("fit_", "urg", "elig", "app", "unresolved", "band"),
    [
        (80, 90, E.ELIGIBLE, "open", False, "critical"),
        (
            80,
            90,
            E.ELIGIBLE,
            "open",
            True,
            "medium",
        ),  # unresolved critical eligibility caps at medium
        (80, 10, E.ELIGIBLE, "not_open", False, "medium"),
        (80, 60, E.ELIGIBLE, "not_open", False, "high"),
        (60, 80, E.POSSIBLY_ELIGIBLE, "open", False, "high"),
        (40, 100, E.ELIGIBLE, "open", False, "low"),  # a deadline never lifts a weak fit
        (95, 100, E.INELIGIBLE, "open", False, "excluded"),
    ],
)
def test_priority_band(fit_, urg, elig, app, unresolved, band):
    assert priority_band(fit_, urg, elig, app, unresolved) == band


def urg(**kw):
    return UrgencyResult(**{"score": 50.0, "distance_days": 10, **kw})


def test_recommended_action_rules():
    t = date(2027, 3, 1)
    assert recommended_action(E.INELIGIBLE, "excluded", "open", urg(), t) == "archived"
    assert recommended_action(E.FUTURE_CYCLE, "medium", "open", urg(), t) == "future_cycle"
    assert recommended_action(E.ELIGIBLE, "high", "open", urg(), t) == "apply"
    assert recommended_action(E.NEEDS_REVIEW, "high", "open", urg(), t) == "prepare"
    assert (
        recommended_action(E.ELIGIBLE, "high", "not_open", urg(open_date=date(2027, 4, 1)), t)
        == "prepare"
    )
    assert (
        recommended_action(E.ELIGIBLE, "high", "not_open", urg(open_date=date(2028, 1, 1)), t)
        == "monitor"
    )
    assert (
        recommended_action(E.ELIGIBLE, "high", "closed", urg(), t) == "monitor"
    )  # past deadlines don't archive
    assert recommended_action(E.ELIGIBLE, "low", "open", urg(), t) == "monitor"


def test_action_plan_and_keys():
    u = urg(close_date=date(2027, 3, 11), close_deadline_id="D1", distance_days=10)
    specs = plan_actions(name="X", action="apply", elig=E.NEEDS_REVIEW, unresolved=True, urg=u, reasons=["HIGH_TRAVEL_COST"],
                         today=date(2027, 3, 1), recommendation_deadline=("R1", "2027-03-20"), close_status="confirmed_official")  # fmt: skip
    types = {s.action_type for s in specs}
    assert types == {"review_eligibility", "submit_application", "prepare_materials", "confirm_travel_costs",
                     "request_recommendation"}  # fmt: skip
    submit = next(s for s in specs if s.action_type == "submit_application")
    assert submit.due_date_local == "2027-03-11" and submit.priority == "high"
    assert submit.key("E1") == "action:E1:submit_application:D1:actions-1"
    assert (
        next(s for s in specs if s.action_type == "prepare_materials").due_date_local
        == "2027-03-01"
    )
    assert (
        next(s for s in specs if s.action_type == "request_recommendation").due_date_local
        == "2027-03-06"
    )
    stale = plan_actions(name="X", action="apply", elig=E.ELIGIBLE, unresolved=False,
                         urg=urg(problem="stale"), reasons=[], today=date(2027, 3, 1),
                         recommendation_deadline=None, close_status="stale")  # fmt: skip
    assert [s.action_type for s in stale] == ["recheck_source"]


def test_research_programme_titles_get_their_own_category():
    from open_hypergamy.discovery.normalize import guess_category as g

    assert g("Undergraduate Research Programme 2027") == "research_programme"
    assert g("Summer Research Program") == "research_programme"
    assert g("Research Internship at CERN") == "internship"  # earlier rules still win
    assert g("Research Fellowship") == "fellowship"
    assert g("Program committee") == "other"
