"""Pick which resume variant to send for a given job.

Implements the decision procedure in ``resumes/BOARDS.md`` — that file, not
this one, is the spec.  Nine PDFs on two axes:

* **Board variants (07-09)** vary how the document is *built*, because
  keyword-first, human-read and semantic-match boards screen through
  incompatible machinery.
* **Role variants (01-06)** vary what work is *emphasised*.

The order matters and is easy to get backwards: **board first, role only as an
override.**  A LinkedIn Easy Apply upload is parsed by an ATS before any human
sees it, so it gets the keyword-first file even for a job whose content
screams "infrastructure".  Content only beats format once a human is reading —
which, on LinkedIn, means recruiter outreach rather than the apply form.  Hence
``channel``.

Scoring is a weighted keyword count over title + description.  A model call per
job would be slower, cost money on every poll, and be no more accurate at
picking between six known buckets.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Final

log = logging.getLogger(__name__)

RESUME_DIR: Final[Path] = Path.home() / "Desktop" / "cognizant" / "interview" / "resumes"
PDF_DIR: Final[Path] = RESUME_DIR / "pdf"

# The base document when a human is reading and the JD names no speciality.
DEFAULT_VARIANT: Final[str] = "Yash_Deshmukh_SDE3"

# Board variant per platform — BOARDS.md steps 1-3.  Anything uploaded into a
# form is keyword-first regardless of who posted it.
BOARD_VARIANT: Final[dict[str, str]] = {
    "linkedin": "Yash_Deshmukh_Resume_LinkedIn_Indeed",
    "indeed": "Yash_Deshmukh_Resume_LinkedIn_Indeed",
    "naukri": "Yash_Deshmukh_Resume_LinkedIn_Indeed",
    "hirist": "Yash_Deshmukh_Resume_LinkedIn_Indeed",
    "cutshort": "Yash_Deshmukh_Resume_LinkedIn_Indeed",
    "weworkremotely": "Yash_Deshmukh_Resume_Remote",
    "wellfound": "Yash_Deshmukh_Resume_Startup",
    "instahyre": "Yash_Deshmukh_Resume_LinkedIn_Indeed",
}

# Keys are PDF stems, matching what `resumes/build.sh` actually emits into
# pdf/.  They were previously LaTeX-source slugs ("01-sde3-faang"), which no
# built file has ever been named — so every lookup raised ResumeNotBuilt and
# auto-apply was blocked 100% of the time.
#
# variant -> (weight, pattern).  Higher weight = stronger signal.
_SIGNALS: Final[dict[str, list[tuple[int, str]]]] = {
    "Yash_Deshmukh_SDE3": [
        (3, r"\b(sde\s*-?\s*[23]|sde[23])\b"),
        (2, r"\b(distributed systems?|low[- ]latency|high[- ]scale|scalab\w+)\b"),
        (2, r"\b(faang|big\s?tech)\b"),
        (1, r"\b(backend|back[- ]end|java|spring boot|microservices?)\b"),
    ],
    "Yash_Deshmukh_AI_Engineer": [
        (3, r"\b(llm|genai|gen[- ]ai|generative ai|rag|prompt engineer\w*)\b"),
        (3, r"\b(machine learning|\bml\b|deep learning|nlp)\b"),
        (2, r"\b(pytorch|tensorflow|langchain|vector (db|database)|embedding)\b"),
        (2, r"\bai engineer\b"),
    ],
    # There is no separate data-platform resume, so the Kafka/Spark/Airflow
    # signals land here — closest of the six to a streaming-infra pitch.
    "Yash_Deshmukh_Systems_Infrastructure": [
        (3, r"\b(platform engineer|infrastructure engineer|\bsre\b|site reliability)\b"),
        (3, r"\b(data engineer|data platform|analytics engineer)\b"),
        (2, r"\b(kubernetes|k8s|terraform|docker|devops|ci/cd)\b"),
        (2, r"\b(observability|prometheus|grafana|service mesh)\b"),
        (2, r"\b(kafka|spark|flink|airflow|dbt)\b"),
        (2, r"\b(etl|elt|data (pipeline|warehouse|lake)|streaming)\b"),
        (1, r"\b(aws|gcp|azure|cloud)\b"),
    ],
    "Yash_Deshmukh_Product_Engineer": [
        (3, r"\b(product engineer|full[- ]stack|fullstack)\b"),
        (2, r"\b(react|next\.?js|typescript|frontend|front[- ]end)\b"),
    ],
    "Yash_Deshmukh_Forward_Deployed_Engineer": [
        (4, r"\b(forward[- ]deployed|\bfde\b)\b"),
        (3, r"\b(solutions? engineer|customer[- ]facing|implementation engineer)\b"),
        (2, r"\b(professional services|deployment engineer)\b"),
    ],
    "Yash_Deshmukh_Founding_Engineer": [
        (4, r"\bfounding engineer\b"),
        (3, r"\b(0\s*to\s*1|zero to one)\b"),
        (2, r"\b(early[- ]stage|seed[- ]stage|first engineer\w*)\b"),
    ],
}

_COMPILED: Final[dict[str, list[tuple[int, re.Pattern[str]]]]] = {
    variant: [(w, re.compile(p, re.IGNORECASE)) for w, p in sigs]
    for variant, sigs in _SIGNALS.items()
}

# A signal at this weight or above means the JD is *explicitly* about that
# flavour of work — the bar BOARDS.md sets for a role variant to override the
# board default.  Lower weights corroborate; they never decide.
_EXPLICIT_WEIGHT: Final[int] = 3


class ResumeNotBuilt(RuntimeError):
    """A variant was selected but its compiled PDF does not exist."""


def score_variants(title: str, description: str = "") -> dict[str, int]:
    """Return the raw score for every variant against this job text."""
    text = f"{title} {description}"
    return {
        variant: sum(weight for weight, pat in sigs if pat.search(text))
        for variant, sigs in _COMPILED.items()
    }


def pick_variant(
    title: str,
    description: str = "",
    platform: str = "linkedin",
    channel: str = "form",
) -> str:
    """Return the PDF stem to send, per the BOARDS.md decision procedure.

    ``channel`` is what actually reads the file first:

    * ``"form"`` — Easy Apply, an ATS portal, any upload field.  The board
      variant wins unconditionally; a parser is doing string comparison and
      does not care how well the content matches.
    * ``"human"`` — a recruiter InMail, where a person opens the attachment.
      Here a role variant beats the board default, but only when the JD is
      *explicitly* about that flavour of work.  "Explicitly" is the >= 3-weight
      signals: a title string or a defining technology, not the weight-1 and -2
      corroborators.  Otherwise a Kubernetes mention in a general backend req
      would send the niche infra resume, which BOARDS.md warns against.
    """
    if channel == "form":
        # Unknown platform still means a form, so keyword-first is the safe default.
        return BOARD_VARIANT.get(platform, "Yash_Deshmukh_Resume_LinkedIn_Indeed")

    text = f"{title} {description}"
    explicit = {
        variant
        for variant, sigs in _COMPILED.items()
        if any(w >= _EXPLICIT_WEIGHT and pat.search(text) for w, pat in sigs)
    }
    if not explicit:
        log.debug("no explicit role signal in %r — defaulting to %s", title, DEFAULT_VARIANT)
        return DEFAULT_VARIANT

    scores = score_variants(title, description)
    return max(sorted(explicit), key=lambda v: scores[v])


def resume_pdf_for(
    title: str,
    description: str = "",
    platform: str = "linkedin",
    channel: str = "form",
) -> Path:
    """Return the PDF path for the chosen variant, raising if it isn't built."""
    variant = pick_variant(title, description, platform, channel)
    pdf = PDF_DIR / f"{variant}.pdf"
    if not pdf.exists():
        raise ResumeNotBuilt(
            f"Resume variant {variant!r} selected but {pdf} does not exist.\n"
            f"Compile the variants first:\n"
            f"    brew install tectonic && {RESUME_DIR}/build.sh"
        )
    return pdf


def available_variants() -> dict[str, bool]:
    """Map every variant this module can select to whether its PDF exists."""
    stems = set(_SIGNALS) | set(BOARD_VARIANT.values())
    return {v: (PDF_DIR / f"{v}.pdf").exists() for v in sorted(stems)}


if __name__ == "__main__":
    # Self-check: each variant must win on its own signature phrase.
    # channel="human": a recruiter opens the attachment, so role beats board.
    human = [
        ("Senior AI Engineer, LLM platform", "Yash_Deshmukh_AI_Engineer"),
        ("Staff Platform Engineer - Kubernetes", "Yash_Deshmukh_Systems_Infrastructure"),
        ("Forward Deployed Engineer", "Yash_Deshmukh_Forward_Deployed_Engineer"),
        ("Senior Data Engineer, Kafka & Spark", "Yash_Deshmukh_Systems_Infrastructure"),
        ("Product Engineer (Full-Stack, React)", "Yash_Deshmukh_Product_Engineer"),
        ("Founding Engineer, 0 to 1", "Yash_Deshmukh_Founding_Engineer"),
        ("SDE 3 - Distributed Systems", "Yash_Deshmukh_SDE3"),
        ("Senior Software Engineer", "Yash_Deshmukh_SDE3"),  # no explicit signal
        # Weight-2 corroborators must NOT override: a general backend req that
        # happens to name Kubernetes and AWS is still a general backend req.
        ("Senior Backend Engineer (Kubernetes, AWS, Docker)", "Yash_Deshmukh_SDE3"),
    ]
    for title, expected in human:
        got = pick_variant(title, channel="human")
        assert got == expected, f"{title!r}: expected {expected}, got {got} ({score_variants(title)})"

    # channel="form": an ATS parses first, so the board variant always wins —
    # even when the content is unmistakably about one speciality.
    form = [
        ("linkedin", "Yash_Deshmukh_Resume_LinkedIn_Indeed"),
        ("wellfound", "Yash_Deshmukh_Resume_Startup"),
        ("weworkremotely", "Yash_Deshmukh_Resume_Remote"),
        ("some-new-board", "Yash_Deshmukh_Resume_LinkedIn_Indeed"),  # unknown -> keyword-first
    ]
    for platform, expected in form:
        got = pick_variant("Forward Deployed Engineer, LLM infra", platform=platform)
        assert got == expected, f"{platform}: expected {expected}, got {got}"

    print(f"resume_picker: {len(human) + len(form)} cases pass")
    for variant, built in available_variants().items():
        print(f"  {'OK ' if built else 'MISSING'}  {variant}")
