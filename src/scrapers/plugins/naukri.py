"""Naukri.com scraper plugin."""

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


class NaukriScraper(BaseScraper):
    platform = "naukri"
    LOGIN_INDICATORS = ["naukri.com/nlogin", "#usernameField"]

    async def login(self, page: Page, vault: CryptoVault) -> None:
        creds = vault.get("naukri")  # {"method": "password", "username": ..., "password": ...}

        await page.goto("https://www.naukri.com/nlogin/login", timeout=30_000)
        await asyncio.sleep(random.uniform(1.0, 2.0))

        try:
            await page.fill("#usernameField", creds["username"], timeout=10_000)
            await page.fill("#passwordField", creds["password"], timeout=10_000)
            await page.press("#passwordField", "Enter")
        except Exception as exc:
            raise LoginError(f"naukri: login form interaction failed: {exc}") from exc

        try:
            await page.wait_for_url("**naukri.com**", timeout=20_000)
        except Exception:
            pass  # check URL manually

        if "nlogin" in page.url:
            raise LoginError("naukri: login failed — still on login page")

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

            kw = "-".join(k.lower().replace(" ", "-") for k in keywords[:2])
            loc = "-".join(l.lower().replace(" ", "-") for l in locations[:2])
            search_url = f"https://www.naukri.com/{kw}-jobs-in-{loc}"

            await asyncio.sleep(random.uniform(2.0, 6.0))
            await page.goto(search_url, timeout=30_000)
            await asyncio.sleep(random.uniform(1.5, 3.0))

            # Gentle scroll
            for _ in range(5):
                await page.evaluate("window.scrollBy(0, 50)")
                await asyncio.sleep(0.2)

            cards = await page.query_selector_all("article.jobTuple")
            for card in cards[:limit]:
                try:
                    title_el = await card.query_selector("a.title")
                    company_el = await card.query_selector("a.subTitle")
                    location_el = await card.query_selector("li.location span")
                    exp_el = await card.query_selector("li.experience span")
                    salary_el = await card.query_selector("li.salary span")

                    title = (await title_el.inner_text()).strip() if title_el else "Unknown"
                    company = (await company_el.inner_text()).strip() if company_el else "Unknown"
                    location = (await location_el.inner_text()).strip() if location_el else None
                    yoe = (await exp_el.inner_text()).strip() if exp_el else None
                    ctc = (await salary_el.inner_text()).strip() if salary_el else None
                    url = await title_el.get_attribute("href") if title_el else ""

                    jobs.append(
                        JobDict(
                            title=title,
                            company=company,
                            platform=self.platform,
                            url=url or search_url,
                            apply_type="easy_apply",
                            ctc=ctc,
                            yoe_required=yoe,
                            location=location,
                            posted_at=datetime.now(tz=timezone.utc),
                        )
                    )
                except Exception as exc:
                    log.debug("naukri: error parsing card: %s", exc)
                    continue

        finally:
            await context.close()

        return jobs
