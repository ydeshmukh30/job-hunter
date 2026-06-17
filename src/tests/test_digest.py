"""Tests for src/notify/digest.py."""

from __future__ import annotations

import smtplib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.notify.digest import build_digest, send_digest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# 2 applied, 1 manual_review, 1 interview_scheduled, 1 rejected
DIGEST_ROWS = [
    {
        "id": "r001",
        "title": "Senior Backend Engineer",
        "company": "Razorpay",
        "platform": "linkedin",
        "url": "https://linkedin.com/jobs/001",
        "apply_type": "easy_apply",
        "status": "applied",
        "ctc": "30-50 LPA",
        "yoe_required": "3-7",
        "location": "Bengaluru",
        "applied_at": "2026-06-17T19:10:00+05:30",
        "interview_date": "",
        "next_steps": "",
        "last_activity": "2026-06-17T19:10:00+05:30",
    },
    {
        "id": "r002",
        "title": "SDE 3",
        "company": "Groww",
        "platform": "naukri",
        "url": "https://naukri.com/jobs/002",
        "apply_type": "easy_apply",
        "status": "applied",
        "ctc": "40-60 LPA",
        "yoe_required": "4-8",
        "location": "Bengaluru",
        "applied_at": "2026-06-17T19:15:00+05:30",
        "interview_date": "",
        "next_steps": "",
        "last_activity": "2026-06-17T19:15:00+05:30",
    },
    {
        "id": "r003",
        "title": "Senior Software Engineer",
        "company": "PhonePe",
        "platform": "wellfound",
        "url": "https://wellfound.com/jobs/003",
        "apply_type": "external_form",
        "status": "manual_review",
        "ctc": "",
        "yoe_required": "5+",
        "location": "Pune",
        "applied_at": "",
        "interview_date": "",
        "next_steps": "",
        "last_activity": "2026-06-17T19:20:00+05:30",
    },
    {
        "id": "r004",
        "title": "Lead Engineer",
        "company": "Zepto",
        "platform": "linkedin",
        "url": "https://linkedin.com/jobs/004",
        "apply_type": "easy_apply",
        "status": "interview_scheduled",
        "ctc": "50-70 LPA",
        "yoe_required": "4-8",
        "location": "Hyderabad",
        "applied_at": "2026-06-10T10:00:00+05:30",
        "interview_date": "2026-06-20T11:00:00+05:30",
        "next_steps": "",
        "last_activity": "2026-06-17T10:00:00+05:30",
    },
    {
        "id": "r005",
        "title": "Staff Engineer",
        "company": "Stripe",
        "platform": "indeed",
        "url": "https://indeed.com/jobs/005",
        "apply_type": "external_form",
        "status": "rejected",
        "ctc": "$180k",
        "yoe_required": "7+",
        "location": "Remote",
        "applied_at": "2026-06-05T10:00:00+05:30",
        "interview_date": "",
        "next_steps": "",
        "last_activity": "2026-06-15T10:00:00+05:30",
    },
]

SKIPPED_WITH_ITEMS = {
    "platforms": [
        {
            "platform": "linkedin",
            "reason": "LoginError",
            "ts": "2026-06-17T19:03:00+05:30",
            "retried": False,
        }
    ],
    "jobs": [
        {
            "id": "r003",
            "company": "PhonePe",
            "title": "Senior Software Engineer",
            "url": "https://wellfound.com/jobs/003",
            "reason": "unknown_ats:greenhouse",
            "ts": "2026-06-17T19:20:00+05:30",
            "retried": False,
        }
    ],
}

SETTINGS = SimpleNamespace(
    smtp_host="smtp.gmail.com",
    smtp_port=587,
    gmail_app_password="test_app_password",
    digest_recipient="yashdeshmukh7@gmail.com",
)


# ---------------------------------------------------------------------------
# Test 1 — Full digest with skipped items
# ---------------------------------------------------------------------------


class TestBuildDigestWithSkipped:
    def test_needs_your_attention_section_present(self):
        html = build_digest(DIGEST_ROWS, SKIPPED_WITH_ITEMS)
        assert "Needs Your Attention" in html

    def test_skipped_platform_name_in_html(self):
        html = build_digest(DIGEST_ROWS, SKIPPED_WITH_ITEMS)
        assert "linkedin" in html

    def test_retry_platform_command_in_html(self):
        html = build_digest(DIGEST_ROWS, SKIPPED_WITH_ITEMS)
        assert "python -m src.run_daily --retry-platform linkedin" in html

    def test_retry_skipped_command_in_html(self):
        html = build_digest(DIGEST_ROWS, SKIPPED_WITH_ITEMS)
        assert "python -m src.run_daily --retry-skipped" in html

    def test_manual_review_company_present(self):
        html = build_digest(DIGEST_ROWS, SKIPPED_WITH_ITEMS)
        # PhonePe is both in rows (manual_review) and in skipped.jobs
        assert "PhonePe" in html

    def test_pipeline_funnel_present(self):
        html = build_digest(DIGEST_ROWS, SKIPPED_WITH_ITEMS)
        assert "Pipeline Funnel" in html

    def test_all_status_labels_present(self):
        html = build_digest(DIGEST_ROWS, SKIPPED_WITH_ITEMS)
        for label in ("Applied", "Manual Review", "Interview", "Offer", "Rejected"):
            assert label in html, f"Label '{label}' missing from digest"

    def test_header_summary_counts(self):
        html = build_digest(DIGEST_ROWS, SKIPPED_WITH_ITEMS)
        # 5 total rows in the fixture
        assert "5" in html

    def test_footer_generated_by(self):
        html = build_digest(DIGEST_ROWS, SKIPPED_WITH_ITEMS)
        assert "Generated by job-hunter" in html

    def test_valid_html_structure(self):
        html = build_digest(DIGEST_ROWS, SKIPPED_WITH_ITEMS)
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html


# ---------------------------------------------------------------------------
# Test 2 — Zero rows, empty skipped → no "Needs Your Attention" section
# ---------------------------------------------------------------------------


class TestBuildDigestEmpty:
    def test_no_attention_section_when_empty(self):
        html = build_digest([], {"platforms": [], "jobs": []})
        assert "Needs Your Attention" not in html

    def test_footer_still_present(self):
        html = build_digest([], {"platforms": [], "jobs": []})
        assert "Generated by job-hunter" in html

    def test_funnel_present_with_zero_counts(self):
        html = build_digest([], {"platforms": [], "jobs": []})
        assert "Pipeline Funnel" in html

    def test_valid_html_structure(self):
        html = build_digest([], {"platforms": [], "jobs": []})
        assert "<!DOCTYPE html>" in html


# ---------------------------------------------------------------------------
# Test 3 — Skipped items with retried=True → not shown in digest
# ---------------------------------------------------------------------------


class TestBuildDigestSkippedRetried:
    def test_retried_platform_not_shown(self):
        skipped = {
            "platforms": [
                {
                    "platform": "naukri",
                    "reason": "CAPTCHA",
                    "ts": "2026-06-16T19:03:00+05:30",
                    "retried": True,  # already retried
                }
            ],
            "jobs": [],
        }
        html = build_digest(DIGEST_ROWS, skipped)
        # naukri is not in any row title/company — it would only appear from the skipped block
        # "Needs Your Attention" only renders for non-retried items or manual_review rows
        # DIGEST_ROWS has 1 manual_review row, so attention block IS present
        # but the retried platform (naukri) must not appear in the skipped platforms table
        assert "python -m src.run_daily --retry-platform naukri" not in html

    def test_retried_job_not_shown_in_skipped_table(self):
        skipped = {
            "platforms": [],
            "jobs": [
                {
                    "id": "r999",
                    "company": "Flipkart",
                    "title": "SDE 2",
                    "url": "https://flipkart.com/jobs/999",
                    "reason": "unknown_ats",
                    "ts": "2026-06-16T19:20:00+05:30",
                    "retried": True,  # already retried
                }
            ],
        }
        html = build_digest([], skipped)
        # No rows at all, retried job → no attention section at all
        assert "Needs Your Attention" not in html
        assert "Flipkart" not in html

    def test_unretried_items_still_show_even_if_mix(self):
        skipped = {
            "platforms": [
                {
                    "platform": "indeed",
                    "reason": "NetworkError",
                    "ts": "2026-06-17T19:05:00+05:30",
                    "retried": False,
                },
                {
                    "platform": "hirist",
                    "reason": "CAPTCHA",
                    "ts": "2026-06-16T19:05:00+05:30",
                    "retried": True,
                },
            ],
            "jobs": [],
        }
        html = build_digest([], skipped)
        assert "Needs Your Attention" in html
        assert "indeed" in html
        assert "python -m src.run_daily --retry-platform indeed" in html
        # hirist was retried — must not appear in action column
        assert "python -m src.run_daily --retry-platform hirist" not in html


# ---------------------------------------------------------------------------
# Test 4 — send_digest mocks smtplib.SMTP
# ---------------------------------------------------------------------------


class TestSendDigest:
    def test_sendmail_called_once_with_correct_recipient(self):
        html = build_digest(DIGEST_ROWS, SKIPPED_WITH_ITEMS)

        mock_smtp_instance = MagicMock()

        with patch("src.notify.digest.smtplib.SMTP") as mock_smtp_class:
            mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_smtp_instance)
            mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

            send_digest(html, SETTINGS)

        mock_smtp_instance.sendmail.assert_called_once()
        call_args = mock_smtp_instance.sendmail.call_args
        # call_args is (from_addr, to_addr, msg_string)
        from_addr, to_addr, _ = call_args[0]
        assert to_addr == SETTINGS.digest_recipient

    def test_smtp_login_uses_app_password(self):
        html = "<html><body>test</body></html>"

        mock_smtp_instance = MagicMock()

        with patch("src.notify.digest.smtplib.SMTP") as mock_smtp_class:
            mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_smtp_instance)
            mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

            send_digest(html, SETTINGS)

        mock_smtp_instance.login.assert_called_once_with(
            SETTINGS.digest_recipient,
            SETTINGS.gmail_app_password,
        )

    def test_smtp_starttls_called(self):
        html = "<html><body>test</body></html>"

        mock_smtp_instance = MagicMock()

        with patch("src.notify.digest.smtplib.SMTP") as mock_smtp_class:
            mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_smtp_instance)
            mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

            send_digest(html, SETTINGS)

        mock_smtp_instance.starttls.assert_called_once()

    def test_smtp_constructor_called_with_host_and_port(self):
        html = "<html><body>test</body></html>"

        mock_smtp_instance = MagicMock()

        with patch("src.notify.digest.smtplib.SMTP") as mock_smtp_class:
            mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_smtp_instance)
            mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

            send_digest(html, SETTINGS)

        mock_smtp_class.assert_called_once_with(SETTINGS.smtp_host, SETTINGS.smtp_port)
