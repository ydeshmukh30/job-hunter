"""Shared fixture job dicts used across all test modules."""

from datetime import datetime, timezone

IST = timezone.utc  # tests use UTC; real code uses Asia/Kolkata

NOW = datetime(2026, 6, 17, 13, 30, 0, tzinfo=IST)

# Passes all 5 filter gates
JOB_PASS = {
    "id": "aaa-001",
    "title": "Senior Backend Engineer",
    "company": "Razorpay",
    "platform": "linkedin",
    "url": "https://linkedin.com/jobs/view/001",
    "apply_type": "easy_apply",
    "status": "scraped",
    "ctc": "30-50 LPA",
    "yoe_required": "3-7 years",
    "location": "Bengaluru",
    "posted_at": NOW.isoformat(),
    "applied_at": "",
    "interview_date": "",
    "next_steps": "",
    "last_activity": NOW.isoformat(),
}

# Fails title gate
JOB_FAIL_TITLE = {**JOB_PASS, "id": "aaa-002", "title": "Data Scientist", "company": "Acme"}

# Fails CTC gate (INR range does not contain 38)
JOB_FAIL_CTC = {**JOB_PASS, "id": "aaa-003", "company": "Infosys", "ctc": "20-35 LPA"}

# No CTC stated, YOE range passes (5 in 3-7)
JOB_NO_CTC_YOE_PASS = {**JOB_PASS, "id": "aaa-004", "company": "PhonePe", "ctc": "", "yoe_required": "3-7"}

# No CTC stated, YOE range fails (5 not in 8-12)
JOB_NO_CTC_YOE_FAIL = {**JOB_PASS, "id": "aaa-005", "company": "TCS", "ctc": "", "yoe_required": "8-12"}

# Neither CTC nor YOE stated → keep
JOB_NEITHER = {**JOB_PASS, "id": "aaa-006", "company": "Freshworks", "ctc": "", "yoe_required": ""}

# Foreign currency → keep (treated as neither stated)
JOB_USD = {**JOB_PASS, "id": "aaa-007", "company": "Stripe", "ctc": "$120k-$180k", "location": "Remote"}

# Fails location gate
JOB_FAIL_LOCATION = {**JOB_PASS, "id": "aaa-008", "company": "Wipro", "location": "Mumbai"}

# Would be deduped (company already in CSV)
JOB_DUPE = {**JOB_PASS, "id": "aaa-009", "company": "Razorpay", "title": "SDE 3"}

# interview_scheduled tomorrow for brief poller tests
JOB_INTERVIEW_TOMORROW = {
    **JOB_PASS,
    "id": "bbb-001",
    "company": "Groww",
    "title": "Senior Backend Engineer",
    "status": "interview_scheduled",
    "applied_at": NOW.isoformat(),
    "interview_date": "2026-06-18T11:00:00+05:30",
}

# interview_scheduled today (should NOT trigger brief)
JOB_INTERVIEW_TODAY = {
    **JOB_INTERVIEW_TOMORROW,
    "id": "bbb-002",
    "company": "Zepto",
    "interview_date": "2026-06-17T15:00:00+05:30",
}

SAMPLE_CSV_ROWS = [
    JOB_PASS,
    JOB_NO_CTC_YOE_PASS,
    JOB_NEITHER,
    JOB_USD,
    JOB_INTERVIEW_TOMORROW,
    JOB_INTERVIEW_TODAY,
]
