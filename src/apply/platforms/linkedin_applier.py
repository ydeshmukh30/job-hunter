"""LinkedIn Easy Apply applier.

Handles the LinkedIn Easy Apply multi-step modal flow.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from .base_applier import BaseApplier, _KNOWN_ATS_PATTERNS

logger = logging.getLogger(__name__)

# LinkedIn Easy Apply button selectors (tried in order)
_EASY_APPLY_SELECTORS = [
    "button.jobs-apply-button",
    "button[aria-label*='Easy Apply']",
    "button[aria-label*='easy apply']",
]

# Selectors for the "Next" button inside the multi-step modal
_NEXT_BUTTON_SELECTORS = [
    "button[aria-label='Continue to next step']",
    "button[aria-label='Review your application']",
    "footer button.artdeco-button--primary",
]

# Submit button in the final modal step
_SUBMIT_BUTTON_SELECTORS = [
    "button[aria-label='Submit application']",
    "button[aria-label='submit application']",
    "footer button.artdeco-button--primary[type='submit']",
]

# Common field label selectors in the Easy Apply modal
_LABEL_SELECTORS = [
    "label",
    "[data-test-form-element-label]",
    ".fb-form-element__label",
]


class LinkedInApplier(BaseApplier):
    """Apply to jobs via LinkedIn Easy Apply modal."""

    platform = "linkedin"

    def _detect_apply_type(
        self, page, url: str
    ) -> Literal["easy_apply", "external_form", "unknown_ats"]:
        """Detect whether the job page has an Easy Apply button or an external link.

        If the page has an Easy Apply button → "easy_apply".
        If clicking apply opens an external URL / new tab → "external_form".
        For known ATS domains → "unknown_ats".
        """
        # Check for known ATS patterns in the current URL
        for pattern in _KNOWN_ATS_PATTERNS:
            if pattern in url:
                return "unknown_ats"

        # Try to find the Easy Apply button
        for selector in _EASY_APPLY_SELECTORS:
            try:
                btn = page.query_selector(selector)
                if btn:
                    logger.debug("Detected Easy Apply button via selector: %s", selector)
                    return "easy_apply"
            except Exception:
                continue

        # Look for an external apply link (opens new tab or leaves linkedin.com)
        try:
            ext_apply = page.query_selector(
                "a.jobs-apply-button, a[data-job-id][href*='apply']"
            )
            if ext_apply:
                href = ext_apply.get_attribute("href") or ""
                if "linkedin.com" not in href:
                    return "external_form"
        except Exception:
            pass

        # Default to unknown when we cannot confidently classify
        return "unknown_ats"

    def _run_apply_flow(
        self,
        page,
        job: dict,
        profile: dict,
        settings,
        live: bool,
    ) -> Literal["applied", "manual_review"]:
        """Click Easy Apply, fill the multi-step modal, submit (or dry-run log)."""
        apply_type = self._detect_apply_type(page, job["url"])
        if apply_type != "easy_apply":
            return "manual_review"

        # Click the Easy Apply button
        for selector in _EASY_APPLY_SELECTORS:
            try:
                btn = page.query_selector(selector)
                if btn:
                    btn.click()
                    page.wait_for_timeout(1500)
                    break
            except Exception:
                continue
        else:
            logger.warning("Easy Apply button not clickable for %s", job["url"])
            return "manual_review"

        # Navigate multi-step modal: fill each page, click Next, repeat until Submit
        max_steps = 10
        for step in range(max_steps):
            logger.debug("Easy Apply modal step %d", step + 1)

            # Fill visible form fields on this step
            self._fill_modal_fields(page, profile, settings)

            # Upload resume if a file input is present
            resume_path = Path(settings.resume_pdf) if settings.resume_pdf else None
            if resume_path:
                self._upload_resume(page, resume_path)

            # Try Submit first (final step)
            submitted = self._try_submit(page, job, profile, live)
            if submitted is not None:
                return submitted

            # Click Next to advance to the next modal step
            advanced = self._try_next(page)
            if not advanced:
                # No Next or Submit found — modal may have closed or errored
                logger.warning("No Next/Submit button found on step %d — manual_review", step + 1)
                return "manual_review"

        logger.warning("Exceeded max steps in Easy Apply modal — manual_review")
        return "manual_review"

    # ------------------------------------------------------------------
    # Modal helpers
    # ------------------------------------------------------------------

    def _fill_modal_fields(self, page, profile: dict, settings) -> None:
        """Find all labelled inputs in the modal and fill them from profile."""
        # Collect all label elements visible in the current modal step
        try:
            labels = page.query_selector_all(", ".join(_LABEL_SELECTORS))
        except Exception:
            return

        for label_el in labels:
            try:
                label_text: str = (label_el.text_content() or "").strip()
                if not label_text:
                    continue

                # Find the associated input
                for_attr = label_el.get_attribute("for")
                if for_attr:
                    input_el = page.query_selector(f"#{for_attr}")
                else:
                    # Try sibling/parent input
                    input_el = label_el.query_selector(
                        "input, textarea, select"
                    ) or label_el.evaluate_handle(
                        "el => el.closest('.fb-form-element') && "
                        "el.closest('.fb-form-element').querySelector('input, textarea, select')"
                    )

                if not input_el:
                    continue

                value = self._fill_field_interactive(
                    page, input_el, label_text, profile
                )
                if not value:
                    continue

                # Fill the input
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
                logger.debug("Error filling field: %s", exc)
                continue

    def _try_next(self, page) -> bool:
        """Click the Next button if present.  Returns True if clicked."""
        for selector in _NEXT_BUTTON_SELECTORS:
            try:
                btn = page.query_selector(selector)
                if btn and btn.is_visible() and btn.is_enabled():
                    btn.click()
                    page.wait_for_timeout(1000)
                    return True
            except Exception:
                continue
        return False

    def _try_submit(
        self,
        page,
        job: dict,
        profile: dict,
        live: bool,
    ) -> Literal["applied", "manual_review"] | None:
        """Attempt to find and click the Submit button.

        Returns "applied" / "manual_review" if submission was handled,
        or None if no Submit button was found (caller should try Next instead).
        """
        for selector in _SUBMIT_BUTTON_SELECTORS:
            try:
                btn = page.query_selector(selector)
                if btn and btn.is_visible():
                    if not live:
                        self._log_submission_payload(job, profile)
                        logger.info(
                            "[DRY-RUN] Would submit Easy Apply for %s @ %s",
                            job.get("title"),
                            job.get("company"),
                        )
                        # Dismiss modal without submitting
                        try:
                            page.keyboard.press("Escape")
                        except Exception:
                            pass
                        return "applied"
                    else:
                        btn.click()
                        page.wait_for_timeout(2000)
                        logger.info(
                            "Submitted Easy Apply for %s @ %s",
                            job.get("title"),
                            job.get("company"),
                        )
                        return "applied"
            except Exception:
                continue
        return None
