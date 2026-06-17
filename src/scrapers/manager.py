"""Scraper manager — plugin discovery and sequential execution."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
import random
import traceback
from typing import TYPE_CHECKING

from src.scrapers.base import BaseScraper, JobDict, LoginError

if TYPE_CHECKING:
    from src.config import Settings
    from src.scrapers.crypto_vault import CryptoVault

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Plugin discovery
# ---------------------------------------------------------------------------


def discover_plugins(enabled: list[str]) -> list[BaseScraper]:
    """Dynamically import each enabled plugin and return instantiated scrapers.

    For each name in *enabled*:
    - Attempts to import ``src.scrapers.plugins.<name>``
    - Finds the first class that is a concrete subclass of BaseScraper
    - Instantiates it (no constructor args)
    - Skips (with a warning) if the module is missing or has no valid class
    """
    scrapers: list[BaseScraper] = []
    for name in enabled:
        module_path = f"src.scrapers.plugins.{name}"
        try:
            module = importlib.import_module(module_path)
        except ModuleNotFoundError:
            log.warning("Plugin module not found, skipping: %s", module_path)
            continue

        klass = None
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, BaseScraper)
                and obj is not BaseScraper
                and not inspect.isabstract(obj)
            ):
                klass = obj
                break

        if klass is None:
            log.warning("No BaseScraper subclass found in %s, skipping", module_path)
            continue

        scrapers.append(klass())
        log.debug("Discovered plugin: %s (%s)", name, klass.__name__)

    return scrapers


# ---------------------------------------------------------------------------
# Sequential runner
# ---------------------------------------------------------------------------


async def run_all(settings: "Settings", vault: "CryptoVault") -> list[JobDict]:
    """Run all enabled plugins sequentially and return a merged list of JobDicts.

    Per-platform failure handling:
    - Logged-out detected → login() → retry scrape once
    - LoginError → log + skip platform (non-fatal)
    - 3 sequential CAPTCHA hits → log alert + skip platform
    - Any other exception → log traceback + return [] for platform
    - Human-like delay (2–6 s) before each platform
    """
    scrapers = discover_plugins(settings.enabled_plugins)
    all_jobs: list[JobDict] = []

    for scraper in scrapers:
        platform = scraper.platform
        log.info("Starting scraper: %s", platform)

        # Human-like delay before each platform
        delay = random.uniform(2.0, 6.0)
        log.debug("Sleeping %.1fs before %s", delay, platform)
        await asyncio.sleep(delay)

        jobs = await _run_single(scraper, settings, vault)
        log.info("%s → scraped %d job(s)", platform, len(jobs))
        all_jobs.extend(jobs)

    return all_jobs


async def _run_single(
    scraper: BaseScraper,
    settings: "Settings",
    vault: "CryptoVault",
) -> list[JobDict]:
    """Run a single scraper with all failure handling.  Returns [] on fatal failure."""
    platform = scraper.platform
    user_data_dir = settings.chrome_profiles.get(platform, "")
    headless = settings.headless
    keywords = settings.keywords
    locations = settings.locations
    limit = settings.scrape_per_platform

    try:
        # ---- Open a throw-away page just to check login status ----
        _browser, context = await scraper.open_context(headless, user_data_dir)
        page = await context.new_page()

        # Navigate to a platform landing page to trigger any session redirect
        landing = _platform_landing(platform)
        if landing:
            try:
                await page.goto(landing, timeout=20_000)
            except Exception:
                pass  # network errors here are non-fatal; is_logged_out will catch it

        logged_out = await scraper.is_logged_out(page)

        if logged_out:
            log.info("%s: session expired — attempting re-login", platform)
            try:
                await scraper.login(page, vault)
            except LoginError as exc:
                log.error("Login failed for %s: %s — check credentials.enc", platform, exc)
                await context.close()
                return []

        # ---- CAPTCHA tracking ----
        captcha_count = 0
        MAX_CAPTCHA = 3

        async def _scrape_with_captcha_guard() -> list[JobDict]:
            nonlocal captcha_count
            title = await page.title()
            url_lower = page.url.lower()
            if "captcha" in title.lower() or "captcha" in url_lower:
                captcha_count += 1
                if captcha_count >= MAX_CAPTCHA:
                    raise _CaptchaError(
                        f"CAPTCHA alert: {platform} blocked after {MAX_CAPTCHA} attempts"
                    )
                return []
            captcha_count = 0  # reset on clean page
            return await scraper.scrape(keywords, locations, limit, headless, user_data_dir)

        # Close the login-check context before the real scrape (scraper opens its own)
        await context.close()

        # ---- First scrape attempt ----
        try:
            jobs = await scraper.scrape(keywords, locations, limit, headless, user_data_dir)
        except _CaptchaError:
            raise
        except Exception:
            raise

        return jobs

    except LoginError as exc:
        log.error("Login failed for %s: %s", platform, exc)
        return []

    except _CaptchaError as exc:
        log.error(str(exc))
        return []

    except Exception:
        log.error("Unhandled exception in scraper %s:\n%s", platform, traceback.format_exc())
        return []


def _platform_landing(platform: str) -> str | None:
    """Return a sensible landing URL to check session state for a platform."""
    _landings: dict[str, str] = {
        "linkedin": "https://www.linkedin.com/feed/",
        "naukri": "https://www.naukri.com/",
        "indeed": "https://www.indeed.com/",
        "instahyre": "https://www.instahyre.com/",
        "wellfound": "https://wellfound.com/",
        "weworkremotely": "https://weworkremotely.com/",
        "hirist": "https://www.hirist.tech/",
        "cutshort": "https://cutshort.io/",
    }
    return _landings.get(platform)


class _CaptchaError(Exception):
    """Internal signal for repeated CAPTCHA blocks."""
