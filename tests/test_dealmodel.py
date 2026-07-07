import numpy as np

from dealfinder.dealmodel import LinearModel, mae, r2, train_test_split


def test_recovers_known_coefficients():
    # y is an exact linear function of X: the normal equation must recover it.
    rng = np.random.default_rng(0)
    X = rng.normal(size=(200, 3))
    true = np.array([5.0, 2.0, -1.0, 3.0])  # [intercept, w1, w2, w3]
    y = true[0] + X @ true[1:]
    m = LinearModel().fit(X, y)
    assert np.allclose(m.coef_, true, atol=1e-6)
    assert np.allclose(m.predict(X), y, atol=1e-6)


def test_predict_before_fit_raises():
    try:
        LinearModel().predict(np.zeros((1, 3)))
    except ValueError:
        return
    raise AssertionError("expected ValueError when predicting before fit")


def test_mae_and_r2():
    y = np.array([10.0, 20.0, 30.0])
    assert mae(y, y) == 0.0
    assert r2(y, y) == 1.0
    assert mae(y, np.array([12.0, 18.0, 30.0])) == (2 + 2 + 0) / 3


def test_train_test_split_is_deterministic():
    tr1, te1 = train_test_split(20, test_frac=0.25, seed=0)
    tr2, te2 = train_test_split(20, test_frac=0.25, seed=0)
    assert len(te1) == 5 and len(tr1) == 15
    assert list(tr1) == list(tr2) and list(te1) == list(te2)
    assert set(tr1).isdisjoint(te1)  # no leakage


def test_trains_on_the_real_snapshot_features():
    # The from-scratch baseline must fit on the real broad-electronics features
    # end to end. R^2 is intentionally weak on heterogeneous data — that failure
    # is what motivates the §4 upgrade — so we only assert it runs and predicts.
    from dealfinder.features import feature_matrix
    from dealfinder.snapshot import load_products

    products = load_products()
    X = feature_matrix(products)
    y = np.array([p.price for p in products])
    model = LinearModel().fit(X, y)
    preds = model.predict(X)
    assert preds.shape == (len(products),)
    assert np.all(np.isfinite(preds))


def test_brand_tier_drives_audio_fair_prices():
    # Within the comparable audio category, flagship (tier 4) fair price should
    # exceed budget (tier 2) fair price — the separation the trap guard needs.
    from dealfinder.features import feature_matrix, featurize
    from dealfinder.snapshot import load_products

    audio = [p for p in load_products() if p.category == "audio"]
    model = LinearModel().fit(feature_matrix(audio), [p.price for p in audio])
    bose = next(p for p in audio if "QuietComfort 45" in p.title)   # tier 4
    anker = next(p for p in audio if "Q20i" in p.title)             # tier 2
    fair_bose = model.predict(np.array([featurize(bose)]))[0]
    fair_anker = model.predict(np.array([featurize(anker)]))[0]
    assert fair_bose > fair_anker
