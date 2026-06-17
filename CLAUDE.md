# CLAUDE.md — Job Hunter

## What This Repo Is

An automated, personal job-hunting pipeline for Yash Deshmukh. It scrapes job boards via Playwright (using pre-logged-in Chrome profiles), filters by title/CTC/YOE, auto-applies, and sends a daily email digest. It runs daily at 7 PM IST via macOS cron, with a brief poller every 30 min.

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
│   ├── run_brief_poller.py    # Standalone interview brief daemon
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

# Run pipeline (dry-run, safe, default)
python -m src.run_daily --dry-run

# Run pipeline (live, actually submits)
python -m src.run_daily --live

# Check if today's 7 PM run happened
python -m src.run_daily --check

# Run a single agent manually
python -m src.run_daily --only scraper --dry-run

# Status summary (per-status counts)
python -m src.run_daily --status-summary

# Run interview brief poller
python -m src.run_brief_poller

# Tests
pytest src/tests/ -v
```

## Environment Variables

All secrets come ONLY from environment variables (never committed).

```
MASTER_CRYPTO_KEY       Fernet key for encrypting stored credentials
GMAIL_APP_PASSWORD      Gmail App Password (not your main password)
ANTHROPIC_API_KEY       Anthropic API key for interview briefs
ANTHROPIC_MODEL         e.g. claude-sonnet-4-6
DAILY_LLM_USD_CAP       e.g. 1.00 (hard cap in USD)
```

## Architecture Decisions

### Sequential-only pipeline
Agents NEVER run concurrently. Order: Init → Scraper → Filter+Apply → Persist+Commit → Notify. A failure in one step logs a warning and lets the next step run on whatever data exists.

### CSV + SHA-256 integrity
The CSV is the single source of truth. Every write recomputes the SHA-256 sidecar. On every read, the hash is verified. A mismatch (manual edit) blocks the pipeline unless `--force-accept-manual-edit` is passed.

### Plugin-based scrapers (adapted from santifer/career-ops provider pattern)
Each platform is a single file in `src/scrapers/plugins/`. The manager auto-discovers enabled plugins from `settings.toml`. To add a platform: drop one file in the plugins directory.

### Pre-logged-in Chrome profiles
No automated credential login. Each platform has a configured `chrome_profiles` path in `settings.toml` pointing to a persistent Chrome user-data-dir where the user is already logged in.

### Self-learning apply form mappings
`src/apply/form_profile.json` has a `learned_mappings` section. When the applier encounters an unknown field label, it prompts the user via `input()`, persists the answer, and uses it for future applications. This is borrowed from the career-ops form-handling pattern.

### Dry-run by default
`--live` is required to actually submit applications. All scraping, filtering, and email always run regardless. Only the final form submission is gated by `--live`.

## Filter Logic

Keep a job ONLY if ALL hold:
1. Full-time role
2. Title matches (fuzzy, case-insensitive): SDE 2, SDE 3, Senior Software Engineer, Senior Backend Engineer, Lead Engineer, Staff Engineer
3. Compensation/YOE rule:
   - CTC range present → keep if 38 LPA ∈ [min, max]
   - Else YOE range present → keep if 5 ∈ [min, max]
   - Else (neither stated) → KEEP
4. Location ∈ {Pune, Bengaluru, Hyderabad, Remote}
5. Company not already in the tracker (dedup by company)

## Caps

- Scrape: 5 listings per platform
- Apply attempts: 5 per platform
- Dedup: by company (one row per company in the CSV)

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
