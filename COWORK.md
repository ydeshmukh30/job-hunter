# Claude Cowork — daily job-hunt brief

Point Cowork at this repo and schedule the task below **daily at 8:00 PM IST**.

## What Cowork owns, and what it does not

Cowork is a knowledge-work agent: it reads and writes local files, works across
connected apps, and carries multi-step tasks to a deliverable. That is a good
description of resume tailoring and outreach drafting. It is not a good
description of a 30-minute browser poller.

Two reasons the fast loop stays in Python:

1. **Cadence.** Cowork schedules at human-readable cadences — "every weekday at
   8am", "first Monday of the month". The poller needs ~22 runs a day.
2. **Speed.** Cowork's browser control is Dispatch (computer use), which is
   explicitly a slow mode. Strategy 1's entire value is applying while a posting
   still has single-digit applicant counts. A computer-use loop clicking through
   LinkedIn is the opposite of that, 22 times a day, at token cost per run.

So the split is:

| Runtime | Owns | Cadence |
|---|---|---|
| **Python + launchd** | Poll LinkedIn, filter, dedup, auto-apply Easy Apply, push notifications | every 30 min |
| **Cowork** | Read the day's captures, tailor resumes, draft outreach, funding radar | daily |

The Python side leaves a clean handoff on disk. Cowork picks it up.

---

## The daily task

### 1. Read the day's captures

`src/data/job_applications.csv` is the source of truth. Take rows where
`last_activity` is today. Do not write to this file — the pipeline is its only
writer, and it is guarded by a SHA-256 sidecar that will refuse a hand edit.

### 2. Tailor a resume per job

For each job captured today, follow the protocol in
`~/Desktop/cognizant/interview/resumes/TAILORING.md`. The rule that matters, in
Yash's own words:

> Match their nouns. Keep your verbs and your mechanisms.

Do not paste the job description into a model and ask for a rewrite. That
produces a resume that reads the JD back to the recruiter, which is the thing
`TAILORING.md` exists to prevent.

The variant is already chosen by `src/apply/resume_picker.py` — six buckets
(`01-sde3-faang`, `02-ai-engineer`, `03-platform-engineer`,
`04-product-engineer`, `05-forward-deployed-engineer`, `06-data-platform`).
Start from that variant's `.tex` source; do not start from a blank page.

Write output to `src/data/tailored/<job-id>/`.

### 3. Funding radar (Strategy 3)

Read the RSS feeds listed under `[funding]` in `config/settings.toml` —
Inc42 and Entrackr. For each Indian startup that announced a round in the last
24 hours and is plausibly hiring backend engineers:

- Identify the CTO, VP Engineering, or Head of Engineering.
- Draft a LinkedIn DM, **300 characters maximum**.
- Pick the resume variant with `resume_picker.pick_variant()`.
- Write the draft to `src/data/outreach/<company>.md`.

Reach out *before* the job is posted. That is the entire point of the strategy.

### 4. Stage, never send

**Nothing in this task sends anything.** No LinkedIn messages, no connection
requests, no emails. Every draft lands on disk for Yash to review and send by
hand.

This is not a limitation to route around. LinkedIn's 2026 cap is 100 invitations
per week across every account tier, and what actually triggers restrictions is
high volume with low reply rates. A restricted account costs Yash the job hunt,
not just the automation.

---

## Guardrails

- **Never** run `python -m src.run_poller --live`. Auto-apply is the Python
  side's job and is gated deliberately.
- **Never** edit `src/data/job_applications.csv` or its `.sha256` sidecar.
- **Never** invent a metric, a company detail, or a funding number. If the feed
  does not say it, it does not go in the draft.
- Resume PDFs must exist before any auto-apply can work. If
  `~/Desktop/cognizant/interview/resumes/pdf/` is empty, say so — do not
  substitute the stale `config/resume.pdf`.
