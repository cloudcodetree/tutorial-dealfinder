import numpy as np

from dealfinder.recommend import collaborative_recommend, content_recommend


def test_content_recommends_nearest_by_features():
    # items 0 and 1 are near-identical; 2 and 3 are far away.
    X = np.array([
        [1.0, 1.0],
        [1.1, 0.9],
        [9.0, 9.0],
        [8.5, 9.5],
    ])
    recs = content_recommend(0, X, k=1)
    assert recs == [1]  # closest neighbour, excluding itself


def test_collaborative_recommends_co_liked_item():
    # users who like item 0 also like item 2 (and vice versa).
    R = np.array([
        [1, 0, 1, 0],
        [1, 0, 1, 0],
        [1, 0, 1, 0],
        [0, 1, 0, 1],
    ])
    # a new user who liked only item 0 → should be recommended item 2
    recs = collaborative_recommend([1, 0, 0, 0], R, k=1)
    assert recs == [2]


def test_collaborative_excludes_already_liked():
    R = np.array([[1, 1, 1], [1, 1, 0], [0, 1, 1]])
    recs = collaborative_recommend([1, 0, 0], R, k=3)
    assert 0 not in recs  # item 0 was already liked
