import pytest
from pydantic import ValidationError

from dealfinder.extract import ListingSpecs, parse_llm_json, rule_extract


def test_rule_extract_pulls_typed_fields():
    s = rule_extract("TrailLite UL2 — ultralight 2-person tent, just 1.1kg, 3-season")
    assert s.brand == "TrailLite"
    assert s.capacity == 2
    assert s.weight_kg == 1.1
    assert s.season == 3


def test_rule_extract_handles_grams_and_sleeps():
    s = rule_extract("BasecampCo family tent (sleeps 3), 2-season, 2400 g")
    assert s.brand == "BasecampCo"
    assert s.capacity == 3
    assert s.weight_kg == 2.4   # grams normalized to kg
    assert s.season == 2


def test_parse_llm_json_validates_into_schema():
    s = parse_llm_json('{"brand": "SummitPro", "capacity": 4, "weight_kg": 3.2, "season": 4}')
    assert isinstance(s, ListingSpecs)
    assert s.capacity == 4 and s.weight_kg == 3.2


def test_schema_rejects_wrong_types():
    # structured output's whole point: a malformed field is caught, not ingested
    with pytest.raises(ValidationError):
        ListingSpecs(brand="X", capacity="lots", weight_kg=1.0, season=3)
