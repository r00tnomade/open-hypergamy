from datetime import date

import pytest

from opportunity_radar.discovery.normalize import (
    clean_title,
    edition_year,
    guess_edition_key,
    normalize_title,
    registrable_domain,
)
from opportunity_radar.domain.enums import FactStatus
from opportunity_radar.domain.models import CandidateFact, EvidenceQuote
from opportunity_radar.verification.chronology import (
    check_chronology,
    derive_application_status,
    freshness_window,
)
from opportunity_radar.verification.evidence import ground_facts, quote_grounded
from opportunity_radar.verification.rules import verify_fact

TODAY = date(2026, 10, 29)
TEXT = "Applications close on 15 March 2027. Please prepare a CV."


def fact(method="rule", value="2027-03-15", excerpt="Applications close on 15 March 2027.", **kw):
    f = CandidateFact(
        field_name="deadline:application_close", proposed_value={"date": value}, raw_text="15 March 2027",
        evidence=[EvidenceQuote(source_url="https://example.edu/p", excerpt=excerpt,
                                field_name="deadline:application_close")],
        extraction_method=method, **kw)  # fmt: skip
    return ground_facts([f], TEXT)[0]


def verify(f, tier="t2_official_org", discovery_only=False, in_scope=True, year=2027, distinct=1):
    return verify_fact(f, source_trust_tier=tier, discovery_only=discovery_only, url_in_scope=in_scope,
                       today=TODAY, edition_year=year, distinct_values_for_field=distinct)  # fmt: skip


def test_official_grounded_rule_fact_is_confirmed():
    assert verify(fact()).status is FactStatus.CONFIRMED_OFFICIAL


@pytest.mark.parametrize("tier", ["t1_official_program", "t2_official_org"])
def test_both_official_tiers_can_confirm(tier):
    assert verify(fact(), tier=tier).confirmed


@pytest.mark.parametrize("tier", ["t3_trusted_listing", "t4_aggregator", "t5_community"])
def test_non_official_tiers_never_confirm(tier):
    r = verify(fact(), tier=tier)
    assert not r.confirmed and r.reasons == ["source_not_authoritative_for_claim"]


@pytest.mark.parametrize("method", ["llm", "feed_metadata", "manual"])
def test_llm_feed_and_manual_never_confirm_even_from_official_sources(method):
    assert not verify(fact(method=method), tier="t1_official_program").confirmed


def test_discovery_only_and_out_of_scope_never_confirm():
    assert not verify(fact(), discovery_only=True).confirmed
    assert not verify(fact(), in_scope=False).confirmed


def test_ungrounded_excerpt_cannot_confirm_and_is_flagged():
    f = fact(excerpt="Applications close on 1 April 2027.")
    assert f.grounded is False
    r = verify(f)
    assert not r.confirmed and r.needs_review and r.reasons == ["ungrounded_excerpt"]


def test_grounding_is_literal_not_fuzzy():
    assert quote_grounded(TEXT, "Applications close\n on  15 March 2027.")  # whitespace only
    assert not quote_grounded(TEXT, "applications close on 15 march 2027.")  # case differs
    assert not quote_grounded(TEXT, "")


def test_ambiguity_and_missing_date_cannot_confirm():
    r = verify(fact(value=None, needs_review=True, review_reason="missing_year"))
    assert not r.confirmed and r.needs_review and r.reasons == ["missing_year"]


def test_implausible_or_mismatched_year_not_confirmed():
    assert verify(fact(value="2099-03-15")).reasons == ["implausible_year"]
    assert verify(fact(), year=2029).reasons == ["year_mismatch_with_edition"]
    assert verify(
        fact(), year=2026
    ).confirmed  # deadline in the year after the edition start is allowed


def test_multiple_values_for_one_field_not_confirmed():
    assert verify(fact(), distinct=2).reasons == ["multiple_dates_for_field"]


def test_chronology():
    d = date
    assert check_chronology(open_date=d(2027, 1, 1), close_date=d(2027, 3, 1),
                            event_start=d(2027, 6, 1), event_end=d(2027, 6, 5)) == []  # fmt: skip
    assert "application_open_after_close" in check_chronology(
        open_date=d(2027, 4, 1), close_date=d(2027, 3, 1), event_start=None, event_end=None
    )
    assert "application_close_after_event" in check_chronology(
        open_date=None, close_date=d(2027, 7, 1), event_start=d(2027, 6, 1), event_end=d(2027, 6, 5)
    )
    assert "event_start_after_end" in check_chronology(
        open_date=None, close_date=None, event_start=d(2027, 6, 5), event_end=d(2027, 6, 1)
    )


def test_application_status_arithmetic_uses_only_given_confirmed_dates():
    kw = dict(announced_not_open=False, conflicting=False)
    d = date
    assert (
        derive_application_status(
            open_date=d(2027, 1, 1), close_date=d(2027, 3, 1), today=d(2026, 12, 1), **kw
        )
        == "not_open"
    )
    assert (
        derive_application_status(
            open_date=d(2027, 1, 1), close_date=d(2027, 3, 1), today=d(2027, 2, 1), **kw
        )
        == "open"
    )
    assert (
        derive_application_status(
            open_date=d(2027, 1, 1), close_date=d(2027, 3, 1), today=d(2027, 3, 2), **kw
        )
        == "closed"
    )
    assert (
        derive_application_status(open_date=None, close_date=None, today=d(2027, 3, 2), **kw)
        == "unknown"
    )
    assert (
        derive_application_status(
            open_date=None,
            close_date=None,
            today=d(2027, 3, 2),
            announced_not_open=True,
            conflicting=False,
        )
        == "not_open"
    )
    assert (
        derive_application_status(
            open_date=None,
            close_date=d(2027, 3, 1),
            today=d(2027, 2, 1),
            announced_not_open=False,
            conflicting=True,
        )
        == "conflicting"
    )


def test_freshness_windows():
    d = date
    assert freshness_window(d(2026, 11, 10), TODAY).days == 1
    assert freshness_window(d(2027, 1, 10), TODAY).days == 7
    assert freshness_window(d(2027, 6, 10), TODAY).days == 30
    assert freshness_window(None, TODAY).days == 30


def test_normalization():
    assert (
        normalize_title("The 5th Annual Robotics Summer School 2027!") == "robotics summer school"
    )
    assert (
        normalize_title("Sommerschule Künstliche Intelligenz 2026/27")
        == "sommerschule kunstliche intelligenz"
    )
    assert (
        clean_title("Robotics Summer School 2027 | Example Institute")
        == "Robotics Summer School 2027"
    )
    assert registrable_domain("cs.uni-example.de") == "uni-example.de"
    assert registrable_domain("www.example.ac.uk") == "example.ac.uk"
    assert edition_year("2026-2027") == 2026


@pytest.mark.parametrize(
    ("title", "url", "years", "key"),
    [
        ("Summer School 2027", "https://e.org/x", None, "2027"),
        ("Summer School", "https://e.org/summer-school-2028", None, "2028"),
        ("Fellowship 2026/27", "https://e.org/x", None, "2026-2027"),
        ("Summer School", "https://e.org/x", {2027}, "2027"),
        ("Summer School 2026 and 2027", "https://e.org/x", None, None),  # two years: no guess
        ("Summer School", "https://e.org/x", None, None),
    ],
)
def test_edition_key_requires_explicit_evidence(title, url, years, key):
    assert guess_edition_key(title, url, years) == key
