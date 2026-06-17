"""WeWorkRemotely scraper plugin (public board — no login required)."""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone
from urllib.parse import quote_plus

from playwright.async_api import Page

from src.scrapers.base import BaseScraper, JobDict
from src.scrapers.crypto_vault import CryptoVault

log = logging.getLogger(__name__)


class WeWorkRemotelyScraper(BaseScraper):
    platform = "weworkremotely"
    LOGIN_INDICATORS = []  # Public board — no login required

    async def login(self, page: Page, vault: CryptoVault) -> None:
        # No-op: WeWorkRemotely is fully public
        return

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

            kw = quote_plus(keywords[0] if keywords else "backend engineer")
            search_url = f"https://weworkremotely.com/remote-jobs/search?term={kw}"

            await asyncio.sleep(random.uniform(2.0, 6.0))
            await page.goto(search_url, timeout=30_000)
            await asyncio.sleep(random.uniform(1.5, 3.0))

            for _ in range(5):
                await page.evaluate("window.scrollBy(0, 50)")
                await asyncio.sleep(0.2)

            # WWR uses sections with <li> job rows
            cards = await page.query_selector_all("section.jobs li:not(.view-all)")
            for card in cards[:limit]:
                try:
                    title_el = await card.query_selector(".title")
                    company_el = await card.query_selector(".company")
                    region_el = await card.query_selector(".region")
                    link_el = await card.query_selector("a")

                    title = (await title_el.inner_text()).strip() if title_el else "Unknown"
                    company = (await company_el.inner_text()).strip() if company_el else "Unknown"
                    location = (await region_el.inner_text()).strip() if region_el else "Remote"
                    href = await link_el.get_attribute("href") if link_el else ""
                    if href and not href.startswith("http"):
                        href = "https://weworkremotely.com" + href

                    jobs.append(
                        JobDict(
                            title=title,
                            company=company,
                            platform=self.platform,
                            url=href or search_url,
                            apply_type="external_form",
                            ctc=None,
                            yoe_required=None,
                            location=location,
                            posted_at=datetime.now(tz=timezone.utc),
                        )
                    )
                except Exception as exc:
                    log.debug("weworkremotely: error parsing card: %s", exc)
                    continue

        finally:
            await context.close()

        return jobs
