"""ML & DL breadth (Part 17) on the frozen snapshot.

Deterministic and offline. Pins the REAL gradient-boosting MAE against the linear
baseline (relative improvement, not the old narrow-tent "$80→$35" fantasy), the
forecaster's deterministic synthetic-history output, and — since torch installs
cleanly here — the real PyTorch MLP's seeded MAE. A small tolerance absorbs
platform BLAS jitter without letting the numbers silently drift.
"""
import numpy as np
import pytest

from dealfinder.models import (
    forecast_price_drop,
    gbdt_vs_linear,
    synthetic_price_history,
    train_torch_pricehead,
)


def test_gbdt_beats_linear_on_full_corpus():
    c = gbdt_vs_linear()
    assert c.category == "all"
    assert c.n_train == 202 and c.n_test == 68
    # REAL numbers (spec §5 reproducibility): linear ~$227.89, GBDT ~$138.11.
    # The absolute MAE is large because the corpus spans $7 accessories to a
    # $13,599 GPU — NOT the old single-category course. The honest win is the
    # ~39% relative cut from embeddings + boosting, not "$80 → $35".
    assert c.linear_mae == pytest.approx(227.89, abs=1.0)
    assert c.gbdt_mae == pytest.approx(138.11, abs=2.0)
    assert c.gbdt_mae < c.linear_mae  # boosting + embeddings genuinely help
    assert c.improvement_pct == pytest.approx(39.4, abs=1.5)


def test_gbdt_vs_linear_on_audio_hero_subset():
    c = gbdt_vs_linear("audio")
    assert c.category == "audio"
    assert c.n_train == 45 and c.n_test == 15
    assert c.linear_mae == pytest.approx(150.84, abs=1.0)
    assert c.gbdt_mae == pytest.approx(123.81, abs=2.0)
    assert c.gbdt_mae < c.linear_mae


def test_gbdt_hand_only_is_the_honest_worse_case():
    # Without the embedding signal the GBDT does NOT beat the linear baseline on
    # this tiny 3-feature vector — the embeddings are what close the gap. We keep
    # this so the prose can't claim boosting alone is the hero.
    c = gbdt_vs_linear(with_embeddings=False)
    assert c.gbdt_mae >= c.linear_mae


def test_forecaster_is_deterministic_and_marked_illustrative():
    h = synthetic_price_history(162.97, seed=42)
    assert h.shape == (12,)
    f = forecast_price_drop(h)
    # Deterministic synthetic history → fixed forecast.
    assert f.forecast_next == pytest.approx(162.32, abs=0.01)
    assert f.last_price == pytest.approx(164.24, abs=0.01)
    assert f.slope_per_step == pytest.approx(-0.816, abs=0.005)
    assert f.will_drop is True
    # HONESTY: this is illustrative on synthetic history, never claimed as real.
    assert f.illustrative is True


def test_synthetic_history_is_reproducible():
    a = synthetic_price_history(162.97, seed=42)
    b = synthetic_price_history(162.97, seed=42)
    assert np.array_equal(a, b)


def test_forecast_needs_two_points():
    with pytest.raises(ValueError):
        forecast_price_drop([100.0])


def test_torch_pricehead_is_a_real_trained_loop():
    r = train_torch_pricehead()
    assert r.real is True  # torch runs here — a real autograd loop, not anchored
    assert r.n_train == 202 and r.n_test == 68 and r.epochs == 300
    # Seeded → deterministic MAE (~$117.11) and a converged final loss.
    assert r.mae == pytest.approx(117.11, abs=3.0)
    assert r.final_loss < 1.0  # MSE in standardized space actually came down
