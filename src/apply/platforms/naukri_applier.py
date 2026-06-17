"""Naukri applier.

Handles Naukri's native apply button + form (modal or redirect).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from .base_applier import BaseApplier, _KNOWN_ATS_PATTERNS

logger = logging.getLogger(__name__)

# Naukri apply button selectors (tried in order)
_APPLY_BUTTON_SELECTORS = [
    "button#apply-button",
    "button.apply-button",
    "a#apply-button",
    "button[data-ga-track*='apply']",
    ".apply-btn",
    "button:has-text('Apply')",
]

# Modal / form submit button selectors
_SUBMIT_SELECTORS = [
    "button[type='submit']",
    "button:has-text('Submit')",
    "button:has-text('Apply Now')",
    "button:has-text('Apply')",
]

# Common field label selectors in Naukri forms
_LABEL_SELECTORS = [
    "label",
    ".lbl",
    "[data-testid='label']",
]


class NaukriApplier(BaseApplier):
    """Apply to jobs via Naukri's apply flow."""

    platform = "naukri"

    def _detect_apply_type(
        self, page, url: str
    ) -> Literal["easy_apply", "external_form", "unknown_ats"]:
        """Detect whether the job uses Naukri's native apply or redirects to an ATS."""
        # Known ATS patterns
        for pattern in _KNOWN_ATS_PATTERNS:
            if pattern in url:
                return "unknown_ats"

        # Look for Naukri's native apply button
        for selector in _APPLY_BUTTON_SELECTORS:
            try:
                btn = page.query_selector(selector)
                if btn and btn.is_visible():
                    # Check if clicking it opens a modal vs redirecting externally
                    # Heuristic: if page URL is naukri.com, it's native
                    if "naukri.com" in (page.url or url):
                        return "easy_apply"
            except Exception:
                continue

        # Fallback — if we can see the page it's likely Naukri native
        if "naukri.com" in url:
            return "easy_apply"

        return "unknown_ats"

    def _run_apply_flow(
        self,
        page,
        job: dict,
        profile: dict,
        settings,
        live: bool,
    ) -> Literal["applied", "manual_review"]:
        """Click Naukri's Apply button, fill the form, submit (or dry-run log)."""
        # Click the apply button
        clicked = False
        for selector in _APPLY_BUTTON_SELECTORS:
            try:
                btn = page.query_selector(selector)
                if btn and btn.is_visible() and btn.is_enabled():
                    btn.click()
                    page.wait_for_timeout(2000)
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            logger.warning("No apply button found on Naukri page: %s", job.get("url"))
            return "manual_review"

        # Check if we were redirected to an external ATS after clicking Apply
        current_url = page.url or ""
        for pattern in _KNOWN_ATS_PATTERNS:
            if pattern in current_url:
                logger.info("Naukri redirected to external ATS (%s) — manual_review", pattern)
                return "manual_review"
        if "naukri.com" not in current_url and current_url.startswith("http"):
            logger.info("Naukri redirected to external URL %s — manual_review", current_url)
            return "manual_review"

        # Fill visible form fields
        self._fill_form_fields(page, profile)

        # Upload resume
        resume_path = Path(settings.resume_pdf) if settings.resume_pdf else None
        if resume_path:
            self._upload_resume(page, resume_path)

        # Submit or dry-run
        return self._submit_or_dryrun(page, job, profile, live)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _fill_form_fields(self, page, profile: dict) -> None:
        """Find labelled inputs and fill from profile / prompt user."""
        try:
            labels = page.query_selector_all(", ".join(_LABEL_SELECTORS))
        except Exception:
            return

        for label_el in labels:
            try:
                label_text: str = (label_el.text_content() or "").strip()
                if not label_text:
                    continue

                for_attr = label_el.get_attribute("for")
                if for_attr:
                    input_el = page.query_selector(f"#{for_attr}")
                else:
                    input_el = label_el.query_selector("input, textarea, select")

                if not input_el:
                    continue

                value = self._fill_field_interactive(page, input_el, label_text, profile)
                if not value:
                    continue

                tag = input_el.evaluate("el => el.tagName.toLowerCase()")
                if tag == "select":
                    try:
                        input_el.select_option(value=value)
                    except Exception:
                        pass
                else:
                    try:
                        input_el.fill(value)
                    except Exception:
                        try:
                            input_el.type(value)
                        except Exception:
                            pass
            except Exception as exc:
                logger.debug("Error filling Naukri field: %s", exc)
                continue

    def _submit_or_dryrun(
        self,
        page,
        job: dict,
        profile: dict,
        live: bool,
    ) -> Literal["applied", "manual_review"]:
        """Find the submit/apply button and submit, or log payload on dry-run."""
        for selector in _SUBMIT_SELECTORS:
            try:
                btn = page.query_selector(selector)
                if btn and btn.is_visible():
                    if not live:
                        self._log_submission_payload(job, profile)
                        logger.info(
                            "[DRY-RUN] Would submit Naukri apply for %s @ %s",
                            job.get("title"),
                            job.get("company"),
                        )
                        return "applied"
                    else:
                        btn.click()
                        page.wait_for_timeout(2000)
                        logger.info(
                            "Submitted Naukri apply for %s @ %s",
                            job.get("title"),
                            job.get("company"),
                        )
                        return "applied"
            except Exception:
                continue

        logger.warning(
            "No submit button found for Naukri job %s — manual_review", job.get("url")
        )
        return "manual_review"
