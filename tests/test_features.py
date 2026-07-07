"""Broad-electronics features: title-brand extraction, tiers, condition, vector.

Uses the real snapshot titles (retailer-polluted `brand` fields) to prove the
manufacturer is recovered from the TITLE, not the raw field (spec §4).
"""
from dealfinder.features import (
    FEATURE_NAMES,
    brand_tier,
    category_code,
    condition_code,
    featurize,
    parse_condition,
    title_brand,
)
from dealfinder.schema import Product


def _headphones(title, brand, category="audio", price=99.0):
    return Product(
        id="x", title=title, brand=brand, category=category,
        price=price, url="http://x", source="snapshot",
    )


def test_title_brand_ignores_retailer_field():
    # Raw brand is the RETAILER ("Walmart - COWIN", "costco.com") — the true
    # manufacturer must come from the title.
    assert title_brand("Sony WH-1000XM5 Wireless Headphones") == "Sony"
    assert title_brand("Bose QuietComfort 45 Wireless Noise Cancelling Headphones") == "Bose"
    assert title_brand("Cowin SE7 Active Noise Cancelling Headphones") == "Cowin"


def test_title_brand_first_token_fallback():
    # Unknown brand → fall back to a plausible first token; junk → None.
    assert title_brand("Dazone Dual 6.5 inch Woofer Portable Speaker") == "Dazone"
    assert title_brand("4k monitor") is None  # lowercase / generic


def test_brand_tier_ranks_flagship_over_budget():
    # Bose/Sony (flagship) outrank Anker/Soundcore (budget) — this is the signal
    # that separates the honest deal from the trap.
    assert brand_tier("Sony WH-1000XM5 Wireless Headphones") == 4
    assert brand_tier("Bose QuietComfort 45 Wireless Noise Cancelling Headphones") == 4
    assert brand_tier("Anker Soundcore Q20i Hybrid ANC Headphones") == 2
    assert brand_tier("Some Noname Earbuds 12345") == 1


def test_parse_condition():
    assert parse_condition("Sony WH-1000XM5 Wireless Headphones") == "new"
    assert parse_condition("Bose QC45 (Certified Refurbished)") == "refurb"
    assert parse_condition("Dell XPS 13 Open-Box") == "refurb"
    assert parse_condition("iPhone 13 Pre-Owned") == "used"


def test_category_and_condition_codes():
    assert category_code("audio") != category_code("computers")
    assert category_code("nonsense-category") == category_code("misc")
    assert condition_code("new") > condition_code("refurb") > condition_code("used")


def test_featurize_shape_and_values():
    p = _headphones("Sony WH-1000XM5 Wireless Headphones", brand="costco.com")
    f = featurize(p)
    assert len(f) == len(FEATURE_NAMES) == 3
    # category_code(audio), brand_tier(Sony=4), condition_code(new=2)
    assert f == [float(category_code("audio")), 4.0, 2.0]
