"""Generic fallback applier for any platform not covered by a dedicated applier.

Detects known ATS URLs (Greenhouse, Lever, Workday, iCIMS) and returns
"manual_review" for those.  For other external forms it attempts to fill
common field patterns but ultimately returns "manual_review" if uncertain.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from .base_applier import BaseApplier, _KNOWN_ATS_PATTERNS

logger = logging.getLogger(__name__)

# Common submit button patterns across generic ATS forms
_SUBMIT_SELECTORS = [
    "button[type='submit']",
    "input[type='submit']",
    "button:has-text('Submit')",
    "button:has-text('Apply Now')",
    "button:has-text('Apply')",
    "button:has-text('Send Application')",
]

# Common field label patterns on generic forms
_LABEL_SELECTORS = [
    "label",
    "[for]",
    ".field-label",
    ".form-label",
    "[data-field-label]",
]


class GenericApplier(BaseApplier):
    """Fallback applier for platforms without a dedicated implementation.

    Strategy:
    - Greenhouse / Lever / Workday / iCIMS URLs → always manual_review.
    - Other external forms → attempt field fill, return manual_review if unsure.
    """

    platform = "generic"

    def _detect_apply_type(
        self, page, url: str
    ) -> Literal["easy_apply", "external_form", "unknown_ats"]:
        """Check for known ATS patterns; otherwise treat as external_form."""
        current_url = page.url or url
        for pattern in _KNOWN_ATS_PATTERNS:
            if pattern in current_url:
                return "unknown_ats"
        # Any page we reached counts as an external_form attempt
        return "external_form"

    def _run_apply_flow(
        self,
        page,
        job: dict,
        profile: dict,
        settings,
        live: bool,
    ) -> Literal["applied", "manual_review"]:
        """Attempt generic form fill.  Returns manual_review for known ATS or on failure."""
        apply_type = self._detect_apply_type(page, job.get("url", ""))

        if apply_type == "unknown_ats":
            logger.info(
                "Known ATS detected for %s — manual_review", job.get("url")
            )
            return "manual_review"

        # Best-effort: fill common fields, upload resume
        filled_any = self._fill_common_fields(page, profile)
        resume_path = Path(settings.resume_pdf) if settings.resume_pdf else None
        if resume_path:
            self._upload_resume(page, resume_path)

        # Try to find a submit button
        submit_btn = None
        for selector in _SUBMIT_SELECTORS:
            try:
                btn = page.query_selector(selector)
                if btn and btn.is_visible():
                    submit_btn = btn
                    break
            except Exception:
                continue

        if submit_btn is None:
            logger.info(
                "No submit button found on generic form for %s — manual_review",
                job.get("url"),
            )
            return "manual_review"

        if not live:
            self._log_submission_payload(job, profile)
            logger.info(
                "[DRY-RUN] Would submit generic form for %s @ %s",
                job.get("title"),
                job.get("company"),
            )
            # We had all the fields but play it safe — return manual_review
            # for generic forms so the user confirms before live applies.
            return "manual_review"

        # Live: attempt submission but still return manual_review so the user
        # can confirm the outcome (generic forms may have unknown validation).
        try:
            submit_btn.click()
            page.wait_for_timeout(2000)
            logger.info(
                "Clicked submit on generic form for %s @ %s (outcome unverified)",
                job.get("title"),
                job.get("company"),
            )
        except Exception as exc:
            logger.warning("Generic form submit click failed: %s", exc)

        return "manual_review"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _fill_common_fields(self, page, profile: dict) -> bool:
        """Fill as many labelled inputs as possible from the profile.

        Returns True if at least one field was filled, False otherwise.
        """
        filled_count = 0
        try:
            labels = page.query_selector_all(", ".join(_LABEL_SELECTORS))
        except Exception:
            return False

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

                # Only auto-fill from known mappings on generic forms — do not
                # prompt the user for unknown fields (they'll handle it manually).
                learned: dict = profile.get("learned_mappings", {})
                profile_key = self._fuzzy_match_mapping(label_text, learned)
                if not profile_key or profile_key not in profile:
                    continue

                value = str(profile[profile_key]) if profile[profile_key] is not None else ""
                if not value:
                    continue

                tag = input_el.evaluate("el => el.tagName.toLowerCase()")
                if tag == "select":
                    try:
                        input_el.select_option(value=value)
                        filled_count += 1
                    except Exception:
                        pass
                else:
                    try:
                        input_el.fill(value)
                        filled_count += 1
                    except Exception:
                        try:
                            input_el.type(value)
                            filled_count += 1
                        except Exception:
                            pass
            except Exception as exc:
                logger.debug("Error filling generic field: %s", exc)
                continue

        logger.debug("GenericApplier filled %d fields", filled_count)
        return filled_count > 0
