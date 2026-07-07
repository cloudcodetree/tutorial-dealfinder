import pytest
from pydantic import ValidationError

from dealfinder.extract import ListingSpecs, parse_llm_json, rule_extract


def test_rule_extract_pulls_true_brand_from_retailer_polluted_title():
    # The raw listing carries the retailer ("Walmart - COWIN"); the true brand
    # must come from the title text.
    s = rule_extract("Walmart - COWIN SE7 Active Noise Cancelling Headphones Bluetooth")
    assert s.brand == "Cowin"
    assert s.category == "audio"
    assert s.condition == "new"


def test_rule_extract_pulls_brand_category_and_model():
    s = rule_extract("Sony WH-1000XM5 Wireless Headphones")
    assert s.brand == "Sony"
    assert s.category == "audio"
    assert s.model == "WH-1000XM5"


def test_rule_extract_parses_condition_from_title():
    s = rule_extract("Apple MacBook Air M2 (Refurbished) 13-inch Laptop")
    assert s.brand == "Apple"
    assert s.category == "computers"
    assert s.condition == "refurb"


def test_parse_llm_json_validates_into_schema():
    s = parse_llm_json(
        '{"brand": "Anker", "category": "audio", "condition": "new", "model": "Q20i"}'
    )
    assert isinstance(s, ListingSpecs)
    assert s.brand == "Anker" and s.model == "Q20i"


def test_schema_rejects_wrong_types():
    # structured output's whole point: a malformed field is caught, not ingested
    with pytest.raises(ValidationError):
        ListingSpecs(brand=123, category="audio", condition="new")
