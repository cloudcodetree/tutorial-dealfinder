"""The two-signal deal score (spec §4) on the frozen snapshot + hero cast.

Deterministic: everything is fit on the committed snapshot, no network. The
load-bearing assertion is that the blended verdict flags the Bose-QC45-at-$46
trap as SUSPICIOUS while passing the Anker-Q20i-at-$44.99 honest deal.
"""
import pytest

from dealfinder.dealmodel import LinearModel
from dealfinder.dealscore import (
    fair_price,
    median_signal,
    residual_fraction,
    verdict,
)
from dealfinder.features import feature_matrix, featurize
from dealfinder.snapshot import load_products

ANCHOR_MEDIAN = 162.97  # "noise cancelling headphones" median at capture (spec §3)


@pytest.fixture(scope="module")
def audio_model_and_products():
    """Fit the linear baseline on the audio category (comparable → brand tier bites)."""
    products = load_products()
    audio = [p for p in products if p.category == "audio"]
    model = LinearModel().fit(feature_matrix(audio), [p.price for p in audio])
    return model, audio


def _find(products, needle):
    return next(p for p in products if needle.lower() in p.title.lower())


def test_median_signal_math():
    assert median_signal(44.99, 162.97) == pytest.approx(0.724, abs=0.01)
    assert median_signal(200.0, 162.97) < 0  # above median


def test_anchor_sits_at_median(audio_model_and_products):
    model, audio = audio_model_and_products
    sony = _find(audio, "WH-1000XM5")
    assert sony.price == 162.97
    fp = fair_price(model, featurize(sony))
    v = verdict(sony.price, ANCHOR_MEDIAN, fp)
    # the flagship anchor sits ON the median → not a deal, not suspicious
    assert v.label == "fair"


def test_anker_q20i_is_an_honest_deal(audio_model_and_products):
    model, audio = audio_model_and_products
    anker = _find(audio, "Q20i")
    assert anker.price == 44.99
    fp = fair_price(model, featurize(anker))
    v = verdict(anker.price, ANCHOR_MEDIAN, fp)
    assert v.label == "deal"  # true positive
    assert v.median_signal == pytest.approx(0.724, abs=0.01)


def test_bose_qc45_trap_is_suspicious(audio_model_and_products):
    model, audio = audio_model_and_products
    bose = _find(audio, "QuietComfort 45")
    assert bose.price == 46.0
    fp = fair_price(model, featurize(bose))
    v = verdict(bose.price, ANCHOR_MEDIAN, fp)
    # median ALONE would call this a 72%-off steal; the model residual guards it.
    assert v.median_signal >= 0.70          # median says "great deal"
    assert v.label == "suspicious"          # …but the blend rejects it
    assert v.residual_frac > 0.70           # way below the flagship fair price


def test_trap_and_honest_deal_are_separated_by_the_residual(audio_model_and_products):
    """Both are ~72% under median at ~$45; only the residual tells them apart."""
    model, audio = audio_model_and_products
    anker = _find(audio, "Q20i")
    bose = _find(audio, "QuietComfort 45")
    rf_anker = residual_fraction(anker.price, fair_price(model, featurize(anker)))
    rf_bose = residual_fraction(bose.price, fair_price(model, featurize(bose)))
    # Bose (flagship) is much further below its fair price than the Anker (budget).
    assert rf_bose > rf_anker
