# Plan: daily 24h sweep → Easy Apply → top-applicant InMail

Supersedes the polling design in `PLAN.md` / `SPEC.md` (both predate the v2
rebuild and still describe `run_daily.py`, which no longer exists).

## Decisions taken

| Question | Decision |
|---|---|
| Window | 24 hours, once daily (`window_seconds = 86400`) — already in `settings.toml` |
| Outreach channel | LinkedIn InMail (Premium Career) |
| Actions | Auto-submit Easy Apply, **then** InMail the recruiter where Yash ranks top applicant |
| Sending | Messages are drafted and queued; nothing goes out without Yash pressing send |
| Non-top-applicant jobs | Recorded + push notification, no outbound action |
| Resume choice | `resumes/BOARDS.md` procedure — board variant for form uploads, role variant for InMail |
| Out of InMail credits | Fall back to a connection request with a short note (300 chars, free) |
| Apply cap | 5 submissions per day |
| Current CTC on forms | Answer with the expected figure (`38+`) in both fields |

## The constraint that shapes everything

**Premium Career grants ~5 InMail credits a month** (rollover to 3 months, so
~15 in hand at best). That is the entire outreach budget. A run that finds 40
qualifying jobs cannot message 40 recruiters. When the balance hits zero the
queue does not stop — it switches to a connection request with a 300-character
note, which is free and roughly unlimited, just lower-response and with no
attachment. So:

- InMail is reserved for top-applicant jobs, and even those get ranked before
  spending a credit.
- Credit spend is tracked in `run_state.json` alongside the existing LLM spend
  cap, and the queue refuses to grow past the remaining balance.
- The queue is ordered best-first so that if only two credits remain, they go
  to the two best jobs, not the two scraped earliest.

## Why applying comes before messaging

LinkedIn's applicant-ranking insight ("You're a top applicant", "top 25% of
applicants") is part of Premium *applicant* insights. On most posts it is only
populated once you are in the applicant pool. Ordering apply → check → message
is therefore not a preference, it is likely the only order in which the signal
exists. **Phase 0 verifies this against a live post before anything is built on
it.**

---

## Phase 0 — probe the live DOM (blocking, do first)

Nothing below this line can be written honestly without seeing the real page.
`LEARNINGS.md` already records the cost of guessing: the original scraper
targeted the logged-out DOM and would have returned zero cards forever, with a
green test suite the whole time.

Extend `--probe` to open the first search result's **detail page** and dump
candidate selectors for:

1. The top-applicant / applicant-insight block — is it present pre-apply?
2. "Meet the hiring team" — is a named poster exposed, and is there a Message
   button? Many posts have neither.
3. The Easy Apply button and the **first modal step's field list**, so
   `form_profile.json` can be populated from reality rather than invention.
4. Whether InMail accepts an attachment from Premium Career, or whether the
   resume has to go in as a link.

Output is a JSON dump committed to `docs/probe/` so the selector decisions have
a dated source.

**Open question this settles:** if the badge turns out to be post-apply only,
the pipeline needs a second pass — apply today, check ranking tomorrow — which
is a different shape than a single daily run.

## Phase 1 — pagination

`linkedin.py:scrape_context` loads one page per location and scrolls it. That
was correct for a 60-minute window; against 24 hours it silently caps at
roughly the newest 25 cards per location and drops the rest. Add pagination
with a hard page cap, plus per-page jitter to stay under LinkedIn's rate
limiting.

## Phase 2 — Easy Apply submission

The submit path does not exist: `run_poller.py:133` logs `would submit` and
increments a counter. The three appliers under `src/apply/platforms/` are
orphaned code written for the deleted `run_daily` pipeline — read them for
reference, then delete them rather than reviving them.

Guardrail contract, unchanged from the existing comment:

- Abort the application on any field absent from `form_profile.json`. Never
  guess.
- **Never call `input()`.** Under launchd there is no tty; a prompt would hang
  forever holding the Chrome profile lock and wedge every subsequent run.
- Unknown field → push notification, job marked `manual_review`, move on.
- `--live` still gates submission. Default stays dry-run.

Resume for this path is always the board variant (`Resume_LinkedIn_Indeed`),
per `BOARDS.md` step 1 — an ATS parses it before a human sees it.

## Phase 3 — top-applicant detection and the InMail queue

For each job submitted in phase 2, read the ranking signal. Where it says top
applicant *and* a hiring-team contact is exposed:

1. Pick the resume with `resume_picker.resume_pdf_for(..., channel="human")` —
   role variant, because a person opens this one.
2. Draft the message with one Anthropic call, against the JD text and
   `INTERVIEW_DELIVERY.md` numbers. Existing `DAILY_LLM_USD_CAP` applies.
3. Write the draft to `src/data/outreach_queue/` and push a notification.
4. Yash reviews and sends. A `--send-approved` command performs the send for
   drafts he has marked approved, and decrements the credit counter.

Message rules are inherited from `00-RULES.md`, not invented here: no em
dashes, no robot vocabulary, no restating the JD back at the reader, overlap
hours stated in the recruiter's timezone.

## Phase 4 — schedule

Rewrite `scripts/com.yash.jobhunter.poller.plist` from `StartInterval 1800` to
a daily `StartCalendarInterval`. `NTFY_TOPIC` must be set inside the plist —
launchd agents do not read the shell profile.

---

## Not doing, and why

- **No auto-send of InMail.** Explicitly declined. A bad draft reaching a real
  recruiter under Yash's name has no undo and costs a scarce credit.
- **No email-address guessing.** InMail was chosen over SMTP; pattern-guessing
  `first.last@company.com` bounces and burns domain reputation.
- **Not reviving the orphaned appliers.** 750 lines targeting a pipeline that
  no longer exists.
