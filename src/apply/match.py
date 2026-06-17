"""Filter logic for the job-hunter apply module.

Applies 5 sequential gates to a list of scraped jobs and returns those that pass all.
Gate order: full-time → title → CTC/YOE → location → dedup.
"""

from __future__ import annotations

import re
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stop-words stripped before tokenising job titles
# ---------------------------------------------------------------------------
_TITLE_STOPWORDS: frozenset[str] = frozenset(
    {
        "senior",
        "lead",
        "staff",
        "principal",
        "remote",
        "india",
        "bangalore",
        "pune",
        "hyderabad",
        "at",
        "for",
    }
)

# ---------------------------------------------------------------------------
# Keywords that indicate a non-full-time role
# ---------------------------------------------------------------------------
_NON_FULLTIME_PATTERNS: list[str] = [
    r"\bcontract(or)?\b",
    r"\bintern(ship)?\b",
    r"\bfreelance\b",
    r"\bpart[\s\-]?time\b",
    r"\btemporary\b",
    r"\btemp\b",
]
_NON_FULLTIME_RE = re.compile(
    "|".join(_NON_FULLTIME_PATTERNS),
    flags=re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Foreign-currency indicators — these make parse_ctc_lpa return None
# ---------------------------------------------------------------------------
_FOREIGN_CURRENCY_RE = re.compile(
    r"[\$£€]|SGD|AED|USD|GBP|EUR|CAD|AUD|HKD|JPY|CHF",
    flags=re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Allowed locations (normalised)
# ---------------------------------------------------------------------------
_ALLOWED_LOCATIONS: frozenset[str] = frozenset(
    {
        "pune",
        "bengaluru",
        "bangalore",
        "hyderabad",
        "remote",
        "work from home",
    }
)


# ===========================================================================
# Public API
# ===========================================================================


def filter_jobs(
    jobs: list[dict],
    existing_companies: set[str],
    settings,
) -> list[dict]:
    """Apply all 5 gates sequentially.  Return jobs that pass every gate.

    Args:
        jobs:               Raw list of scraped job dicts.
        existing_companies: Company names already present in the CSV tracker.
        settings:           A ``Settings`` dataclass with ``min_ctc_lpa``,
                            ``target_yoe``, and ``titles`` attributes.

    Returns:
        Subset of *jobs* that passed all 5 gates, preserving original order.
    """
    passed: list[dict] = []
    allowed_titles: list[str] = settings.titles
    target_ctc: float = settings.min_ctc_lpa
    target_yoe: int = settings.target_yoe

    for job in jobs:
        title: str = job.get("title", "") or ""
        company: str = job.get("company", "") or ""
        ctc_str: str | None = job.get("ctc") or None
        yoe_str: str | None = job.get("yoe_required") or None
        location: str | None = job.get("location") or None

        # Gate 1 — full-time check
        if not is_full_time(job):
            logger.debug("Gate 1 FAIL (not full-time): %s @ %s", title, company)
            continue

        # Gate 2 — title match
        if not title_matches(title, allowed_titles):
            logger.debug("Gate 2 FAIL (title): %s @ %s", title, company)
            continue

        # Gate 3 — CTC / YOE
        if not ctc_matches(ctc_str, yoe_str, target_ctc, target_yoe):
            logger.debug("Gate 3 FAIL (ctc/yoe): %s @ %s", title, company)
            continue

        # Gate 4 — location
        if not location_matches(location, list(_ALLOWED_LOCATIONS)):
            logger.debug("Gate 4 FAIL (location=%s): %s @ %s", location, title, company)
            continue

        # Gate 5 — company dedup
        if normalize_company(company) in {normalize_company(c) for c in existing_companies}:
            logger.debug("Gate 5 FAIL (dupe company): %s", company)
            continue

        passed.append(job)

    logger.info("filter_jobs: %d/%d jobs passed all gates", len(passed), len(jobs))
    return passed


def is_full_time(job: dict) -> bool:
    """Return False if the title contains a non-full-time indicator.

    Checks the ``title`` field (and ``description`` if present) for keywords
    such as contract, intern, freelance, part-time, temporary / temp.
    """
    text = (job.get("title") or "") + " " + (job.get("description") or "")
    return not bool(_NON_FULLTIME_RE.search(text))


def _normalise_title_tokens(title: str) -> frozenset[str]:
    """Lowercase, strip stop-words, tokenise on non-alphanumeric characters."""
    lowered = title.lower()
    # Split on any non-alphanumeric character
    tokens = re.split(r"[^a-z0-9]+", lowered)
    return frozenset(t for t in tokens if t and t not in _TITLE_STOPWORDS)


def title_matches(title: str, allowed_titles: list[str]) -> bool:
    """Fuzzy Jaccard match between *title* and any entry in *allowed_titles*.

    Normalisation:
    - Lowercase
    - Strip stop-words: senior, lead, staff, principal, remote, india,
      bangalore, pune, hyderabad, at, for
    - Tokenise on non-alphanumeric boundaries

    Match criterion (must satisfy **both**):
    - Jaccard(title_tokens, allowed_tokens) >= 0.5
    - len(shared_tokens) >= 1
    """
    job_tokens = _normalise_title_tokens(title)
    if not job_tokens:
        return False

    for allowed in allowed_titles:
        allowed_tokens = _normalise_title_tokens(allowed)
        if not allowed_tokens:
            continue
        shared = job_tokens & allowed_tokens
        if not shared:
            continue
        union = job_tokens | allowed_tokens
        jaccard = len(shared) / len(union)
        if jaccard >= 0.5 and len(shared) >= 1:
            return True

    return False


def ctc_matches(
    ctc_str: str | None,
    yoe_str: str | None,
    target_ctc: float,
    target_yoe: int,
) -> bool:
    """Three-branch CTC / YOE gate.

    Branch 1: If ``parse_ctc_lpa(ctc_str)`` succeeds → pass iff
              ``target_ctc`` ∈ [min_lpa, max_lpa].
    Branch 2: Else if ``parse_yoe_range(yoe_str)`` succeeds → pass iff
              ``target_yoe`` ∈ [min_yoe, max_yoe].
    Branch 3: Else (neither parseable, foreign currency included) → True.
    """
    ctc_range = parse_ctc_lpa(ctc_str)
    if ctc_range is not None:
        min_lpa, max_lpa = ctc_range
        return min_lpa <= target_ctc <= max_lpa

    yoe_range = parse_yoe_range(yoe_str)
    if yoe_range is not None:
        min_yoe, max_yoe = yoe_range
        return min_yoe <= target_yoe <= max_yoe

    # Neither parseable — keep
    return True


def parse_ctc_lpa(ctc_str: str | None) -> tuple[float, float] | None:
    """Parse an INR CTC string to an LPA range.

    Returns ``None`` for:
    - Foreign-currency strings (USD, GBP, SGD, EUR, AED, $, £, €, …)
    - Blank / None strings
    - Unparseable strings

    Handled formats:
    - "30-50 LPA"       → (30.0, 50.0)
    - "₹30L - ₹50L"    → (30.0, 50.0)
    - "30 to 50 LPA"   → (30.0, 50.0)
    - "30L"            → (30.0, 30.0)
    - "30,00,000"      → (30.0, 30.0)   (rupees ÷ 100_000)
    """
    if not ctc_str or not ctc_str.strip():
        return None

    s = ctc_str.strip()

    # Foreign-currency check — return None to "keep" the job
    if _FOREIGN_CURRENCY_RE.search(s):
        return None

    # Strip currency symbols and whitespace for easier parsing
    cleaned = re.sub(r"[₹,\s]", " ", s).strip()

    # Pattern: Indian comma-separated rupees (e.g. "30,00,000" after cleaning → "300000")
    # After cleaning commas we have a plain integer — detect by checking original had commas
    # and no "L"/"LPA" suffix
    original_no_space = re.sub(r"\s", "", s)
    if re.fullmatch(r"[\d,]+", original_no_space):
        # Pure number with commas → rupee amount
        rupees_str = original_no_space.replace(",", "")
        try:
            rupees = float(rupees_str)
            lpa = round(rupees / 100_000, 2)
            return (lpa, lpa)
        except ValueError:
            return None

    # Extract all numbers from the cleaned string
    # Supports: "30L", "30 L", "30 LPA", "30-50 LPA", "30 to 50 LPA"
    numbers = re.findall(r"\d+(?:\.\d+)?", cleaned)
    if not numbers:
        return None

    try:
        values = [float(n) for n in numbers]
    except ValueError:
        return None

    if len(values) == 1:
        return (values[0], values[0])
    elif len(values) >= 2:
        # Take the first two numbers as min/max
        lo, hi = values[0], values[1]
        if lo > hi:
            lo, hi = hi, lo
        return (lo, hi)

    return None


def parse_yoe_range(yoe_str: str | None) -> tuple[int, int] | None:
    """Parse a YOE string to an integer range.

    Supported formats:
    - "3-6 years"      → (3, 6)
    - "3+ years"       → (3, 99)
    - "minimum 3 yrs"  → (3, 99)
    - "3 to 6 years"   → (3, 6)
    - "3-7"            → (3, 7)

    Returns ``None`` for blank, None, or unparseable input.
    """
    if not yoe_str or not yoe_str.strip():
        return None

    s = yoe_str.strip().lower()

    # Pattern: "3+ years" or "3+"
    m = re.search(r"(\d+)\s*\+", s)
    if m:
        return (int(m.group(1)), 99)

    # Pattern: "minimum 3 yrs" / "min 3 years"
    m = re.search(r"min(?:imum)?\s+(\d+)", s)
    if m:
        return (int(m.group(1)), 99)

    # Pattern: "3-6 years" / "3 to 6 years" / "3-7" / "3 to 7"
    m = re.search(r"(\d+)\s*(?:-|to)\s*(\d+)", s)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo > hi:
            lo, hi = hi, lo
        return (lo, hi)

    # Single number — treat as "exactly N years" → (N, N)
    m = re.search(r"(\d+)", s)
    if m:
        val = int(m.group(1))
        return (val, val)

    return None


def location_matches(location: str | None, allowed_locations: list[str]) -> bool:
    """Case-insensitive check whether *location* is an allowed city / remote.

    Allowed set: pune, bengaluru, bangalore, hyderabad, remote, work from home.
    Returns True if any allowed value appears as a substring of the (lowercased)
    location string.
    """
    if not location:
        return False
    loc_lower = location.lower().strip()
    for allowed in allowed_locations:
        if allowed.lower() in loc_lower:
            return True
    return False


def normalize_company(name: str) -> str:
    """Lowercase and strip common corporate suffixes for dedup comparison.

    Suffixes removed: pvt, ltd, inc, private, limited, .com
    """
    if not name:
        return ""
    s = name.lower().strip()
    # Remove trailing punctuation + known suffixes iteratively
    suffixes = [
        r"\s+pvt\.?\s*ltd\.?$",
        r"\s+private\s+limited$",
        r"\s+pvt\.?$",
        r"\s+ltd\.?$",
        r"\s+limited$",
        r"\s+inc\.?$",
        r"\.com$",
    ]
    for pattern in suffixes:
        s = re.sub(pattern, "", s, flags=re.IGNORECASE).strip()
    return s
