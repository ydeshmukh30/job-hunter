# CSM branch — Customer Success Manager applications

This branch re-points the job-hunter pipeline at a **different candidate and a different
role family**: Vanshika Tewary, Customer Success Manager, rather than Yash Deshmukh,
Senior Backend Engineer.

Built 2026-09-02 against the
[LinkedIn CSM job-description template](https://business.linkedin.com/en-in/talent-solutions/resources/talent-acquisition/job-descriptions/customer-success-manager).

## What differs from `yash/feat/job-hunter-v2`

**No pipeline code is changed.** Scrapers, appliers, matcher, notifiers and tests are
untouched, so fixes on the base branch merge in cleanly. Only candidate configuration and
these documents differ:

| File | Change |
|---|---|
| `config/settings.toml` | CSM titles and keywords, Bengaluru/Mumbai locations, CTC floor disabled pending a real number, resume path repointed |
| `src/apply/form_profile.json` | Vanshika's identity; unconfirmed fields marked `[[NEED]]` |
| `docs/csm/` | This kit — the source of truth for everything above |

The markdown here is not decoration: it is where the config values come from. When
`settings.toml` says `titles = [...]`, `keyword-map.md` is the derivation.

## Read in this order

| # | File | What it gives you |
|---|---|---|
| 1 | [`gap-analysis.md`](gap-analysis.md) | **Start here.** Four gaps; two block applying at all. |
| 2 | [`jd-analysis.md`](jd-analysis.md) | 13 responsibilities collapsed into 4 themes + a requirements scorecard |
| 3 | [`resume.md`](resume.md) | Tailored resume — the source for `config/resume-vanshika-csm.pdf` |
| 4 | [`cover-letter.md`](cover-letter.md) | Reusable draft; hook rewritten per company |
| 5 | [`linkedin.md`](linkedin.md) | Headline + About rewrite, 7 ranked profile fixes |
| 6 | [`interview/star-stories.md`](interview/star-stories.md) | 6 STAR stories mapped to the 4 themes |
| 7 | [`interview/likely-questions.md`](interview/likely-questions.md) | Questions by stage, each routed to a story |
| 8 | [`interview/questions-to-ask.md`](interview/questions-to-ask.md) | 5 worth asking, 4 to avoid |
| 9 | [`outreach/email-templates.md`](outreach/email-templates.md) | 6 templates + timing table |
| — | [`profile-source.md`](profile-source.md) | Source facts from LinkedIn — the evidence base |
| — | [`job-description.md`](job-description.md) | The JD, verbatim |
| — | [`keyword-map.md`](keyword-map.md) | 45 ATS terms → where each is covered |

## The `[[NEED: ...]]` convention

**No metric here is invented.** Every claim traces to `profile-source.md`, taken from the
public LinkedIn profile. Where a number would make a bullet land, there is a
`[[NEED: ...]]` marker instead of a plausible-sounding figure — a number the candidate
cannot defend in an interview is worse than none at all.

The same convention now extends into the config:

```bash
grep -rn "\[\[NEED" config/ src/apply/form_profile.json docs/csm/
```

**`src/apply/form_profile.json` markers are load-bearing.** Unlike the documents, that file
is read by the applier at runtime — a `--live` run with placeholders still in it would type
`[[NEED: candidate phone]]` into a real application form. Fill them, or keep runs to the
default `--dry-run`.

## Before any live run

1. Close **Gap 1** (retention metrics) and **Gap 2** (CRM / CS platform names) in
   `gap-analysis.md`.
2. Fill the `[[NEED]]` markers in `resume.md`, then export to
   `config/resume-vanshika-csm.pdf`.
3. Fill every `[[NEED]]` in `src/apply/form_profile.json`.
4. Set `[filter] min_ctc_lpa` in `config/settings.toml` — it is currently `0.0`, which
   disables the floor rather than guessing one.
5. Write **Story 7** (expansion revenue) in `interview/star-stories.md` — the JD asks for
   upsell and no story covers it.
6. Decide whether `[notify] digest_recipient` moves from Yash's address to hers.

## Known limitation of this branch

It was authored on a machine with **Python 3.9**, and this project requires 3.11+. The
config changes are structurally validated but were **not** executed, and the 138-test suite
was not run here. Run it once on a 3.11+ machine before trusting the branch:

```bash
pytest
python -m src.run_daily --dry-run
```
