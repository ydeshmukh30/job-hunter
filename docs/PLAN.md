# Implementation Plan — Job Hunter

**Target:** Production-ready Python 3.11+ codebase, private GitHub repo, daily 7 PM IST cron.  
**Date drafted:** 2026-06-17  
**Status:** In progress

---

## Phase 0 — Foundation (must complete before parallel modules)

**Goal:** Working repo skeleton that all module agents can build against.

### 0.1 Scaffold
- [x] Create private GitHub repo `ydeshmukh30/job-hunter`
- [x] Create directory tree
- [x] Write CLAUDE.md, README.md, MEMORY.md, PLAN.md, SPEC.md

### 0.2 Config foundation
- [ ] `config/settings.toml` — full schema with commented defaults
- [ ] `src/config.py` — typed `Settings` dataclass, loads from `settings.toml` + env vars
- [ ] `.env.example` — all 5 env vars with placeholder values + generation instructions
- [ ] `requirements.txt` — pinned versions for all dependencies

### 0.3 Common plumbing
- [ ] `src/data/` directory with `.gitkeep` placeholder (CSV created at runtime)
- [ ] `src/tests/fixtures/` — sample CSV, sample job dicts, HTML fixtures
- [ ] `.gitignore` — excludes `.env`, `src/data/*.csv`, `src/data/*.sha256`, `src/data/*.json`, `__pycache__`

**Dependency:** Phase 1–4 agents start only after 0.2 is committed and pushed.

---

## Phase 1 — Module 1: Init & Data Store

**Owns:** `src/common/`  
**Agent scope:** Isolated — no other module touches these files during parallel build.

### Files to create
```
src/common/__init__.py
src/common/data_store.py
src/common/integrity.py
src/common/run_state.py
src/tests/test_data_store.py
```

### data_store.py
- `CSV_PATH` and `HEADERS` constants
- `init_csv()` — create with correct headers if absent
- `append_jobs(jobs: list[dict]) -> list[str]` — appends rows, returns new IDs; uses `filelock`
- `update_job(job_id: str, **fields)` — updates a single row by ID; uses `filelock`
- `read_all() -> list[dict]` — reads all rows; triggers integrity check
- `read_by_status(status: str) -> list[dict]`
- `get_companies() -> set[str]` — for dedup check
- Every successful write recomputes SHA-256 sidecar

### integrity.py
- `verify()` — reads sidecar, recomputes hash, raises `IntegrityError` on mismatch
- `baseline()` — write new hash (used after `--force-accept-manual-edit`)
- `IntegrityError(Exception)` custom exception

### run_state.py
- `run_state.json` structure: `{agent: {last_success_ts, last_task_summary, last_status}, llm_spend: {date, usd}}`
- `record_agent_success(agent: str, summary: str)`
- `record_agent_failure(agent: str, error: str)`
- `did_run_today(agent: str, expected_hour: int = 19) -> bool`
- `get_llm_spend_today() -> float`
- `add_llm_spend(usd: float)`
- `reset_daily_spend_if_new_day()`

### Smoke tests
- Bulk append 100 rows under filelock, assert zero row loss
- Tamper CSV (mutate a byte), assert `IntegrityError` raised
- `--force-accept-manual-edit` re-baselines and allows read
- `did_run_today()` returns True/False correctly

---

## Phase 2 — Module 2: Scraper

**Owns:** `src/scrapers/`  
**Agent scope:** Isolated — writes only to `src/scrapers/`. Calls `data_store.append_jobs()` interface.

### Files to create
```
src/scrapers/__init__.py
src/scrapers/base.py
src/scrapers/manager.py
src/scrapers/crypto_vault.py
src/scrapers/encrypt_creds.py
src/scrapers/plugins/__init__.py
src/scrapers/plugins/linkedin.py
src/scrapers/plugins/naukri.py
src/scrapers/plugins/indeed.py
src/scrapers/plugins/instahyre.py
src/scrapers/plugins/wellfound.py
src/scrapers/plugins/weworkremotely.py
src/scrapers/plugins/hirist.py
src/scrapers/plugins/cutshort.py
src/tests/test_scraper.py
src/tests/fixtures/mock_jobs.py
```

### base.py — BaseScraper ABC
```python
class BaseScraper(ABC):
    platform: str
    @abstractmethod
    async def scrape(self, keywords: list[str], locations: list[str], limit: int) -> list[JobDict]
    async def open_context(self, headless: bool, user_data_dir: str) -> BrowserContext
```

`JobDict` TypedDict: `{title, company, platform, url, apply_type, ctc, yoe_required, location, posted_at}`

### manager.py
- `discover_plugins(enabled: list[str]) -> list[BaseScraper]` — scans `plugins/` dir, imports matching modules
- `run_all(settings) -> list[JobDict]` — sequential loop, catches per-platform exceptions, logs and continues
- 3 sequential CAPTCHA failures → skip platform, log alert
- Each scraper: randomized viewport, human-like delays (2–6 s), gentle scrolling

### Plugin pattern (each plugin)
```python
class LinkedInScraper(BaseScraper):
    platform = "linkedin"
    async def scrape(self, keywords, locations, limit) -> list[JobDict]:
        # Use self.open_context() with chrome profile
        # Navigate search, extract listings
        # Return normalized JobDicts
```

### crypto_vault.py (optional fallback)
- `decrypt_credentials(platform: str) -> dict` — Fernet decrypt `config/credentials.enc`
- `CryptoVault(key: bytes)` class

### Smoke tests
- `--dry-run` on mocked Playwright returns ≥3 valid JobDicts schema-clean
- New plugin file auto-discovered (place fixture plugin, assert it appears in discovered list)
- Single platform exception does not prevent other platforms running

---

## Phase 3 — Module 3: Filter + Apply

**Owns:** `src/apply/`  
**Agent scope:** Isolated — writes only to `src/apply/`. Reads from `data_store` interface.

### Files to create
```
src/apply/__init__.py
src/apply/match.py
src/apply/form_profile.json
src/apply/platforms/__init__.py
src/apply/platforms/base_applier.py
src/apply/platforms/linkedin_applier.py
src/apply/platforms/naukri_applier.py
src/apply/platforms/generic_applier.py
src/tests/test_matcher.py
```

### match.py — Filter logic
```python
def filter_jobs(jobs: list[JobDict], existing_companies: set[str]) -> list[JobDict]
def title_matches(title: str, allowed_titles: list[str]) -> bool
def ctc_matches(ctc_str: str | None, yoe_str: str | None, target_ctc: float, target_yoe: int) -> bool
def parse_ctc_lpa(ctc_str: str) -> tuple[float, float] | None
def parse_yoe_range(yoe_str: str) -> tuple[int, int] | None
```

**Filter algorithm (from locked spec):**
1. Full-time check (title/description contains no "contract"/"intern"/etc.)
2. `title_matches()` — fuzzy, case-insensitive, Jaccard-based (adapted from career-ops `role-matcher.mjs`)
3. `ctc_matches()` — three-branch CTC/YOE/neither logic
4. Location in allowed set
5. Company not in `existing_companies`

### form_profile.json schema
```json
{
  "name": "Yash Deshmukh",
  "email": "yashdeshmukh7@gmail.com",
  "phone": "",
  "linkedin": "",
  "github": "",
  "resume_path": "",
  "years_experience": 5,
  "current_ctc": "",
  "expected_ctc": "38+",
  "notice_period": "30 days",
  "learned_mappings": {
    "expected compensation": "expected_ctc",
    "years of experience": "years_experience"
  }
}
```

### Apply flow (per platform, per job)
1. Load form profile + learned_mappings
2. Open platform Playwright context (pre-logged-in Chrome profile)
3. Navigate to job URL
4. Detect apply type (Easy Apply vs external form)
5. For each field: extract label → fuzzy-match `learned_mappings` → fill or prompt
6. Upload resume PDF
7. DRY-RUN: log submission payload, update status to `applied` (with dry-run marker)
8. LIVE: click final submit → update status to `applied`
9. On error/unknown ATS/timeout: status → `manual_review`, log URL, continue

### Smoke tests (`test_matcher.py`)
- Title hit: "Senior Backend Engineer at Razorpay" → pass
- Title miss: "Data Scientist" → fail
- CTC range hit: ctc="30-50 LPA" → pass (38 ∈ range)
- CTC range miss: ctc="20-35 LPA" → fail
- No CTC, YOE range hit: yoe="3-7" → pass (5 ∈ range)
- No CTC, YOE range miss: yoe="8-12" → fail
- Neither stated → pass (keep by default)
- Location filter: location="Mumbai" → fail; location="Bengaluru" → pass
- Company dedup: company already in CSV → skip

---

## Phase 4 — Module 4: Notify + Brief

**Owns:** `src/notify/`, `src/run_brief_poller.py`  
**Agent scope:** Isolated — writes only to `src/notify/`. Reads from `data_store` interface.

### Files to create
```
src/notify/__init__.py
src/notify/digest.py
src/notify/brief.py
src/run_brief_poller.py
src/tests/test_digest.py
src/tests/test_brief.py
```

### digest.py
- `build_digest(rows: list[dict]) -> str` — returns HTML string
- `send_digest(html: str, settings: Settings)` — SMTP via Gmail
- HTML sections:
  - Header: date + run summary (N applied, N found, N manual_review)
  - Action table: all `manual_review` rows with hyperlinked URLs
  - Funnel: `interview_scheduled` count, `offer` count, `rejected` count
  - Footer: "generated by job-hunter"
- Send even on zero-activity days (just shows "No activity today")

### brief.py
- `generate_brief(job: dict, candidate_profile: dict, model: str) -> str`
- Anthropic SDK call (async), `max_tokens=2000`
- Prompt injects: candidate profile + YOE/stack + company + JD URL + `last_activity`
- Output sections:
  - Core system-design topics relevant to this company's stack
  - 5 deep-dive questions tailored to company tech
  - 3 resume bullet alignments (which of Yash's bullets match the JD)
- `send_brief(html: str, interview_date: datetime, settings: Settings)` — SMTP

### run_brief_poller.py
- Runs standalone (cron every 30 min)
- `poll()`:
  1. `reset_daily_spend_if_new_day()`
  2. Read rows with `status='interview_scheduled'`
  3. Filter: `interview_date` is within 45–75 min from now
  4. For each: check `get_llm_spend_today() < DAILY_LLM_USD_CAP`
  5. If cap OK: `generate_brief()`, `send_brief()`, `add_llm_spend(estimated_usd)`
  6. If cap exceeded: send "cap reached" email notice instead
  7. Corrupt/unparseable row → log warning, skip, continue

### Smoke tests
- `test_digest.py`: fixture with 5 rows (2 applied, 1 manual_review, 1 interview_scheduled, 1 rejected) → HTML contains expected sections; SMTP mocked (assert `sendmail` called once)
- Zero-activity fixture → HTML shows "No activity today"; email still sent
- `test_brief.py`: fixture row with interview 60 min out → brief generated (mocked Anthropic); `add_llm_spend` called; spending at $1.00 → skipped + notice sent

---

## Phase 5 — Integration Wiring

**Owns:** `src/run_daily.py`  
**Done by:** Main session after Phase 1–4 complete.

### run_daily.py
```python
# Flags: --live, --dry-run (default), --check, --only <agent>, --status-summary, --force-accept-manual-edit
def run_pipeline(live: bool, only: str | None, force_manual: bool):
    # 1. Init: verify/create CSV, verify integrity (or re-baseline if --force-accept-manual-edit)
    # 2. Scraper: manager.run_all() → new scraped rows → data_store.append_jobs()
    # 3. Filter+Apply: match.filter_jobs() → apply each → data_store.update_job()
    # 4. Persist+Commit: recompute hash → git add + commit + push (failure = warning, not crash)
    # 5. Notify: digest.build_digest() + send_digest()
    # 6. Record run state

def check_command():
    # Print whether today's 7 PM run happened

def status_summary():
    # Print per-status counts from CSV
```

### End-to-end smoke test
```bash
python -m src.run_daily --dry-run
# Must complete full pipeline, zero crashes, on fixture data
```

---

## Phase 6 — Final Commit & Push

- `git add -A`
- `git commit -m "feat: initial production build"`
- `git push`
- Print final repo tree
- Update MEMORY.md with all module statuses → Done

---

## Dependencies Between Phases

```
Phase 0 (scaffold) → Phase 1, 2, 3, 4 (parallel) → Phase 5 (wiring) → Phase 6 (push)
```

Phases 1–4 are fully independent — they write to separate directories and call `data_store` only through its public interface (which Phase 1 implements). Agents for 2, 3, 4 should use stub/mock calls to data_store during their isolated build, then wire to the real implementation in Phase 5.

---

## Risk Register

| Risk | Mitigation |
|---|---|
| LinkedIn/Naukri DOM changes break scraper | Plugin pattern isolates impact; one fix = one file |
| CAPTCHA on all platforms simultaneously | Per-platform failure is non-fatal; digest shows 0 scrapes |
| Gmail SMTP rate limit | One email/day (digest) + one/interview (brief); well within limits |
| Anthropic API latency | Brief generation is async; 2000 token cap keeps it fast |
| Chrome profile expires (login session) | Health check in `--check` flag; user re-logs in manually |
| CSV corruption | SHA-256 guard detects immediately; `--force-accept-manual-edit` as escape hatch |
| Mac asleep at 7 PM | Claude remote control fallback documented in README |
