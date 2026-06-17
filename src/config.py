"""Typed settings loader — reads config/settings.toml + environment variables."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).parent.parent  # repo root


class ConfigError(Exception):
    pass


@dataclass
class Settings:
    # [general]
    enabled_plugins: list[str]

    # [search]
    keywords: list[str]
    locations: list[str]

    # [limits]
    scrape_per_platform: int
    apply_attempts_per_platform: int

    # [filter]
    min_ctc_lpa: float
    target_yoe: int
    full_time_only: bool
    titles: list[str]

    # [schedule]
    daily_run_cron: str
    brief_poll_cron: str

    # [paths]
    resume_pdf: Path

    # [runtime]
    headless: bool
    timezone: str

    # [chrome_profiles]
    chrome_profiles: dict[str, str]

    # [notify]
    digest_recipient: str
    smtp_host: str
    smtp_port: int

    # From environment variables
    master_crypto_key: bytes
    gmail_app_password: str
    anthropic_api_key: str
    anthropic_model: str
    daily_llm_usd_cap: float


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"Required environment variable '{name}' is not set. See .env.example.")
    return value


def load(toml_path: Path | None = None) -> Settings:
    """Load and validate settings from settings.toml + environment variables."""
    toml_path = toml_path or ROOT / "config" / "settings.toml"
    if not toml_path.exists():
        raise ConfigError(f"Settings file not found: {toml_path}")

    with open(toml_path, "rb") as f:
        cfg = tomllib.load(f)

    resume_raw = cfg.get("paths", {}).get("resume_pdf", "")
    resume_pdf = (ROOT / resume_raw) if resume_raw else ROOT / "config" / "resume.pdf"

    return Settings(
        enabled_plugins=cfg["general"]["enabled_plugins"],
        keywords=cfg["search"]["keywords"],
        locations=cfg["search"]["locations"],
        scrape_per_platform=cfg["limits"]["scrape_per_platform"],
        apply_attempts_per_platform=cfg["limits"]["apply_attempts_per_platform"],
        min_ctc_lpa=float(cfg["filter"]["min_ctc_lpa"]),
        target_yoe=int(cfg["filter"]["target_yoe"]),
        full_time_only=bool(cfg["filter"]["full_time_only"]),
        titles=cfg["filter"]["titles"],
        daily_run_cron=cfg["schedule"]["daily_run_cron"],
        brief_poll_cron=cfg["schedule"]["brief_poll_cron"],
        resume_pdf=resume_pdf,
        headless=bool(cfg["runtime"]["headless"]),
        timezone=cfg["runtime"]["timezone"],
        chrome_profiles=dict(cfg.get("chrome_profiles", {})),
        digest_recipient=cfg["notify"]["digest_recipient"],
        smtp_host=cfg["notify"]["smtp_host"],
        smtp_port=int(cfg["notify"]["smtp_port"]),
        master_crypto_key=_require_env("MASTER_CRYPTO_KEY").encode(),
        gmail_app_password=_require_env("GMAIL_APP_PASSWORD"),
        anthropic_api_key=_require_env("ANTHROPIC_API_KEY"),
        anthropic_model=_require_env("ANTHROPIC_MODEL"),
        daily_llm_usd_cap=float(_require_env("DAILY_LLM_USD_CAP")),
    )
