# Job Hunter v2 — minutes-old polling + funded-startup outreach

Status: implemented through Phase 4. Live verification blocked on a one-time
LinkedIn sign-in. 2026-07-30.

## Problem

The repo had 6,867 lines of Python, 138 passing tests, and had never scraped a
single real job. The tests ran against fixture HTML, so they proved nothing
about whether the scrapers worked — and reading the code showed most of them
could not have.

Separately, the highest-conversion part of a job hunt was missing entirely:
being early, and reaching a human directly.

## Strategy

Two plays, chosen by Yash from a job-search post he brought:

1. **Minutes-old jobs.** LinkedIn's `f_TPR` search parameter takes a window in
   seconds. At `r1800` you see postings with single-digit applicant counts
   instead of "100+". The `r` prefix is required — a bare `f_TPR=1800` is
   silently ignored, which is the kind of detail that makes a feature look
   implemented while doing nothing.
2. **Funded-startup outreach.** Newly funded Indian startups hire before they
   post. Inc42 and Entrackr publish free RSS. Reach the CTO before the job
   exists.

Rejected: the Top Applicant badge as a trigger. It requires ≥10 applicants on
the posting, which is mutually exclusive with reaching jobs at 0–5 applicants.
Dropping it also removed the need for LinkedIn Premium ($29.99/mo).

## Architecture

Two runtimes, split by what each is actually good at.

| Runtime | Owns | Cadence |
|---|---|---|
| Python + launchd | poll, filter, dedup, auto-apply Easy Apply, push | every 30 min |
| Claude Cowork | resume tailoring, outreach drafting, funding radar | daily |

Cowork does not own the fast loop. Its scheduler works in human-readable
cadences ("every weekday at 8am"), not 22 runs a day, and its browser control
is Dispatch/computer-use, which is explicitly a slow mode. Strategy 1's entire
value is speed. Putting a computer-use loop in the hot path would spend tokens
to be slower than the thing it replaced. `COWORK.md` is the handoff contract.

### Session strategy

One dedicated Chrome profile at `~/.chrome-jobhunter`, signed into once.

Two constraints found by testing, not assumption:

1. **Chrome ≥136 refuses `--remote-debugging-port` on the default profile.**
   Deliberate hardening against cookie-stealing malware. Chrome here is 150, so
   driving Yash's everyday profile is not possible regardless of approach.
2. **`connect_over_cdp` is broken on Playwright 1.60 + Chrome 150**, failing the
   handshake with `Browser.setDownloadBehavior: Browser context management is
   not supported`. So Playwright launches and owns Chrome via
   `launch_persistent_context` rather than attaching to an external one.

Consequence: the profile is locked during a run, so the manual login window must
be closed before the poller can drive it. `--login` opens it; the session then
persists indefinitely.

### Cadence

30-minute interval, 60-minute window. The window is deliberately wider than the
interval so a posting cannot fall through a gap between runs; the resulting
overlap re-surfaces jobs, which URL dedup absorbs.

launchd rather than cron: this laptop sleeps, and cron silently drops every slot
it slept through. For a 22-runs-a-day poller that is most of the coverage.

## Bugs fixed

All found by reading the code, all with regression tests in
`src/tests/test_matcher.py`.

| Where | Was | Now |
|---|---|---|
| `match.py` CTC gate | `min <= 38 <= max` — rejected "45-60 LPA" because `45 <= 38` is false | `max >= target` |
| `match.py` title gate | stripped `senior`/`staff`/`lead` as stopwords, then Jaccard ≥ 0.5 on `{engineer}` — admitted "QA Engineer" | three explicit gates: reject / core / seniority |
| `match.py` dedup | by company, against all rows including `scraped` — one role seen hid every future role there forever | by canonical job URL |
| `linkedin.py` selectors | logged-out DOM classes; zero matches on an authenticated session | authenticated classes with ordered fallbacks |
| `linkedin.py:18` | `IST = timezone.utc  # replaced in production` — never was | real `ZoneInfo("Asia/Kolkata")` |
| `linkedin.py` | hardcoded `ctc=None, yoe_required=None`, so the CTC gate was inert | unchanged, but now honest — LinkedIn cards genuinely lack CTC |

## Deleted

CDP-free session handling made an entire subsystem dead:
`crypto_vault.py`, `encrypt_creds.py`, `credentials.enc`, all eight `login()`
methods, `LoginError` retry paths, `MASTER_CRYPTO_KEY`, the `[chrome_profiles]`
config table, and the `cryptography` dependency. `run_daily.py` was replaced by
`run_poller.py` (fast half) and `run_digest.py` (daily half).

Seven of eight scraper plugins were removed from `enabled_plugins`. They have
never run live, so they are not working code — they are untested guesses that
would generate noise during debugging. Each earns its way back after LinkedIn is
proven.

## Safety

- Auto-apply is gated on `--live`, on Easy Apply, and on every form field being
  known. **Unknown field aborts and notifies.** Under launchd there is no tty,
  so the old `input()` prompt in the form-learning path would hang the run
  forever holding the profile lock.
- Nothing sends LinkedIn messages or connection requests. Drafts stage to disk.
  LinkedIn's 2026 cap is 100 invitations/week across all tiers, and what
  triggers restrictions is volume with low reply rates. A restricted account
  costs the job hunt, not just the automation.
- Resume PDFs must exist before auto-apply can work. The picker raises
  `ResumeNotBuilt` rather than silently falling back to a stale resume.

## Open

- **Live verification of the LinkedIn selectors.** Blocked on the one-time
  sign-in. `--probe` reports which selectors matched, so repair is a config
  edit, not a debugging session.
- **Resume PDFs.** The six variants exist as LaTeX only, and no TeX toolchain is
  installed. `scripts/build_resumes.sh` compiles them via tectonic.
- **Easy Apply submission.** Deliberately not wired until the modal has been
  seen on a live posting.
- **Strategy 3 implementation.** Feeds configured; the reader lives on the
  Cowork side per `COWORK.md`.
