"""Standalone interview-brief poller.

Run via cron at 9 PM IST daily::

    30 15 * * *  cd /path/to/job-hunter && python -m src.run_brief_poller

Generates AI-powered interview prep briefs for every interview scheduled
for the next calendar day (IST), and emails each brief to the configured
recipient.  Respects the ``daily_llm_usd_cap`` hard cap — stops processing
remaining interviews and sends a cap-notice email if the cap is reached.
"""

from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

from src.notify.brief import generate_brief, send_brief

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)

IST = ZoneInfo("Asia/Kolkata")

# Estimated USD cost per brief call.
# ~1500 input tokens + ~800 output tokens for claude-sonnet-4-6 pricing.
_BRIEF_ESTIMATED_USD: float = 0.006


# ---------------------------------------------------------------------------
# Cap-notice helper
# ---------------------------------------------------------------------------


def _send_cap_notice(settings, remaining: int) -> None:
    """Send a plain-text cap-notice email when the daily LLM spend cap is hit."""
    subject = "Job Hunter — Daily LLM cap reached"
    body = (
        f"The daily LLM spend cap of ${settings.daily_llm_usd_cap:.2f} has been reached.\n\n"
        f"{remaining} interview brief(s) could not be generated today.\n\n"
        "Increase DAILY_LLM_USD_CAP in your .env file and re-run "
        "python -m src.run_brief_poller if you need the missing briefs."
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Job Hunter <{settings.digest_recipient}>"
    msg["To"] = settings.digest_recipient
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(settings.digest_recipient, settings.gmail_app_password)
            server.sendmail(
                settings.digest_recipient,
                settings.digest_recipient,
                msg.as_string(),
            )
        logging.info("Cap-notice email sent.")
    except Exception as exc:  # pragma: no cover — SMTP failures are non-fatal
        logging.warning(f"Could not send cap-notice email: {exc}")


# ---------------------------------------------------------------------------
# Main poll function
# ---------------------------------------------------------------------------


def poll(settings, run_state_module, data_store_module) -> None:
    """Check for tomorrow's interviews and email a brief for each one.

    Parameters
    ----------
    settings:
        A :class:`src.config.Settings` instance.
    run_state_module:
        Module with ``reset_daily_spend_if_new_day``, ``get_llm_spend_today``,
        and ``add_llm_spend`` callables (i.e. ``src.common.run_state``).
    data_store_module:
        Module with a ``read_by_status(status)`` callable
        (i.e. ``src.common.data_store``).
    """
    run_state_module.reset_daily_spend_if_new_day()

    now_ist = datetime.now(IST)
    tomorrow = (now_ist + timedelta(days=1)).date()

    logging.info(f"Brief poller started — looking for interviews on {tomorrow}")

    interviews = data_store_module.read_by_status("interview_scheduled")

    next_day: list[dict] = []
    for job in interviews:
        interview_date_raw = job.get("interview_date", "")
        if not interview_date_raw:
            continue
        try:
            interview_date = (
                datetime.fromisoformat(interview_date_raw)
                .astimezone(IST)
                .date()
            )
        except (ValueError, TypeError):
            logging.warning(
                f"Unparseable interview_date for {job.get('company', '?')}: "
                f"{interview_date_raw!r} — skipping"
            )
            continue
        if interview_date == tomorrow:
            next_day.append(job)

    logging.info(f"Found {len(next_day)} interview(s) scheduled for tomorrow.")

    for i, job in enumerate(next_day):
        interview_dt = datetime.fromisoformat(job["interview_date"])

        spend = run_state_module.get_llm_spend_today()
        if spend >= settings.daily_llm_usd_cap:
            remaining = len(next_day) - i
            logging.warning(
                f"Daily LLM cap ${settings.daily_llm_usd_cap:.2f} reached "
                f"(spent ${spend:.4f}). {remaining} brief(s) skipped."
            )
            _send_cap_notice(settings, remaining=remaining)
            break

        try:
            logging.info(f"Generating brief for {job['company']} — {job['title']}")
            html = generate_brief(job, settings)
            send_brief(html, interview_dt, job, settings)
            run_state_module.add_llm_spend(_BRIEF_ESTIMATED_USD)
            logging.info(f"Brief sent for {job['company']}.")
        except Exception as e:
            logging.warning(f"Brief failed for {job['company']}: {e}")
            continue

    logging.info("Brief poller finished.")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    from src.config import load as load_settings
    from src.common import run_state, data_store

    poll(load_settings(), run_state, data_store)
