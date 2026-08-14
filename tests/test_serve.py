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


def test_pipeline_endpoint_runs_the_five_stages():
    # Part 20 surface: the orchestrated flow's trail — gate + label dist + good_deals.
    r = client.get("/pipeline")
    assert r.status_code == 200
    b = r.json()
    assert [s["name"] for s in b["stages"]] == \
        ["ingest", "normalize", "quality-gate", "label", "good_deals model"]
    assert all(s["ok"] for s in b["stages"])
    assert b["contract"] == {"total": 270, "valid": 270, "passed": True, "violations": []}
    assert b["label_distribution"] == {"deal": 71, "fair": 40, "suspicious": 32, "overpriced": 127}
    assert b["good_deals"] == 111


def test_models_endpoint_reports_the_gbdt_lift():
    # Part 21 surface: linear vs GBDT+embeddings, the hand-only loss, and the MLP.
    r = client.get("/models")
    assert r.status_code == 200
    b = r.json()
    assert b["split"] == {"n_train": 202, "n_test": 68, "seed": 0}
    assert b["full"]["linear_mae"] == 227.89 and b["full"]["gbdt_mae"] == 138.11
    assert b["full"]["improvement_pct"] == 39.4
    assert b["full"]["linear_r2"] == 0.268 and b["full"]["gbdt_r2"] == 0.727
    assert b["hand_only"]["gbdt_mae"] == 257.99      # boosting alone loses
    assert b["audio"]["gbdt_mae"] == 123.81
    assert b["torch_mlp"]["mae"] == 117.11 and b["torch_mlp"]["real"] is True


def test_tracking_endpoint_reports_the_ledger_and_winner():
    # Part 22 surface: the MLflow run ledger with the registered winner.
    from dealfinder.tracking import mlflow_available
    r = client.get("/tracking")
    assert r.status_code == 200
    b = r.json()
    if not b.get("mlflow_available"):
        import pytest
        pytest.skip("mlflow not installed")
    assert b["registered_model"] == "dealfinder-fair-price"
    assert b["winner"] == "gbdt" and abs(b["winner_mae"] - 138.11) < 0.05
    runs = {run["name"]: run for run in b["runs"]}
    assert runs["gbdt"]["selectable"] and runs["gbdt"]["contract"] == "fair-price"
    assert not runs["torch_baseline"]["selectable"]      # logged, not selectable
    assert abs(runs["torch_baseline"]["mae"] - 117.11) < 0.05


def test_evals_endpoint_reports_the_gate_and_both_rankers():
    # Part 23 surface: the eval gate + both rankers' top-5 on the golden set.
    r = client.get("/evals")
    assert r.status_code == 200
    b = r.json()
    assert b["n"] == 20 and b["distribution"]["deal"] == 6
    assert b["two_signal"]["precision_at_5"] == 1.0 and b["two_signal"]["passes"] is True
    assert b["median_only"]["precision_at_5"] == 0.4 and b["median_only"]["passes"] is False
    assert b["ab"] == {"winner": "two_signal", "delta": 0.6}
    # two_signal top-5 are all real deals; median_only is fooled by suspicious traps
    assert all(t["label"] == "deal" for t in b["two_signal"]["top5"])
    assert any(t["label"] == "suspicious" for t in b["median_only"]["top5"])


def test_mlops_endpoint_reports_the_full_cycle():
    # Part 24 surface: drift → retrain → gate → promote, one auditable trace.
    r = client.get("/mlops")
    assert r.status_code == 200
    b = r.json()
    assert b["drift"]["psi"] == 0.3182 and b["drift"]["drifted"] is True
    assert b["retrained"] is True and b["retrain"]["gbdt_mae"] == 138.11
    assert b["gate"]["challenger"] == "two_signal" and b["gate"]["precision_at_5"] == 1.0
    assert b["gate"]["passes"] is True
    assert b["champion"] == "median_only" and b["champion_precision_at_5"] == 0.4
    assert b["promote"] is True
    assert len(b["trace"]) == 4      # drift, retrain, gate, promote


def test_safety_endpoint_reports_every_guardrail_layer():
    # Part 25 surface: injection, PII, spec validation, audit, tool-trust.
    r = client.get("/safety")
    assert r.status_code == 200
    b = r.json()
    assert b["injection"]["attack"]["flagged"] is True
    assert b["injection"]["clean"]["flagged"] is False
    assert b["pii"]["after"] == "mail me at [email] or call [phone], card [card]"
    assert b["spec"]["ok"]["errors"] == []
    assert set(b["spec"]["bad"]["errors"]) == {"category unknown", "condition invalid"}
    assert b["audit"]["action"] == "tool_call"
    assert b["tool_trust"]["registered"] == ["search_deals", "score_deal"]
    assert b["tool_trust"]["quarantined"][0]["name"] == "get_weather"
    assert b["tool_trust"]["deps"]["reqests"] == "requests"   # slopsquat blocked


def test_inference_endpoint_reports_the_four_levers():
    # Part 27 surface: cache hit rates, batching, anchored GPU refs.
    r = client.get("/inference")
    assert r.status_code == 200
    b = r.json()
    assert b["cache_095"]["hits"] == 6 and b["cache_095"]["hit_rate"] == 0.429
    assert b["cache_090"]["hits"] == 7 and b["cache_090"]["hit_rate"] == 0.5
    assert b["cache_095"]["near_duplicate_cosine"] == 0.9498
    assert b["batching"]["speedup"] == 16.0 and b["batching"]["illustrative"] is True
    assert len(b["anchored"]) == 2 and all(a["illustrative"] for a in b["anchored"])


def test_ops_endpoint_reports_cost_budget_and_drift():
    # Part 30 surface: FinOps cost attribution, budget thresholds, PSI drift.
    r = client.get("/ops")
    assert r.status_code == 200
    b = r.json()
    assert b["cost"]["total"] == 0.00295
    assert b["cost"]["by_model"] == {"gpt-4o-mini": 0.00045, "gpt-4o": 0.0025}
    assert b["budget"] == {"0.5": "ok", "0.85": "warn", "1.2": "over"}
    assert b["drift"]["identical"]["psi"] == 0.0 and b["drift"]["identical"]["drifted"] is False
    assert b["drift"]["big"]["psi"] == 1.08322 and b["drift"]["big"]["drifted"] is True


def test_auth_endpoint_reports_every_jwt_verdict():
    # Part 32 surface: every Supabase-JWT verdict driven through the real verifier.
    r = client.get("/auth")
    assert r.status_code == 200
    b = r.json()
    assert b["algo"] == "HS256" and b["audience"] == "authenticated"
    by_name = {s["name"]: s["result"] for s in b["scenarios"]}
    assert by_name["valid · pro"]["status"] == 200
    assert by_name["valid · pro"]["user"] == {"id": "u1", "email": "pro@x.com", "role": "pro"}
    assert by_name["valid · free"]["user"]["role"] == "free"
    assert by_name["expired"] == {"status": 401, "detail": "token expired"}
    assert by_name["tampered"] == {"status": 401, "detail": "invalid token"}
    assert by_name["wrong secret"] == {"status": 401, "detail": "invalid token"}
    assert by_name["missing subject"] == {"status": 401, "detail": "token missing subject"}
    assert by_name["role gate: free → /pro"] == {"status": 403, "detail": "requires role 'pro'"}
    assert by_name["role gate: pro → /pro"]["status"] == 200


def test_suggestions_endpoint_reports_the_diff_loop():
    # Part 33 surface: the suggestions worker's three canonical runs.
    r = client.get("/suggestions")
    assert r.status_code == 200
    b = r.json()
    assert b["threshold"] == 0.3
    runs = b["runs"]
    assert len(runs) == 3
    # run 1: exactly one notification, the Anker Soundcore Q20i hero deal.
    n1 = runs[0]["notifications"]
    assert len(n1) == 1
    assert "Anker Soundcore Q20i" in n1[0]["title"]
    assert n1[0]["price"] == 44.99 and n1[0]["deal_score"] == 0.7239
    # run 2: idempotent — same state fed back, nothing fires.
    assert runs[1]["notifications"] == []
    # run 3: adding a new saved search fires exactly one new deal.
    n3 = runs[2]["notifications"]
    assert len(n3) == 1 and n3[0]["query"] == "bluetooth speaker"
    assert n3[0]["deal_score"] >= 0.30


def test_billing_endpoint_reports_plans_quota_webhook_and_checkout():
    # Part 34 surface: billing.py exercised read-only (plans, quota, webhook, checkout).
    r = client.get("/billing")
    assert r.status_code == 200
    b = r.json()
    plans = {p["key"]: p["monthly_searches"] for p in b["plans"]}
    assert plans == {"free": 25, "pro": 1000}
    # quota gate: the 26th free search is blocked; pro clears the free limit.
    assert b["metering"]["free_limit"] == 25
    assert "25 searches/mo" in b["metering"]["free_blocked"]
    assert b["metering"]["pro_within_quota_at_free_limit"] is True
    # webhook verification (real HMAC): good → entitlement, bad/wrong → rejected, other → ignored.
    w = b["webhook"]
    assert w["good_signature"] == {"ok": True, "entitlement": {"user_id": "user-123", "plan": "pro"}}
    assert w["bad_signature"] == {"ok": False, "error": "SignatureVerificationError"}
    assert w["wrong_secret"] == {"ok": False, "error": "SignatureVerificationError"}
    assert w["other_event"] == {"ok": True, "entitlement": None}
    # checkout builder shape (mock client, no network).
    c = b["checkout"]
    assert c["mode"] == "subscription"
    assert c["line_items"] == [{"price": "price_demo_pro_123", "quantity": 1}]
    assert c["metadata"] == {"user_id": "user-9", "plan": "pro"}
    assert c["returned"]["id"] == "cs_demo_abc"
