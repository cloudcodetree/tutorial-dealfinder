from urllib.parse import quote

from fastapi.testclient import TestClient

from dealfinder.cache import SemanticCache
from dealfinder.serve import _catalog, app

client = TestClient(app)


def _id(needle):
    return next(p.id for p in _catalog if needle.lower() in p.title.lower())


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_deal_endpoint():
    # the honest Anker Q20i deal — a real snapshot listing
    r = client.get(f"/deal/{quote(_id('Anker Soundcore Q20i'), safe='')}")
    assert r.status_code == 200
    assert r.json()["deal_score"] > 0.15           # the known deal
    assert client.get("/deal/nope").status_code == 404


def test_semantic_cache_hit_and_miss():
    c = SemanticCache(threshold=0.95)
    c.put([1.0, 0.0], "A")
    assert c.get([1.0, 0.02]) == "A"               # near-identical query → hit
    assert c.get([0.0, 1.0]) is None               # different meaning → miss
