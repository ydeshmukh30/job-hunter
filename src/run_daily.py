"""
Main pipeline entrypoint for the job-hunter system.

Usage:
    python -m src.run_daily                          # dry-run (default)
    python -m src.run_daily --live                   # actually submit applications
    python -m src.run_daily --dry-run                # explicit dry-run
    python -m src.run_daily --check                  # did today's 7 PM run happen?
    python -m src.run_daily --status-summary         # per-status counts + unretried skips
    python -m src.run_daily --only scraper           # single-agent run
    python -m src.run_daily --retry-skipped          # retry all unretried skipped items
    python -m src.run_daily --retry-platform linkedin  # retry one platform
    python -m src.run_daily --force-accept-manual-edit  # re-baseline integrity hash
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

from src.config import load as load_settings, ConfigError
from src.common import data_store, integrity, run_state
from src.scrapers.crypto_vault import CryptoVault
from src.scrapers.manager import discover_plugins, run_all as scraper_run_all
from src.apply.match import filter_jobs
from src.apply.platforms.linkedin_applier import LinkedInApplier
from src.apply.platforms.naukri_applier import NaukriApplier
from src.apply.platforms.generic_applier import GenericApplier
from src.notify.digest import build_digest, send_digest

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).parent.parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("run_daily")

PLATFORM_APPLIERS = {
    "linkedin": LinkedInApplier,
    "naukri": NaukriApplier,
}


# ---------------------------------------------------------------------------
# Individual agents
# ---------------------------------------------------------------------------

def _agent_init(settings, force_manual: bool) -> bool:
    """Initialise CSV and verify integrity. Returns True on success."""
    try:
        data_store.init_csv()
        if force_manual:
            integrity.baseline(data_store.CSV_PATH, data_store.SIDECAR_PATH)
            log.info("Integrity hash re-baselined (--force-accept-manual-edit).")
        else:
            integrity.verify(data_store.CSV_PATH, data_store.SIDECAR_PATH)
        run_state.record_agent_success("init", "CSV verified")
        return True
    except integrity.IntegrityError as e:
        log.error("Integrity check failed: %s — pass --force-accept-manual-edit to override.", e)
        run_state.record_agent_failure("init", str(e))
        return False
    except Exception as e:
        log.error("Init agent failed: %s", e, exc_info=True)
        run_state.record_agent_failure("init", str(e))
        return False


async def _agent_scrape(settings, vault: CryptoVault, target_platforms: list[str] | None = None) -> list[dict]:
    """Run scrapers. If target_platforms given, only scrape those."""
    scraped: list[dict] = []
    try:
        plugins = discover_plugins(target_platforms or settings.enabled_plugins)
        jobs = await scraper_run_all(plugins, settings, vault)
        scraped = jobs

        new_ids = data_store.append_jobs(jobs)
        log.info("Scraper: %d new jobs across %d plugins.", len(new_ids), len(plugins))
        run_state.record_agent_success("scraper", f"Scraped {len(new_ids)} jobs")

        # Record any platforms that returned zero jobs due to errors (manager already logged them)
        attempted = {p.platform for p in plugins}
        succeeded = {j["platform"] for j in jobs}
        for platform in attempted - succeeded:
            run_state.record_skipped_platform(platform, "no_jobs_returned")

    except Exception as e:
        log.error("Scraper agent failed: %s", e, exc_info=True)
        run_state.record_agent_failure("scraper", str(e))

    if target_platforms:
        for p in target_platforms:
            run_state.mark_retried_platform(p)

    return scraped


def _agent_apply(settings, live: bool, target_job_ids: list[str] | None = None) -> None:
    """Filter and apply to jobs. If target_job_ids given, only apply to those."""
    try:
        existing_companies = data_store.get_companies()

        if target_job_ids:
            # Retry mode: apply only to specified jobs
            all_rows = data_store.read_all()
            candidates = [r for r in all_rows if r["id"] in target_job_ids]
        else:
            # Normal mode: filter freshly scraped jobs
            scraped = data_store.read_by_status("scraped")
            candidates = filter_jobs(scraped, existing_companies, settings)

        attempt_counts: dict[str, int] = {}
        applied = 0
        manual = 0

        for job in candidates:
            platform = job.get("platform", "")
            count = attempt_counts.get(platform, 0)
            if count >= settings.apply_attempts_per_platform:
                log.info("Apply cap reached for %s — skipping %s", platform, job["company"])
                continue

            applier_cls = PLATFORM_APPLIERS.get(platform, GenericApplier)
            applier = applier_cls()
            try:
                outcome = applier.apply(job, settings, live=live)
            except Exception as e:
                log.warning("Apply failed for %s/%s: %s", platform, job["company"], e, exc_info=True)
                outcome = "manual_review"

            attempt_counts[platform] = count + 1
            data_store.update_job(job["id"], status=outcome)

            if outcome == "applied":
                applied += 1
            else:
                manual += 1
                run_state.record_skipped_job(job, reason="apply_failed_or_unknown_ats")
                if target_job_ids:
                    run_state.mark_retried_job(job["id"])

        log.info("Apply agent: %d applied, %d manual_review.", applied, manual)
        run_state.record_agent_success("apply", f"{applied} applied, {manual} manual_review")

    except Exception as e:
        log.error("Apply agent failed: %s", e, exc_info=True)
        run_state.record_agent_failure("apply", str(e))


def _agent_persist(settings) -> None:
    """Recompute hash and git commit + push data files."""
    try:
        integrity.baseline(data_store.CSV_PATH, data_store.SIDECAR_PATH)
        ts = datetime.now(IST).strftime("%Y-%m-%d %H:%M %Z")
        subprocess.run(
            ["git", "add",
             "src/data/job_applications.csv",
             "src/data/job_applications.csv.sha256",
             "src/data/run_state.json"],
            cwd=ROOT, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", f"data: daily run {ts}"],
            cwd=ROOT, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "push"],
            cwd=ROOT, check=True, capture_output=True,
        )
        log.info("Persist agent: committed and pushed.")
        run_state.record_agent_success("persist", "committed and pushed")
    except subprocess.CalledProcessError as e:
        log.warning("Persist agent: git operation failed (non-fatal): %s", e.stderr.decode())
        run_state.record_agent_failure("persist", str(e))
    except Exception as e:
        log.error("Persist agent failed: %s", e, exc_info=True)
        run_state.record_agent_failure("persist", str(e))


def _agent_notify(settings) -> None:
    """Build and send daily digest email."""
    try:
        rows = data_store.read_all()
        skipped = {
            "platforms": run_state.get_unretried_platforms(),
            "jobs": run_state.get_unretried_jobs(),
        }
        html = build_digest(rows, skipped)
        send_digest(html, settings)
        log.info("Notify agent: digest sent.")
        run_state.record_agent_success("notify", "digest sent")
    except Exception as e:
        log.error("Notify agent failed: %s", e, exc_info=True)
        run_state.record_agent_failure("notify", str(e))


# ---------------------------------------------------------------------------
# Pipeline modes
# ---------------------------------------------------------------------------

async def run_pipeline(settings, live: bool, only: str | None, force_manual: bool) -> None:
    vault = CryptoVault(settings.master_crypto_key)

    agents = {
        "init":    lambda: _agent_init(settings, force_manual),
        "scraper": lambda: asyncio.get_event_loop().run_until_complete(_agent_scrape(settings, vault)),
        "apply":   lambda: _agent_apply(settings, live),
        "persist": lambda: _agent_persist(settings),
        "notify":  lambda: _agent_notify(settings),
    }

    if only:
        if only not in agents:
            log.error("Unknown agent '%s'. Valid: %s", only, ", ".join(agents))
            sys.exit(1)
        log.info("Running single agent: %s", only)
        agents[only]()
        return

    log.info("Starting full pipeline (mode=%s).", "LIVE" if live else "DRY-RUN")
    ok = _agent_init(settings, force_manual)
    if not ok:
        log.error("Pipeline aborted: init failed.")
        sys.exit(1)

    await _agent_scrape(settings, vault)
    _agent_apply(settings, live)
    _agent_persist(settings)
    _agent_notify(settings)
    log.info("Pipeline complete.")


async def run_retry(settings, platforms: list[str], live: bool) -> None:
    """Retry pipeline: targeted scrape + targeted apply."""
    vault = CryptoVault(settings.master_crypto_key)

    log.info("Retry pipeline — platforms: %s", platforms or "none")

    ok = _agent_init(settings, force_manual=False)
    if not ok:
        sys.exit(1)

    # Step 1: retry scraper for targeted platforms
    if platforms:
        await _agent_scrape(settings, vault, target_platforms=platforms)

    # Step 2: retry apply for unretried manual_review jobs
    unretried_jobs = run_state.get_unretried_jobs()
    target_ids = [j["id"] for j in unretried_jobs]
    if target_ids:
        log.info("Retrying %d manual_review job(s).", len(target_ids))
        _agent_apply(settings, live=live, target_job_ids=target_ids)
    else:
        log.info("No unretried manual_review jobs.")

    _agent_persist(settings)
    _agent_notify(settings)
    log.info("Retry pipeline complete.")


# ---------------------------------------------------------------------------
# Info commands
# ---------------------------------------------------------------------------

def cmd_check(settings) -> None:
    ran = run_state.did_run_today("scraper", expected_hour_ist=19)
    ts = run_state.load().get("agents", {}).get("scraper", {}).get("last_success_ts", "never")
    print(f"Today's 7 PM IST run: {'✓ completed' if ran else '✗ NOT run'} (last: {ts})")

    unretried_p = run_state.get_unretried_platforms()
    unretried_j = run_state.get_unretried_jobs()
    if unretried_p or unretried_j:
        print(f"\nUnretried skipped items:")
        for p in unretried_p:
            print(f"  platform: {p['platform']} — {p['reason']} at {p['ts']}")
        for j in unretried_j:
            print(f"  job: {j['company']} / {j['title']} — {j['reason']}")
        print("\nRun: python -m src.run_daily --retry-skipped to resolve all")


def cmd_status_summary() -> None:
    from collections import Counter
    rows = data_store.read_all()
    counts = Counter(r.get("status", "unknown") for r in rows)
    print(f"\nJob applications — {len(rows)} total\n")
    for status in ["scraped", "applied", "manual_review", "interview_scheduled", "offer", "rejected"]:
        print(f"  {status:<22} {counts.get(status, 0)}")

    unretried_p = run_state.get_unretried_platforms()
    unretried_j = run_state.get_unretried_jobs()
    if unretried_p or unretried_j:
        print(f"\nNeeds attention:")
        for p in unretried_p:
            print(f"  platform {p['platform']} skipped — {p['reason']}")
        for j in unretried_j:
            print(f"  job {j['company']} ({j['title']}) — {j['reason']}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Job Hunter — daily pipeline")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--live",    action="store_true", help="Actually submit applications")
    mode.add_argument("--dry-run", action="store_true", help="Scrape + filter only, no submit (default)")

    p.add_argument("--check",   action="store_true", help="Report whether today's 7 PM run happened")
    p.add_argument("--status-summary", action="store_true", help="Print per-status counts")
    p.add_argument("--only",    metavar="AGENT", help="Run a single agent: init|scraper|apply|persist|notify")
    p.add_argument("--force-accept-manual-edit", action="store_true", help="Re-baseline integrity hash")
    p.add_argument("--retry-skipped", action="store_true", help="Retry all unretried skipped platforms + jobs")
    p.add_argument("--retry-platform", metavar="NAME", help="Retry a single platform by name")
    return p


def main() -> None:
    args = build_parser().parse_args()

    # Info-only commands (no settings needed)
    if args.check:
        try:
            settings = load_settings()
        except ConfigError:
            pass
        cmd_check(None)
        return

    if args.status_summary:
        cmd_status_summary()
        return

    try:
        settings = load_settings()
    except ConfigError as e:
        log.error("Configuration error: %s", e)
        sys.exit(1)

    live = args.live

    if args.retry_skipped or args.retry_platform:
        platforms = []
        if args.retry_platform:
            platforms = [args.retry_platform]
        elif args.retry_skipped:
            platforms = [p["platform"] for p in run_state.get_unretried_platforms()]
        asyncio.run(run_retry(settings, platforms, live=True))
        return

    asyncio.run(run_pipeline(
        settings,
        live=live,
        only=args.only,
        force_manual=args.force_accept_manual_edit,
    ))


if __name__ == "__main__":
    main()
