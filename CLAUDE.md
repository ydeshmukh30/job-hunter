# CLAUDE.md — Job Hunter

## What This Repo Is

An automated, personal job-hunting pipeline for Yash Deshmukh. It scrapes job boards via Playwright (using pre-logged-in Chrome profiles), filters by title/CTC/YOE, auto-applies, and sends a daily email digest. It runs daily at 7 PM IST via macOS cron. A separate brief poller runs at 9 PM IST daily and emails prep briefs for all interviews scheduled the next day.

## Candidate Profile

**Yash Deshmukh** — Senior Backend Engineer, 5 YOE  
Stack: Java, Spring Boot, Kafka, Cassandra, AWS  
Scale: ~1M RPM pipelines, ~680 GB/day streaming across distributed Kafka + Cassandra clusters  
Email: yashdeshmukh7@gmail.com

## Tech Stack

- Python 3.11+
- Playwright (headless browser, Chromium)
- `filelock` for CSV concurrency safety
- `anthropic` SDK for interview brief generation
- `smtplib` + Gmail App Password for email
- `tomllib` (stdlib) for config
- `pytest` for tests
- No database — plain CSV with SHA-256 integrity sidecar

## Directory Structure

```
job-hunter/
├── config/
│   └── settings.toml          # All tunable knobs (platforms, limits, filters)
├── src/
│   ├── config.py              # Typed settings loader (env + toml)
│   ├── run_daily.py           # Main pipeline entrypoint
│   ├── run_brief_poller.py    # Standalone brief runner — 9 PM IST, next-day interviews
│   ├── common/
│   │   ├── data_store.py      # ONLY writer to the CSV
│   │   ├── integrity.py       # SHA-256 guard
│   │   └── run_state.py       # Per-agent heartbeat + LLM spend tracking
│   ├── scrapers/
│   │   ├── base.py            # BaseScraper ABC
│   │   ├── manager.py         # Plugin discovery + sequential execution
│   │   └── plugins/           # One file per platform (linkedin.py, naukri.py, etc.)
│   ├── apply/
│   │   ├── match.py           # Filter logic (title + CTC/YOE + location + dedup)
│   │   ├── form_profile.json  # Base profile + learned DOM field mappings
│   │   └── platforms/         # Per-platform Playwright appliers
│   └── notify/
│       ├── digest.py          # Daily HTML email
│       └── brief.py           # Interview prep brief (Anthropic API)
├── src/data/
│   ├── job_applications.csv   # Source of truth — agents are only writers
│   ├── job_applications.csv.sha256
│   └── run_state.json
├── src/tests/
│   ├── test_matcher.py
│   ├── fixtures/
│   └── mocks/
├── docs/
│   ├── PLAN.md
│   └── SPEC.md
├── .env.example
├── requirements.txt
├── MEMORY.md
└── README.md
```

## Key Commands

```bash
# Install
pip install -r requirements.txt
playwright install chromium

# ONE-TIME: sign in to LinkedIn in the dedicated Chrome profile, then close it
python -m src.run_poller --login

# ONE-TIME: compile the six resume variants to PDF (auto-apply uploads a PDF)
brew install tectonic && ./scripts/build_resumes.sh

# Which selectors match on the live page? Run this when a poll returns nothing.
python -m src.run_poller --probe

# One poll cycle (dry-run, safe, default). launchd calls this every 30 min.
python -m src.run_poller

# Same, but actually submits Easy Apply forms
python -m src.run_poller --live

# Daily digest email
python -m src.run_digest --dry-run
python -m src.run_digest

# Interview brief poller
python -m src.run_brief_poller

# Tests
pytest src/tests/ -v
```

## Environment Variables

All secrets come ONLY from environment variables (never committed).

```
GMAIL_APP_PASSWORD      Gmail App Password (not your main password)
ANTHROPIC_API_KEY       Anthropic API key for interview briefs
ANTHROPIC_MODEL         e.g. claude-sonnet-4-6
DAILY_LLM_USD_CAP       e.g. 1.00 (hard cap in USD)
NTFY_TOPIC              Long random string — your ntfy.sh push channel.
                        Anyone who knows it can read your notifications.
                        Must be set inside the launchd plist: launchd agents
                        do not read your shell profile.
```

`MASTER_CRYPTO_KEY` is gone. The Fernet credential vault was deleted along with
every automated-login path — see "One dedicated Chrome profile" below.

## Architecture Decisions

### Sequential-only pipeline
Agents NEVER run concurrently. Order: Init → Scraper → Filter+Apply → Persist+Commit → Notify. A failure in one step logs a warning and lets the next step run on whatever data exists.

### Skip tracking and manual-intervention retry
Every skipped platform (LoginError / CAPTCHA / network) and every skipped job (manual_review) is recorded in `run_state.json → skipped`. They surface in the daily digest email under "Needs your attention" with exact retry commands. After fixing the issue manually, run `--retry-skipped` (all unretried) or `--retry-platform <name>` (single platform). The retry pipeline runs scraper + apply only for the targeted items — not the full daily pipeline.

### CSV + SHA-256 integrity
The CSV is the single source of truth. Every write recomputes the SHA-256 sidecar. On every read, the hash is verified. A mismatch (manual edit) blocks the pipeline unless `--force-accept-manual-edit` is passed.

### Plugin-based scrapers (adapted from santifer/career-ops provider pattern)
Each platform is a single file in `src/scrapers/plugins/`. The manager auto-discovers enabled plugins from `settings.toml`. To add a platform: drop one file in the plugins directory.

### One dedicated Chrome profile, signed in once
All platforms share `~/.chrome-jobhunter`, a Chrome profile the user signs into
manually one time (`python -m src.run_poller --login`). Playwright reuses it via
`launch_persistent_context`. No stored credentials, no automated login, no
CAPTCHA loop — which is why the Fernet vault, `encrypt_creds.py`, and every
per-platform `login()` method were deleted.

Two constraints, both verified by testing rather than assumed:

- **Chrome ≥136 refuses `--remote-debugging-port` on the default profile** — a
  deliberate defence against cookie-stealing malware. Chrome here is 150, so
  Yash's everyday profile cannot be automated by any approach. Migrating its
  cookies is also not an option: that is the malware pattern, and tooling
  blocks it.
- **`connect_over_cdp` was broken and now works.** It failed the handshake on
  Playwright 1.60 + Chrome 150 with `Browser.setDownloadBehavior: Browser
  context management is not supported`. Re-tested 2026-08-11 on Chrome
  151.0.7922.76: port opens, handshake completes, pages drive fine.

Consequence: `--login` now opens the window with `--remote-debugging-port=9222`
and `session()` attaches to it if it is up, leaving it running afterwards. The
login window should stay open, not be closed. If a Chrome holds the profile
*without* a port, it cannot be attached to and cannot be given one — close it
and re-run `--login`.

### Daily 24-hour sweep
`f_TPR` takes a window in seconds and **requires an `r` prefix** — a bare
`f_TPR=86400` is silently ignored, so the filter looks applied while doing
nothing. Window is 24 hours, run once daily. This replaced the 30-minute
Strategy 1 loop because the action is now recruiter outreach on top-applicant
jobs, and that ranking needs an applicant pool to exist at all. launchd, not
cron — this laptop sleeps, and cron drops every slot it slept through.

**Pagination is mandatory at this window.** LinkedIn serves 25 results a page
via `&start=N`. One page was the whole of a 60-minute window and is a small
slice of a 24-hour one, and the truncation is silent. The scraper walks pages
until one returns nothing new, capped by `limits.max_pages_per_location`.

### Self-learning apply form mappings
`src/apply/form_profile.json` has a `learned_mappings` section. **Under the
poller there is no tty**, so an unknown field must abort the application and
fire a notification. It must never call `input()`: that would hang the run
forever holding the Chrome profile lock, wedging every subsequent poll.

### Dry-run by default
`--live` is required to actually submit applications. All scraping, filtering,
and email always run regardless. Only the final form submission is gated.

## Filter Logic

Keep a job ONLY if ALL hold:
1. Full-time role
2. Title passes three gates: no disqualifier (intern/QA/sales/manager/director),
   contains an IC engineering token, and carries a seniority signal. The old
   Jaccard-over-stopword-stripped-tokens matcher admitted "QA Engineer".
3. Compensation/YOE rule:
   - INR CTC parseable → keep if **max ≥ 38 LPA**. NOT band-containment: the old
     `min <= 38 <= max` rejected "45-60 LPA" because `45 <= 38` is false, which
     threw away exactly the best-paying jobs.
   - Else YOE range present → keep if 5 ∈ [min−1, max]. One year of stretch.
   - Else → KEEP (CTC not stated, foreign currency, "Competitive")
4. Location ∈ {Pune, Bengaluru, Hyderabad, Remote}
5. **Job URL** not already in the tracker

## Caps

- Scrape: `max_pages_per_location = 8` (up to 200 postings per location). A
  ceiling, not a target — pagination stops on the first page with nothing new.
- Apply attempts: 5 per run
- Dedup: by canonical job URL (query string and fragment stripped). NOT by
  company — that permanently hid every future role at any company once one of
  its roles had been seen.

## Data Model (CSV headers)

```
id,title,company,platform,url,apply_type,status,ctc,yoe_required,location,applied_at,interview_date,next_steps,last_activity
```

Status values: `scraped` | `applied` | `manual_review` | `interview_scheduled` | `offer` | `rejected`

## What NOT to Do

- Never commit `.env` or any file containing real secrets
- Never write to `src/data/job_applications.csv` except through `data_store.py`
- Never run agents concurrently — always sequential
- Never use `--live` during tests — always `--dry-run`
- Never hard-code paths — use `settings.paths.*` from config
- Never crash the pipeline on a single platform failure — log and continue

## Testing Rules

- All smoke tests use fixtures in `src/tests/fixtures/`
- SMTP and Anthropic API are always mocked in tests
- Playwright is mocked via fixture HTML files
- A test passing does NOT mean the feature works — verify with `--dry-run` on real boards

## Adapting from santifer/career-ops

These patterns are borrowed and adapted to Python:
- Provider plugin pattern → `src/scrapers/plugins/`
- Role fuzzy matching algorithm → `src/apply/match.py`
- Salary annualization logic (hourly/monthly → annual LPA) → `src/apply/match.py`
- A-F job evaluation framework → `src/apply/match.py` (simplified to pass/fail filter)
- Data contract (user data vs system files) → `src/data/` vs `src/` distinction
- Portal scanner with dedup history → `src/scrapers/manager.py`
- Human-readable status states → `status` column enum
