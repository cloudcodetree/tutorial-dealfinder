"""The per-source license policy table (offline)."""
from dealfinder import licensing


def test_best_buy_carries_verdicts_and_expires_in_72h():
    p = licensing.policy_for("BestBuy:sale")
    assert (p.key, p.verdicts, p.store, p.max_age_s) == ("BestBuy", True, True, 72 * 3600)
    assert p.attribution["logo"] == "bestbuy"


def test_ebay_is_unrated_unstored_unembedded_and_separate():
    p = licensing.policy_for("eBay:Used")
    assert (p.verdicts, p.store, p.embed, p.comingle) == (False, False, False, False)
    assert p.max_age_s <= 6 * 3600


def test_unknown_source_is_denied_everything():
    assert licensing.policy_for("Walmart") is None
    checks = (licensing.may_verdict, licensing.may_store, licensing.may_embed, licensing.may_comingle)
    assert not any(f("Walmart:x") for f in checks)


def test_launch_sources_are_best_buy_and_ebay_only():
    assert licensing.LAUNCH_SOURCES == {"BestBuy", "eBay"}


def test_every_source_class_has_a_policy():
    from dealfinder.live_sources import EBAY, LIVE_SOURCES
    assert all(licensing.policy_for(s.name) for s in [*LIVE_SOURCES, EBAY])
