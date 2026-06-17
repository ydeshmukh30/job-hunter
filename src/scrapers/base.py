"""Base scraper ABC and shared types."""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, ClassVar, Literal

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

if TYPE_CHECKING:
    from src.scrapers.crypto_vault import CryptoVault

from typing import TypedDict


class LoginError(Exception):
    """Raised when a platform re-login attempt fails."""


class JobDict(TypedDict):
    title: str
    company: str
    platform: str
    url: str
    apply_type: Literal["easy_apply", "external_form"]
    ctc: str | None
    yoe_required: str | None
    location: str | None
    posted_at: datetime


class BaseScraper(ABC):
    platform: ClassVar[str]
    LOGIN_INDICATORS: ClassVar[list[str]] = []

    # ------------------------------------------------------------------ #
    # Abstract interface
    # ------------------------------------------------------------------ #

    @abstractmethod
    async def scrape(
        self,
        keywords: list[str],
        locations: list[str],
        limit: int,
        headless: bool,
        user_data_dir: str,
    ) -> list[JobDict]:
        """Scrape job listings and return a list of JobDicts."""

    # ------------------------------------------------------------------ #
    # Shared helpers
    # ------------------------------------------------------------------ #

    async def open_context(
        self, headless: bool, user_data_dir: str
    ) -> tuple[Browser, BrowserContext]:
        """Launch Playwright with a randomized viewport and persistent user-data-dir."""
        width = random.choice([1280, 1366, 1440, 1920])
        height = random.choice([720, 768, 900, 1080])

        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=headless)
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=headless,
            viewport={"width": width, "height": height},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="Asia/Kolkata",
        )
        return browser, context

    async def is_logged_out(self, page: Page) -> bool:
        """Return True if the current page looks like a login / auth wall."""
        current_url = page.url
        for indicator in self.LOGIN_INDICATORS:
            # Check as URL substring
            if indicator in current_url:
                return True
            # Check as CSS selector visibility
            try:
                locator = page.locator(indicator)
                if await locator.is_visible(timeout=2_000):
                    return True
            except Exception:
                # Invalid CSS selector or timeout — not a match
                pass
        return False

    async def login(self, page: Page, vault: "CryptoVault") -> None:
        """Platform-specific re-login. Override in subclasses. Raises LoginError."""
        raise LoginError(f"{self.platform}: no login implementation")
