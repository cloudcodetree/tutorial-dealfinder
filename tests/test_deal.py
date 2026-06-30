from dealfinder.deal import deal_score, is_deal


def test_deal_score_sign():
    # actual below predicted fair price → positive score (a deal)
    assert deal_score(actual=80.0, predicted=100.0) == 0.2
    # actual above predicted → negative (overpriced)
    assert deal_score(actual=120.0, predicted=100.0) == -0.2


def test_is_deal_threshold():
    assert is_deal(80.0, 100.0, threshold=0.10) is True   # 20% under
    assert is_deal(95.0, 100.0, threshold=0.10) is False  # only 5% under
