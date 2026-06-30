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
