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
- `run_state.json` structure: `{agents, llm_spend, skipped: {platforms, jobs}}`
- `record_agent_success(agent: str, summary: str)`
- `record_agent_failure(agent: str, error: str)`
- `did_run_today(agent: str, expected_hour: int = 19) -> bool`
- `get_llm_spend_today() -> float`
- `add_llm_spend(usd: float)`
- `reset_daily_spend_if_new_day()`
- `record_skipped_platform(platform: str, reason: str)` — appends to `skipped.platforms`
- `record_skipped_job(job: dict, reason: str)` — appends to `skipped.jobs` (id, company, title, url, reason, ts, retried=false)
- `get_unretried_platforms() -> list[dict]` — returns `skipped.platforms` where `retried=false`
- `get_unretried_jobs() -> list[dict]` — returns `skipped.jobs` where `retried=false`
- `mark_retried_platform(platform: str)` — sets `retried=true` for all matching platform entries
- `mark_retried_job(job_id: str)` — sets `retried=true` for the matching job entry

### Smoke tests
- Bulk append 100 rows under filelock, assert zero row loss
- Tamper CSV (mutate a byte), assert `IntegrityError` raised
- `--force-accept-manual-edit` re-baselines and allows read
- `did_run_today()` returns True/False correctly
- `record_skipped_platform` + `get_unretried_platforms` round-trip correctly
- `mark_retried_platform` sets flag; `get_unretried_platforms` no longer returns it

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
class LoginError(Exception): ...

class BaseScraper(ABC):
    platform: ClassVar[str]
    LOGIN_INDICATORS: ClassVar[list[str]] = []  # URL substrings / CSS selectors → logged-out

    @abstractmethod
    async def scrape(self, keywords: list[str], locations: list[str], limit: int) -> list[JobDict]: ...

    async def open_context(self, headless: bool, user_data_dir: str) -> tuple[Browser, BrowserContext]: ...
    async def is_logged_out(self, page: Page) -> bool: ...
    async def login(self, page: Page, vault: CryptoVault) -> None: ...
```

`JobDict` TypedDict: `{title, company, platform, url, apply_type, ctc, yoe_required, location, posted_at}`

### manager.py
- `discover_plugins(enabled: list[str]) -> list[BaseScraper]` — scans `plugins/` dir, imports matching modules
- `run_all(settings, vault: CryptoVault) -> list[JobDict]` — sequential loop; for each platform:
  1. Open page → call `is_logged_out()`
  2. If logged out → `login(page, vault)` → retry scrape once
  3. `LoginError` → log + skip platform (non-fatal)
  4. 3 sequential CAPTCHA failures → skip platform, log alert
  5. Any other exception → log traceback, return partial, continue
- Each scraper: randomized viewport, human-like delays (2–6 s), gentle scrolling

### Plugin pattern (each plugin)
```python
class LinkedInScraper(BaseScraper):
    platform = "linkedin"
    LOGIN_INDICATORS = ["linkedin.com/login", "linkedin.com/authwall"]

    async def login(self, page: Page, vault: CryptoVault) -> None:
        creds = vault.get("linkedin")           # {"method": "google_sso", "google_email": ...}
        await page.goto("https://www.linkedin.com/login")
        await page.click("text=Sign in with Google")
        # Select google_email account in popup, wait for feed redirect
        await page.wait_for_url("**/feed**", timeout=30_000)

    async def scrape(self, keywords, locations, limit) -> list[JobDict]:
        # open_context → is_logged_out → (login if needed) → navigate → extract
        ...

class NaukriScraper(BaseScraper):
    platform = "naukri"
    LOGIN_INDICATORS = ["naukri.com/nlogin", "#usernameField"]

    async def login(self, page: Page, vault: CryptoVault) -> None:
        creds = vault.get("naukri")             # {"method": "password", "username": ..., "password": ...}
        await page.goto("https://www.naukri.com/nlogin/login")
        await page.fill("#usernameField", creds["username"])
        await page.fill("#passwordField", creds["password"])
        await page.press("#passwordField", "Enter")
        await page.wait_for_url("**naukri.com**", timeout=20_000)
        if "nlogin" in page.url:
            raise LoginError("Naukri login failed")

# All other platforms follow the same password pattern as Naukri
```

### crypto_vault.py — required
- `CryptoVault(key: bytes)` — loads `config/credentials.enc`, decrypts with Fernet on first `get()` call (lazy)
- `vault.get(platform: str) -> dict` — returns credential dict; raises `KeyError` if platform not found
- Passwords held in memory only; never logged

### encrypt_creds.py — one-shot setup CLI
```bash
python src/scrapers/encrypt_creds.py
```
Interactive prompts for each platform. Writes `config/credentials.enc`. Safe to re-run to update a single platform's credentials.

### Smoke tests
- `--dry-run` on mocked Playwright returns ≥3 valid JobDicts schema-clean
- New plugin file auto-discovered (place fixture plugin, assert it appears in discovered list)
- Single platform exception does not prevent other platforms running
- Mocked logged-out page → `is_logged_out()` returns True → `login()` called → scrape retried
- `LoginError` from `login()` → platform skipped, other platforms unaffected
- `vault.get("linkedin")` returns `{"method": "google_sso", ...}`; `vault.get("naukri")` returns `{"method": "password", ...}`

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

Two sections live in the same file:

**Base profile fields** (pre-seeded, user-editable):
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
  "willing_to_relocate": "Yes",
  "work_authorization": "Indian Citizen"
}
```

**`learned_mappings`** — auto-grown at runtime. Maps raw form-label (lowercased) → profile key. When a label maps to a key that is NOT yet in the profile (i.e. a genuinely new field), the user is prompted, the value is added to the profile, and the mapping is stored:
```json
{
  "learned_mappings": {
    "expected compensation": "expected_ctc",
    "years of experience": "years_experience",
    "current notice period": "notice_period",
    "are you open to relocation": "willing_to_relocate",
    "current_salary_band": "current_ctc"
    // ... grows automatically as new fields are encountered
  }
}
```

**Runtime growth example** — when the applier hits an unseen field `"Preferred work arrangement"`:
```json
// Before
{ "learned_mappings": { ... } }

// After user enters "Hybrid"
{
  "preferred_work_arrangement": "Hybrid",
  "learned_mappings": {
    "preferred work arrangement": "preferred_work_arrangement",
    ...
  }
}
```
This means each unique field label is only asked **once** across all platforms and all future runs.

### Apply flow (per platform, per job)
1. Load `form_profile.json` — base profile fields + `learned_mappings`
2. Open platform Playwright context (pre-logged-in Chrome profile)
3. Navigate to job URL
4. Detect apply type (Easy Apply vs external form)
5. For each form field:
   ```
   label = extract_field_label()          # e.g. "Current Notice Period"
   key   = fuzzy_match_learned_mappings(label)

   if key found AND key in profile:
       fill(profile[key])                 # auto-fill from stored value
   else:
       # NEW FIELD — prompt user
       value = input(f"New field '{label}': enter your answer: ")
       key   = slugify(label)             # e.g. "current_notice_period"

       # Persist value + mapping back to form_profile.json (atomic write)
       profile[key]                   = value
       profile["learned_mappings"][label] = key
       write_form_profile(profile)

       fill(value)
   ```
6. Upload resume PDF (`settings.paths.resume_pdf`)
7. DRY-RUN: log full submission payload (field → value pairs); update status → `applied` (tagged `dry_run=true`)
8. LIVE: click final submit → update status → `applied`, record `applied_at`
9. On error / unknown ATS / selector timeout: status → `manual_review`, preserve URL, continue to next job

**`write_form_profile(profile)`** must be atomic: write to a `.tmp` file first, then `os.replace()` to avoid partial-write corruption. Re-verify the written JSON parses cleanly before continuing.

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
- `build_digest(rows: list[dict], skipped: dict) -> str` — returns HTML string; `skipped` comes from `run_state.get_unretried_*()` calls
- `send_digest(html: str, settings: Settings)` — SMTP via Gmail
- HTML sections:
  1. Header: date + run summary (N applied, N found, N manual_review)
  2. **Needs your attention** (render only if non-empty):
     - Skipped platforms table: platform, reason, ts — each row includes the exact retry command
     - Manual review jobs table: title, company, hyperlinked URL, reason — footer includes the bulk retry command
  3. Pipeline funnel: `interview_scheduled`, `offer`, `rejected`, `applied` counts
  4. Footer: "generated by job-hunter"
- Send even on zero-activity days
- Unretried skipped items from **previous runs** also appear in section 2 — they persist until resolved

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
- Runs standalone (cron once daily at 9 PM IST)
- `poll()`:
  1. `reset_daily_spend_if_new_day()`
  2. Compute `tomorrow = (now_IST + 1 day).date()`
  3. Read rows with `status='interview_scheduled'`
  4. Filter: `interview_date` (as IST date) == tomorrow
  5. For each: check `get_llm_spend_today() < DAILY_LLM_USD_CAP`
  6. If cap OK: `generate_brief()`, `send_brief()`, `add_llm_spend(estimated_usd)`
  7. If cap exceeded: send "cap reached" email notice, stop processing remaining interviews
  8. Corrupt/unparseable row → log warning, skip, continue

### Smoke tests
- `test_digest.py`: fixture with 5 rows (2 applied, 1 manual_review, 1 interview_scheduled, 1 rejected) + 1 skipped platform + 1 skipped job → HTML contains "Needs your attention" section with both tables; retry commands present; SMTP mocked
- Zero-activity fixture, no skipped items → no "Needs your attention" section rendered
- Skipped items from a previous run (retried=false, different date) → still appear in digest
- `test_brief.py`: fixture rows with interviews tomorrow → briefs generated (mocked Anthropic); `add_llm_spend` called per brief; fixture row with interview today or day-after-tomorrow → skipped; spending at $1.00 → cap notice sent, remaining briefs skipped
- `test_retry.py`: `run_state` with 1 unretried platform + 2 unretried jobs → `run_retry()` calls scraper only for that platform; calls apply only for the 2 unretried jobs + any new scrapes; `mark_retried_*` called for all attempted items

---

## Phase 5 — Integration Wiring

**Owns:** `src/run_daily.py`  
**Done by:** Main session after Phase 1–4 complete.

### run_daily.py
```python
# Flags: --live, --dry-run (default), --check, --only <agent>, --status-summary,
#        --force-accept-manual-edit, --retry-skipped, --retry-platform <name>

def run_pipeline(live: bool, only: str | None, force_manual: bool):
    # 1. Init: verify/create CSV, integrity check (or re-baseline)
    # 2. Scraper: manager.run_all() → append new jobs; record any skipped platforms via run_state.record_skipped_platform()
    # 3. Apply: filter → apply → update statuses; record any manual_review jobs via run_state.record_skipped_job()
    # 4. Persist+Commit: recompute hash → git add + commit + push (failure = warning)
    # 5. Notify: digest.build_digest(rows, skipped=run_state.get_all_unretried()) + send_digest()

def run_retry(platforms: list[str] | None, live: bool):
    """
    --retry-skipped:        platforms = run_state.get_unretried_platforms()
    --retry-platform <name>: platforms = [name]

    Retry pipeline:
    1. Init (same as normal)
    2. Retry scraper: manager.run_platforms(platforms) → append new jobs
       → run_state.mark_retried_platform(p) for each attempted platform
    3. Retry apply:
       (a) apply to jobs newly scraped in step 2
       (b) apply to all CSV rows with status=manual_review AND in run_state.get_unretried_jobs()
       → run_state.mark_retried_job(id) for each attempted job (win or lose)
    4. Persist+Commit (same as normal)
    5. Notify (same as normal — digest reflects retry outcomes)
    """

def check_command():
    # Print whether today's 7 PM run happened; also print count of unretried skipped items

def status_summary():
    # Print per-status counts from CSV + list of unretried skipped items
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
