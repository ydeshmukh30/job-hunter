"""LinkedIn scraper plugin."""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone
from urllib.parse import quote_plus

from playwright.async_api import Page

from src.scrapers.base import BaseScraper, JobDict, LoginError
from src.scrapers.crypto_vault import CryptoVault

log = logging.getLogger(__name__)

IST = timezone.utc  # replaced with real IST in production via zoneinfo


class LinkedInScraper(BaseScraper):
    platform = "linkedin"
    LOGIN_INDICATORS = ["linkedin.com/login", "linkedin.com/authwall"]

    async def login(self, page: Page, vault: CryptoVault) -> None:
        creds = vault.get("linkedin")  # {"method": "google_sso", "google_email": ...}
        google_email: str = creds.get("google_email", "")

        await page.goto("https://www.linkedin.com/login", timeout=30_000)
        await asyncio.sleep(random.uniform(1.0, 2.0))

        # Click "Sign in with Google"
        try:
            await page.click("text=Sign in with Google", timeout=10_000)
        except Exception as exc:
            raise LoginError(f"linkedin: could not find 'Sign in with Google' button: {exc}") from exc

        await asyncio.sleep(random.uniform(1.5, 3.0))

        # Google account picker popup — select the correct account
        try:
            # Try to click on the account with matching email
            await page.click(f"text={google_email}", timeout=15_000)
        except Exception:
            # May already be on the consent screen with a single account
            try:
                await page.click("[data-identifier]", timeout=8_000)
            except Exception:
                pass  # Already proceeding — wait for redirect

        # Wait for redirect to LinkedIn feed
        try:
            await page.wait_for_url("**/feed**", timeout=30_000)
        except Exception:
            if "feed" not in page.url:
                raise LoginError(
                    f"linkedin: still on auth page after 30s (url={page.url})"
                )

    async def scrape(
        self,
        keywords: list[str],
        locations: list[str],
        limit: int,
        headless: bool,
        user_data_dir: str,
    ) -> list[JobDict]:
        _browser, context = await self.open_context(headless, user_data_dir)
        jobs: list[JobDict] = []

        try:
            page = await context.new_page()

            # Build search URL — join keywords and pick first location
            kw = quote_plus(" ".join(keywords[:3]))
            loc = quote_plus(locations[0] if locations else "India")
            search_url = (
                f"https://www.linkedin.com/jobs/search/?keywords={kw}&location={loc}"
                "&f_TPR=r86400&sortBy=DD"
            )

            await asyncio.sleep(random.uniform(2.0, 6.0))
            await page.goto(search_url, timeout=30_000)
            await asyncio.sleep(random.uniform(1.5, 3.0))

            # Gentle scroll to load listings
            for _ in range(5):
                await page.evaluate("window.scrollBy(0, 50)")
                await asyncio.sleep(0.2)

            # Extract job cards
            cards = await page.query_selector_all(".jobs-search__results-list > li")
            for card in cards[:limit]:
                try:
                    title_el = await card.query_selector(".base-search-card__title")
                    company_el = await card.query_selector(".base-search-card__subtitle")
                    location_el = await card.query_selector(".job-search-card__location")
                    link_el = await card.query_selector("a.base-card__full-link")
                    metadata_el = await card.query_selector(".job-search-card__listdate")

                    title = (await title_el.inner_text()).strip() if title_el else "Unknown"
                    company = (await company_el.inner_text()).strip() if company_el else "Unknown"
                    location = (await location_el.inner_text()).strip() if location_el else None
                    url = await link_el.get_attribute("href") if link_el else ""
                    if url and not url.startswith("http"):
                        url = "https://www.linkedin.com" + url

                    # LinkedIn jobs are generally Easy Apply or external
                    easy_apply_el = await card.query_selector(".job-search-card__easy-apply-label")
                    apply_type = "easy_apply" if easy_apply_el else "external_form"

                    posted_at = datetime.now(tz=timezone.utc)
                    if metadata_el:
                        dt_attr = await metadata_el.get_attribute("datetime")
                        if dt_attr:
                            try:
                                posted_at = datetime.fromisoformat(dt_attr.replace("Z", "+00:00"))
                            except ValueError:
                                pass

                    jobs.append(
                        JobDict(
                            title=title,
                            company=company,
                            platform=self.platform,
                            url=url or search_url,
                            apply_type=apply_type,
                            ctc=None,
                            yoe_required=None,
                            location=location,
                            posted_at=posted_at,
                        )
                    )
                except Exception as exc:
                    log.debug("linkedin: error parsing card: %s", exc)
                    continue

        finally:
            await context.close()

        return jobs
