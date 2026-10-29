from datetime import date

import pytest

from open_hypergamy.extraction.dates import EVENT, classify_context, find_dates


def one(text):
    [m] = find_dates(text)
    return m


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("15 March 2027", date(2027, 3, 15), None),
        ("March 15, 2027", date(2027, 3, 15), None),
        ("15th of March 2027", date(2027, 3, 15), None),
        ("15. März 2027", date(2027, 3, 15), None),
        ("2027-03-15", date(2027, 3, 15), None),
        ("15.03.2027", date(2027, 3, 15), None),
        ("13/6/2027", date(2027, 6, 13), None),  # day > 12: unambiguous d/m
        ("6/13/2027", date(2027, 6, 13), None),  # second part > 12: unambiguous m/d
        ("10-14 June 2027", date(2027, 6, 10), date(2027, 6, 14)),
        ("10 to 14 June 2027", date(2027, 6, 10), date(2027, 6, 14)),
        ("10. bis 14. Juni 2027", date(2027, 6, 10), date(2027, 6, 14)),
        ("June 28 – July 2, 2027", date(2027, 6, 28), date(2027, 7, 2)),
        ("28 Dec – 3 Jan 2027", date(2026, 12, 28), date(2027, 1, 3)),
        ("Dec 28, 2026 – Jan 3, 2027", date(2026, 12, 28), date(2027, 1, 3)),
    ],
)
def test_usable_formats(text, start, end):
    m = one(text)
    assert m.usable and (m.start, m.end) == (start, end) and m.raw == text


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("15 March", "missing_year"),
        ("March 15", "missing_year"),
        ("5/6/2027", "ambiguous_numeric_format"),
        ("31 Feb 2027", "invalid_date"),
        ("30.02.2027", "invalid_date"),
        ("14-10 June 2027", "range_inverted"),
        ("March 2027", "month_only_precision"),
    ],
)
def test_ambiguous_never_yield_a_date(text, reason):
    m = one(text)
    assert m.ambiguous == reason and not m.usable
    assert m.end is None and (m.start is None or reason == "month_only_precision")


def test_year_is_never_guessed():
    assert one("close on 15 March").start is None


def test_may_the_verb_is_not_a_date():
    assert find_dates("applicants may 3 times apply") == []
    assert one("close on May 3").ambiguous == "missing_year"


def test_numeric_tokens_without_month_are_not_dates():
    assert find_dates("Room 12, floor 3, 2027 budget of 15 000") == []


@pytest.mark.parametrize(
    ("text", "ctx"),
    [
        ("Applications close on 15 March 2027.", "application_close"),
        ("Application deadline: 15 March 2027", "application_close"),
        ("Bewerbungsfrist: 15. März 2027", "application_close"),
        ("Applications open on 1 January 2027.", "application_open"),
        ("Abstract submission deadline: 1 June 2027", "abstract_submission"),
        ("Full paper deadline 1 June 2027", "paper_submission"),
        ("Registration closes 1 June 2027", "registration_close"),
        ("Recommendation letters are due 1 June 2027", "recommendation_letter"),
        ("The school takes place from 10 to 14 June 2027.", EVENT),
        ("Application deadline\n15.03.2027", "application_close"),  # value on the next line
        ("15 March 2027: applications close", "application_close"),  # keyword after the date
    ],
)
def test_context_classification(text, ctx):
    assert classify_context(text, find_dates(text)[0]) == ctx


def test_open_and_close_in_one_sentence_use_nearest_keyword():
    t = "Applications open on 1 January 2027 and close on 15 March 2027."
    a, b = find_dates(t)
    assert (
        classify_context(t, a) == "application_open"
        and classify_context(t, b) == "application_close"
    )


def test_previous_sentence_does_not_leak():
    t = "Applications close on 15 March 2027. The school takes place in Berlin. See 3 May 2026 news."
    last = find_dates(t)[-1]
    assert classify_context(t, last) is None


def test_unrelated_date_has_no_context():
    t = "Posted on 3 May 2026 by the web team."
    assert classify_context(t, find_dates(t)[0]) is None
