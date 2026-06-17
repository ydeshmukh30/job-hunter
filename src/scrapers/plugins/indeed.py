"""Indeed.com scraper plugin."""

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


class IndeedScraper(BaseScraper):
    platform = "indeed"
    LOGIN_INDICATORS = ["indeed.com/account/login"]

    async def login(self, page: Page, vault: CryptoVault) -> None:
        creds = vault.get("indeed")

        await page.goto("https://secure.indeed.com/account/login", timeout=30_000)
        await asyncio.sleep(random.uniform(1.0, 2.0))

        try:
            # Indeed uses an email → password two-step flow
            await page.fill("input[name='__email']", creds["username"], timeout=10_000)
            await page.click("button[type='submit']", timeout=10_000)
            await asyncio.sleep(random.uniform(1.0, 2.0))
            await page.fill("input[name='__password']", creds["password"], timeout=10_000)
            await page.click("button[type='submit']", timeout=10_000)
        except Exception as exc:
            raise LoginError(f"indeed: login form interaction failed: {exc}") from exc

        try:
            await page.wait_for_url("**/indeed.com/**", timeout=20_000)
        except Exception:
            pass

        if "account/login" in page.url or "signin" in page.url:
            raise LoginError("indeed: login failed — still on login page")

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

            kw = quote_plus(" ".join(keywords[:3]))
            loc = quote_plus(locations[0] if locations else "India")
            search_url = f"https://in.indeed.com/jobs?q={kw}&l={loc}&sort=date"

            await asyncio.sleep(random.uniform(2.0, 6.0))
            await page.goto(search_url, timeout=30_000)
            await asyncio.sleep(random.uniform(1.5, 3.0))

            for _ in range(5):
                await page.evaluate("window.scrollBy(0, 50)")
                await asyncio.sleep(0.2)

            cards = await page.query_selector_all(".job_seen_beacon")
            for card in cards[:limit]:
                try:
                    title_el = await card.query_selector("h2.jobTitle span[title]")
                    company_el = await card.query_selector("[data-testid='company-name']")
                    location_el = await card.query_selector("[data-testid='text-location']")
                    salary_el = await card.query_selector(".salary-snippet-container")
                    link_el = await card.query_selector("h2.jobTitle a")

                    title = await title_el.get_attribute("title") if title_el else "Unknown"
                    company = (await company_el.inner_text()).strip() if company_el else "Unknown"
                    location = (await location_el.inner_text()).strip() if location_el else None
                    ctc = (await salary_el.inner_text()).strip() if salary_el else None
                    href = await link_el.get_attribute("href") if link_el else ""
                    if href and not href.startswith("http"):
                        href = "https://in.indeed.com" + href

                    jobs.append(
                        JobDict(
                            title=title or "Unknown",
                            company=company,
                            platform=self.platform,
                            url=href or search_url,
                            apply_type="external_form",
                            ctc=ctc,
                            yoe_required=None,
                            location=location,
                            posted_at=datetime.now(tz=timezone.utc),
                        )
                    )
                except Exception as exc:
                    log.debug("indeed: error parsing card: %s", exc)
                    continue

        finally:
            await context.close()

        return jobs
