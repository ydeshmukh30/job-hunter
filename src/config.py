"""Typed settings loader — reads config/settings.toml + environment variables."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
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

    # [poll]
    interval_minutes: int
    window_seconds: int
    active_start_ist: int
    active_end_ist: int

    # [limits]
    apply_attempts_per_run: int

    # [filter]
    min_ctc_lpa: float
    target_yoe: int
    full_time_only: bool
    titles: list[str]

    # [schedule]
    brief_poll_cron: str

    # [paths]
    resume_pdf: Path
    resume_dir: Path

    # [runtime]
    timezone: str

    # [notify]
    digest_recipient: str
    smtp_host: str
    smtp_port: int

    # [funding]
    funding_enabled: bool
    funding_feeds: list[str]

    # From environment variables
    gmail_app_password: str
    anthropic_api_key: str
    anthropic_model: str
    daily_llm_usd_cap: float
    ntfy_topic: str


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"Required environment variable '{name}' is not set. See .env.example.")
    return value


def _optional_env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip() or default


def load(toml_path: Path | None = None) -> Settings:
    """Load and validate settings from settings.toml + environment variables."""
    toml_path = toml_path or ROOT / "config" / "settings.toml"
    if not toml_path.exists():
        raise ConfigError(f"Settings file not found: {toml_path}")

    with open(toml_path, "rb") as f:
        cfg = tomllib.load(f)

    resume_raw = cfg.get("paths", {}).get("resume_pdf", "")
    resume_pdf = (ROOT / resume_raw) if resume_raw else ROOT / "config" / "resume.pdf"
    resume_dir = Path(
        cfg.get("paths", {}).get("resume_dir", "~/Desktop/cognizant/interview/resumes")
    ).expanduser()

    poll = cfg.get("poll", {})
    funding = cfg.get("funding", {})

    return Settings(
        enabled_plugins=cfg["general"]["enabled_plugins"],
        keywords=cfg["search"]["keywords"],
        locations=cfg["search"]["locations"],
        interval_minutes=int(poll.get("interval_minutes", 30)),
        window_seconds=int(poll.get("window_seconds", 3600)),
        active_start_ist=int(poll.get("active_start_ist", 8)),
        active_end_ist=int(poll.get("active_end_ist", 22)),
        apply_attempts_per_run=int(cfg["limits"]["apply_attempts_per_run"]),
        min_ctc_lpa=float(cfg["filter"]["min_ctc_lpa"]),
        target_yoe=int(cfg["filter"]["target_yoe"]),
        full_time_only=bool(cfg["filter"]["full_time_only"]),
        titles=cfg["filter"]["titles"],
        brief_poll_cron=cfg["schedule"]["brief_poll_cron"],
        resume_pdf=resume_pdf,
        resume_dir=resume_dir,
        timezone=cfg["runtime"]["timezone"],
        digest_recipient=cfg["notify"]["digest_recipient"],
        smtp_host=cfg["notify"]["smtp_host"],
        smtp_port=int(cfg["notify"]["smtp_port"]),
        funding_enabled=bool(funding.get("enabled", False)),
        funding_feeds=list(funding.get("feeds", [])),
        # Secrets are optional at load time so `--probe` and `--dry-run` work on a
        # bare checkout. The code paths that actually need one check at use.
        gmail_app_password=_optional_env("GMAIL_APP_PASSWORD"),
        anthropic_api_key=_optional_env("ANTHROPIC_API_KEY"),
        anthropic_model=_optional_env("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        daily_llm_usd_cap=float(_optional_env("DAILY_LLM_USD_CAP", "1.00")),
        ntfy_topic=_optional_env("NTFY_TOPIC"),
    )
