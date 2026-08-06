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


def test_semantic_offline_fallback_returns_verdicts():
    # With no DATABASE_URL, /semantic falls back to snapshot retrieval and every
    # result carries its two-signal verdict — so the UI can badge DEAL/SUSPICIOUS.
    r = client.get("/semantic", params={"q": "noise cancelling headphones", "k": 6})
    assert r.status_code == 200
    body = r.json()
    assert body["backend"] == "snapshot"
    assert body["count"] > 0
    verdicts = {v["verdict"] for v in body["results"]}
    assert verdicts <= {"deal", "fair", "suspicious", "overpriced"}
    # the honest Anker DEAL surfaces and the $46 Bose is flagged, not sold as a deal
    anker = next(v for v in body["results"] if "Anker Soundcore Q20i" in v["title"])
    assert anker["verdict"] == "deal" and anker["price"] == 44.99
    bose = next((v for v in body["results"] if "QuietComfort 45" in v["title"]), None)
    if bose:
        assert bose["verdict"] == "suspicious"


def test_context_window_packs_orders_and_evicts():
    # Part 16 surface: retrieve wide, pack to a budget, evict the tail, and place
    # the survivors at the edges. Real bge token math, fully offline.
    r = client.get("/context", params={"q": "noise cancelling headphones under $150",
                                        "budget": 256, "k": 20})
    assert r.status_code == 200
    b = r.json()
    assert b["retrieved"] == 20
    assert b["block_tokens"] > b["budget"]         # k=20 does NOT fit
    assert b["packed_tokens"] <= b["budget"]       # what we send fits
    assert b["kept"] + b["evicted"] == 20
    assert b["evicted"] > 0                         # tail was dropped
    assert b["system_prompt_tokens"] == 62          # the real DealFinder system prompt
    # Survivors carry an edge/middle position; the strongest bracket the block.
    positions = [it["pos"] for it in b["included"]]
    assert positions[0] == "start" and positions[-1] == "end"


def test_review_endpoint_catches_the_trap_and_revises():
    # Part 17 surface: the trap-writer draft is rejected and revised to a grounded
    # answer that leads with the real Anker DEAL.
    r = client.get("/review", params={"q": "noise cancelling headphones under $150", "trap": "true"})
    assert r.status_code == 200
    b = r.json()
    assert b["draft_review"]["approved"] is False          # trap draft rejected
    assert b["draft_review"]["checks"]["lead_is_a_deal"] is False
    assert any("SUSPICIOUS" in i for i in b["draft_review"]["issues"])
    assert b["revised"] is True                             # orchestrator revised
    assert b["final_review"]["approved"] is True            # revision passes review
    assert "Anker Soundcore Q20i" in b["final"] and "$44.99" in b["final"]


def test_dataset_endpoint_reports_labels_split_and_weights():
    # Part 19 surface: the labeled training set's real shape, exposed for inspection.
    r = client.get("/dataset")
    assert r.status_code == 200
    b = r.json()
    assert b["n_rows"] == 270 and b["n_queries"] == 18
    assert b["counts"] == {"deal": 71, "fair": 40, "suspicious": 32, "overpriced": 127}
    assert b["majority_class"] == "overpriced" and b["majority_fraction"] == 0.4704
    assert b["class_weights"]["suspicious"] == 2.1094      # rarest → largest weight
    assert b["split"]["train_rows"] == 210 and b["split"]["test_rows"] == 60
    assert len(b["split"]["train_queries"]) == 14 and len(b["split"]["test_queries"]) == 4
    assert b["split"]["disjoint"] is True                  # no query straddles the split
