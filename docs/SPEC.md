# Technical Specification — Job Hunter

**Version:** 1.0  
**Date:** 2026-06-17  
**Author:** Yash Deshmukh (yashdeshmukh7@gmail.com)

---

## 1. System Overview

Job Hunter is a macOS-resident Python pipeline that:

1. Scrapes job listings from 8 Indian/global job boards daily at 7 PM IST
2. Filters listings against a fixed criteria set (title, CTC, YOE, location, dedup)
3. Auto-applies to matched jobs using Playwright (dry-run by default, live with `--live`)
4. Persists all state in a plain CSV with cryptographic integrity
5. Emails a daily HTML digest
6. Generates AI-powered interview prep briefs 1 hour before interviews

The system is designed for single-user use, sequential execution, and complete crash-safety. Every step is independently fault-tolerant.

---

## 2. Environment & Runtime

| Attribute | Value |
|---|---|
| Language | Python 3.11+ |
| OS | macOS (Ventura or later) |
| Browser | Chromium via Playwright (headless) |
| Dependency manager | pip, pinned `requirements.txt` |
| Execution | Sequential (no concurrent agent execution) |
| Schedule | macOS cron or launchd |
| Timezone | Asia/Kolkata (IST, UTC+5:30) |

---

## 3. Configuration System

### 3.1 config/settings.toml

Full schema (all fields required unless marked optional):

```toml
[general]
enabled_plugins = [
  "linkedin", "naukri", "indeed", "instahyre",
  "wellfound", "weworkremotely", "hirist", "cutshort"
]

[search]
keywords  = ["Senior Backend Engineer", "SDE 2", "SDE 3", "Staff Engineer",
             "Lead Backend Engineer", "Senior Software Engineer"]
locations = ["Pune", "Bengaluru", "Hyderabad", "Remote"]

[limits]
scrape_per_platform       = 5
apply_attempts_per_platform = 5

[filter]
min_ctc_lpa    = 38.0     # 38 LPA must lie within stated CTC range
target_yoe     = 5        # 5 YOE must lie within stated YOE range
full_time_only = true
titles = [
  "SDE 2", "SDE 3",
  "Senior Software Engineer", "Senior Backend Engineer",
  "Lead Engineer", "Staff Engineer"
]

[schedule]
daily_run_cron  = "30 13 * * *"   # 7:00 PM IST = 13:30 UTC
brief_poll_cron = "30 15 * * *"   # 9:00 PM IST = 15:30 UTC

[paths]
resume_pdf = "config/resume.pdf"   # Yash_resume_v3.pdf — committed to repo

[runtime]
headless  = true
timezone  = "Asia/Kolkata"

[chrome_profiles]
# Map platform slug → absolute path to Chrome user-data-dir
# User must log in to each platform in its dedicated profile once
linkedin        = ""
naukri          = ""
indeed          = ""
instahyre       = ""
wellfound       = ""
weworkremotely  = ""
hirist          = ""
cutshort        = ""
```

### 3.2 src/config.py

Typed dataclass loader. Loads `config/settings.toml` at import time. Overrides from environment where applicable. Raises `ConfigError` on missing required fields.

```python
@dataclass
class Settings:
    enabled_plugins: list[str]
    keywords: list[str]
    locations: list[str]
    scrape_per_platform: int
    apply_attempts_per_platform: int
    min_ctc_lpa: float
    target_yoe: int
    full_time_only: bool
    titles: list[str]
    resume_pdf: Path
    headless: bool
    timezone: str
    chrome_profiles: dict[str, str]
    # From env:
    master_crypto_key: bytes
    gmail_app_password: str
    anthropic_api_key: str
    anthropic_model: str
    daily_llm_usd_cap: float
```

### 3.3 Environment variables

| Variable | Type | Description |
|---|---|---|
| `MASTER_CRYPTO_KEY` | str (base64 Fernet key) | Used by `crypto_vault.py` for optional credential encryption |
| `GMAIL_APP_PASSWORD` | str | Gmail App Password (16-char, not account password) |
| `ANTHROPIC_API_KEY` | str | Anthropic API key |
| `ANTHROPIC_MODEL` | str | Model ID (e.g. `claude-sonnet-4-6`) |
| `DAILY_LLM_USD_CAP` | float (str) | Hard daily spend cap (default `1.00`) |

---

## 4. Data Layer Specification

### 4.1 CSV schema

**Path:** `src/data/job_applications.csv`  
**Encoding:** UTF-8  
**Newline:** `\n` (Unix)

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID4 string | Primary key, set on insert, never changed |
| `title` | string | Raw title from scraper |
| `company` | string | Normalized (stripped whitespace) |
| `platform` | string | One of enabled_plugins values |
| `url` | string | Absolute URL, direct to posting |
| `apply_type` | string | `easy_apply` or `external_form` |
| `status` | string | See status enum below |
| `ctc` | string or empty | Raw string from listing, e.g. "30-50 LPA" |
| `yoe_required` | string or empty | Raw string, e.g. "3-6 years" |
| `location` | string | City name |
| `applied_at` | ISO 8601 | Timezone-aware, Asia/Kolkata; empty until applied |
| `interview_date` | ISO 8601 | Set when user updates; empty until scheduled |
| `next_steps` | string | Free text; may be empty |
| `last_activity` | ISO 8601 | Updated on every status change |

### 4.2 Status enum

```
scraped → [filter passes] → applied | manual_review
applied → [company responds] → interview_scheduled | rejected
interview_scheduled → [outcome] → offer | rejected
offer → [user decides] → (terminal — no further system updates)
manual_review → (user handles outside the system)
```

### 4.3 Integrity guard

- Sidecar: `src/data/job_applications.csv.sha256` contains `sha256:<hex_digest>`
- Hash computed over raw bytes of the CSV file
- On every `read_all()` / `read_by_status()` call: recompute hash, compare to sidecar
- Mismatch → raise `IntegrityError("manual edit detected: hash mismatch")`
- On every `append_jobs()` / `update_job()` call: recompute and overwrite sidecar
- `--force-accept-manual-edit` calls `integrity.baseline()` to re-baseline before reading

### 4.4 Concurrency

- All CSV writes use `filelock.FileLock("src/data/job_applications.csv.lock")`
- Lock timeout: 30 seconds (raises `Timeout` if exceeded)
- Only one process writes at a time (pipeline is sequential by design)

### 4.5 Run state

**Path:** `src/data/run_state.json`

```json
{
  "agents": {
    "scraper": {
      "last_success_ts": "2026-06-17T19:05:12+05:30",
      "last_task_summary": "Scraped 23 jobs across 7 platforms",
      "last_status": "success"
    },
    "filter_apply": { ... },
    "persist_commit": { ... },
    "notify": { ... }
  },
  "llm_spend": {
    "date": "2026-06-17",
    "usd": 0.42
  }
}
```

---

## 5. Scraper Module Specification

### 5.1 Architecture

Plugin-based. Each platform is a class in `src/scrapers/plugins/<platform>.py` that extends `BaseScraper`. The manager auto-discovers plugins by iterating `settings.enabled_plugins` and importing `src.scrapers.plugins.<slug>`.

**Inspired by:** santifer/career-ops provider pattern (JS ESM → Python class adaptation)

### 5.2 BaseScraper interface

```python
class BaseScraper(ABC):
    platform: ClassVar[str]           # must match settings slug
    LOGIN_INDICATORS: ClassVar[list[str]] = []  # URL fragments / selectors that mean "logged out"

    async def scrape(
        self,
        keywords: list[str],
        locations: list[str],
        limit: int,
        headless: bool,
        user_data_dir: str,
    ) -> list[JobDict]:
        ...

    async def open_context(
        self, headless: bool, user_data_dir: str
    ) -> tuple[Browser, BrowserContext]:
        """Launch Playwright with randomized viewport + pre-logged-in Chrome profile."""

    async def is_logged_out(self, page: Page) -> bool:
        """Return True if the current page looks like a login/auth wall."""

    async def login(self, page: Page, vault: CryptoVault) -> None:
        """Platform-specific re-login. Raises LoginError on failure."""
```

### 5.3 JobDict contract

```python
class JobDict(TypedDict):
    title: str
    company: str
    platform: str
    url: str                         # absolute, direct to posting
    apply_type: Literal["easy_apply", "external_form"]
    ctc: str | None                  # raw string from listing
    yoe_required: str | None         # raw string
    location: str | None
    posted_at: datetime              # timezone-aware
```

### 5.4 Stealth requirements

Each scraper must:
- Set randomized viewport: `width` in [1280, 1366, 1440, 1920], `height` in [720, 768, 900, 1080]
- Wait 2–6 seconds (random) before any page action
- Scroll gradually (50px at a time, 200ms intervals) rather than jumping to bottom
- Use the platform's configured Chrome user-data-dir (keeps cookies, localStorage, etc.)

### 5.5 Failure handling

Per-platform, per-invocation:
- **Logged-out detected** → attempt re-login (see §5.8); retry scrape once; on second failure → log + skip platform
- Network error → log warning, return partial results, continue to next platform
- CAPTCHA detected (3 consecutive) → log `"CAPTCHA alert: {platform} blocked"`, skip platform
- `LoginError` (re-login failed) → log `"Login failed: {platform} — check credentials.enc"`, skip platform
- Selector timeout → log, return partial results
- Any other exception → log full traceback, return `[]` for this platform, continue

### 5.6 Platform roster

| Platform | Apply type | Notes |
|---|---|---|
| LinkedIn | easy_apply | EasyApply flow; multi-step modal |
| Naukri | easy_apply | Native apply button + form |
| Indeed | external_form | Usually redirects to ATS |
| Instahyre | easy_apply | Profile-based apply |
| Wellfound | easy_apply | AngelList/Wellfound native |
| WeWorkRemotely | external_form | Redirects to company ATS |
| Hirist | easy_apply | Tech-focused India board |
| CutShort | easy_apply | AI-matched; profile-based |

### 5.7 Credential vault

`src/scrapers/crypto_vault.py` — **required** (not optional). Fernet-AES encryption. Key from `MASTER_CRYPTO_KEY` env var. Encrypted store at `config/credentials.enc` — never committed (in `.gitignore`).

**Schema of `credentials.enc` (decrypted JSON):**
```json
{
  "linkedin":       { "method": "google_sso", "google_email": "yashdeshmukh7@gmail.com" },
  "naukri":         { "method": "password",   "username": "yashdeshmukh7@gmail.com", "password": "..." },
  "indeed":         { "method": "password",   "username": "yashdeshmukh7@gmail.com", "password": "..." },
  "instahyre":      { "method": "password",   "username": "yashdeshmukh7@gmail.com", "password": "..." },
  "wellfound":      { "method": "password",   "username": "yashdeshmukh7@gmail.com", "password": "..." },
  "weworkremotely": { "method": "password",   "username": "yashdeshmukh7@gmail.com", "password": "..." },
  "hirist":         { "method": "password",   "username": "yashdeshmukh7@gmail.com", "password": "..." },
  "cutshort":       { "method": "password",   "username": "yashdeshmukh7@gmail.com", "password": "..." }
}
```

**`CryptoVault` API:**
```python
class CryptoVault:
    def __init__(self, key: bytes): ...
    def get(self, platform: str) -> dict:
        """Decrypt credentials.enc, return entry for platform. Raises KeyError if missing."""
```

**`encrypt_creds.py`** — one-shot CLI to write/update `credentials.enc`:
```bash
python src/scrapers/encrypt_creds.py
# Interactive: prompts for each platform's credentials, writes config/credentials.enc
```

### 5.8 Session-expiry detection and re-login

The manager calls `is_logged_out()` immediately after opening the platform page and before scraping. On detection, it calls `login()` and retries once.

**Logged-out detection (per platform):**

| Platform | Indicator |
|---|---|
| LinkedIn | URL contains `linkedin.com/login` or `linkedin.com/authwall` |
| Naukri | URL contains `naukri.com/nlogin` or login form selector `#usernameField` present |
| Indeed | URL contains `indeed.com/account/login` |
| Instahyre | URL contains `instahyre.com/login` |
| Wellfound | URL contains `wellfound.com/login` or `angel.co/login` |
| WeWorkRemotely | Not applicable (public board — no login required) |
| Hirist | URL contains `hirist.tech/login` |
| CutShort | URL contains `cutshort.io/login` |

**Re-login flows:**

**LinkedIn — Google SSO:**
```
1. Navigate to linkedin.com/login
2. Click "Sign in with Google"
3. Google auth popup appears — select account "yashdeshmukh7@gmail.com"
4. Wait for redirect back to linkedin.com/feed (timeout 30s)
5. If still on auth page after 30s → raise LoginError
```

**All other platforms — username/password:**
```
1. creds = vault.get(platform)          # {"method": "password", "username": ..., "password": ...}
2. Navigate to platform login URL
3. Fill username field with creds["username"]
4. Fill password field with creds["password"]
5. Click submit / press Enter
6. Wait for redirect away from login page (timeout 20s)
7. If login page still visible after timeout → raise LoginError
```

**`LoginError`** — custom exception in `src/scrapers/base.py`. Caught by manager; triggers skip + log. Never propagates to the pipeline level.

**Security:** Passwords are decrypted in memory only, never logged, never stored in plaintext on disk.

---

## 6. Filter Module Specification

### 6.1 Filter pipeline

Applied sequentially to each scraped job. A job passes only if ALL gates pass.

**Gate 1: Full-time check**
```
reject if title or description contains (case-insensitive):
  "contract", "contractor", "intern", "internship", "freelance",
  "part-time", "part time", "temporary", "temp"
```

**Gate 2: Title match** (adapted from career-ops `role-matcher.mjs`)
```
normalize(title):
  lowercase
  strip stop words: ["senior", "lead", "staff", "principal", "remote",
                     "india", "bangalore", "pune", "hyderabad", "at", "for"]
  tokenize

for each allowed_title in settings.filter.titles:
  normalize(allowed_title) → allowed_tokens
  compute Jaccard(title_tokens, allowed_tokens)
  if Jaccard >= 0.5 AND shared_tokens >= 1: PASS

if no allowed_title matched: FAIL
```

**Gate 3: CTC / YOE rule**
```
parse_ctc_lpa(ctc_str) → (min_lpa, max_lpa) | None
parse_yoe_range(yoe_str) → (min_yoe, max_yoe) | None

if ctc_parsed:
    pass if min_lpa <= 38.0 <= max_lpa
elif yoe_parsed:
    pass if min_yoe <= 5 <= max_yoe
else:
    PASS (neither stated → keep)
```

**Gate 4: Location**
```
allowed = {"pune", "bengaluru", "bangalore", "hyderabad", "remote", "work from home"}
normalize location to lowercase
pass if any(loc in normalized_location for loc in allowed)
```

**Gate 5: Company dedup**
```
normalize(company): lowercase, strip " inc", " ltd", " pvt", " private", " limited", ".com"
pass if normalized_company not in {normalize(c) for c in existing_companies}
```

### 6.2 CTC parsing spec

Handles formats found on Indian job boards:
```
"30-50 LPA"      → (30.0, 50.0)
"₹30L - ₹50L"   → (30.0, 50.0)
"30 to 50 LPA"   → (30.0, 50.0)
"30L"            → (30.0, 30.0)   # single value → treat as exact
"30,00,000"      → (30.0, 30.0)   # rupees → convert to LPA (÷100000)
"$80k-$120k"     → None           # USD → skip (out of scope)
```

### 6.3 YOE parsing spec

```
"3-6 years"     → (3, 6)
"3+ years"      → (3, 99)
"minimum 3 yrs" → (3, 99)
"3 to 6 years"  → (3, 6)
```

---

## 7. Apply Module Specification

### 7.1 Form profile

`src/apply/form_profile.json` — **the single persistent store for everything the applier knows about form fields**. Read at the start of every apply session; written back atomically whenever a new field is encountered. The file grows over time and never shrinks — so each unique field label is asked at most once across all runs and all platforms.

```json
{
  "name": "Yash Deshmukh",
  "email": "yashdeshmukh7@gmail.com",
  "phone": "",
  "linkedin_url": "",
  "github_url": "",
  "resume_path": "",
  "years_experience": 5,
  "current_ctc": "",
  "expected_ctc": "38+",
  "notice_period": "30 days",
  "willing_to_relocate": "Yes",
  "work_authorization": "Indian Citizen",
  "cover_letter_default": "",
  "learned_mappings": {
    "expected compensation": "expected_ctc",
    "years of experience": "years_experience",
    "current salary": "current_ctc",
    "notice period": "notice_period"
  }
}
```

**Runtime growth example** — first time the applier hits `"Preferred work arrangement"`:
```json
// After user enters "Hybrid":
{
  ...
  "preferred_work_arrangement": "Hybrid",   // ← new value stored at top level
  "learned_mappings": {
    ...,
    "preferred work arrangement": "preferred_work_arrangement"  // ← new mapping stored
  }
}
```
Next time any platform shows this label, it auto-fills `"Hybrid"` with no prompt.

### 7.2 Apply flow

```
for each filtered job (up to apply_attempts_per_platform per platform):
  1. navigate to job.url
  2. detect_apply_type() → "easy_apply" | "external_form" | "unknown_ats"
  3. if "unknown_ats" or detection fails:
       update status → "manual_review"
       continue
  4. begin_apply_flow()
  5. for each form field:
       label = extract_field_label()            # raw text, e.g. "Current Notice Period"
       norm  = label.lower().strip()
       key   = fuzzy_match_learned_mappings(norm, profile["learned_mappings"])

       if key and key in profile:
           fill(profile[key])                   # known field — auto-fill silently
       else:
           # NEW FIELD — prompt user, persist value + mapping
           value = input(f"New field '{label}': ")
           key   = slugify(norm)                # e.g. "current_notice_period"
           profile[key] = value
           profile["learned_mappings"][norm] = key
           write_form_profile_atomic(profile)   # tmp file → os.replace()
           fill(value)
  6. upload_resume(settings.paths.resume_pdf)
  7. if --dry-run:
       log_submission_payload()
       update status → "applied" (tagged as dry_run)
  8. if --live:
       click_submit()
       update status → "applied"
       record applied_at
```

### 7.3 Cap enforcement

```
per_platform_attempt_count = defaultdict(int)
if per_platform_attempt_count[platform] >= settings.limits.apply_attempts_per_platform:
    skip job (log: "cap reached for {platform}")
```

Both `applied` and `manual_review` outcomes count as an attempt.

### 7.4 ATS fallback taxonomy

| ATS | Detection | Action |
|---|---|---|
| Workday | URL contains "myworkdayjobs.com" or "wd3.myworkday" | → manual_review |
| Greenhouse | URL contains "greenhouse.io" | → manual_review |
| Lever | URL contains "lever.co" | → manual_review |
| iCIMS | URL contains "icims.com" | → manual_review |
| Unknown / timeout | Selector not found within 15s | → manual_review |

---

## 8. Notify Module Specification

### 8.1 Daily digest email

**Trigger:** Final step of every daily pipeline run.  
**Sender:** SMTP via Gmail App Password  
**Recipient:** `yashdeshmukh7@gmail.com`  
**Subject:** `Job Hunter — Daily Digest [YYYY-MM-DD]`  
**Format:** HTML

**Required sections:**
1. **Run summary** — date/time, N jobs found, N auto-applied, N flagged for manual review
2. **Manual review table** — all `manual_review` rows, each as a hyperlinked row (title, company, platform, URL)
3. **Pipeline funnel** — `interview_scheduled` count, `offer` count, `rejected` count, `applied` count
4. **Footer** — "Generated by job-hunter • {timestamp}"

**Zero-activity day:** Email is still sent. Run summary shows "No new applications today."

### 8.2 Interview brief email

**Trigger:** `run_brief_poller.py` runs once at 9 PM IST daily and generates briefs for all rows with `status=interview_scheduled` whose `interview_date` falls on the next calendar day (midnight to midnight IST).  
**Subject:** `Interview Brief — {company} ({title}) tomorrow at {time}`  
**Format:** HTML

**Required sections:**
1. **Role summary** — title, company, location, JD URL (from CSV row)
2. **System design topics** — 3–5 topics most relevant to this company's likely stack
3. **Deep-dive questions** — 5 questions tailored to company + role
4. **Resume alignment** — 3 bullets from Yash's profile that map strongest to this JD
5. **Company context** — funding stage, engineering blog if known, team size

**Prompt injected to Anthropic API:**
```
You are helping Yash Deshmukh prepare for an interview at {company} for the role of {title}.

Yash's profile:
- 5 YOE, Senior Backend Engineer
- Stack: Java, Spring Boot, Kafka, Cassandra, AWS
- Scale: ~1M RPM pipelines, ~680 GB/day streaming across distributed Kafka + Cassandra clusters
- Notable: Designed and operates large-scale event-driven microservice architectures

Job URL: {url}
Interview in: {minutes_until} minutes

Generate:
1. Top 3–5 system design topics to review for this interview
2. 5 deep-dive technical questions tailored to {company}'s likely stack/challenges
3. 3 of Yash's experience bullets that best align with this role
4. Any known context about {company}'s engineering culture or recent technical content

Be specific and actionable. Yash is reading this 1 hour before the call.
```

### 8.3 LLM spend tracking

```python
# Before each Anthropic call:
if run_state.get_llm_spend_today() >= settings.daily_llm_usd_cap:
    send_cap_notice_email(settings)
    return

# After each Anthropic call:
estimated_usd = (input_tokens * 0.000003) + (output_tokens * 0.000015)  # sonnet pricing
run_state.add_llm_spend(estimated_usd)
```

---

## 9. Pipeline Entrypoints

### 9.1 run_daily.py

**CLI flags:**

| Flag | Description |
|---|---|
| `--dry-run` | Default. Scrape + filter + render digest. No form submit. |
| `--live` | Enables final form submission step. |
| `--check` | Print whether today's 7 PM run happened. No pipeline execution. |
| `--only <agent>` | Run a single agent: `init`, `scraper`, `apply`, `persist`, `notify` |
| `--status-summary` | Print per-status counts. No pipeline execution. |
| `--force-accept-manual-edit` | Re-baseline integrity hash before running. |

**Execution order:**
```
1. init_agent:     load settings, verify/create CSV, integrity check (or re-baseline)
2. scraper_agent:  manager.run_all() → append new jobs to CSV
3. apply_agent:    filter → apply → update statuses
4. persist_agent:  recompute hash → git add + commit + push
5. notify_agent:   build digest → send email
```

Each agent:
- Records start in `run_state.json`
- Catches all exceptions, logs them, records failure
- Pipeline continues to next agent regardless

### 9.2 run_brief_poller.py

Standalone script. Designed to run once per day via cron at 9 PM IST. Generates briefs for all interviews scheduled on the next calendar day.

```python
def poll():
    run_state.reset_daily_spend_if_new_day()
    now = datetime.now(tz=IST)
    tomorrow = (now + timedelta(days=1)).date()

    interviews = data_store.read_by_status("interview_scheduled")
    next_day_interviews = [
        job for job in interviews
        if parse_iso(job["interview_date"]).astimezone(IST).date() == tomorrow
    ]

    for job in next_day_interviews:
        interview_dt = parse_iso(job["interview_date"]).astimezone(IST)
        if run_state.get_llm_spend_today() >= settings.daily_llm_usd_cap:
            send_cap_notice_email(settings)
            break  # cap hit — no point continuing; remaining jobs skipped
        try:
            brief_html = brief.generate_brief(job, settings)
            brief.send_brief(brief_html, interview_dt, settings)
            run_state.add_llm_spend(estimated_usd)
        except Exception as e:
            log.warning(f"Brief failed for {job['company']}: {e}")
            continue  # always continue to next interview on error
```

---

## 10. Persist & Commit Step

After `apply_agent` completes:

```python
def persist_and_commit():
    integrity.baseline()  # recompute + write sidecar
    try:
        subprocess.run(["git", "add",
            "src/data/job_applications.csv",
            "src/data/job_applications.csv.sha256",
            "src/data/run_state.json"], check=True)
        subprocess.run(["git", "commit", "-m",
            f"data: daily run {datetime.now(IST).strftime('%Y-%m-%d %H:%M %Z')}"],
            check=True)
        subprocess.run(["git", "push"], check=True)
    except subprocess.CalledProcessError as e:
        log.warning(f"git push failed (non-fatal): {e}")
        # Pipeline continues — next agent runs normally
```

Git failure is always non-fatal. The CSV is the source of truth on disk regardless of push status.

---

## 11. Security Constraints

1. **No secrets in code.** All credentials from environment variables only.
2. **`.env` in `.gitignore`.** Never committed.
3. **No plain-text credential storage.** Chrome profiles store sessions implicitly (browser-managed). Optional `crypto_vault.py` uses Fernet (AES-128-CBC + HMAC) if any credential must be stored.
4. **No logging of secrets.** Loggers must never include passwords, keys, or tokens.
5. **CSV is readable.** It contains job titles, URLs, and status — not personal financial data. Acceptable to commit.
6. **`form_profile.json` contains email and phone.** Not committed if user adds real values. Base skeleton with empty fields is committed.

---

## 12. Reuse from santifer/career-ops

| Career-ops component | Language | Adapted to job-hunter as |
|---|---|---|
| `providers/` plugin pattern | JavaScript ESM | `src/scrapers/plugins/` Python classes |
| `role-matcher.mjs` Jaccard matching | JavaScript | `src/apply/match.py::title_matches()` |
| `providers/ashby.mjs` salary annualization | JavaScript | `src/apply/match.py::parse_ctc_lpa()` |
| `tracker.mjs` dedup logic | JavaScript | `src/common/data_store.py::get_companies()` |
| `scan.mjs` CAPTCHA detection + skip | JavaScript | `src/scrapers/manager.py` failure handling |
| `data/DATA_CONTRACT.md` user vs system data | Pattern | `src/data/` (user) vs `src/` (system) |
| Form learned mappings | Concept | `src/apply/form_profile.json::learned_mappings` |
| Status states pattern | Pattern | CSV `status` enum |
| `doctor.mjs` health check | JavaScript | `python -m src.run_daily --check` |
| `config/profile.example.yml` | YAML | `config/settings.toml` + `.env.example` |

License: career-ops is MIT. Full attribution in README.

---

## 13. Success Criteria

The build is complete when all of the following are true:

- [ ] Private repo at `github.com/ydeshmukh30/job-hunter`, committed and pushed
- [ ] `pip install -r requirements.txt && playwright install chromium` succeeds
- [ ] `python -m src.run_daily --dry-run` completes full pipeline on fixture data, zero crashes
- [ ] `pytest src/tests/ -v` — all tests pass
- [ ] CSV integrity guard detects tampered CSV and blocks
- [ ] `--force-accept-manual-edit` re-baselines and allows continuation
- [ ] A new file dropped in `src/scrapers/plugins/` is auto-discovered
- [ ] Single platform failure in scraper does not abort other platforms
- [ ] Digest HTML renders all required sections (verified in test)
- [ ] Brief poller respects `$1.00/day` LLM cap (verified in test)
- [ ] `python -m src.run_daily --status-summary` prints correct counts
- [ ] `python -m src.run_daily --check` correctly reports missed/completed run
- [ ] README "How to Run" section is complete and accurate
