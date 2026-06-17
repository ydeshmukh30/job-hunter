# MEMORY.md — Job Hunter Build Log

Live log of build status, decisions, and blockers. Updated after each module.

---

## Build Status

| Module | Status | Notes |
|---|---|---|
| Repo + scaffold | ✅ Done | `~/Desktop/job-hunter`, pushed to `ydeshmukh30/job-hunter` |
| Docs (CLAUDE.md, README.md, SPEC.md, PLAN.md) | ✅ Done | All written |
| `src/config.py` | ⏳ Pending | |
| `config/settings.toml` | ⏳ Pending | |
| `requirements.txt` + `.env.example` | ⏳ Pending | |
| Module 1: Data Store (`src/common/`) | ⏳ Pending | data_store.py, integrity.py, run_state.py |
| Module 2: Scrapers (`src/scrapers/`) | ⏳ Pending | base.py, manager.py, 8 plugins |
| Module 3: Filter+Apply (`src/apply/`) | ⏳ Pending | match.py, form_profile.json, platforms/ |
| Module 4: Notify+Brief (`src/notify/`) | ⏳ Pending | digest.py, brief.py |
| `src/run_daily.py` wiring | ⏳ Pending | |
| `src/run_brief_poller.py` | ⏳ Pending | |
| Smoke tests | ⏳ Pending | |
| Final commit + push | ⏳ Pending | |

---

## Key Decisions

### 2026-06-17

**Repo name:** `job-hunter` (user confirmed), private, `ydeshmukh30/job-hunter`

**Language:** Python 3.11+ (not JavaScript — career-ops is JS/Node, we adapt patterns not code)

**Data layer:** Plain CSV + SHA-256 sidecar (user requirement). No SQLite, no markdown table.

**Scraper architecture:** Plugin-based (adapted from career-ops provider pattern). Each platform = one file in `src/scrapers/plugins/`. Manager auto-discovers from `settings.toml::enabled_plugins`.

**Chrome profiles:** Pre-logged-in persistent user-data-dirs. No credential storage. No automated login. Each platform needs its own profile dir (user sets up manually once).

**Filter rule (locked):** Senior title AND (38 ∈ CTC range) OR (no CTC AND 5 ∈ YOE range) OR (neither stated → keep)

**LLM spend cap:** $1.00/day hard cap tracked in `run_state.json`. Brief poller respects this; pipeline itself does not make LLM calls.

**Cron schedule:** Daily pipeline at 7:00 PM IST (`30 13 * * *` UTC). Brief poller at 9:00 PM IST (`30 15 * * *` UTC) — batches all next-day interviews in a single run rather than polling every 30 min.

**Dry-run default:** `--live` required for actual form submission. Scraping + filtering + email always run.

**Dedup strategy:** By company name. One row per company in the CSV. Applied jobs are never re-applied.

**Fallback for unhandled ATSs:** Status → `manual_review`, URL preserved. User handles manually.

**Re-login strategy:** Chrome profiles are primary (sessions persist). On expiry, scrapers auto-re-login:
- LinkedIn: Google SSO with `yashdeshmukh7@gmail.com` — no password stored
- All others (Naukri, Indeed, Instahyre, Wellfound, WeWorkRemotely, Hirist, CutShort): username/password from `config/credentials.enc` (Fernet-encrypted, key = `MASTER_CRYPTO_KEY` env var; never committed)
- `LoginError` → platform skipped for the run (non-fatal); pipeline continues

**Inspiration from career-ops:**
- Provider plugin pattern (JS → Python adaptation)
- Fuzzy role title matching (Jaccard similarity approach)
- Salary/CTC annualization (hourly/monthly → annual LPA)
- Self-learning form field mappings
- Data contract: `src/data/` = user data (never auto-wiped), `src/` = system code

---

## Blockers / Open Questions

- Chrome profile paths: user must set these manually in `config/settings.toml` before first run
- Resume PDF path: user must set in `config/settings.toml → paths.resume_pdf`
- Gmail App Password: user must generate and set in `.env`
- Anthropic API key: user must set in `.env`
- Platform-specific apply logic: LinkedIn Easy Apply and Naukri apply flows differ significantly; platforms/ may need iterative refinement

---

## Verification Checklist (to fill in as each module completes)

- [ ] `pip install -r requirements.txt` completes without errors
- [ ] `playwright install chromium` succeeds
- [ ] `python -m src.run_daily --dry-run` completes full pipeline on fixtures, zero crashes
- [ ] `pytest src/tests/ -v` — all tests pass
- [ ] CSV integrity guard blocks tampered CSV
- [ ] `python -m src.run_daily --check` reports correctly
- [ ] Digest email renders correct HTML (mocked)
- [ ] Brief poller respects $1.00/day cap (mocked)
- [ ] A new plugin file in `src/scrapers/plugins/` is auto-discovered

---

## Adapted From career-ops (santifer/career-ops)

Reference: https://github.com/santifer/career-ops  
License: MIT

Patterns ported to Python:
- **Provider plugin pattern** → `src/scrapers/plugins/` (JS ESM modules → Python classes)
- **Role fuzzy matching** → `src/apply/match.py::title_matches()` (Jaccard coefficient + stopword filter)
- **Salary/CTC parsing** → `src/apply/match.py::parse_ctc_lpa()` (interval annualization: hourly×2080, monthly×12)
- **Portal scanner dedup** → `src/scrapers/manager.py` (company-based dedup in CSV instead of TSV scan-history)
- **Self-learning form mappings** → `src/apply/form_profile.json::learned_mappings`
- **Data contract** → `src/data/` never auto-overwritten by system updates
- **Status states** → borrowed canonical status progression pattern
- **Health check** → `python -m src.run_daily --check` (analogous to `npm run doctor`)
