"""Tests for src/notify/brief.py and src/run_brief_poller.py."""

from __future__ import annotations

import io
import textwrap
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch
from zoneinfo import ZoneInfo

import pytest

IST = ZoneInfo("Asia/Kolkata")

# ---------------------------------------------------------------------------
# Shared settings fixture
# ---------------------------------------------------------------------------

SETTINGS = SimpleNamespace(
    smtp_host="smtp.gmail.com",
    smtp_port=587,
    gmail_app_password="test_app_password",
    digest_recipient="yashdeshmukh7@gmail.com",
    anthropic_api_key="sk-ant-test",
    anthropic_model="claude-sonnet-4-6",
    daily_llm_usd_cap=1.00,
    resume_pdf=Path(__file__).parent.parent.parent / "config" / "resume.pdf",
)

# ---------------------------------------------------------------------------
# Shared job fixture (interview tomorrow at 11 AM IST from 2026-06-17)
# ---------------------------------------------------------------------------

_NOW_IST = datetime(2026, 6, 17, 21, 0, 0, tzinfo=IST)  # 9 PM IST

JOB_TOMORROW = {
    "id": "bbb-001",
    "title": "Senior Backend Engineer",
    "company": "Groww",
    "platform": "linkedin",
    "url": "https://linkedin.com/jobs/bbb-001",
    "apply_type": "easy_apply",
    "status": "interview_scheduled",
    "ctc": "40-60 LPA",
    "yoe_required": "3-7",
    "location": "Bengaluru",
    "applied_at": "2026-06-10T10:00:00+05:30",
    "interview_date": "2026-06-18T11:00:00+05:30",  # tomorrow
    "next_steps": "",
    "last_activity": "2026-06-17T10:00:00+05:30",
}

JOB_TODAY = {
    **JOB_TOMORROW,
    "id": "bbb-002",
    "company": "Zepto",
    "interview_date": "2026-06-17T15:00:00+05:30",  # today
}


# ---------------------------------------------------------------------------
# Helper: build a mock Anthropic message response
# ---------------------------------------------------------------------------


def _make_mock_anthropic_response(text: str) -> MagicMock:
    block = MagicMock()
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


# ---------------------------------------------------------------------------
# Test 1 — extract_resume_text with a real tiny PDF
# ---------------------------------------------------------------------------


class TestExtractResumeText:
    def test_extract_real_resume_pdf(self):
        """extract_resume_text should return non-empty text from the real resume."""
        from src.notify.brief import extract_resume_text

        resume_path = Path(__file__).parent.parent.parent / "config" / "resume.pdf"
        if not resume_path.exists():
            pytest.skip("config/resume.pdf not present — skipping real-PDF test")

        text = extract_resume_text(resume_path)
        assert isinstance(text, str)
        assert len(text) > 0

    def test_extract_returns_string(self):
        """extract_resume_text must return a str even on a minimal PDF."""
        from src.notify.brief import extract_resume_text

        resume_path = Path(__file__).parent.parent.parent / "config" / "resume.pdf"
        if not resume_path.exists():
            pytest.skip("config/resume.pdf not present")

        result = extract_resume_text(resume_path)
        assert isinstance(result, str)

    def test_extract_mocked_pdfplumber(self):
        """Verify pdfplumber pages are concatenated correctly."""
        from src.notify.brief import extract_resume_text

        fake_page_1 = MagicMock()
        fake_page_1.extract_text.return_value = "Page one content."
        fake_page_2 = MagicMock()
        fake_page_2.extract_text.return_value = "Page two content."
        fake_page_3 = MagicMock()
        fake_page_3.extract_text.return_value = None  # pdfplumber can return None

        mock_pdf = MagicMock()
        mock_pdf.pages = [fake_page_1, fake_page_2, fake_page_3]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with patch("src.notify.brief.pdfplumber.open", return_value=mock_pdf):
            result = extract_resume_text(Path("/fake/resume.pdf"))

        assert "Page one content." in result
        assert "Page two content." in result
        # None pages are treated as empty string
        # strip() on the joined text removes the trailing newline
        assert result == "Page one content.\nPage two content."


# ---------------------------------------------------------------------------
# Test 2 — generate_brief mocks Anthropic API
# ---------------------------------------------------------------------------


class TestGenerateBrief:
    def _make_settings_with_fake_pdf(self, fake_resume_text: str):
        """Return settings + patch pdfplumber to yield fake_resume_text."""
        settings = SimpleNamespace(**vars(SETTINGS))
        settings.resume_pdf = Path("/fake/resume.pdf")
        return settings, fake_resume_text

    def test_prompt_contains_resume_marker(self):
        from src.notify.brief import generate_brief

        settings, resume_text = self._make_settings_with_fake_pdf(
            "Yash Deshmukh — Senior Backend Engineer\nKafka, Cassandra, Java"
        )

        mock_response = _make_mock_anthropic_response("Here is your brief.")

        mock_page = MagicMock()
        mock_page.extract_text.return_value = resume_text
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with patch("src.notify.brief.pdfplumber.open", return_value=mock_pdf):
            with patch("src.notify.brief.anthropic.Anthropic") as mock_anthropic_cls:
                mock_client = MagicMock()
                mock_client.messages.create.return_value = mock_response
                mock_anthropic_cls.return_value = mock_client

                html = generate_brief(JOB_TOMORROW, settings)

        # Verify the prompt sent to Anthropic contained the resume marker
        create_call = mock_client.messages.create.call_args
        messages_arg = create_call.kwargs.get("messages") or create_call[1].get("messages") or create_call[0][2]
        # Extract content from whatever form messages was passed
        if isinstance(messages_arg, list):
            prompt_content = messages_arg[0]["content"]
        else:
            prompt_content = str(messages_arg)

        assert "=== YASH'S RESUME (plain text) ===" in prompt_content

    def test_prompt_contains_company_name(self):
        from src.notify.brief import generate_brief

        settings = SimpleNamespace(**vars(SETTINGS))
        settings.resume_pdf = Path("/fake/resume.pdf")

        resume_text = "Yash Deshmukh — Senior Backend Engineer"
        mock_response = _make_mock_anthropic_response("Brief content here.")

        mock_page = MagicMock()
        mock_page.extract_text.return_value = resume_text
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with patch("src.notify.brief.pdfplumber.open", return_value=mock_pdf):
            with patch("src.notify.brief.anthropic.Anthropic") as mock_anthropic_cls:
                mock_client = MagicMock()
                mock_client.messages.create.return_value = mock_response
                mock_anthropic_cls.return_value = mock_client

                html = generate_brief(JOB_TOMORROW, settings)

        create_call = mock_client.messages.create.call_args
        # Pull out the messages list regardless of how kwargs were passed
        kwargs = create_call.kwargs if create_call.kwargs else create_call[1]
        args = create_call.args if create_call.args else create_call[0]

        messages = kwargs.get("messages") or (args[2] if len(args) > 2 else None)
        if messages is None:
            # Try positional fallback
            messages = create_call[1].get("messages", create_call[0])

        prompt_text = str(messages)
        assert "Groww" in prompt_text

    def test_returned_html_is_non_empty(self):
        from src.notify.brief import generate_brief

        settings = SimpleNamespace(**vars(SETTINGS))
        settings.resume_pdf = Path("/fake/resume.pdf")

        resume_text = "Yash Deshmukh — Java, Kafka"
        mock_response = _make_mock_anthropic_response(
            "1. System design topics\n2. Deep-dive questions\n3. Resume alignment"
        )

        mock_page = MagicMock()
        mock_page.extract_text.return_value = resume_text
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with patch("src.notify.brief.pdfplumber.open", return_value=mock_pdf):
            with patch("src.notify.brief.anthropic.Anthropic") as mock_anthropic_cls:
                mock_client = MagicMock()
                mock_client.messages.create.return_value = mock_response
                mock_anthropic_cls.return_value = mock_client

                html = generate_brief(JOB_TOMORROW, settings)

        assert isinstance(html, str)
        assert len(html) > 0
        assert "<!DOCTYPE html>" in html

    def test_anthropic_called_with_correct_model(self):
        from src.notify.brief import generate_brief

        settings = SimpleNamespace(**vars(SETTINGS))
        settings.resume_pdf = Path("/fake/resume.pdf")

        resume_text = "Yash Deshmukh"
        mock_response = _make_mock_anthropic_response("Content.")

        mock_page = MagicMock()
        mock_page.extract_text.return_value = resume_text
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with patch("src.notify.brief.pdfplumber.open", return_value=mock_pdf):
            with patch("src.notify.brief.anthropic.Anthropic") as mock_anthropic_cls:
                mock_client = MagicMock()
                mock_client.messages.create.return_value = mock_response
                mock_anthropic_cls.return_value = mock_client

                generate_brief(JOB_TOMORROW, settings)

        create_kwargs = mock_client.messages.create.call_args.kwargs
        assert create_kwargs.get("model") == settings.anthropic_model
        assert create_kwargs.get("max_tokens") == 2000


# ---------------------------------------------------------------------------
# Test 3 — Brief poller: 1 interview tomorrow → generate_brief and add_llm_spend called once
# ---------------------------------------------------------------------------


class TestBriefPollerTomorrow:
    def _make_modules(self, jobs: list[dict], spend_today: float = 0.0):
        run_state = MagicMock()
        run_state.get_llm_spend_today.return_value = spend_today
        data_store = MagicMock()
        data_store.read_by_status.return_value = jobs
        return run_state, data_store

    def test_generate_brief_called_once_for_tomorrow(self):
        from src.run_brief_poller import poll

        run_state, data_store = self._make_modules([JOB_TOMORROW])

        mock_response = _make_mock_anthropic_response("Brief content.")
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Yash Deshmukh resume text"
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        mock_smtp = MagicMock()

        now_ist = datetime(2026, 6, 17, 21, 0, 0, tzinfo=IST)

        with patch("src.run_brief_poller.datetime") as mock_dt:
            mock_dt.now.return_value = now_ist
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            with patch("src.notify.brief.pdfplumber.open", return_value=mock_pdf):
                with patch("src.notify.brief.anthropic.Anthropic") as mock_anthropic_cls:
                    mock_client = MagicMock()
                    mock_client.messages.create.return_value = mock_response
                    mock_anthropic_cls.return_value = mock_client
                    with patch("src.notify.brief.smtplib.SMTP") as mock_smtp_cls:
                        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
                        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

                        poll(SETTINGS, run_state, data_store)

        mock_client.messages.create.assert_called_once()
        run_state.add_llm_spend.assert_called_once()

    def test_add_llm_spend_called_with_correct_amount(self):
        from src.run_brief_poller import poll, _BRIEF_ESTIMATED_USD

        run_state, data_store = self._make_modules([JOB_TOMORROW])

        mock_response = _make_mock_anthropic_response("Brief content.")
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Resume text"
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        mock_smtp = MagicMock()
        now_ist = datetime(2026, 6, 17, 21, 0, 0, tzinfo=IST)

        with patch("src.run_brief_poller.datetime") as mock_dt:
            mock_dt.now.return_value = now_ist
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            with patch("src.notify.brief.pdfplumber.open", return_value=mock_pdf):
                with patch("src.notify.brief.anthropic.Anthropic") as mock_anthropic_cls:
                    mock_client = MagicMock()
                    mock_client.messages.create.return_value = mock_response
                    mock_anthropic_cls.return_value = mock_client
                    with patch("src.notify.brief.smtplib.SMTP") as mock_smtp_cls:
                        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
                        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

                        poll(SETTINGS, run_state, data_store)

        run_state.add_llm_spend.assert_called_once_with(_BRIEF_ESTIMATED_USD)


# ---------------------------------------------------------------------------
# Test 4 — Interview today (not tomorrow) → generate_brief NOT called
# ---------------------------------------------------------------------------


class TestBriefPollerToday:
    def test_generate_brief_not_called_for_today_interview(self):
        from src.run_brief_poller import poll

        run_state = MagicMock()
        run_state.get_llm_spend_today.return_value = 0.0
        data_store = MagicMock()
        data_store.read_by_status.return_value = [JOB_TODAY]

        now_ist = datetime(2026, 6, 17, 21, 0, 0, tzinfo=IST)

        with patch("src.run_brief_poller.datetime") as mock_dt:
            mock_dt.now.return_value = now_ist
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            with patch("src.notify.brief.anthropic.Anthropic") as mock_anthropic_cls:
                mock_client = MagicMock()
                mock_anthropic_cls.return_value = mock_client

                poll(SETTINGS, run_state, data_store)

        mock_client.messages.create.assert_not_called()
        run_state.add_llm_spend.assert_not_called()


# ---------------------------------------------------------------------------
# Test 5 — LLM spend already at cap → generate_brief NOT called, cap-notice sent
# ---------------------------------------------------------------------------


class TestBriefPollerCapReached:
    def test_generate_brief_not_called_when_at_cap(self):
        from src.run_brief_poller import poll

        run_state = MagicMock()
        run_state.get_llm_spend_today.return_value = 1.00  # exactly at cap
        data_store = MagicMock()
        data_store.read_by_status.return_value = [JOB_TOMORROW]

        now_ist = datetime(2026, 6, 17, 21, 0, 0, tzinfo=IST)

        mock_smtp = MagicMock()

        with patch("src.run_brief_poller.datetime") as mock_dt:
            mock_dt.now.return_value = now_ist
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            with patch("src.notify.brief.anthropic.Anthropic") as mock_anthropic_cls:
                mock_client = MagicMock()
                mock_anthropic_cls.return_value = mock_client
                with patch("src.run_brief_poller.smtplib.SMTP") as mock_smtp_cls:
                    mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
                    mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

                    poll(SETTINGS, run_state, data_store)

        mock_client.messages.create.assert_not_called()

    def test_cap_notice_email_sent_when_at_cap(self):
        from src.run_brief_poller import poll

        run_state = MagicMock()
        run_state.get_llm_spend_today.return_value = 1.00
        data_store = MagicMock()
        data_store.read_by_status.return_value = [JOB_TOMORROW]

        now_ist = datetime(2026, 6, 17, 21, 0, 0, tzinfo=IST)

        mock_smtp = MagicMock()

        with patch("src.run_brief_poller.datetime") as mock_dt:
            mock_dt.now.return_value = now_ist
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            with patch("src.notify.brief.anthropic.Anthropic"):
                with patch("src.run_brief_poller.smtplib.SMTP") as mock_smtp_cls:
                    mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
                    mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

                    poll(SETTINGS, run_state, data_store)

        # Cap-notice SMTP call should have been made
        mock_smtp.sendmail.assert_called_once()

    def test_add_llm_spend_not_called_when_at_cap(self):
        from src.run_brief_poller import poll

        run_state = MagicMock()
        run_state.get_llm_spend_today.return_value = 1.00
        data_store = MagicMock()
        data_store.read_by_status.return_value = [JOB_TOMORROW]

        now_ist = datetime(2026, 6, 17, 21, 0, 0, tzinfo=IST)

        mock_smtp = MagicMock()

        with patch("src.run_brief_poller.datetime") as mock_dt:
            mock_dt.now.return_value = now_ist
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            with patch("src.notify.brief.anthropic.Anthropic"):
                with patch("src.run_brief_poller.smtplib.SMTP") as mock_smtp_cls:
                    mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
                    mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

                    poll(SETTINGS, run_state, data_store)

        run_state.add_llm_spend.assert_not_called()

    def test_cap_exceeded_mid_run_stops_remaining(self):
        """With 3 jobs tomorrow but cap hit after 1st, only 1 brief sent."""
        from src.run_brief_poller import poll

        job_a = {**JOB_TOMORROW, "id": "cap-001", "company": "Alpha"}
        job_b = {**JOB_TOMORROW, "id": "cap-002", "company": "Beta"}
        job_c = {**JOB_TOMORROW, "id": "cap-003", "company": "Gamma"}

        call_count = 0

        def spend_side_effect():
            nonlocal call_count
            call_count += 1
            # first call: under cap; second call: at cap
            if call_count <= 1:
                return 0.994
            return 1.00

        run_state = MagicMock()
        run_state.get_llm_spend_today.side_effect = spend_side_effect
        data_store = MagicMock()
        data_store.read_by_status.return_value = [job_a, job_b, job_c]

        now_ist = datetime(2026, 6, 17, 21, 0, 0, tzinfo=IST)

        mock_smtp = MagicMock()
        mock_response = _make_mock_anthropic_response("Brief content.")
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Resume text"
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with patch("src.run_brief_poller.datetime") as mock_dt:
            mock_dt.now.return_value = now_ist
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            with patch("src.notify.brief.pdfplumber.open", return_value=mock_pdf):
                with patch("src.notify.brief.anthropic.Anthropic") as mock_anthropic_cls:
                    mock_client = MagicMock()
                    mock_client.messages.create.return_value = mock_response
                    mock_anthropic_cls.return_value = mock_client
                    with patch("src.notify.brief.smtplib.SMTP") as brief_smtp_cls:
                        brief_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
                        brief_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
                        with patch("src.run_brief_poller.smtplib.SMTP") as cap_smtp_cls:
                            cap_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
                            cap_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

                            poll(SETTINGS, run_state, data_store)

        # Only the first brief was generated before the cap was hit
        assert mock_client.messages.create.call_count == 1
