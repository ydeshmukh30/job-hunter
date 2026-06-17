"""Instahyre scraper plugin."""

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


class InstaHyreScraper(BaseScraper):
    platform = "instahyre"
    LOGIN_INDICATORS = ["instahyre.com/login"]

    async def login(self, page: Page, vault: CryptoVault) -> None:
        creds = vault.get("instahyre")

        await page.goto("https://www.instahyre.com/login/", timeout=30_000)
        await asyncio.sleep(random.uniform(1.0, 2.0))

        try:
            await page.fill("input[name='username']", creds["username"], timeout=10_000)
            await page.fill("input[name='password']", creds["password"], timeout=10_000)
            await page.click("button[type='submit']", timeout=10_000)
        except Exception as exc:
            raise LoginError(f"instahyre: login form interaction failed: {exc}") from exc

        try:
            await page.wait_for_url("**/instahyre.com/**", timeout=20_000)
        except Exception:
            pass

        if "login" in page.url:
            raise LoginError("instahyre: login failed — still on login page")

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

            kw = quote_plus(keywords[0] if keywords else "Senior Backend Engineer")
            loc = quote_plus(locations[0] if locations else "Bengaluru")
            search_url = f"https://www.instahyre.com/search-jobs/?q={kw}&location={loc}"

            await asyncio.sleep(random.uniform(2.0, 6.0))
            await page.goto(search_url, timeout=30_000)
            await asyncio.sleep(random.uniform(1.5, 3.0))

            for _ in range(5):
                await page.evaluate("window.scrollBy(0, 50)")
                await asyncio.sleep(0.2)

            cards = await page.query_selector_all(".opportunity-card")
            for card in cards[:limit]:
                try:
                    title_el = await card.query_selector(".opportunity-title")
                    company_el = await card.query_selector(".company-name")
                    location_el = await card.query_selector(".location")
                    exp_el = await card.query_selector(".experience")
                    link_el = await card.query_selector("a")

                    title = (await title_el.inner_text()).strip() if title_el else "Unknown"
                    company = (await company_el.inner_text()).strip() if company_el else "Unknown"
                    location = (await location_el.inner_text()).strip() if location_el else None
                    yoe = (await exp_el.inner_text()).strip() if exp_el else None
                    href = await link_el.get_attribute("href") if link_el else ""
                    if href and not href.startswith("http"):
                        href = "https://www.instahyre.com" + href

                    jobs.append(
                        JobDict(
                            title=title,
                            company=company,
                            platform=self.platform,
                            url=href or search_url,
                            apply_type="easy_apply",
                            ctc=None,
                            yoe_required=yoe,
                            location=location,
                            posted_at=datetime.now(tz=timezone.utc),
                        )
                    )
                except Exception as exc:
                    log.debug("instahyre: error parsing card: %s", exc)
                    continue

        finally:
            await context.close()

        return jobs
