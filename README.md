# job-hunter

Automated job-hunting pipeline for senior backend engineers. Scrapes job boards daily, filters by title/CTC/YOE, auto-applies (or flags for manual review), and emails a digest every evening.

Built for: **Yash Deshmukh** — Senior Backend Engineer (Java, Spring Boot, Kafka, Cassandra, AWS)

---

## What it does

1. **Scrapes** up to 5 listings per platform from LinkedIn, Naukri, Indeed, Instahyre, Wellfound, WeWorkRemotely, Hirist, and CutShort — using your pre-logged-in Chrome profiles (no credential storage)
2. **Filters** by title (SDE 2–Staff), CTC (38+ LPA), YOE (5), location (Pune / Bengaluru / Hyderabad / Remote)
3. **Auto-applies** via Playwright — filling forms from a self-learning profile, pausing to ask you about unknown fields
4. **Persists** everything to a plain CSV (`src/data/job_applications.csv`) with SHA-256 integrity checking
5. **Emails** a daily HTML digest to `yashdeshmukh7@gmail.com` — applied, manual-review, and funnel summary
6. **Generates interview briefs** 1 hour before each scheduled interview using Claude

**Safety first:** `--live` is required to actually submit applications. Default mode is always `--dry-run`.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   run_daily.py                          │
│  Init/Data → Scraper → Filter+Apply → Persist → Notify │
└──────┬───────────┬──────────┬──────────┬────────────────┘
       │           │          │          │
  data_store   scrapers/   apply/    notify/
  integrity    plugins/   platforms/ digest.py
  run_state    (8 plugs)  match.py   brief.py
```

- **Sequential execution only** — agents never run concurrently
- **Failure-agnostic** — one platform failing never aborts the rest
- **Plugin-based scrapers** — add a platform by dropping one file in `src/scrapers/plugins/`
- **Self-learning forms** — unknown DOM fields prompt you once, then auto-fill forever

---

## Setup

### 1. Prerequisites

- Python 3.11+
- macOS (cron/launchd setup is macOS-specific)
- Chrome installed (for persistent profiles)
- Gmail App Password ([generate here](https://myaccount.google.com/apppasswords))
- Anthropic API key

### 2. Install

```bash
cd ~/Desktop/job-hunter
pip install -r requirements.txt
playwright install chromium
```

### 3. Environment variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

```env
MASTER_CRYPTO_KEY=<generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-6
DAILY_LLM_USD_CAP=1.00
```

Never commit `.env`. It is already in `.gitignore`.

### 4. Configure settings

Edit `config/settings.toml`:

```toml
[search]
keywords = ["Senior Backend Engineer", "SDE 2", "SDE 3", "Staff Engineer"]
locations = ["Pune", "Bengaluru", "Hyderabad", "Remote"]

[limits]
scrape_per_platform = 5
apply_attempts_per_platform = 5

[paths]
resume_pdf = "config/resume.pdf"   # already committed — update if you replace the file

[chrome_profiles]
linkedin  = "/Users/yashdeshmukh/Library/Application Support/Google/Chrome/JobHunterLinkedIn"
naukri    = "/Users/yashdeshmukh/Library/Application Support/Google/Chrome/JobHunterNaukri"
# ... one per platform
```

### 5. Set up Chrome profiles

For each platform, create a dedicated Chrome profile and log in manually:

```bash
# Example for LinkedIn (repeat for each platform)
open -a "Google Chrome" --args \
  --user-data-dir="/Users/yashdeshmukh/Library/Application Support/Google/Chrome/JobHunterLinkedIn"
# Log in to LinkedIn in this window. Close Chrome.
```

This ensures scrapers and appliers run with your authenticated session. No passwords are stored by the system.

### 6. Resume

`config/resume.pdf` (Yash_resume_v3.pdf) is already committed. To use a different version, replace that file and update `paths.resume_pdf` in `config/settings.toml` if the filename changes.

---

## Running

### Dry-run (safe, always default)

```bash
python -m src.run_daily --dry-run
```

Scraping, filtering, and email rendering all run. Form submission is skipped. Safe to run any time.

### Live run (actually submits applications)

```bash
python -m src.run_daily --live
```

### Check if today's 7 PM run happened

```bash
python -m src.run_daily --check
```

Prints whether the daily run completed today (reads `src/data/run_state.json`).

### Run a single agent manually

```bash
python -m src.run_daily --only scraper --dry-run
python -m src.run_daily --only apply --live
python -m src.run_daily --only notify
```

### Status summary

```bash
python -m src.run_daily --status-summary
```

Prints per-status counts from the CSV: scraped / applied / manual_review / interview_scheduled / offer / rejected.

### Force-accept a manual edit to the CSV

```bash
python -m src.run_daily --force-accept-manual-edit --dry-run
```

If you edited the CSV manually (integrity check will block the pipeline), pass this flag to re-baseline the hash.

### Run interview brief poller

```bash
python -m src.run_brief_poller
```

Checks for interviews in ~1 hour, generates a prep brief via Claude, emails it. Normally run via cron.

---

## Cron / launchd setup (macOS)

### Option A: crontab (simplest)

```bash
crontab -e
```

Add these two lines:

```cron
# Daily pipeline at 7:00 PM IST (UTC+5:30 = 13:30 UTC)
30 13 * * * /usr/bin/env bash -c 'source /Users/yashdeshmukh/.zshenv && cd /Users/yashdeshmukh/Desktop/job-hunter && python -m src.run_daily --live >> /tmp/job-hunter-daily.log 2>&1'

# Interview brief poller at 9:00 PM IST daily (15:30 UTC) — briefs for next-day interviews
30 15 * * * /usr/bin/env bash -c 'source /Users/yashdeshmukh/.zshenv && cd /Users/yashdeshmukh/Desktop/job-hunter && python -m src.run_brief_poller >> /tmp/job-hunter-poller.log 2>&1'
```

> **Note:** macOS cron runs in UTC. 7:00 PM IST = 13:30 UTC.

### Option B: launchd (recommended — survives sleep/wake better)

Create `~/Library/LaunchAgents/com.yash.job-hunter-daily.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.yash.job-hunter-daily</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/env</string>
        <string>bash</string>
        <string>-c</string>
        <string>source ~/.zshenv &amp;&amp; cd ~/Desktop/job-hunter &amp;&amp; python -m src.run_daily --live</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>19</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/tmp/job-hunter-daily.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/job-hunter-daily.err</string>
    <key>TimeZone</key>
    <string>Asia/Kolkata</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.yash.job-hunter-daily.plist
```

### Manual fallback via Claude remote control

If the Mac was asleep at 7 PM and the cron run was missed:

1. Open Claude Code remotely (Claude remote control)
2. In this repo session:
   ```
   python -m src.run_daily --check
   ```
3. If it shows missed, run:
   ```
   python -m src.run_daily --live
   ```

---

## Data model

The CSV lives at `src/data/job_applications.csv`. Only `src/common/data_store.py` may write to it.

| Column | Description |
|---|---|
| `id` | UUID |
| `title` | Job title |
| `company` | Company name |
| `platform` | Source platform |
| `url` | Direct URL to the job posting |
| `apply_type` | `easy_apply` or `external_form` |
| `status` | `scraped` → `applied` / `manual_review` → `interview_scheduled` → `offer` / `rejected` |
| `ctc` | CTC range string (e.g. "30-45 LPA") |
| `yoe_required` | YOE range string (e.g. "3-6") |
| `location` | City |
| `applied_at` | ISO 8601 timestamp |
| `interview_date` | ISO 8601 timestamp |
| `next_steps` | Free text |
| `last_activity` | ISO 8601 timestamp |

Integrity: every write recomputes `src/data/job_applications.csv.sha256`. On every read, the hash is verified. A mismatch means the CSV was edited manually — the pipeline refuses to proceed unless `--force-accept-manual-edit` is passed.

---

## Filter logic

A job passes the filter only if ALL of the following hold:

1. **Full-time role** (not contract, not internship)
2. **Title match** (fuzzy, case-insensitive): SDE 2, SDE 3, Senior Software Engineer, Senior Backend Engineer, Lead Engineer, Staff Engineer
3. **Compensation/experience rule**:
   - If CTC range is stated: keep if 38 LPA lies within [min, max]
   - Else if YOE range is stated: keep if 5 lies within [min, max]
   - Else (neither stated): **keep** (safer than dropping)
4. **Location**: Pune, Bengaluru, Hyderabad, or Remote
5. **Dedup**: company not already in the CSV

---

## LLM spend cap

`DAILY_LLM_USD_CAP` (default `1.00`) is tracked in `src/data/run_state.json`. The brief poller checks remaining budget before each Anthropic API call. If the cap is reached, it skips the LLM call and emails a "cap reached" notice instead.

---

## Tests

```bash
pytest src/tests/ -v
```

Key test files:
- `src/tests/test_matcher.py` — filter logic (title, CTC, YOE, location, dedup)
- `src/tests/test_data_store.py` — CSV append/update, integrity guard
- `src/tests/test_digest.py` — email rendering (mocked SMTP)
- `src/tests/test_brief.py` — brief generation (mocked Anthropic SDK)

---

## Credits

Provider plugin pattern and role fuzzy-matching algorithm adapted from [santifer/career-ops](https://github.com/santifer/career-ops) — a production-grade job-hunting system that evaluated 740+ offers for the original author.
