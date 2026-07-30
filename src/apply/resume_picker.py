"""Pick which resume variant to send for a given job.

Yash maintains six role variants as LaTeX sources in
``~/Desktop/cognizant/interview/resumes/``.  Auto-apply uploads a PDF, so the
variants must be compiled first — see ``scripts/build_resumes.sh``.

Scoring is a weighted keyword count over title + description.  A model call per
job would be slower, cost money on every one of ~22 polls a day, and be no more
accurate at picking between six known buckets.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Final

log = logging.getLogger(__name__)

RESUME_DIR: Final[Path] = Path.home() / "Desktop" / "cognizant" / "interview" / "resumes"
PDF_DIR: Final[Path] = RESUME_DIR / "pdf"

DEFAULT_VARIANT: Final[str] = "01-sde3-faang"

# variant -> (weight, pattern).  Higher weight = stronger signal.
_SIGNALS: Final[dict[str, list[tuple[int, str]]]] = {
    "01-sde3-faang": [
        (3, r"\b(sde\s*-?\s*[23]|sde[23])\b"),
        (2, r"\b(distributed systems?|low[- ]latency|high[- ]scale|scalab\w+)\b"),
        (2, r"\b(faang|big\s?tech)\b"),
        (1, r"\b(backend|back[- ]end|java|spring boot|microservices?)\b"),
    ],
    "02-ai-engineer": [
        (3, r"\b(llm|genai|gen[- ]ai|generative ai|rag|prompt engineer\w*)\b"),
        (3, r"\b(machine learning|\bml\b|deep learning|nlp)\b"),
        (2, r"\b(pytorch|tensorflow|langchain|vector (db|database)|embedding)\b"),
        (2, r"\bai engineer\b"),
    ],
    "03-platform-engineer": [
        (3, r"\b(platform engineer|infrastructure engineer|\bsre\b|site reliability)\b"),
        (2, r"\b(kubernetes|k8s|terraform|docker|devops|ci/cd)\b"),
        (2, r"\b(observability|prometheus|grafana|service mesh)\b"),
        (1, r"\b(aws|gcp|azure|cloud)\b"),
    ],
    "04-product-engineer": [
        (3, r"\b(product engineer|full[- ]stack|fullstack)\b"),
        (2, r"\b(react|next\.?js|typescript|frontend|front[- ]end)\b"),
        (2, r"\b(0\s*to\s*1|zero to one|early[- ]stage|founding engineer)\b"),
    ],
    "05-forward-deployed-engineer": [
        (4, r"\b(forward[- ]deployed|\bfde\b)\b"),
        (3, r"\b(solutions? engineer|customer[- ]facing|implementation engineer)\b"),
        (2, r"\b(professional services|deployment engineer)\b"),
    ],
    "06-data-platform": [
        (3, r"\b(data engineer|data platform|analytics engineer)\b"),
        (3, r"\b(kafka|spark|flink|airflow|dbt)\b"),
        (2, r"\b(etl|elt|data (pipeline|warehouse|lake)|streaming)\b"),
        (2, r"\b(redshift|snowflake|bigquery|cassandra)\b"),
    ],
}

_COMPILED: Final[dict[str, list[tuple[int, re.Pattern[str]]]]] = {
    variant: [(w, re.compile(p, re.IGNORECASE)) for w, p in sigs]
    for variant, sigs in _SIGNALS.items()
}


class ResumeNotBuilt(RuntimeError):
    """A variant was selected but its compiled PDF does not exist."""


def score_variants(title: str, description: str = "") -> dict[str, int]:
    """Return the raw score for every variant against this job text."""
    text = f"{title} {description}"
    return {
        variant: sum(weight for weight, pat in sigs if pat.search(text))
        for variant, sigs in _COMPILED.items()
    }


def pick_variant(title: str, description: str = "") -> str:
    """Return the best-matching variant slug.

    Falls back to the SDE3 variant, which is the closest to Yash's default
    positioning as a senior backend engineer.
    """
    scores = score_variants(title, description)
    best = max(scores, key=lambda v: scores[v])
    if scores[best] == 0:
        log.debug("no resume signal in %r — defaulting to %s", title, DEFAULT_VARIANT)
        return DEFAULT_VARIANT
    return best


def resume_pdf_for(title: str, description: str = "") -> Path:
    """Return the PDF path for the best variant, raising if it isn't built."""
    variant = pick_variant(title, description)
    pdf = PDF_DIR / f"{variant}.pdf"
    if not pdf.exists():
        raise ResumeNotBuilt(
            f"Resume variant {variant!r} selected but {pdf} does not exist.\n"
            f"The variants are LaTeX sources only — compile them first:\n"
            f"    brew install tectonic && ./scripts/build_resumes.sh"
        )
    return pdf


def available_variants() -> dict[str, bool]:
    """Map every variant slug to whether its compiled PDF exists."""
    return {v: (PDF_DIR / f"{v}.pdf").exists() for v in sorted(_SIGNALS)}


if __name__ == "__main__":
    # Self-check: each variant must win on its own signature phrase.
    cases = [
        ("Senior AI Engineer, LLM platform", "02-ai-engineer"),
        ("Staff Platform Engineer - Kubernetes", "03-platform-engineer"),
        ("Forward Deployed Engineer", "05-forward-deployed-engineer"),
        ("Senior Data Engineer, Kafka & Spark", "06-data-platform"),
        ("Product Engineer (Full-Stack, React)", "04-product-engineer"),
        ("SDE 3 - Distributed Systems", "01-sde3-faang"),
        ("Senior Software Engineer", "01-sde3-faang"),  # no signal -> default
    ]
    for title, expected in cases:
        got = pick_variant(title)
        assert got == expected, f"{title!r}: expected {expected}, got {got} ({score_variants(title)})"
    print(f"resume_picker: {len(cases)} cases pass")
    for variant, built in available_variants().items():
        print(f"  {'OK ' if built else 'MISSING'}  {variant}")
