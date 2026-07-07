"""Turn a Product into the numeric feature vector the price model learns from.

Broad consumer electronics, not one narrow category (spec §4). A single feature
vector has to span audio, computers, displays, peripherals, storage, … so it is
built from fields that generalize across categories:

- ``category``   — ordinal code (the *kind* of thing sets the price scale).
- ``brand_tier`` — ranked, derived from the manufacturer we EXTRACT FROM THE
  TITLE. The raw ``Product.brand`` field is the *retailer* in 154/270 snapshot
  rows ("Walmart - COWIN", "Target"), so trusting it would poison the model;
  the true brand lives in the title.
- ``condition``  — new / refurb / used, ordinal, parsed from the title.

Everything the (simple, hand-feature) model knows, it knows through these three
columns. The signal hand-features can't carry for broad data — the title
embedding — is the Part-5/Part-17 upgrade; here we keep the vector legible.
"""
from __future__ import annotations

import re

from .schema import Product

FEATURE_NAMES = ["category_code", "brand_tier", "condition_code"]

# ---------------------------------------------------------------------------
# Category — ordinal code over the 11 snapshot categories (spec §4).
# ---------------------------------------------------------------------------
CATEGORY_CODES: dict[str, int] = {
    "accessories": 0,
    "peripherals": 1,
    "storage": 2,
    "audio": 3,
    "smart-home": 4,
    "wearables": 5,
    "mobile": 6,
    "components": 7,
    "displays": 8,
    "computers": 9,
    "misc": 10,
}


def category_code(category: str) -> int:
    """Ordinal code for a category; unknown categories fall in the ``misc`` bucket."""
    return CATEGORY_CODES.get((category or "").strip().lower(), CATEGORY_CODES["misc"])


# ---------------------------------------------------------------------------
# Brand — extracted from the TITLE, then ranked into a tier.
# ---------------------------------------------------------------------------
# Known manufacturers seen in the corpus, longest/multiword first so "JLab GO"
# beats a bare "GO". Matching is case-insensitive on a word boundary.
KNOWN_BRANDS: tuple[str, ...] = (
    "Amazon Basics", "Google Nest", "Ultimate Ears", "Western Digital",
    "Anker", "Soundcore", "Bose", "Sony", "JBL", "Samsung", "Logitech", "Razer",
    "Acer", "ASUS", "Apple", "Beats", "Skullcandy", "Sennheiser", "Keychron",
    "Glorious", "SteelSeries", "Corsair", "HyperX", "Dell", "HP", "Lenovo", "MSI",
    "LG", "Google", "Kindle", "Amazon", "PNY", "SanDisk", "Seagate", "WD",
    "Crucial", "Kingston", "JLab", "Onn", "LINSAY", "Shark", "Blink", "Roku",
    "TP-Link", "Wyze", "Ring", "Echo", "Cowin", "Marshall", "Sonos", "Nintendo",
    "Microsoft", "Intel", "AMD", "NVIDIA", "Netgear", "Belkin", "Yubico",
    "Fitbit", "Garmin", "Motorola",
)
# Deduplicate while preserving order, then sort longest-first for greedy match.
_BRAND_LIST = sorted(dict.fromkeys(KNOWN_BRANDS), key=len, reverse=True)
_BRAND_PATTERNS = [
    (b, re.compile(rf"\b{re.escape(b)}\b", re.IGNORECASE)) for b in _BRAND_LIST
]

# Ranked brand tiers (higher = commands a higher price). Derived from the
# title-extracted manufacturer, never the raw retailer field.
BRAND_TIER: dict[str, int] = {
    # tier 4 — premium flagships
    "Apple": 4, "Sony": 4, "Bose": 4, "Sonos": 4, "Sennheiser": 4, "Garmin": 4,
    # tier 3 — strong majors
    "Samsung": 3, "LG": 3, "Dell": 3, "Lenovo": 3, "HP": 3, "ASUS": 3, "Acer": 3,
    "MSI": 3, "Logitech": 3, "Razer": 3, "Beats": 3, "JBL": 3, "Marshall": 3,
    "Google": 3, "Google Nest": 3, "Nest": 3, "Microsoft": 3, "Nintendo": 3,
    "Ultimate Ears": 3, "SteelSeries": 3, "Corsair": 3, "HyperX": 3, "Fitbit": 3,
    # tier 2 — value / mid brands
    "Anker": 2, "Soundcore": 2, "JLab": 2, "Skullcandy": 2, "Keychron": 2,
    "Glorious": 2, "TP-Link": 2, "Wyze": 2, "Ring": 2, "Blink": 2, "Roku": 2,
    "SanDisk": 2, "Seagate": 2, "Western Digital": 2, "WD": 2, "Crucial": 2,
    "Kingston": 2, "PNY": 2, "Shark": 2, "Netgear": 2, "Belkin": 2, "Motorola": 2,
    "Cowin": 2, "Amazon Basics": 2, "Amazon": 2, "Kindle": 2, "Echo": 2,
    # tier 1 — everything else (unknown / no-name) via the default below.
    "Onn": 1, "LINSAY": 1,
}
DEFAULT_BRAND_TIER = 1


def title_brand(title: str) -> str | None:
    """Extract the true manufacturer from a listing title, or None if unknown.

    Tries the known-brand vocabulary first (greedy, longest match), falling back
    to the first title token when it looks like a proper brand name. This is the
    normalization the raw ``brand`` field can't give us — see module docstring.
    """
    if not title:
        return None
    for canonical, pat in _BRAND_PATTERNS:
        if pat.search(title):
            return canonical
    # Fallback: first token if it's capitalized/alnum and not a generic word.
    first = title.strip().split()[0] if title.strip().split() else ""
    first = first.strip(".,")
    if first and first[0].isalpha() and first[:1].isupper() and len(first) > 1:
        return first
    return None


def brand_tier(title: str) -> int:
    """Ranked price tier (1–4) for a title's extracted manufacturer."""
    brand = title_brand(title)
    return BRAND_TIER.get(brand or "", DEFAULT_BRAND_TIER)


# ---------------------------------------------------------------------------
# Condition — parsed from the title (new / refurb / used), ordinal.
# ---------------------------------------------------------------------------
CONDITION_CODES = {"new": 2, "refurb": 1, "used": 0}
_REFURB_RE = re.compile(
    r"\b(refurb(?:ished)?|renew(?:ed)?|recertified|open[\s-]?box)\b", re.IGNORECASE
)
_USED_RE = re.compile(r"\b(used|pre[\s-]?owned|preowned|second[\s-]?hand)\b", re.IGNORECASE)


def parse_condition(title: str) -> str:
    """Classify a title as new / refurb / used. Defaults to ``new`` when unmarked."""
    if not title:
        return "new"
    if _REFURB_RE.search(title):
        return "refurb"
    if _USED_RE.search(title):
        return "used"
    return "new"


def condition_code(condition: str) -> int:
    """Ordinal code for a condition string (new=2, refurb=1, used=0)."""
    return CONDITION_CODES.get((condition or "new").strip().lower(), CONDITION_CODES["new"])


# ---------------------------------------------------------------------------
# The feature vector.
# ---------------------------------------------------------------------------
def featurize(p: Product) -> list[float]:
    """The shared broad-electronics feature vector for one product.

    ``category_code``, ``brand_tier`` (from the title, not the retailer field),
    and ``condition_code`` (title-parsed, falling back to ``p.condition``).
    """
    cond = p.condition if p.condition else parse_condition(p.title)
    return [
        float(category_code(p.category)),
        float(brand_tier(p.title)),
        float(condition_code(cond)),
    ]


def feature_matrix(products: list[Product]):
    import numpy as np

    return np.array([featurize(p) for p in products], dtype=float)
