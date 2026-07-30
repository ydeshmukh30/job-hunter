"""LinkedIn scraper — authenticated DOM, minutes-old window.

Two things differ from the original implementation:

1. **Authenticated selectors.**  The previous version queried
   ``.jobs-search__results-list`` / ``.base-search-card__title``, which are the
   *logged-out* public job-search classes.  A CDP-attached session is logged
   in, and LinkedIn serves a completely different tree there, so the old
   selectors matched zero cards.

2. **``f_TPR=r{window}``.**  The window is seconds, and the ``r`` prefix is
   required — a bare ``f_TPR=1800`` is silently ignored by LinkedIn.  A short
   window is the whole strategy: postings surfaced within ~30 minutes have
   single-digit applicant counts.

LinkedIn reshuffles class names regularly.  Rather than hard-code one guess per
field, each field has a list of candidates tried in order, and ``probe()``
dumps what the live page actually contains so selectors can be repaired in
minutes without a debugging session.
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

from playwright.async_api import BrowserContext, Page

from src.scrapers.base import BaseScraper, JobDict

log = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

# Ordered candidates — first selector that yields a node wins.
_CARD_SELECTORS = [
    "li.scaffold-layout__list-item",
    "div.job-card-container",
    "li.jobs-search-results__list-item",
    ".jobs-search__results-list > li",  # logged-out fallback
]
_TITLE_SELECTORS = [
    "a.job-card-container__link",
    ".job-card-list__title--link",
    ".job-card-list__title",
    ".base-search-card__title",
]
_COMPANY_SELECTORS = [
    ".artdeco-entity-lockup__subtitle",
    ".job-card-container__primary-description",
    ".job-card-container__company-name",
    ".base-search-card__subtitle",
]
_LOCATION_SELECTORS = [
    ".job-card-container__metadata-item",
    ".artdeco-entity-lockup__caption",
    ".job-search-card__location",
]
_FOOTER_SELECTORS = [
    ".job-card-container__footer-wrapper",
    ".job-card-list__footer-wrapper",
    "ul.job-card-container__footer-wrapper",
]


async def _first_text(node, selectors: list[str]) -> str | None:
    """Return stripped inner text of the first selector that matches."""
    for sel in selectors:
        try:
            el = await node.query_selector(sel)
        except Exception:
            continue
        if el is None:
            continue
        try:
            text = (await el.inner_text()).strip()
        except Exception:
            continue
        if text:
            return text
    return None


class LinkedInScraper(BaseScraper):
    platform = "linkedin"

    # ------------------------------------------------------------------ #
    # URL construction
    # ------------------------------------------------------------------ #

    @staticmethod
    def build_search_url(keywords: list[str], location: str, window_seconds: int) -> str:
        """Build an authenticated job-search URL for a time window.

        ``f_TPR`` MUST carry the ``r`` prefix; without it LinkedIn ignores the
        filter entirely and returns the unfiltered feed.  ``f_JT=F`` is a
        server-side full-time filter, free of charge.
        """
        kw = quote_plus(" OR ".join(f'"{k}"' for k in keywords))
        loc = quote_plus(location)
        return (
            "https://www.linkedin.com/jobs/search/"
            f"?keywords={kw}"
            f"&location={loc}"
            f"&f_TPR=r{int(window_seconds)}"
            "&f_JT=F"
            "&sortBy=DD"
        )

    # ------------------------------------------------------------------ #
    # Scrape
    # ------------------------------------------------------------------ #

    async def scrape_context(
        self,
        context: BrowserContext,
        keywords: list[str],
        locations: list[str],
        window_seconds: int,
        limit: int | None = None,
    ) -> list[JobDict]:
        """Scrape every location in *locations* using an existing CDP context."""
        jobs: list[JobDict] = []
        seen_urls: set[str] = set()

        for location in locations:
            url = self.build_search_url(keywords, location, window_seconds)
            page = await context.new_page()
            try:
                await page.goto(url, timeout=45_000, wait_until="domcontentloaded")
                # Give the virtualised list a beat, then nudge it to render.
                await asyncio.sleep(random.uniform(1.5, 3.0))
                await self._nudge_list(page)

                cards, used = await self._find_cards(page)
                if not cards:
                    log.warning("linkedin[%s]: no job cards matched any selector", location)
                    continue
                log.info("linkedin[%s]: %d cards via %r", location, len(cards), used)

                for card in cards:
                    job = await self._parse_card(card, location)
                    if job is None or job["url"] in seen_urls:
                        continue
                    seen_urls.add(job["url"])
                    jobs.append(job)
                    if limit is not None and len(jobs) >= limit:
                        return jobs
            except Exception as exc:
                log.warning("linkedin[%s]: scrape failed: %s", location, exc)
            finally:
                await page.close()

        return jobs

    async def _nudge_list(self, page: Page) -> None:
        """LinkedIn lazy-renders the results list; scroll it into existence."""
        for _ in range(6):
            try:
                await page.mouse.wheel(0, 400)
            except Exception:
                break
            await asyncio.sleep(random.uniform(0.2, 0.45))

    async def _find_cards(self, page: Page) -> tuple[list, str | None]:
        for sel in _CARD_SELECTORS:
            try:
                cards = await page.query_selector_all(sel)
            except Exception:
                continue
            if cards:
                return cards, sel
        return [], None

    async def _parse_card(self, card, fallback_location: str) -> JobDict | None:
        title = await _first_text(card, _TITLE_SELECTORS)
        company = await _first_text(card, _COMPANY_SELECTORS)
        location = await _first_text(card, _LOCATION_SELECTORS) or fallback_location

        href = None
        for sel in ("a.job-card-container__link", "a.job-card-list__title--link", "a[href*='/jobs/view/']"):
            try:
                link = await card.query_selector(sel)
            except Exception:
                continue
            if link is not None:
                href = await link.get_attribute("href")
                if href:
                    break

        if not title or not href:
            return None

        if href.startswith("/"):
            href = "https://www.linkedin.com" + href
        # Strip tracking query params so the URL is a stable dedup key.
        href = href.split("?")[0]

        footer = await _first_text(card, _FOOTER_SELECTORS) or ""
        apply_type = "easy_apply" if "easy apply" in footer.lower() else "external_form"

        return JobDict(
            title=title,
            company=company or "Unknown",
            platform=self.platform,
            url=href,
            apply_type=apply_type,
            ctc=None,
            yoe_required=None,
            location=location,
            posted_at=datetime.now(tz=IST),
        )

    # ------------------------------------------------------------------ #
    # Diagnostics
    # ------------------------------------------------------------------ #

    async def probe(self, context: BrowserContext, keywords: list[str], location: str) -> dict:
        """Report which selectors match on the live page.

        Run this when a scrape returns zero jobs.  It tells you whether the
        session died or LinkedIn renamed a class, without a debugger.
        """
        url = self.build_search_url(keywords, location, 86_400)
        page = await context.new_page()
        try:
            await page.goto(url, timeout=45_000, wait_until="domcontentloaded")
            await asyncio.sleep(2.0)
            await self._nudge_list(page)

            report: dict = {"url": page.url, "title": await page.title(), "selectors": {}}
            report["authenticated"] = "authwall" not in page.url and "/login" not in page.url

            for name, sels in (
                ("card", _CARD_SELECTORS),
                ("title", _TITLE_SELECTORS),
                ("company", _COMPANY_SELECTORS),
                ("location", _LOCATION_SELECTORS),
                ("footer", _FOOTER_SELECTORS),
            ):
                hits = {}
                for sel in sels:
                    try:
                        hits[sel] = len(await page.query_selector_all(sel))
                    except Exception:
                        hits[sel] = -1
                report["selectors"][name] = hits
            return report
        finally:
            await page.close()

    # ------------------------------------------------------------------ #
    # BaseScraper compatibility
    # ------------------------------------------------------------------ #

    async def scrape(
        self,
        keywords: list[str],
        locations: list[str],
        limit: int,
        headless: bool,  # noqa: ARG002 — kept for the ABC signature
        user_data_dir: str,  # noqa: ARG002
    ) -> list[JobDict]:
        """Legacy entrypoint — opens its own CDP attach."""
        from src.common.browser import attach

        _browser, context = await attach()
        return await self.scrape_context(context, keywords, locations, 86_400, limit)
