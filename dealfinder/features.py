"""The true brand of a listing, read from its title (Part 1).

The raw ``Product.brand`` field is often the *retailer*, not the manufacturer
("Walmart - COWIN", "Target"), so trusting it would poison anything built on it.
The true brand lives in the title. ``title_brand`` extracts it from a known-brand
vocabulary, longest match first. ``parse_condition`` reads new / refurb / used
from the same title. Later parts turn both into price features.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Brand — extracted from the TITLE.
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


# ANCHOR: title-brand
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
# ANCHOR_END: title-brand


# ---------------------------------------------------------------------------
# Condition — parsed from the title (new / refurb / used).
# ---------------------------------------------------------------------------
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
