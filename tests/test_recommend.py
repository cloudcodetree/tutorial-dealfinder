import numpy as np

from dealfinder.recommend import (
    collaborative_recommend,
    content_recommend,
    load_interactions,
    similar_products,
)


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


def test_similar_products_to_xm5_are_real_audio_items():
    """'More like the Sony WH-1000XM5' returns other real audio listings."""
    recs = similar_products("WH-1000XM5 Wireless Headphones", k=5)
    assert len(recs) == 5
    assert all(r["category"] == "audio" for r in recs)
    # the nearest neighbour is the same product from another retailer (dedup case)
    assert "WH-1000XM5" in recs[0]["title"]
    # the XM6 and the Sony WH-CH720N pair are all in the neighbourhood
    titles = " | ".join(r["title"] for r in recs)
    assert "WH-1000XM6" in titles


def test_collaborative_over_real_interaction_log():
    from dealfinder.snapshot import load_snapshot

    item_ids, R = load_interactions()
    items = {r["id"]: r["title"] for r in load_snapshot()}
    # find the index of the flagship Sony WH-1000XM5 in the log
    idx = next(i for i, iid in enumerate(item_ids)
               if items[iid] == "Sony WH-1000XM5 Wireless Headphones")
    user = np.zeros(len(item_ids))
    user[idx] = 1
    recs = collaborative_recommend(user, R, k=3)
    rec_titles = [items[item_ids[j]] for j in recs]
    # top co-like is the premium sibling XM6 (people who like the XM5 like the XM6)
    assert any("WH-1000XM6" in t for t in rec_titles)
    assert idx not in recs
