"""Drive a dedicated, already-logged-in Chrome profile.

Session strategy: one Chrome profile at ``~/.chrome-jobhunter`` that the user
signs into once.  Playwright reuses it on every run, so there are no stored
credentials, no automated login, and no CAPTCHA loop.  That deleted the Fernet
vault, all eight per-platform ``login()`` methods, and the re-login retry paths.

Two constraints shaped the mechanism, both discovered by testing rather than
assumption:

1. **Chrome >= 136 refuses ``--remote-debugging-port`` on the default profile.**
   Deliberate hardening against cookie-stealing malware.  Chrome here is 150,
   so pointing at the user's everyday profile is not an option; a dedicated
   ``--user-data-dir`` is required either way.
   https://developer.chrome.com/blog/remote-debugging-port

2. **``connect_over_cdp`` is broken on this pairing.**  Playwright 1.60 against
   Chrome 150 fails the connect handshake with
   ``Browser.setDownloadBehavior: Browser context management is not supported``.
   So we do not attach to an externally-launched Chrome — Playwright launches
   and owns it via ``launch_persistent_context``, which is the supported path
   and immune to that version skew.

Consequence worth knowing: the profile is locked while a run is in progress, so
the manual login window must be closed before the poller can drive it.
"""

from __future__ import annotations

import logging
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Final

from playwright.async_api import BrowserContext, async_playwright

log = logging.getLogger(__name__)

CHROME_BIN: Final[str] = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE_DIR: Final[Path] = Path.home() / ".chrome-jobhunter"

# Far enough right to stay out of the way on a large display, but still on it.
# Fully off-screen positions are unrecoverable without Accessibility access,
# which macOS will not grant a headless script.
_WINDOW: Final[tuple[int, int, int, int]] = (60, 60, 1280, 860)


class BrowserUnavailable(RuntimeError):
    """Chrome is missing, or its profile is locked by another process."""


def profile_in_use() -> bool:
    """True if a Chrome process already holds the job-hunter profile.

    Playwright cannot open a profile another Chrome has locked, and the failure
    mode is an opaque timeout, so check first and say something useful.
    """
    result = subprocess.run(
        ["pgrep", "-f", f"user-data-dir={PROFILE_DIR}"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def open_for_login(url: str = "https://www.linkedin.com/login") -> None:
    """Open the profile in a normal Chrome window so the user can sign in.

    Not a Playwright launch: Google blocks sign-in from automation-flagged
    browsers, and this window is for a human anyway.  The session it
    establishes persists in the profile directory for every later run.
    """
    if not Path(CHROME_BIN).exists():
        raise BrowserUnavailable(f"Chrome not found at {CHROME_BIN}")
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    x, y, w, h = _WINDOW
    subprocess.Popen(
        [
            CHROME_BIN,
            f"--user-data-dir={PROFILE_DIR}",
            "--no-first-run",
            "--no-default-browser-check",
            f"--window-position={x},{y}",
            f"--window-size={w},{h}",
            url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


@asynccontextmanager
async def session(headless: bool = False):
    """Yield a Playwright context bound to the job-hunter profile.

    ``headless`` defaults to False: the profile has to survive a Google OAuth
    flow, and Google blocks headless sign-in.  Once the session cookie exists,
    headless works for scraping — but a visible window also makes it obvious
    when something has gone wrong at 11am on a Tuesday.
    """
    if not Path(CHROME_BIN).exists():
        raise BrowserUnavailable(f"Chrome not found at {CHROME_BIN}")

    if profile_in_use():
        raise BrowserUnavailable(
            f"A Chrome window already has {PROFILE_DIR} open. Close it and retry — "
            "Chrome will not share a profile between two processes."
        )

    x, y, w, h = _WINDOW
    playwright = await async_playwright().start()
    context: BrowserContext = await playwright.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        channel="chrome",  # real Chrome, not bundled Chromium — fewer bot signals
        headless=headless,
        viewport={"width": w, "height": h},
        args=[
            "--no-first-run",
            "--no-default-browser-check",
            f"--window-position={x},{y}",
        ],
        locale="en-US",
        timezone_id="Asia/Kolkata",
    )
    try:
        yield context
    finally:
        await context.close()
        await playwright.stop()


async def is_logged_in_linkedin(context: BrowserContext) -> bool:
    """Cheap check that the profile still holds a LinkedIn session."""
    page = await context.new_page()
    try:
        await page.goto("https://www.linkedin.com/feed/", timeout=30_000)
        return "/feed" in page.url and "login" not in page.url and "authwall" not in page.url
    except Exception as exc:
        log.warning("linkedin session check failed: %s", exc)
        return False
    finally:
        await page.close()
