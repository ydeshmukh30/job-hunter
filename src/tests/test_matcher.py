"""Tests for src/apply/match.py.

Rewritten alongside the filter fixes. The previous suite encoded the old
contract, including three behaviours that were bugs:

* CTC band-containment (``min <= target <= max``) rejected every posting paying
  MORE than the target.
* Jaccard title matching over seniority-stripped tokens admitted "QA Engineer".
* Dedup by company permanently hid every future role at a company once one of
  its roles had been seen.

The regression tests for those three live at the bottom of this file and are
the reason it exists in this shape.
"""

from __future__ import annotations

import types

import pytest

from src.apply.match import (
    _canonical_url,
    ctc_matches,
    filter_jobs,
    is_full_time,
    location_matches,
    normalize_company,
    parse_ctc_lpa,
    parse_yoe_range,
    title_matches,
)
from src.tests.fixtures.mock_jobs import (
    JOB_DUPE,
    JOB_FAIL_LOCATION,
    JOB_FAIL_TITLE,
    JOB_NEITHER,
    JOB_NO_CTC_YOE_FAIL,
    JOB_NO_CTC_YOE_PASS,
    JOB_PASS,
    JOB_USD,
)

TITLES = [
    "SDE 2",
    "SDE 3",
    "Senior Software Engineer",
    "Senior Backend Engineer",
    "Lead Engineer",
    "Staff Engineer",
]


def _make_settings(min_ctc_lpa: float = 38.0, target_yoe: int = 5) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        min_ctc_lpa=min_ctc_lpa, target_yoe=target_yoe, titles=TITLES
    )


SETTINGS = _make_settings()
NO_URLS: set[str] = set()


# ===========================================================================
# filter_jobs — end to end
# ===========================================================================


def test_job_pass_included():
    assert filter_jobs([JOB_PASS], NO_URLS, SETTINGS) == [JOB_PASS]


def test_title_gate_rejects_non_engineering():
    assert filter_jobs([JOB_FAIL_TITLE], NO_URLS, SETTINGS) == []


def test_location_gate_rejects_mumbai():
    assert filter_jobs([JOB_FAIL_LOCATION], NO_URLS, SETTINGS) == []


def test_no_ctc_yoe_in_range_passes():
    assert filter_jobs([JOB_NO_CTC_YOE_PASS], NO_URLS, SETTINGS) == [JOB_NO_CTC_YOE_PASS]


def test_no_ctc_yoe_far_above_range_rejected():
    # 8-12 years against a 5-YOE candidate: one year of stretch is allowed,
    # three is not.
    assert filter_jobs([JOB_NO_CTC_YOE_FAIL], NO_URLS, SETTINGS) == []


def test_neither_ctc_nor_yoe_kept():
    assert filter_jobs([JOB_NEITHER], NO_URLS, SETTINGS) == [JOB_NEITHER]


def test_foreign_currency_kept():
    assert filter_jobs([JOB_USD], NO_URLS, SETTINGS) == [JOB_USD]


def test_seen_url_deduped():
    seen = {_canonical_url(JOB_DUPE["url"])}
    assert filter_jobs([JOB_DUPE], seen, SETTINGS) == []


def test_same_company_different_url_still_passes():
    """The bug this replaces: one role at a company hid all future roles."""
    other_role = {**JOB_PASS, "url": "https://linkedin.com/jobs/view/999", "title": "SDE 3"}
    seen = {_canonical_url(JOB_PASS["url"])}
    assert filter_jobs([other_role], seen, SETTINGS) == [other_role]


# ===========================================================================
# Unit gates
# ===========================================================================


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Senior Backend Engineer", True),
        ("Staff Software Engineer", True),
        ("SDE 3", True),
        ("SDE-2", True),
        ("Lead Engineer", True),
        ("Principal Engineer", True),
        # Regression: these all passed the old Jaccard matcher.
        ("QA Engineer", False),
        ("Senior QA Engineer", False),
        ("SDET", False),
        ("Sales Engineer", False),
        ("Engineering Manager", False),
        ("Senior Engineering Manager", False),
        ("Junior Software Engineer", False),
        ("Software Engineer Intern", False),
        ("Graduate Engineer Trainee", False),
        ("Data Scientist", False),
        ("Director of Engineering", False),
    ],
)
def test_title_matches(title, expected):
    assert title_matches(title, TITLES) is expected


@pytest.mark.parametrize(
    "ctc,expected",
    [
        ("30-50 LPA", True),   # band spans the target
        ("45-60 LPA", True),   # REGRESSION: pays more than target, used to fail
        ("50 LPA", True),      # single value above target
        ("20-35 LPA", False),  # ceiling below target
        ("25 LPA", False),
    ],
)
def test_ctc_gate(ctc, expected):
    assert ctc_matches(ctc, None, 38.0, 5) is expected


@pytest.mark.parametrize(
    "yoe,expected",
    [
        ("3-7 years", True),
        ("6-10 years", True),   # one year of stretch above the floor
        ("5+ years", True),
        ("8-12 years", False),
        ("1-3 years", False),
    ],
)
def test_yoe_gate(yoe, expected):
    assert ctc_matches(None, yoe, 38.0, 5) is expected


def test_unparseable_keeps():
    assert ctc_matches("Competitive", None, 38.0, 5) is True
    assert ctc_matches(None, None, 38.0, 5) is True


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("30-50 LPA", (30.0, 50.0)),
        ("₹30L - ₹50L", (30.0, 50.0)),
        ("30 to 50 LPA", (30.0, 50.0)),
        ("30L", (30.0, 30.0)),
        ("30,00,000", (30.0, 30.0)),
        ("$120k-$180k", None),
        ("", None),
    ],
)
def test_parse_ctc(raw, expected):
    assert parse_ctc_lpa(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [("3-6 years", (3, 6)), ("3+ years", (3, 99)), ("minimum 3 yrs", (3, 99)), ("", None)],
)
def test_parse_yoe(raw, expected):
    assert parse_yoe_range(raw) == expected


def test_full_time_gate():
    assert is_full_time({"title": "Senior Backend Engineer"}) is True
    assert is_full_time({"title": "Backend Engineer (Contract)"}) is False
    assert is_full_time({"title": "Engineer", "description": "6 month internship"}) is False


@pytest.mark.parametrize(
    "loc,expected",
    [("Bengaluru", True), ("Pune, India", True), ("Remote", True), ("Mumbai", False), (None, False)],
)
def test_location_gate(loc, expected):
    assert location_matches(loc, ["pune", "bengaluru", "bangalore", "hyderabad", "remote"]) is expected


def test_normalize_company():
    assert normalize_company("Razorpay Pvt Ltd") == "razorpay"
    assert normalize_company("Acme Inc.") == "acme"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://linkedin.com/jobs/view/001?trk=abc", "https://linkedin.com/jobs/view/001"),
        ("https://linkedin.com/jobs/view/001/", "https://linkedin.com/jobs/view/001"),
        ("https://LinkedIn.com/jobs/view/001#top", "https://linkedin.com/jobs/view/001"),
        ("", ""),
    ],
)
def test_canonical_url(raw, expected):
    """Tracking params differ between polls for the same posting."""
    assert _canonical_url(raw) == expected
