"""Wellfound (formerly AngelList Talent) scraper plugin."""

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


class WellfoundScraper(BaseScraper):
    platform = "wellfound"
    LOGIN_INDICATORS = ["wellfound.com/login", "angel.co/login"]

    async def login(self, page: Page, vault: CryptoVault) -> None:
        creds = vault.get("wellfound")

        await page.goto("https://wellfound.com/login", timeout=30_000)
        await asyncio.sleep(random.uniform(1.0, 2.0))

        try:
            await page.fill("input[name='user[email]']", creds["username"], timeout=10_000)
            await page.fill("input[name='user[password]']", creds["password"], timeout=10_000)
            await page.click("input[type='submit'], button[type='submit']", timeout=10_000)
        except Exception as exc:
            raise LoginError(f"wellfound: login form interaction failed: {exc}") from exc

        try:
            await page.wait_for_url("**/wellfound.com/**", timeout=20_000)
        except Exception:
            pass

        if "login" in page.url:
            raise LoginError("wellfound: login failed — still on login page")

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
            loc = quote_plus(locations[0] if locations else "India")
            search_url = f"https://wellfound.com/jobs?q={kw}&l={loc}"

            await asyncio.sleep(random.uniform(2.0, 6.0))
            await page.goto(search_url, timeout=30_000)
            await asyncio.sleep(random.uniform(1.5, 3.0))

            for _ in range(5):
                await page.evaluate("window.scrollBy(0, 50)")
                await asyncio.sleep(0.2)

            cards = await page.query_selector_all("[data-test='StartupJobResult']")
            for card in cards[:limit]:
                try:
                    title_el = await card.query_selector("a[data-test='job-title']")
                    company_el = await card.query_selector("a[data-test='startup-link']")
                    location_el = await card.query_selector("[data-test='job-location']")
                    comp_el = await card.query_selector("[data-test='job-compensation']")
                    exp_el = await card.query_selector("[data-test='job-experience']")

                    title = (await title_el.inner_text()).strip() if title_el else "Unknown"
                    company = (await company_el.inner_text()).strip() if company_el else "Unknown"
                    location = (await location_el.inner_text()).strip() if location_el else None
                    ctc = (await comp_el.inner_text()).strip() if comp_el else None
                    yoe = (await exp_el.inner_text()).strip() if exp_el else None
                    href = await title_el.get_attribute("href") if title_el else ""
                    if href and not href.startswith("http"):
                        href = "https://wellfound.com" + href

                    jobs.append(
                        JobDict(
                            title=title,
                            company=company,
                            platform=self.platform,
                            url=href or search_url,
                            apply_type="easy_apply",
                            ctc=ctc,
                            yoe_required=yoe,
                            location=location,
                            posted_at=datetime.now(tz=timezone.utc),
                        )
                    )
                except Exception as exc:
                    log.debug("wellfound: error parsing card: %s", exc)
                    continue

        finally:
            await context.close()

        return jobs
