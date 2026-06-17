"""Tests for Module 2 — Scraper.

Covers:
1. discover_plugins() finds a plugin placed in plugins/ dir
2. Exception during scrape → run_all() returns [] for that platform, continues
3. is_logged_out() returns True when URL matches LOGIN_INDICATORS
4. Mocked logged-out page → run_all() calls login() then retries scrape
5. LoginError from login() → platform skipped, others still run
6. CryptoVault.get() returns correct dict for valid encrypted data
7. run_all() with mocked plugins returns merged JobDict list, schema-valid
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet

# ---------------------------------------------------------------------------
# Ensure the repo root is on sys.path so `src.*` imports work
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.scrapers.base import BaseScraper, JobDict, LoginError
from src.scrapers.crypto_vault import CryptoVault
from src.scrapers.manager import discover_plugins, run_all


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 6, 17, 13, 30, 0, tzinfo=timezone.utc)

SAMPLE_JOB: JobDict = {
    "title": "Senior Backend Engineer",
    "company": "Razorpay",
    "platform": "testplatform",
    "url": "https://example.com/jobs/1",
    "apply_type": "easy_apply",
    "ctc": "30-50 LPA",
    "yoe_required": "3-7 years",
    "location": "Bengaluru",
    "posted_at": NOW,
}


def _make_settings(enabled_plugins: list[str]) -> MagicMock:
    """Create a minimal Settings-like mock."""
    s = MagicMock()
    s.enabled_plugins = enabled_plugins
    s.keywords = ["Senior Backend Engineer"]
    s.locations = ["Bengaluru"]
    s.scrape_per_platform = 5
    s.headless = True
    s.chrome_profiles = {p: f"/tmp/profile_{p}" for p in enabled_plugins}
    return s


def _make_vault() -> MagicMock:
    return MagicMock(spec=CryptoVault)


# ---------------------------------------------------------------------------
# Fixture plugin class (used in test_discover_plugins)
# ---------------------------------------------------------------------------

class _GoodScraper(BaseScraper):
    platform = "testplatform"
    LOGIN_INDICATORS = ["example.com/login"]

    async def scrape(self, keywords, locations, limit, headless, user_data_dir) -> list[JobDict]:
        return [SAMPLE_JOB]


class _BadScraper(BaseScraper):
    platform = "badplatform"
    LOGIN_INDICATORS = []

    async def scrape(self, keywords, locations, limit, headless, user_data_dir) -> list[JobDict]:
        raise RuntimeError("Intentional failure for testing")


class _LoginErrorScraper(BaseScraper):
    platform = "loginplatform"
    LOGIN_INDICATORS = []

    async def login(self, page, vault) -> None:
        raise LoginError("loginplatform: test login failure")

    async def scrape(self, keywords, locations, limit, headless, user_data_dir) -> list[JobDict]:
        return [SAMPLE_JOB]


# ---------------------------------------------------------------------------
# 1. discover_plugins() — finds a plugin dynamically
# ---------------------------------------------------------------------------


def test_discover_plugins_finds_injected_module(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject a fake plugin module into sys.modules, assert discovery finds it."""
    module_name = "src.scrapers.plugins.fakeplatform"
    fake_module = types.ModuleType(module_name)
    fake_module.FakeScraper = type(
        "FakeScraper",
        (_GoodScraper,),
        {"platform": "fakeplatform"},
    )
    monkeypatch.setitem(sys.modules, module_name, fake_module)

    result = discover_plugins(["fakeplatform"])
    assert len(result) == 1
    assert result[0].platform == "fakeplatform"


def test_discover_plugins_skips_missing_module() -> None:
    """Missing plugin module → warning logged, no crash, empty list."""
    result = discover_plugins(["nonexistent_platform_xyz"])
    assert result == []


def test_discover_plugins_multiple(monkeypatch: pytest.MonkeyPatch) -> None:
    """Discovers multiple injected plugins in order."""
    for slug in ("alpha", "beta"):
        mod = types.ModuleType(f"src.scrapers.plugins.{slug}")
        cls = type(
            f"{slug.capitalize()}Scraper",
            (_GoodScraper,),
            {"platform": slug},
        )
        setattr(mod, f"{slug.capitalize()}Scraper", cls)
        monkeypatch.setitem(sys.modules, f"src.scrapers.plugins.{slug}", mod)

    result = discover_plugins(["alpha", "beta"])
    platforms = [s.platform for s in result]
    assert platforms == ["alpha", "beta"]


# ---------------------------------------------------------------------------
# 2. Exception during scrape → run_all returns [] for that platform, continues
# ---------------------------------------------------------------------------


def test_run_all_exception_in_scrape_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scraper that raises during scrape() → [] returned, other platform still runs."""
    # Inject bad + good plugins
    for slug, cls in [("badplatform", _BadScraper), ("testplatform", _GoodScraper)]:
        mod = types.ModuleType(f"src.scrapers.plugins.{slug}")
        setattr(mod, cls.__name__, cls)
        monkeypatch.setitem(sys.modules, f"src.scrapers.plugins.{slug}", mod)

    settings = _make_settings(["badplatform", "testplatform"])
    vault = _make_vault()

    # We need to mock open_context to avoid real browser calls.
    _patch_open_context(monkeypatch)

    jobs = asyncio.run(run_all(settings, vault))

    # bad platform returns [], good platform returns 1 job
    assert any(j["platform"] == "testplatform" for j in jobs)
    assert not any(j["platform"] == "badplatform" for j in jobs)


# ---------------------------------------------------------------------------
# 3. is_logged_out() returns True when URL matches LOGIN_INDICATORS
# ---------------------------------------------------------------------------


def test_is_logged_out_url_match() -> None:
    """is_logged_out() detects login page via URL substring."""
    scraper = _GoodScraper()

    page = MagicMock()
    page.url = "https://example.com/login?next=/dashboard"

    # page.locator(...).is_visible() should return False (URL already matched)
    async def run():
        return await scraper.is_logged_out(page)

    result = asyncio.run(run())
    assert result is True


def test_is_logged_out_no_match() -> None:
    """is_logged_out() returns False when URL does not match indicators."""
    scraper = _GoodScraper()

    page = MagicMock()
    page.url = "https://example.com/dashboard"
    locator = AsyncMock()
    locator.is_visible = AsyncMock(return_value=False)
    page.locator = MagicMock(return_value=locator)

    async def run():
        return await scraper.is_logged_out(page)

    result = asyncio.run(run())
    assert result is False


def test_is_logged_out_css_selector_visible() -> None:
    """is_logged_out() detects login via visible CSS selector."""

    class SelectorScraper(BaseScraper):
        platform = "selectortest"
        LOGIN_INDICATORS = ["#loginModal"]

        async def scrape(self, *args, **kwargs):
            return []

    scraper = SelectorScraper()
    page = MagicMock()
    page.url = "https://example.com/dashboard"  # URL does not match

    locator = AsyncMock()
    locator.is_visible = AsyncMock(return_value=True)
    page.locator = MagicMock(return_value=locator)

    async def run():
        return await scraper.is_logged_out(page)

    result = asyncio.run(run())
    assert result is True


# ---------------------------------------------------------------------------
# 4. Mocked logged-out page → run_all() calls login() then retries scrape
# ---------------------------------------------------------------------------


def test_run_all_calls_login_on_logged_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """When is_logged_out() returns True, login() is called and scrape is retried."""
    login_called = []
    scrape_called = []

    class LoggedOutScraper(BaseScraper):
        platform = "loggedoutplatform"
        LOGIN_INDICATORS = ["loggedoutplatform.com/login"]

        async def login(self, page, vault):
            login_called.append(True)

        async def scrape(self, keywords, locations, limit, headless, user_data_dir):
            scrape_called.append(True)
            return [SAMPLE_JOB]

    mod = types.ModuleType("src.scrapers.plugins.loggedoutplatform")
    mod.LoggedOutScraper = LoggedOutScraper
    monkeypatch.setitem(sys.modules, "src.scrapers.plugins.loggedoutplatform", mod)

    settings = _make_settings(["loggedoutplatform"])
    vault = _make_vault()

    # Patch open_context + is_logged_out to simulate logged-out state
    async def mock_open_context(self, headless, user_data_dir):
        browser = MagicMock()
        context = AsyncMock()
        page = AsyncMock()
        page.url = "https://loggedoutplatform.com/login"
        page.title = AsyncMock(return_value="Login")
        context.new_page = AsyncMock(return_value=page)
        context.close = AsyncMock()
        return browser, context

    monkeypatch.setattr(BaseScraper, "open_context", mock_open_context)

    # Patch is_logged_out to return True then False
    is_logged_out_calls = []

    async def mock_is_logged_out(self, page):
        is_logged_out_calls.append(1)
        # First call: logged out; subsequent calls: logged in
        return len(is_logged_out_calls) == 1

    monkeypatch.setattr(BaseScraper, "is_logged_out", mock_is_logged_out)

    jobs = asyncio.run(run_all(settings, vault))

    assert len(login_called) >= 1, "login() was not called"
    assert len(scrape_called) >= 1, "scrape() was not called after login"


# ---------------------------------------------------------------------------
# 5. LoginError from login() → platform skipped, other platforms still run
# ---------------------------------------------------------------------------


def test_run_all_login_error_skips_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    """LoginError from login() logs and skips platform; other platforms run."""
    # loginplatform raises LoginError; testplatform succeeds
    for slug, cls in [("loginplatform", _LoginErrorScraper), ("testplatform", _GoodScraper)]:
        mod = types.ModuleType(f"src.scrapers.plugins.{slug}")
        setattr(mod, cls.__name__, cls)
        monkeypatch.setitem(sys.modules, f"src.scrapers.plugins.{slug}", mod)

    settings = _make_settings(["loginplatform", "testplatform"])
    vault = _make_vault()

    _patch_open_context(monkeypatch)

    async def mock_is_logged_out(self, page):
        # loginplatform appears logged out to trigger login(); testplatform is fine
        return self.platform == "loginplatform"

    monkeypatch.setattr(BaseScraper, "is_logged_out", mock_is_logged_out)

    jobs = asyncio.run(run_all(settings, vault))

    # testplatform's job should appear; loginplatform's should not
    assert any(j["platform"] == "testplatform" for j in jobs)
    assert not any(j["platform"] == "loginplatform" for j in jobs)


# ---------------------------------------------------------------------------
# 6. CryptoVault.get() returns correct dict for valid encrypted data
# ---------------------------------------------------------------------------


def test_crypto_vault_get_returns_correct_dict(tmp_path: Path) -> None:
    """CryptoVault decrypts credentials.enc and returns the right platform dict."""
    key = Fernet.generate_key()
    fernet = Fernet(key)

    payload = {
        "linkedin": {"method": "google_sso", "google_email": "yashdeshmukh7@gmail.com"},
        "naukri": {"method": "password", "username": "yashdeshmukh7@gmail.com", "password": "secret"},
    }
    encrypted = fernet.encrypt(json.dumps(payload).encode())

    enc_path = tmp_path / "credentials.enc"
    enc_path.write_bytes(encrypted)

    vault = CryptoVault(key)
    vault._enc_path = enc_path  # point to temp file

    linkedin_creds = vault.get("linkedin")
    assert linkedin_creds["method"] == "google_sso"
    assert linkedin_creds["google_email"] == "yashdeshmukh7@gmail.com"

    naukri_creds = vault.get("naukri")
    assert naukri_creds["method"] == "password"
    assert naukri_creds["username"] == "yashdeshmukh7@gmail.com"
    assert naukri_creds["password"] == "secret"


def test_crypto_vault_raises_key_error_for_unknown_platform(tmp_path: Path) -> None:
    """CryptoVault.get() raises KeyError for platform not in store."""
    key = Fernet.generate_key()
    fernet = Fernet(key)
    payload = {"linkedin": {"method": "google_sso", "google_email": "x@x.com"}}
    encrypted = fernet.encrypt(json.dumps(payload).encode())

    enc_path = tmp_path / "credentials.enc"
    enc_path.write_bytes(encrypted)

    vault = CryptoVault(key)
    vault._enc_path = enc_path

    with pytest.raises(KeyError):
        vault.get("nonexistent_platform")


def test_crypto_vault_raises_file_not_found(tmp_path: Path) -> None:
    """CryptoVault.get() raises FileNotFoundError if credentials.enc is missing."""
    key = Fernet.generate_key()
    vault = CryptoVault(key)
    vault._enc_path = tmp_path / "missing.enc"

    with pytest.raises(FileNotFoundError):
        vault.get("linkedin")


def test_crypto_vault_lazy_loads_once(tmp_path: Path) -> None:
    """CryptoVault decrypts only on first get(); subsequent calls use the cache."""
    key = Fernet.generate_key()
    fernet = Fernet(key)
    payload = {"platform_a": {"data": "value_a"}}
    encrypted = fernet.encrypt(json.dumps(payload).encode())

    enc_path = tmp_path / "credentials.enc"
    enc_path.write_bytes(encrypted)

    vault = CryptoVault(key)
    vault._enc_path = enc_path

    result1 = vault.get("platform_a")
    # Remove the file — cache should still work
    enc_path.unlink()
    result2 = vault.get("platform_a")

    assert result1 == result2 == {"data": "value_a"}


# ---------------------------------------------------------------------------
# 7. run_all() with mocked plugins returns merged JobDict list, schema-valid
# ---------------------------------------------------------------------------


def test_run_all_returns_merged_schema_valid_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_all() with two working plugins returns all jobs merged and schema-valid."""
    required_keys = {
        "title", "company", "platform", "url", "apply_type",
        "ctc", "yoe_required", "location", "posted_at",
    }

    job_a: JobDict = {**SAMPLE_JOB, "platform": "platform_a", "company": "CompA"}
    job_b: JobDict = {**SAMPLE_JOB, "platform": "platform_b", "company": "CompB"}

    class ScraperA(BaseScraper):
        platform = "platform_a"
        LOGIN_INDICATORS = []

        async def scrape(self, keywords, locations, limit, headless, user_data_dir):
            return [job_a]

    class ScraperB(BaseScraper):
        platform = "platform_b"
        LOGIN_INDICATORS = []

        async def scrape(self, keywords, locations, limit, headless, user_data_dir):
            return [job_b]

    for slug, cls in [("platform_a", ScraperA), ("platform_b", ScraperB)]:
        mod = types.ModuleType(f"src.scrapers.plugins.{slug}")
        setattr(mod, cls.__name__, cls)
        monkeypatch.setitem(sys.modules, f"src.scrapers.plugins.{slug}", mod)

    settings = _make_settings(["platform_a", "platform_b"])
    vault = _make_vault()

    _patch_open_context(monkeypatch)

    async def mock_is_logged_out(self, page):
        return False

    monkeypatch.setattr(BaseScraper, "is_logged_out", mock_is_logged_out)

    jobs = asyncio.run(run_all(settings, vault))

    assert len(jobs) == 2
    platforms = {j["platform"] for j in jobs}
    assert "platform_a" in platforms
    assert "platform_b" in platforms

    for job in jobs:
        missing = required_keys - set(job.keys())
        assert not missing, f"Job is missing required keys: {missing}"
        assert isinstance(job["title"], str)
        assert isinstance(job["company"], str)
        assert isinstance(job["posted_at"], datetime)
        assert job["apply_type"] in ("easy_apply", "external_form")


def test_run_all_empty_enabled_plugins() -> None:
    """run_all() with no enabled plugins returns empty list without crashing."""
    settings = _make_settings([])
    vault = _make_vault()

    jobs = asyncio.run(run_all(settings, vault))
    assert jobs == []


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


def _patch_open_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch BaseScraper.open_context to return a dummy context with a clean page."""

    async def mock_open_context(self, headless, user_data_dir):
        browser = MagicMock()
        context = AsyncMock()
        page = AsyncMock()
        page.url = "https://dashboard.example.com/"
        page.title = AsyncMock(return_value="Dashboard")
        context.new_page = AsyncMock(return_value=page)
        context.close = AsyncMock()
        return browser, context

    monkeypatch.setattr(BaseScraper, "open_context", mock_open_context)
