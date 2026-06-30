from dealfinder.evals import ab_compare, evaluate, exact_match
from dealfinder.extract import ListingSpecs, rule_extract


def test_exact_match():
    a = ListingSpecs(brand="X", capacity=2, weight_kg=1.1, season=3)
    b = ListingSpecs(brand="X", capacity=2, weight_kg=1.1, season=3)
    c = ListingSpecs(brand="X", capacity=3, weight_kg=1.1, season=3)
    assert exact_match(a, b) and not exact_match(a, c)


def test_evaluate_scores_the_golden_set():
    report = evaluate(rule_extract)
    assert report["n"] >= 4
    assert report["exact_match"] == 1.0          # rule_extract nails the golden set
    assert report["field_accuracy"] == 1.0


def test_ab_compare_picks_the_winner():
    res = ab_compare("rule", 0.95, "baseline", 0.40)
    assert res["winner"] == "rule"
    assert res["delta"] == 0.55
