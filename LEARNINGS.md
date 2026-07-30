# LEARNINGS — job-hunter

- 2026-07-30 — Poll interval is 30 minutes, not 15; window stays wider than the interval (60 min) so postings can't fall through a gap between runs.
- 2026-07-30 — Yash wants his existing logged-in Chrome used, not a new browser instance — but Chrome >=136 blocks automation on the default profile and copying its cookie DB is the malware pattern, so a one-time sign-in to a dedicated profile is the only workable path.
- 2026-07-30 — Passing tests against fixture HTML prove nothing about a scraper; the LinkedIn selectors targeted the logged-OUT DOM and would have returned zero cards forever. Verify against the live page before trusting any scraper here.
- 2026-07-30 — LinkedIn's `f_TPR` needs the `r` prefix (`r1800`, not `1800`); without it the time filter is silently ignored and the search looks like it works.
