"""Tests for the LinkedIn scraper's URL construction.

The previous suite exercised the credential vault and per-platform ``login()``
methods. Both are gone: sessions now live in a dedicated Chrome profile the
user signs into once, so there is nothing to encrypt and nothing to log in to.

What is worth testing without a live browser is the search URL. The ``f_TPR``
time filter is silently ignored by LinkedIn unless the value carries an ``r``
prefix, and the whole minutes-old strategy rests on that one character.
"""

from __future__ import annotations

import pytest

from src.scrapers.plugins.linkedin import LinkedInScraper

KEYWORDS = ["Senior Backend Engineer", "SDE 3"]


def test_time_window_carries_r_prefix():
    """A bare f_TPR=1800 is ignored by LinkedIn — the 'r' is load-bearing."""
    url = LinkedInScraper.build_search_url(KEYWORDS, "Pune", 1800)
    assert "f_TPR=r1800" in url


@pytest.mark.parametrize(
    "window,expected",
    [(900, "r900"), (1800, "r1800"), (3600, "r3600"), (86400, "r86400")],
)
def test_window_values(window, expected):
    assert f"f_TPR={expected}" in LinkedInScraper.build_search_url(KEYWORDS, "Pune", window)


def test_window_coerced_to_int():
    assert "f_TPR=r1800" in LinkedInScraper.build_search_url(KEYWORDS, "Pune", 1800.0)


def test_sorts_by_date_not_relevance():
    """sortBy=DD is what puts the newest posting first; relevance buries it."""
    assert "sortBy=DD" in LinkedInScraper.build_search_url(KEYWORDS, "Pune", 1800)


def test_full_time_filtered_server_side():
    assert "f_JT=F" in LinkedInScraper.build_search_url(KEYWORDS, "Pune", 1800)


def test_location_and_keywords_encoded():
    url = LinkedInScraper.build_search_url(["Staff Engineer"], "Bengaluru, India", 1800)
    assert "Bengaluru%2C+India" in url
    assert "Staff+Engineer" in url
    assert " " not in url


def test_uses_authenticated_host():
    url = LinkedInScraper.build_search_url(KEYWORDS, "Pune", 1800)
    assert url.startswith("https://www.linkedin.com/jobs/search/")


def test_selector_lists_have_fallbacks():
    """LinkedIn renames classes without notice; one guess per field is fragile."""
    from src.scrapers.plugins import linkedin as mod

    for name in ("_CARD_SELECTORS", "_TITLE_SELECTORS", "_COMPANY_SELECTORS"):
        selectors = getattr(mod, name)
        assert len(selectors) >= 2, f"{name} needs fallbacks"
        assert all(isinstance(s, str) and s for s in selectors)
