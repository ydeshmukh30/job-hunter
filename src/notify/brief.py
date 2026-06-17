"""Interview preparation brief generator and sender.

Usage
-----
::

    from src.notify.brief import generate_brief, send_brief
    html = generate_brief(job, settings)
    send_brief(html, interview_dt, job, settings)
"""

from __future__ import annotations

import smtplib
import textwrap
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic
import pdfplumber

IST = ZoneInfo("Asia/Kolkata")

# ---------------------------------------------------------------------------
# Resume extraction
# ---------------------------------------------------------------------------


def extract_resume_text(resume_path: Path) -> str:
    """Extract plain text from a PDF file using pdfplumber.

    Parameters
    ----------
    resume_path:
        Absolute or relative path to the PDF.

    Returns
    -------
    str
        Concatenated plain text of all pages, stripped of leading/trailing
        whitespace.
    """
    with pdfplumber.open(resume_path) as pdf:
        pages_text = [page.extract_text() or "" for page in pdf.pages]
    return "\n".join(pages_text).strip()


# ---------------------------------------------------------------------------
# Brief generation
# ---------------------------------------------------------------------------


def _build_prompt(job: dict, resume_text: str) -> str:
    company = job.get("company", "Unknown Company")
    title = job.get("title", "Unknown Role")
    url = job.get("url", "")
    interview_date_raw = job.get("interview_date", "")

    interview_time = "TBD"
    if interview_date_raw:
        try:
            dt = datetime.fromisoformat(interview_date_raw).astimezone(IST)
            interview_time = dt.strftime("%I:%M %p IST")
        except (ValueError, TypeError):
            interview_time = interview_date_raw

    return textwrap.dedent(f"""\
        You are helping Yash Deshmukh prepare for an interview at {company} for the role of {title}.

        === YASH'S RESUME (plain text) ===
        {resume_text}
        === END RESUME ===

        Job URL: {url}
        Interview is tomorrow at {interview_time}.

        Using the resume above, generate the following — be specific and anchor every point
        to actual projects, metrics, or technologies mentioned in the resume:

        1. Top 3–5 system design topics Yash should review for this specific role at {company}.

        2. 5 deep-dive technical questions the interviewer is likely to ask, tailored to
           {company}'s known stack/challenges. For each question, include a 2-line hint
           referencing the most relevant part of Yash's resume as a starting point.

        3. The 3 resume bullets that align most strongly with this JD. For each, write
           a 1-sentence talking-point expansion Yash can use to open his answer.

        4. Any relevant context about {company}'s engineering culture, recent tech blog
           posts, or known architectural challenges (clearly label if speculative).

        Be direct and concise. Yash is reading this the evening before the interview.
    """)


def _wrap_in_html(text: str, company: str, title: str) -> str:
    """Wrap plain-text API response in minimal HTML."""
    import html as html_lib

    escaped = html_lib.escape(text)
    # Convert markdown-style headers (lines starting with a digit + period or ##)
    lines = escaped.split("\n")
    formatted_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            formatted_lines.append(f"<h3>{stripped[3:]}</h3>")
        elif len(stripped) > 1 and stripped[0].isdigit() and stripped[1] == ".":
            formatted_lines.append(f"<p><strong>{stripped}</strong></p>")
        elif stripped.startswith("- ") or stripped.startswith("• "):
            formatted_lines.append(f"<li>{stripped[2:]}</li>")
        elif stripped == "":
            formatted_lines.append("<br>")
        else:
            formatted_lines.append(f"<p>{stripped}</p>")

    body = "\n".join(formatted_lines)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f4f6f9; margin: 0; padding: 20px; color: #333; }}
    .container {{ max-width: 720px; margin: 0 auto; background: #fff;
                  border-radius: 8px; padding: 32px;
                  box-shadow: 0 2px 8px rgba(0,0,0,.08); }}
    h1 {{ color: #1a1a2e; margin-top: 0; }}
    h3 {{ color: #1a1a2e; border-bottom: 1px solid #eee; padding-bottom: 6px; }}
    li {{ margin-bottom: 6px; }}
    p  {{ line-height: 1.6; }}
    .footer {{ margin-top: 32px; font-size: 12px; color: #888; border-top: 1px solid #eee; padding-top: 12px; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>Interview Brief — {html_lib.escape(company)} ({html_lib.escape(title)})</h1>
    {body}
    <div class="footer">Generated by job-hunter</div>
  </div>
</body>
</html>"""


def generate_brief(job: dict, settings) -> str:
    """Generate an HTML interview prep brief using the Anthropic API.

    Steps
    -----
    1. Extract plain text from ``settings.resume_pdf``.
    2. Build a prompt injecting the full resume text + job details.
    3. Call the Anthropic API synchronously.
    4. Return an HTML-formatted brief string.

    Parameters
    ----------
    job:
        A job dict with keys: ``company``, ``title``, ``url``,
        ``interview_date``.
    settings:
        A :class:`src.config.Settings` instance.  Uses
        ``settings.resume_pdf``, ``settings.anthropic_api_key``, and
        ``settings.anthropic_model``.

    Returns
    -------
    str
        Complete HTML brief string.
    """
    resume_text = extract_resume_text(Path(settings.resume_pdf))
    prompt = _build_prompt(job, resume_text)

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    # Extract text content from the response
    response_text = ""
    for block in message.content:
        if hasattr(block, "text"):
            response_text += block.text

    company = job.get("company", "Unknown Company")
    title = job.get("title", "Unknown Role")
    return _wrap_in_html(response_text, company, title)


# ---------------------------------------------------------------------------
# Email sending
# ---------------------------------------------------------------------------


def send_brief(html: str, interview_dt: datetime, job: dict, settings) -> None:
    """Send the interview brief via Gmail SMTP.

    Parameters
    ----------
    html:
        HTML body produced by :func:`generate_brief`.
    interview_dt:
        Timezone-aware datetime of the interview.
    job:
        Job dict with at least ``company`` and ``title`` keys.
    settings:
        A :class:`src.config.Settings` instance.  Uses
        ``settings.smtp_host``, ``settings.smtp_port``,
        ``settings.gmail_app_password``, and ``settings.digest_recipient``.
    """
    company = job.get("company", "Unknown Company")
    title = job.get("title", "Unknown Role")

    interview_ist = interview_dt.astimezone(IST)
    time_str = interview_ist.strftime("%I:%M %p IST").lstrip("0")

    subject = f"Interview Brief — {company} ({title}) tomorrow at {time_str}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Job Hunter <{settings.digest_recipient}>"
    msg["To"] = settings.digest_recipient

    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(settings.digest_recipient, settings.gmail_app_password)
        server.sendmail(
            settings.digest_recipient,
            settings.digest_recipient,
            msg.as_string(),
        )
